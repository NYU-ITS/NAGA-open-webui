from sentence_transformers import CrossEncoder
from typing import List
from langchain_core.documents import Document

class Reranker:
    def __init__(self):
        self.cross_encoder = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        self.min_confidence = 0.7  # Tune if needed

    def rerank(self, query: str, docs: List[Document], strategy: str = "cross-encoder", top_k: int = 5):
        if not docs:
            return []
        if strategy == "cross-encoder":
            return self._cross_encoder_rerank(query, docs, top_k)
        elif strategy == "hybrid":
            return self._hybrid_rerank(query, docs, top_k)
        else:
            return docs[:top_k]

    def _cross_encoder_rerank(self, query: str, docs: List[Document], top_k: int):
        pairs = [(query, d.page_content if hasattr(d, 'page_content') else str(d)) for d in docs]
        scores = self.cross_encoder.predict(pairs)
        ranked = sorted(zip(scores, docs), key=lambda x: x[0], reverse=True)
        return [doc for score, doc in ranked if score > self.min_confidence][:top_k]

    def _hybrid_rerank(self, query: str, docs: List[Document], top_k: int):
        pairs = [(query, d.page_content) for d in docs if hasattr(d, "page_content") and d.page_content.strip()]
        if not pairs:
            return docs[:top_k]
        scores = self.cross_encoder.predict(pairs)
        seen = set()
        reranked_docs = []
        for score, doc in sorted(zip(scores, docs), reverse=True):
            if hash(doc.page_content[:500]) not in seen and score > self.min_confidence:
                seen.add(hash(doc.page_content[:500]))
                reranked_docs.append(doc)
                if len(reranked_docs) >= top_k:
                    break
        return reranked_docs or docs[:top_k]

    def summarize_doc(self, llm: callable, doc: Document) -> str:
        prompt = f"""
You are an NSF grant writing assistant.

Summarize the following document into 5 required NSF 'Facilities and Resources' sections.

Structure:
1. Research Space and Facilities:
2. Core Instrumentation:
3. Computing and Data Resources:
4. Shared Facilities:
5. Special Infrastructure:

- Include technical and factual details (e.g., space sizes, equipment models, compute specs).
- Omit generic or background content.
- Write full sentences.

Document:
{doc.page_content}

Return the structured summary.
"""
        return llm.invoke(prompt).content.strip()

    def validate_response(self, llm: callable, response: str, reference_docs: List[Document], style_guide: str = None) -> str:
        summaries = "\n\n".join(
            f"Document {i+1} Summary:\n{self.summarize_doc(llm, d)}"
            for i, d in enumerate(reference_docs)
        )

        prompt = f"""
NSF RESPONSE VALIDATION TASK

You are an NSF grant writing assistant. Review the draft below and revise it based on these criteria:

---

### Validation Tasks

1. **Factual Accuracy**
   - Cross-check all claims and numbers against the reference summaries.
   - Remove unverifiable or speculative statements.

2. **Section Completeness**
   - Ensure all 5 sections are present:
     - Research Space and Facilities
     - Core Instrumentation
     - Computing and Data Resources
     - Shared/Campus-wide Facilities
     - Special Infrastructure

3. **Technical Specificity**
   - Add detailed facts (e.g., square footage, model names, specs).

4. **Style and Tone**
   - Use third-person, academic tone suited for NSF peer review.

5. **Clarity on Missing Data**
   - If info is missing, say so explicitly (e.g., "No details available").

---

### Input

**Draft Response:**  
{response}

**Reference Summaries:**  
{summaries}

---

Return ONLY the corrected version. Rewrite fully if needed. Maintain the original 5-section structure.
"""
        return llm.invoke(prompt).content
