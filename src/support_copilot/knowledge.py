"""A deterministic lexical retriever suitable for an offline MVP and evals."""

import math
import re
from collections import Counter
from dataclasses import dataclass

from support_copilot.models import KnowledgeDocument, SearchResult


TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
DEFAULT_MINIMUM_SCORE = 9.0
DEFAULT_MINIMUM_SCORE_RATIO = 1.1
STOP_WORDS = frozenset(
    {
        "a", "agent", "agents", "an", "and", "ask", "asked", "asks", "can",
        "customer", "customers", "do", "for", "help", "i", "information", "is",
        "issue", "issues", "me", "my", "of", "policies", "policy", "problem",
        "problems", "question", "questions", "request", "requests", "support", "the",
        "to",
    }
)


def tokenize(text: str) -> list[str]:
    return [
        token
        for token in TOKEN_PATTERN.findall(text.lower())
        if token not in STOP_WORDS
    ]


@dataclass(frozen=True)
class _Passage:
    document: KnowledgeDocument
    text: str
    terms: Counter[str]


class KnowledgeBase:
    """Index documents as passages and rank them with explainable BM25 scores."""

    def __init__(self, documents: list[KnowledgeDocument], chunk_words: int = 120) -> None:
        if not documents:
            raise ValueError("at least one knowledge document is required")
        if chunk_words < 20:
            raise ValueError("chunk_words must be at least 20")
        identities = [(document.tenant_id, document.document_id) for document in documents]
        if len(set(identities)) != len(identities):
            raise ValueError("document ids must be unique within each tenant")
        self._passages = self._chunk(documents, chunk_words)
        self._passages_by_tenant: dict[str, list[_Passage]] = {}
        for passage in self._passages:
            self._passages_by_tenant.setdefault(
                passage.document.tenant_id, []
            ).append(passage)
        self._document_frequency_by_tenant: dict[str, Counter[str]] = {}
        self._average_passage_length_by_tenant: dict[str, float] = {}
        for tenant_id, tenant_passages in self._passages_by_tenant.items():
            document_frequency: Counter[str] = Counter()
            for passage in tenant_passages:
                document_frequency.update(passage.terms.keys())
            self._document_frequency_by_tenant[tenant_id] = document_frequency
            self._average_passage_length_by_tenant[tenant_id] = sum(
                sum(passage.terms.values()) for passage in tenant_passages
            ) / len(tenant_passages)

    @property
    def tenant_ids(self) -> frozenset[str]:
        return frozenset(self._passages_by_tenant)

    @staticmethod
    def _chunk(documents: list[KnowledgeDocument], chunk_words: int) -> list[_Passage]:
        passages: list[_Passage] = []
        for document in documents:
            if not document.document_id or not document.title or not document.text.strip():
                raise ValueError("documents require an id, title, and non-empty text")
            words = document.text.split()
            for start in range(0, len(words), chunk_words):
                text = " ".join(words[start : start + chunk_words])
                index_text = f"{document.title} {document.title} {text}"
                passages.append(_Passage(document, text, Counter(tokenize(index_text))))
        return passages

    def search(
        self,
        query: str,
        limit: int = 3,
        tenant_id: str | None = None,
    ) -> list[SearchResult]:
        if not query.strip():
            raise ValueError("query must contain searchable text")
        query_terms = Counter(tokenize(query))
        if not query_terms:
            return []
        if limit <= 0:
            raise ValueError("limit must be greater than zero")
        if tenant_id is None:
            if len(self._passages_by_tenant) != 1:
                raise ValueError("tenant_id is required for a multi-tenant knowledge base")
            tenant_id = next(iter(self._passages_by_tenant))
        passages = self._passages_by_tenant.get(tenant_id)
        if passages is None:
            raise ValueError("unknown tenant_id")

        scored: list[tuple[float, _Passage]] = []
        passage_count = len(passages)
        document_frequency = self._document_frequency_by_tenant[tenant_id]
        average_passage_length = self._average_passage_length_by_tenant[tenant_id]
        k1 = 1.5
        b = 0.75
        for passage in passages:
            score = 0.0
            passage_length = sum(passage.terms.values())
            for term in query_terms:
                term_count = passage.terms.get(term, 0)
                if term_count:
                    inverse_frequency = math.log(
                        1
                        + (passage_count - document_frequency[term] + 0.5)
                        / (document_frequency[term] + 0.5)
                    )
                    length_normalization = 1 - b + b * (
                        passage_length / average_passage_length
                    )
                    score += inverse_frequency * (
                        term_count * (k1 + 1)
                    ) / (term_count + k1 * length_normalization)
            if score:
                scored.append((score, passage))

        scored.sort(key=lambda item: (-item[0], item[1].document.document_id))
        results = []
        seen_document_ids = set()
        for score, passage in scored:
            if passage.document.document_id in seen_document_ids:
                continue
            seen_document_ids.add(passage.document.document_id)
            results.append(
                SearchResult(
                    document_id=passage.document.document_id,
                    title=passage.document.title,
                    source=passage.document.source,
                    passage=passage.text,
                    score=round(score, 4),
                    tenant_id=passage.document.tenant_id,
                )
            )
            if len(results) == limit:
                break
        return results


def retrieval_is_confident(
    results: list[SearchResult],
    minimum_score: float = DEFAULT_MINIMUM_SCORE,
    minimum_score_ratio: float = DEFAULT_MINIMUM_SCORE_RATIO,
) -> bool:
    if not results or results[0].score < minimum_score:
        return False
    if len(results) == 1:
        return True
    return results[0].score / results[1].score >= minimum_score_ratio
