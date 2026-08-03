import random
import shutil
import string

import pytest

from open_webui.models.chats import ChatTitleMessagesForm
from open_webui.utils.katex_compiler import KaTeXCompiler
from open_webui.utils.pdf_generator import PDFGenerator


def make_generator(messages=None):
    return PDFGenerator(ChatTitleMessagesForm(title="test", messages=messages or []))


def detect(content):
    return make_generator().detect_latex_in_message(content)


class TestLatexDetection:
    """
    The backend must recognize the same spans as the frontend tokenizer in
    src/lib/utils/marked/katex-extension.ts, or the PDF shows different
    content from the chat the user exported.
    """

    def test_inline_math_is_detected(self):
        found = detect("The derivative of $x^2$ is $2x$.")
        assert [item["expression"] for item in found] == ["x^2", "2x"]
        assert all(item["display"] is False for item in found)

    def test_display_math_is_detected(self):
        found = detect("Result:\n$$f'(x) = 2x$$\ndone.")
        assert len(found) == 1
        assert found[0]["display"] is True

    def test_currency_is_not_math(self):
        assert detect("The book costs $20 and the pen costs $5.") == []

    def test_currency_mixed_with_math_keeps_only_the_math(self):
        found = detect("It costs $20, and the derivative of $x^2$ is $2x$.")
        assert [item["expression"] for item in found] == ["x^2", "2x"]

    def test_span_does_not_cross_a_blank_line(self):
        assert detect("Total is $30 for today.\n\nAnother $40 tomorrow.") == []

    def test_delimiter_glued_to_a_word_is_not_math(self):
        assert detect("read the file cost$total and price$sum now") == []

    def test_latex_inside_fenced_code_is_skipped(self):
        assert detect("```\nprintf(\"$x^2$\")\n```") == []

    def test_latex_inside_inline_code_is_skipped(self):
        assert detect("Write `$x^2$` to typeset it.") == []

    def test_paren_and_bracket_delimiters(self):
        found = detect("Inline \\(a+b\\) and block \\[c+d\\] here.")
        assert [item["expression"] for item in found] == ["a+b", "c+d"]
        assert [item["display"] for item in found] == [False, True]

    def test_equation_environment(self):
        found = detect("\\begin{equation}E = mc^2\\end{equation}")
        assert found[0]["expression"] == "E = mc^2"
        assert found[0]["display"] is True

    def test_matches_are_returned_in_document_order(self):
        found = detect("$$a$$ then $b$ then $$c$$")
        starts = [item["start"] for item in found]
        assert starts == sorted(starts)


class TestSoftBreaks:
    """
    \\allowbreak is undefined in text mode. Injecting it into a \\text{}
    argument makes KaTeX render the whole expression as a red error.
    """

    def test_text_argument_is_left_untouched(self):
        expr = r"\text{Answer: } f(x) = x^2"
        assert r"\text{Answer: }" in make_generator()._insert_soft_breaks(expr)

    def test_comma_inside_text_is_left_untouched(self):
        expr = r"\text{Let's solve, step by step}"
        assert make_generator()._insert_soft_breaks(expr) == expr

    def test_math_outside_text_still_gets_breaks(self):
        out = make_generator()._insert_soft_breaks(r"\text{Area} = a \cdot b + c")
        assert r"\text{Area}" in out
        assert r"\allowbreak" in out.split(r"\text{Area}")[1]

    def test_textbf_is_matched_as_its_own_command(self):
        expr = r"\textbf{a, b}"
        assert make_generator()._insert_soft_breaks(expr) == expr

    def test_mandatory_argument_stays_attached_to_its_command(self):
        out = make_generator()._insert_soft_breaks(r"\sqrt[3]{27}")
        assert out == r"\sqrt[3]{27}"

    def test_scripted_sign_is_not_broken(self):
        out = make_generator()._insert_soft_breaks("10^-3")
        assert out == "10^-3"

    def test_matrix_entries_are_left_alone(self):
        expr = r"\begin{pmatrix} 2 & 3 \\ 1 & -1 \end{pmatrix}"
        assert make_generator()._insert_soft_breaks(expr) == expr

    def test_short_expressions_are_not_rewritten(self):
        _, to_render = make_generator()._extract_latex("$a + b = c$")
        assert to_render == [("a + b = c", False)]

    def test_long_expressions_are_still_broken(self):
        long_expr = "x_{1} + x_{2} + x_{3} + x_{4} + x_{5} + x_{6} + x_{7} + x_{8} = y"
        _, to_render = make_generator()._extract_latex(f"${long_expr}$")
        assert r"\allowbreak" in to_render[0][0]


class TestMessageBody:
    def test_math_is_replaced_by_placeholders(self):
        body, to_render = make_generator()._extract_latex("Given $x^2$ and $y^2$.")
        assert "$" not in body
        assert len(to_render) == 2

    def test_html_in_text_is_escaped_whether_or_not_math_is_present(self):
        generator = make_generator()
        with_math, _ = generator._extract_latex("Use <b>bold</b> with $x$.")
        without_math, _ = generator._extract_latex("Use <b>bold</b> with no math.")
        assert "<b>" not in with_math
        assert "<b>" not in without_math

    def test_fragments_are_spliced_back_in_order(self):
        generator = make_generator()
        body, to_render = generator._extract_latex("Given $x^2$ and $y^2$.")
        out = generator._apply_latex_fragments(body, ["<i>FIRST</i>", "<i>SECOND</i>"])
        assert out.index("FIRST") < out.index("SECOND")
        assert "xkatexph" not in out

    def test_list_normalization_cannot_touch_rendered_math(self):
        generator = make_generator()
        body, _ = generator._extract_latex("Steps:\n- compute $a - b$ - then check")
        assert generator._fix_broken_list_items(body).count("xkatexph0endx") == 1


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for KaTeX")
class TestKaTeXBatch:
    def test_one_bad_expression_does_not_discard_the_others(self):
        compiler = KaTeXCompiler()
        rendered = compiler.render_many_to_html(
            [("x^2", False), ("\\nosuchmacro{", False), ("y^2", False)]
        )
        assert len(rendered) == 3
        assert "katex" in rendered[0]
        assert "katex" in rendered[2]

    def test_results_line_up_with_inputs_when_some_are_cached(self):
        compiler = KaTeXCompiler()
        compiler.render_many_to_html([("a+b", False)])
        rendered = compiler.render_many_to_html([("a+b", False), ("c+d", True), ("a+b", False)])
        assert len(rendered) == 3
        assert rendered[0] == rendered[2]
        assert "katex-display" in rendered[1]


class TestRenderTransport:
    """
    Regression test for the failure that made every large export report a
    timeout: the parent joined the renderer process before reading its queue,
    so any PDF above the 64 KiB pipe buffer deadlocked the child.
    """

    def test_pdf_larger_than_the_pipe_buffer_is_returned(self):
        rnd = random.Random(7)
        vocabulary = [
            "".join(rnd.choice(string.ascii_lowercase) for _ in range(rnd.randint(3, 11)))
            for _ in range(2000)
        ]
        messages = [
            {
                "role": "assistant",
                "content": " ".join(rnd.choice(vocabulary) for _ in range(120)),
                "timestamp": 1735689600 + i,
            }
            for i in range(60)
        ]
        pdf_bytes = make_generator(messages).generate_chat_pdf()
        assert pdf_bytes.startswith(b"%PDF")
        assert len(pdf_bytes) > 64 * 1024

    def test_timeout_is_scaled_to_the_conversation(self):
        short = make_generator([{"role": "user", "content": "hi"}])
        long = make_generator([{"role": "user", "content": "hi"}] * 200)
        assert short._render_timeout() == 60.0
        assert long._render_timeout() > short._render_timeout()
