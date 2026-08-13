from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List
from html import escape
import re
import os
import queue as queue_lib
import time
import multiprocessing as mp
import base64
import markdown
from zoneinfo import ZoneInfo

from weasyprint import HTML
from open_webui.env import STATIC_DIR
from open_webui.models.chats import ChatTitleMessagesForm
from .katex_compiler import KaTeXCompiler

PDF_DEBUG = os.environ.get("PDF_DEBUG", "False").lower() == "true"
LATEX_DEBUG = os.environ.get("LATEX_DEBUG", "False").lower() == "true"

# Minimum and maximum wall clock budget for the WeasyPrint render, and the
# per-message allowance used to interpolate between them.
RENDER_TIMEOUT_MIN_SEC = 60.0
RENDER_TIMEOUT_MAX_SEC = 600.0
RENDER_TIMEOUT_PER_MESSAGE_SEC = 2.0

# Placeholder that stands in for a rendered LaTeX fragment while the message
# body goes through list normalization, escaping and markdown. Letters and
# digits only so that no markdown or regex pass can rewrite it.
LATEX_PLACEHOLDER = "xkatexph{index}endx"
LATEX_PLACEHOLDER_RE = re.compile(r"xkatexph(\d+)endx")

# Spans a whole tag, so placeholder substitution can tell markup from text.
HTML_TAG_RE = re.compile(r"<[^>]*>")


# Character class the frontend tokenizer requires on both sides of a math span:
# whitespace or punctuation. A delimiter glued to a letter or a digit (a price
# such as "$20", a variable named x$) is not math.
LATEX_BOUNDARY = r"\s?。，!-/:-@\[-`{-~"
_LEAD = f"(?<![^{LATEX_BOUNDARY}])"
_TRAIL = f"(?=[{LATEX_BOUNDARY}]|$)"
# Same body pattern as the frontend: any run of characters, treating a
# backslash and the character after it as one unit so escaped delimiters
# do not terminate the span.
_BODY = r"((?:\\[\s\S]|[^\\])+?)"
# Inline math never contains a bare dollar sign; a literal one is written \$.
# Refusing to span one stops a stray delimiter, a price for instance, from
# pairing with the opening delimiter of the next real expression and
# swallowing the prose in between.
_BODY_NO_DOLLAR = r"((?:\\[\s\S]|[^\\$])+?)"
_BRACED = r"([^{}]*(?:\{[^{}]*\}[^{}]*)*)"

PARAGRAPH_BREAK_RE = re.compile(r"\n[ \t]*\n")

# (compiled pattern, delimiter name, display mode). Display delimiters are
# matched first so that the inline scan cannot claim part of a block span.
LATEX_PATTERNS = [
    (re.compile(rf"{_LEAD}\$\${_BODY}\$\${_TRAIL}"), "$$", True),
    (re.compile(rf"{_LEAD}\\\[{_BODY}\\\]{_TRAIL}"), "\\[\\]", True),
    (re.compile(rf"{_LEAD}\\begin\{{equation\}}([\s\S]*?)\\end\{{equation\}}{_TRAIL}"),
     "\\begin{equation}\\end{equation}", True),
    (re.compile(rf"{_LEAD}(?<!\$)\${_BODY_NO_DOLLAR}\$(?!\$){_TRAIL}"), "$", False),
    (re.compile(rf"{_LEAD}\\\({_BODY}\\\){_TRAIL}"), "\\(\\)", False),
    (re.compile(rf"{_LEAD}\\ce\{{{_BRACED}\}}{_TRAIL}"), "\\ce{}", False),
    (re.compile(rf"{_LEAD}\\pu\{{{_BRACED}\}}{_TRAIL}"), "\\pu{}", False),
    (re.compile(rf"{_LEAD}\\boxed\{{{_BRACED}\}}{_TRAIL}"), "\\boxed{}", False),
]

# Arguments of these commands are typeset in text mode, where the soft break
# macro is not defined. Anything inside their braces is left untouched.
TEXT_MODE_COMMANDS = ("\\text", "\\textbf", "\\textit", "\\textrm", "\\textsf",
                      "\\texttt", "\\textnormal", "\\mbox", "\\operatorname")

# Breaking inside a matrix or a case distinction only adds gaps between the
# entries; these environments lay themselves out.
RIGID_ENVIRONMENTS = ("pmatrix", "bmatrix", "Bmatrix", "vmatrix", "Vmatrix",
                      "matrix", "smallmatrix", "array", "cases")
RIGID_ENVIRONMENT_RE = re.compile(
    r"\\begin\{(" + "|".join(RIGID_ENVIRONMENTS) + r")\}[\s\S]*?\\end\{\1\}"
)

# Short expressions fit on one line, so the soft breaks would only show up as
# extra spacing around operators.
SOFT_BREAK_MIN_LENGTH = 60

# A math font macro takes one group. An alignment tab, a row break, or a \right
# closing a \left that was opened outside can never legally sit inside it. A
# model that puts the closing brace in the wrong place -- \mathbf{v_1 &= ...}
# for \mathbf{v_1} &= ... -- produces markup a full TeX engine digests, because
# TeX only sees alignment tabs at the outermost brace level, but that KaTeX
# refuses outright. Closing the group at the offending token is the smallest
# edit that makes it parse. Text macros are left alone: an ampersand inside
# \text{} is ordinary prose.
FONT_MACROS = ("\\mathbf", "\\boldsymbol", "\\bm", "\\mathrm", "\\mathit",
               "\\mathsf", "\\mathtt", "\\mathbb", "\\mathcal", "\\mathfrak")


def _matching_brace(expr: str, open_idx: int) -> int:
    """Index of the brace closing the one at open_idx, or -1 if unbalanced."""
    depth = 0
    i = open_idx
    while i < len(expr):
        char = expr[i]
        if char == "\\":
            i += 2  # an escaped brace is a character, not a group
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _first_illegal_in_font_group(arg: str) -> int:
    """
    Offset of the first token that cannot appear inside a font macro group.

    Alignment tabs and row breaks only count at the top level of the argument:
    inside a nested group or a \\begin{...}\\end{...} they belong to that
    construct and are perfectly legal.
    """
    depth = env = pending_left = 0
    i = 0
    while i < len(arg):
        char = arg[i]
        if char == "\\":
            if arg.startswith(r"\\", i):
                if depth == 0 and env == 0:
                    return i
                i += 2
                continue
            if arg.startswith(r"\begin", i):
                env += 1
                i += 6
                continue
            if arg.startswith(r"\end", i):
                env -= 1
                i += 4
                continue
            if arg.startswith(r"\left", i):
                pending_left += 1
                i += 5
                continue
            if arg.startswith(r"\right", i):
                if pending_left == 0 and depth == 0 and env == 0:
                    return i
                pending_left -= 1
                i += 6
                continue
            i += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif char == "&" and depth == 0 and env == 0:
            return i
        i += 1
    return -1


def _weasyprint_worker(result_queue, doc_html: str, base_url: str | None) -> None:
    """Render HTML to PDF bytes in a child process and hand the result back."""
    try:
        document = HTML(string=doc_html, base_url=base_url) if base_url else HTML(string=doc_html)
        result_queue.put((True, document.write_pdf()))
    except Exception as ex:
        result_queue.put((False, f"{type(ex).__name__}: {ex}"))

class PDFGenerator:
    """
    Description:
    The `PDFGenerator` class is designed to create PDF documents from chat messages.
    The process involves transforming markdown content into HTML and then into a PDF format

    Attributes:
    - `form_data`: An instance of `ChatTitleMessagesForm` containing title and messages.

    """

    def __init__(self, form_data: ChatTitleMessagesForm):
        self.html_body = None
        self.messages_html = None
        self.form_data = form_data
        self.temp_images = []
        self.katex_compiler = KaTeXCompiler(debug=LATEX_DEBUG)
        self.debug_latex = LATEX_DEBUG
        self.debug_pdf = PDF_DEBUG

        self.css = Path(STATIC_DIR / "assets" / "pdf-style.css").read_text()

    @staticmethod
    def _coerce_epoch_seconds(timestamp) -> float | None:
        """
        Normalize whatever a message carries into epoch seconds.

        The frontend writes seconds, but a value that has been through JSON,
        a webhook or an import can arrive as a numeric string or in
        milliseconds. Both used to fall through to the empty string, which is
        why a message could show no date at all despite having a timestamp.
        """
        if isinstance(timestamp, bool) or timestamp is None:
            return None
        if isinstance(timestamp, str):
            try:
                timestamp = float(timestamp.strip())
            except ValueError:
                return None
        if not isinstance(timestamp, (int, float)):
            return None
        value = float(timestamp)
        if value <= 0:
            return None
        # Anything this large is not seconds; a seconds value that big would be
        # far past year 9999. Milliseconds and microseconds both fold down.
        while value > 1e11:
            value /= 1000.0
        return value

    def format_timestamp(self, timestamp: float) -> str:
        """Convert a UNIX timestamp to a formatted date string in Eastern Time (EST/EDT)."""
        timestamp = self._coerce_epoch_seconds(timestamp)
        if timestamp is None:
            return ""
        try:
            date_time = datetime.fromtimestamp(timestamp, tz=ZoneInfo("America/New_York"))
            
            # Get timezone abbreviation (EST/EDT) - fallback based on offset if %Z is empty
            tz_abbrev = date_time.strftime("%Z")
            if not tz_abbrev:
                offset_hours = int(date_time.utcoffset().total_seconds() / 3600) if date_time.utcoffset() else -5
                tz_abbrev = "EDT" if offset_hours == -4 else "EST"
            
            # Format UTC offset
            offset_str = date_time.strftime("%z")
            offset_formatted = f"UTC{offset_str[:3]}:{offset_str[3:]}" if offset_str else "UTC"
            
            return date_time.strftime(f"%B %d, %Y %I:%M:%S %p {tz_abbrev} ({offset_formatted})")
        except Exception:
            try:
                return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%B %d, %Y %I:%M:%S %p UTC")
            except Exception:
                return ""

    def _detect_code_blocks(self, content: str) -> List[tuple[int, int]]:
        """
        Detect code block regions in content.
        Returns a list of (start, end) tuples representing code block regions.
        Handles both fenced code blocks (```...```) and inline code (`...`).
        """
        code_regions = []
        
        # Pattern for fenced code blocks: ```[language]\n...```
        # Matches ```, optional language identifier (word chars, hyphens, spaces), 
        # optional newline, content (non-greedy), then closing ```
        # The pattern handles both ```language\n...``` and ```\n...``` formats
        fenced_pattern = r'```(?:[^\n`]*)?\n?[\s\S]*?```'
        for match in re.finditer(fenced_pattern, content, re.MULTILINE):
            code_regions.append((match.start(), match.end()))
        
        # Pattern for inline code: `...` (but not inside fenced blocks)
        # We need to be careful to not match backticks that are part of fenced blocks
        # Simple approach: find all `...` patterns, then filter out those inside fenced blocks
        inline_pattern = r'`[^`\n]+`'
        for match in re.finditer(inline_pattern, content):
            # Check if this inline code is inside a fenced block
            is_inside_fenced = any(
                match.start() >= fence_start and match.end() <= fence_end
                for fence_start, fence_end in code_regions
            )
            if not is_inside_fenced:
                code_regions.append((match.start(), match.end()))
        
        # Sort by start position for easier checking
        code_regions.sort()
        
        if self.debug_pdf:
            print("*"*20, f"\nPDF: detected {len(code_regions)} code block(s)\n", "*"*20)
        
        return code_regions
    
    def _is_in_code_block(self, position: int, code_regions: List[tuple[int, int]]) -> bool:
        """
        Check if a given position is inside any code block region.
        """
        for start, end in code_regions:
            if start <= position < end:
                return True
        return False

    def detect_latex_in_message(self, content: str) -> List[Dict[str, Any]]:
        """
        Detect LaTeX code in a chat message content.
        Returns a list of dictionaries containing LaTeX expressions found.
        Mirrors the frontend tokenizer in src/lib/utils/marked/katex-extension.ts so
        that the PDF renders the same expressions the user saw in the chat.
        Excludes LaTeX expressions that are inside code blocks.
        """
        # First, detect all code block regions
        code_regions = self._detect_code_blocks(content)

        found_latex = []
        # Track used positions to avoid duplicate matches (e.g., $ inside $$)
        used_positions = set()

        for pattern, delimiter, display in LATEX_PATTERNS:
            for match in pattern.finditer(content):
                start, end = match.start(), match.end()

                # Skip if this LaTeX expression is inside a code block
                if self._is_in_code_block(start, code_regions) or self._is_in_code_block(end - 1, code_regions):
                    if self.debug_pdf:
                        print("*"*20, f"\nPDF: Skipping LaTeX in code block at position {start}-{end}, delimiter={delimiter}\n", "*"*20)
                    continue

                # Skip pathological matches (likely unmatched delimiters)
                if end - start > 10000:
                    if self.debug_pdf:
                        print("*"*20, f"\nPDF: Skipping pathological LaTeX span length={end-start} delimiter={delimiter}\n", "*"*20)
                    continue

                # Skip if this position range overlaps with a previously matched expression
                if any(start < used_end and end > used_start for used_start, used_end in used_positions):
                    continue

                # A blank line ends a paragraph, so it also ends a math span. Without
                # this a stray delimiter swallows unrelated prose further down.
                if PARAGRAPH_BREAK_RE.search(match.group(1)):
                    if self.debug_pdf:
                        print("*"*20, f"\nPDF: Skipping LaTeX span crossing a blank line, delimiter={delimiter}\n", "*"*20)
                    continue

                latex_expr = match.group(1).strip()
                # Only add if we have meaningful content (not just whitespace)
                if latex_expr and len(latex_expr) > 0 and not latex_expr.isspace():
                    found_latex.append({
                        "expression": latex_expr,
                        "full_match": match.group(0),
                        "display": display,
                        "delimiter": delimiter,
                        "start": start,
                        "end": end
                    })
                    used_positions.add((start, end))

        found_latex.sort(key=lambda item: item["start"])

        if self.debug_pdf:
            print("*"*20, f"\nPDF: detect_latex_in_message count={len(found_latex)} content_len={len(content)}\n", "*"*20)
        return found_latex

    def _fix_svg_sizing(self, html_fragment: str) -> str:
        """
        Fix SVG sizing issues in HTML fragment, keeping SVG tags embedded directly.
        This preserves the em context that would be lost with base64 image conversion.
        """
        import re
        
        svg_pattern = r'<svg[^>]*>.*?</svg>'
        svg_matches = list(re.finditer(svg_pattern, html_fragment, re.DOTALL | re.IGNORECASE))
        
        if not svg_matches:
            return html_fragment
        
        result = html_fragment
        for match in reversed(svg_matches):
            svg_html = match.group(0)
            
            try:
                # Fix pathological width values (KaTeX placeholders like 1e6em, 10000em)
                # These need to be replaced with reasonable values, but we keep the SVG tag
                fixed_svg = svg_html
                
                # Replace pathological width values - we'll need to calculate proper width based on content
                # For now, let's just remove or replace the problematic width attributes
                # The SVG should size based on viewBox and content
                fixed_svg = re.sub(r'width=["\'](1e6|10000)em["\']', '', fixed_svg, flags=re.IGNORECASE)
                fixed_svg = re.sub(r'width=["\']100%["\']', '', fixed_svg, flags=re.IGNORECASE)
                
                # Keep the SVG tag embedded directly in HTML
                result = result[:match.start()] + fixed_svg + result[match.end():]
            except Exception:
                continue
        
        return result

    def cleanup_temp_images(self):
        """Clean up temporary image files."""
        for temp_path in self.temp_images:
            try:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
            except Exception as e:
                print(f"Error cleaning up temp file {temp_path}: {e}")
        self.temp_images.clear()
        
        # Also clean up KaTeX temp images
        if hasattr(self, 'katex_compiler'):
            self.katex_compiler.cleanup_temp_images()


    def print_latex_detected(self, message: Dict[str, Any]) -> None:
        """
        Check for LaTeX code in a message and print it to terminal if found.
        """
        content = message.get("content", "")
        role = message.get("role", "user")
        
        latex_expressions = self.detect_latex_in_message(content)
        
        if latex_expressions:
            print(f"\n=== LaTeX detected in {role} message ===")
            for i, latex in enumerate(latex_expressions, 1):
                print(f"Expression {i}:")
                print(f"  Type: {'Block' if latex['display'] else 'Inline'}")
                print(f"  Delimiter: {latex['delimiter']}")
                print(f"  Content: {latex['expression']}")
                print(f"  Position: {latex['start']}-{latex['end']}")
                print(f"  Full match: {latex['full_match']}")
                print()

    def _build_html_message(
        self, message: Dict[str, Any], body: str, fragments: List[str]
    ) -> str:
        """
        Build HTML for a single message from its placeholder body and the KaTeX
        fragments already rendered for it.
        """
        role = escape(message.get("role", "user"))
        timestamp = message.get("timestamp")

        model = escape(message.get("model") or "" if role == "assistant" else "")

        date_str = escape(self.format_timestamp(timestamp) if timestamp else "")

        # Minimal preprocessing: only fix items that are clearly on the same line
        # when they should be separate (e.g., "text - (a) text - (b)" -> separate lines)
        # This is minimal and doesn't touch well-formed markdown. It runs on the
        # placeholder body so it can never rewrite generated KaTeX markup.
        html_content = self._fix_broken_list_items(body)

        # Convert markdown to HTML with extensions that preserve formatting
        # Use markdown extensions for better formatting support
        # No 'toc': it slugifies heading text into an id, and the LaTeX
        # placeholder is part of that text. The id then received a whole KaTeX
        # fragment, whose first quote closed the attribute and spilled the rest
        # into the document as markup. A PDF has nothing to anchor to anyway.
        html_content = markdown.markdown(
            html_content,
            extensions=['fenced_code', 'tables']
        )

        html_content = self._apply_latex_fragments(html_content, fragments)

        # Wrap in markdown-section div for proper CSS styling
        html_message = f"""
            <div>
                <div>
                    <h4>
                        <strong>{role.title()}</strong>
                        <span style=\"font-size: 12px;\">{model}</span>
                    </h4>
                    <div> {date_str} </div>
                </div>
                <br/>
                <br/>

                <div class="markdown-section">
                    {html_content}
                </div>
            </div>
            <br/>
          """
        return html_message

    def _fix_broken_list_items(self, content: str) -> str:
        """
        Ensure list items are properly formatted for markdown.
        Markdown requires list items to start at the beginning of lines (or with proper indentation).
        This ensures list items are recognized and separated properly.
        """
        result = content
        
        # First, fix cases where list items appear on the same line as text
        # Fix numbered lists: "text 1. item" -> "text\n1. item"
        result = re.sub(r'([^\n])\s+(\d+\.\s+)', r'\1\n\2', result)
        
        # Fix bullet points: "text - item" -> "text\n- item"  
        result = re.sub(r'([^\n])\s+(-\s+)', r'\1\n\2', result)
        
        # Fix lettered items with dash: "text - (a)" -> "text\n- (a)"
        result = re.sub(r'([^\n])\s+-\s+\(([a-zA-Z0-9ivxlcdmIVXLCDM]+)\)', r'\1\n- (\2)', result)
        
        # Now ensure list items are properly separated from preceding text
        # Split into lines to process line by line
        lines = result.split('\n')
        processed_lines = []
        
        for i, line in enumerate(lines):
            # Check if this line is a list item (preserving indentation)
            is_numbered_list = re.match(r'^\s*\d+\.\s+', line)
            is_bullet_list = re.match(r'^\s*[-*+]\s+', line)
            
            if is_numbered_list or is_bullet_list:
                # If previous line was not a list item and not empty, 
                # ensure there's proper separation (markdown needs this)
                if processed_lines:
                    prev_line = processed_lines[-1].strip()
                    # If previous line has content and is not a list item, add blank line
                    if prev_line:
                        prev_is_list = re.match(r'^\s*[-*+]\s+', processed_lines[-1]) or re.match(r'^\s*\d+\.\s+', processed_lines[-1])
                        if not prev_is_list:
                            # Add blank line before list to help markdown recognize it
                            processed_lines.append('')
            
            processed_lines.append(line)
        
        result = '\n'.join(processed_lines)
        
        # Clean up multiple consecutive blank lines (max 2)
        result = re.sub(r'\n{3,}', '\n\n', result)
        
        return result

    def _generate_html_body(self) -> str:
        """Generate the full HTML body for the PDF."""
        escaped_title = escape(self.form_data.title)
        return f"""
        <html>
            <head>
                <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
            </head>
            <body>
            <div>
                <div>
                    <h2>{escaped_title}</h2>
                    {self.messages_html}
                </div>
            </div>
            </body>
        </html>
        """

    def _extract_latex(self, content: str) -> tuple[str, List[tuple[str, bool]]]:
        """
        Replace every LaTeX span in a message with a neutral placeholder.

        Returns the placeholder body, which is safe to run through list
        normalization, escaping and markdown, plus the list of
        (expression, display) pairs to render, in placeholder order.
        """
        latex_expressions = self.detect_latex_in_message(content)

        to_render: List[tuple[str, bool]] = []
        parts: List[str] = []
        cursor = 0

        for index, latex in enumerate(latex_expressions):
            expr = latex['expression']

            # Rebuild expression for special delimiters (boxed, ce, pu)
            # These need to be wrapped in their command syntax
            if latex['delimiter'] in ['\\boxed{}', '\\ce{}', '\\pu{}']:
                expr = latex['delimiter'].replace('{}', '{' + expr + '}')

            # Repair before breaking: soft breaks assume the expression parses.
            expr = self._repair_font_macro_groups(expr)
            expr = self._close_unbalanced_groups(expr)

            # Insert soft breaks to allow long expressions to wrap in PDF
            if len(expr) >= SOFT_BREAK_MIN_LENGTH:
                expr = self._insert_soft_breaks(expr)

            parts.append(escape(content[cursor:latex['start']], quote=False))
            parts.append(LATEX_PLACEHOLDER.format(index=index))
            cursor = latex['end']
            to_render.append((expr, latex['display']))

        parts.append(escape(content[cursor:], quote=False))
        return "".join(parts), to_render

    def _repair_font_macro_groups(self, expr: str) -> str:
        """
        Close a font macro group at the first token that cannot live inside it.

        \\mathbf{v_1 &= \\begin{pmatrix}...\\end{pmatrix}} becomes
        \\mathbf{v_1} &= \\begin{pmatrix}...\\end{pmatrix}. Nothing is added or
        dropped, the closing brace only moves, so an expression that already
        parses is returned untouched.
        """
        for macro in FONT_MACROS:
            start = 0
            while True:
                idx = expr.find(macro, start)
                if idx == -1:
                    break

                cursor = idx + len(macro)
                while cursor < len(expr) and expr[cursor] == " ":
                    cursor += 1
                if cursor >= len(expr) or expr[cursor] != "{":
                    start = idx + len(macro)
                    continue

                close = _matching_brace(expr, cursor)
                if close == -1:
                    start = idx + len(macro)
                    continue

                arg = expr[cursor + 1:close]
                offset = _first_illegal_in_font_group(arg)
                head = arg[:offset].rstrip() if offset != -1 else ""
                if offset == -1 or not head:
                    # Nothing to repair, or the offender is the whole argument
                    # and closing early would leave an empty group.
                    start = close + 1
                    continue

                expr = expr[:cursor + 1] + head + "}" + arg[offset:] + expr[close + 1:]
                start = cursor + 1 + len(head) + 1

        return expr

    def _close_unbalanced_groups(self, expr: str) -> str:
        """
        Append the closing braces an expression is missing.

        A model sometimes drops a brace outright, leaving \\boxed{ open to the
        end of the expression. KaTeX rejects the whole thing, so the reader
        gets red source instead of maths. Only ever adds braces, and only when
        some are missing, so an expression that already balances is untouched
        and one that already fails cannot be made worse.
        """
        depth = 0
        i = 0
        while i < len(expr):
            char = expr[i]
            if char == "\\":
                i += 2  # an escaped brace is a character, not a group
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth < 0:  # more closers than openers, not ours to fix
                    return expr
            i += 1

        return expr + "}" * depth if depth > 0 else expr

    def _apply_latex_fragments(self, html_content: str, fragments: List[str]) -> str:
        """Swap the placeholders in rendered markdown for their KaTeX fragments."""
        if not fragments:
            return html_content

        def _replace(match: re.Match) -> str:
            index = int(match.group(1))
            if index >= len(fragments):
                return ""
            fragment = fragments[index]
            if '<svg' in fragment:
                try:
                    return self._fix_svg_sizing(fragment)
                except Exception:
                    return fragment
            return fragment

        # Substitute in text only. A placeholder that markdown copied into an
        # attribute (a heading id, an image alt) must not receive a KaTeX
        # fragment: the fragment's own quotes would close the attribute and the
        # rest of it would land in the document as markup.
        pieces: List[str] = []
        cursor = 0
        for tag in HTML_TAG_RE.finditer(html_content):
            pieces.append(LATEX_PLACEHOLDER_RE.sub(_replace, html_content[cursor:tag.start()]))
            pieces.append(LATEX_PLACEHOLDER_RE.sub("", tag.group(0)))
            cursor = tag.end()
        pieces.append(LATEX_PLACEHOLDER_RE.sub(_replace, html_content[cursor:]))

        return "".join(pieces)

    def _render_timeout(self) -> float:
        """Scale the render budget with the size of the conversation."""
        per_message = RENDER_TIMEOUT_PER_MESSAGE_SEC * len(self.form_data.messages)
        return min(max(RENDER_TIMEOUT_MIN_SEC, per_message), RENDER_TIMEOUT_MAX_SEC)

    def _render_with_timeout(self, html_full: str, timeout_sec: float | None = None, use_base_url: bool = True) -> bytes:
        """
        Render PDF in a separate process with a timeout. Returns bytes or raises TimeoutError.

        The result is read off the queue before the process is joined. A
        multiprocessing queue writes through a pipe with a 64 KiB kernel buffer,
        so a child holding a larger payload cannot exit until a reader drains it.
        Joining first deadlocks on every PDF above that size no matter how
        generous the timeout is.
        """
        if timeout_sec is None:
            timeout_sec = self._render_timeout()

        base_url_val = str(STATIC_DIR) if use_base_url else None
        q: mp.Queue = mp.Queue()
        p = mp.Process(target=_weasyprint_worker, args=(q, html_full, base_url_val))
        p.daemon = True
        p.start()

        deadline = time.monotonic() + timeout_sec
        result = None
        while result is None:
            try:
                result = q.get(timeout=min(1.0, max(0.0, deadline - time.monotonic())))
            except queue_lib.Empty:
                if not p.is_alive():
                    # The renderer died without producing anything, for example
                    # killed by the container memory limit. Give the queue a
                    # moment in case the payload is still in flight.
                    try:
                        result = q.get(timeout=5)
                    except queue_lib.Empty:
                        raise RuntimeError(
                            f"PDF renderer exited unexpectedly (exit code {p.exitcode})"
                        )
                    break
                if time.monotonic() >= deadline:
                    if self.debug_pdf:
                        print("*"*20, "\nPDF: write_pdf timed out; terminating renderer process\n", "*"*20)
                    p.terminate()
                    p.join(5)
                    raise TimeoutError("WeasyPrint write_pdf timeout")

        ok, payload = result
        p.join(10)
        if p.is_alive():
            p.terminate()
            p.join(5)

        if not ok:
            raise RuntimeError(payload)
        return payload

    def _protected_spans(self, expr: str) -> List[tuple[int, int]]:
        """
        Return (start, end) ranges that soft break insertion must not touch:
        text mode arguments and self laying out environments.
        """
        spans: List[tuple[int, int]] = [
            (match.start(), match.end()) for match in RIGID_ENVIRONMENT_RE.finditer(expr)
        ]
        for command in TEXT_MODE_COMMANDS:
            search_from = 0
            while True:
                idx = expr.find(command, search_from)
                if idx == -1:
                    break
                search_from = idx + len(command)
                # Reject a longer command that merely starts with this one
                # (\textbf found while scanning for \text).
                if search_from < len(expr) and expr[search_from].isalpha():
                    continue
                brace = expr.find("{", search_from)
                if brace == -1 or expr[search_from:brace].strip():
                    continue
                depth = 0
                for pos in range(brace, len(expr)):
                    if expr[pos] == "{":
                        depth += 1
                    elif expr[pos] == "}":
                        depth -= 1
                        if depth == 0:
                            spans.append((idx, pos + 1))
                            search_from = pos + 1
                            break
                else:
                    spans.append((idx, len(expr)))
                    search_from = len(expr)

        spans.sort()
        # Drop ranges already contained in an earlier one, for example \text{}
        # inside a matrix cell, so the merge below stays linear.
        merged: List[tuple[int, int]] = []
        for start, end in spans:
            if merged and start < merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        return merged

    def _insert_soft_breaks(self, expr: str) -> str:
        """
        Insert KaTeX-friendly soft breakpoints into long LaTeX expressions.
        Text mode arguments are skipped: \\allowbreak is undefined there and
        makes KaTeX render the whole expression as an error.
        """
        spans = self._protected_spans(expr)
        if spans:
            out = []
            cursor = 0
            for start, end in spans:
                if start > cursor:
                    out.append(self._insert_soft_breaks_math(expr[cursor:start]))
                out.append(expr[start:end])
                cursor = end
            out.append(self._insert_soft_breaks_math(expr[cursor:]))
            return "".join(out)
        return self._insert_soft_breaks_math(expr)

    def _insert_soft_breaks_math(self, expr: str) -> str:
        """Soft breakpoint insertion for a run of pure math mode LaTeX."""
        multi_token_replacements = {
            r"\\cdot": r"\\allowbreak{}\\cdot\\allowbreak{}",
            r"\\times": r"\\allowbreak{}\\times\\allowbreak{}",
            r"\\pm": r"\\allowbreak{}\\pm\\allowbreak{}",
            r"\\mp": r"\\allowbreak{}\\mp\\allowbreak{}",
            r"\\leq": r"\\allowbreak{}\\leq\\allowbreak{}",
            r"\\geq": r"\\allowbreak{}\\geq\\allowbreak{}",
            r"\\approx": r"\\allowbreak{}\\approx\\allowbreak{}",
            r"\\sim": r"\\allowbreak{}\\sim\\allowbreak{}",
        }

        for k, v in multi_token_replacements.items():
            expr = re.sub(k, v, expr)

        # A break directly after ^ or _ would become the scripted token itself,
        # so those positions are excluded as well.
        expr = re.sub(r"(?<![\\\\a-zA-Z0-9^_])\+", r"\\allowbreak{}+\\allowbreak{}", expr)
        expr = re.sub(r"(?<![\\\\a-zA-Z0-9^_])-", r"\\allowbreak{}-\\allowbreak{}", expr)
        expr = re.sub(r"(?<![\\\\a-zA-Z0-9^_])=", r"\\allowbreak{}=\\allowbreak{}", expr)
        expr = re.sub(r"(?<![\\\\^_]),", r",\\allowbreak{}", expr)
        expr = re.sub(r"(?<![\\\\^_]);", r";\\allowbreak{}", expr)
        expr = re.sub(r"(?<![\\\\^_]):", r":\\allowbreak{}", expr)
        # Not before an opening brace: \sqrt[3]{27} and friends would lose their
        # mandatory argument to the break macro.
        expr = re.sub(r"\)(?!\s*\{)", r")\\allowbreak{}", expr)
        expr = re.sub(r"\](?!\s*\{)", r"]\\allowbreak{}", expr)

        return expr

    def generate_chat_pdf(self) -> bytes:
        """
        Generate a PDF from chat messages. Uses WeasyPrint to render HTML with KaTeX.
        """
        try:
            gen_start = time.perf_counter()
            if self.debug_pdf:
                print("*"*20, f"\nPDF: starting build for {len(self.form_data.messages)} messages\n", "*"*20)

            # Pass one: detect LaTeX in every message and collect the whole
            # conversation into a single render batch. Rendering per message
            # spawns one Node process per message.
            bodies: List[str] = []
            batch: List[tuple[str, bool]] = []
            spans: List[tuple[int, int]] = []
            for message in self.form_data.messages:
                if self.debug_latex:
                    self.print_latex_detected(message)
                body, to_render = self._extract_latex(message.get("content", ""))
                bodies.append(body)
                spans.append((len(batch), len(batch) + len(to_render)))
                batch.extend(to_render)

            t_katex0 = time.perf_counter()
            rendered = self.katex_compiler.render_many_to_html(batch) if batch else []
            t_katex1 = time.perf_counter()
            if self.debug_pdf:
                print("*"*20, f"\nPDF: rendered {len(batch)} LaTeX expressions in {t_katex1 - t_katex0:.3f}s\n", "*"*20)

            # Pass two: markdown and assembly, with the fragments spliced back in.
            messages_html_parts = []
            for message, body, (start, end) in zip(self.form_data.messages, bodies, spans):
                messages_html_parts.append(
                    self._build_html_message(message, body, rendered[start:end])
                )

            self.messages_html = "\n".join(messages_html_parts)
            html_body = self._generate_html_body()

            katex_css_path = Path(STATIC_DIR / "assets" / "katex" / "katex.min.css")

            html_full = html_body.replace(
                "<head>",
                (
                    "<head>\n"
                    f'<link rel="stylesheet" href="{katex_css_path}">\n'
                    "<style>\n"
                    f'{self.css}\n'
                    "  .katex, .katex-display {\n"
                    "    white-space: normal !important;\n"
                    "    font-size: 1.15em;\n"
                    "  }\n"
                    "  .katex-display {\n"
                    "    overflow-wrap: anywhere;\n"
                    "    word-break: break-word;\n"
                    "    line-break: anywhere;\n"
                    "    text-align: center;\n"
                    "  }\n"
                    "  .katex-display > .katex {\n"
                    "    display: inline-block;\n"
                    "    max-width: 100%;\n"
                    "  }\n"
                    "  .katex-display .katex {\n"
                    "    font-size: 1em;\n"
                    "  }\n"
                    "  /* Fix for radical symbols in denominators - allow vertical overflow */\n"
                    "  .katex .sqrt > .vlist-t,\n"
                    "  .katex .root > .vlist-t {\n"
                    "    overflow: visible !important;\n"
                    "  }\n"
                    "  .katex .stretchy:has(> svg),\n"
                    "  .katex .sqrt .stretchy,\n"
                    "  .katex .root .stretchy {\n"
                    "    overflow: visible !important;\n"
                    "    min-height: auto !important;\n"
                    "  }\n"
                    "  .katex .sqrt svg,\n"
                    "  .katex .root svg {\n"
                    "    overflow: visible !important;\n"
                    "    max-height: none !important;\n"
                    "  }\n"
                    "  pre, code, pre code {\n"
                    "    overflow-wrap: break-word !important;\n"
                    "    word-wrap: break-word !important;\n"
                    "    word-break: break-all !important;\n"
                    "    white-space: pre-wrap !important;\n"
                    "    max-width: 100% !important;\n"
                    "    box-sizing: border-box !important;\n"
                    "  }\n"
                    "  .markdown-section pre,\n"
                    "  .markdown-section pre code {\n"
                    "    overflow-wrap: break-word !important;\n"
                    "    word-wrap: break-word !important;\n"
                    "    word-break: break-all !important;\n"
                    "    white-space: pre-wrap !important;\n"
                    "    max-width: 100% !important;\n"
                    "    box-sizing: border-box !important;\n"
                    "  }\n"
                    "</style>\n"
                )
            )

            if self.debug_pdf:
                build_elapsed = time.perf_counter() - gen_start
                katex_count = html_full.count('<span class="katex') + html_full.count('<span class="katex-display')
                code_error_count = html_full.count('class="latex-error"')
                svg_count = html_full.count('<svg')
                print("*"*20)
                print(f"PDF: HTML built in {build_elapsed:.3f}s")
                print(f"PDF: html_len={len(html_full)}")
                print(f"PDF: KaTeX fragments={katex_count}, SVG elements={svg_count}, quarantined={code_error_count}")
                print("PDF: starting WeasyPrint write_pdf")
                print("*"*20)
            t_wp0 = time.perf_counter()
            try:
                pdf_bytes = self._render_with_timeout(html_full)
            except TimeoutError:
                if self.debug_pdf:
                    print("*"*20, "\nPDF: render timed out; returning error without retry\n", "*"*20)
                raise RuntimeError("PDF generation timed out. Please try again.")
            t_wp1 = time.perf_counter()
            if self.debug_pdf:
                print("*"*20, f"\nPDF: WeasyPrint write_pdf completed in {t_wp1 - t_wp0:.3f}s; total {t_wp1 - gen_start:.3f}s\n", "*"*20)
            return pdf_bytes
        except Exception as e:
            if self.debug_pdf:
                print("*"*20, f"\nPDF: generation failed: {e}\n", "*"*20)
            raise e
        finally:
            self.cleanup_temp_images()
