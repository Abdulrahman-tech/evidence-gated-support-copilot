"""Domain models for the support copilot."""

from dataclasses import dataclass


@dataclass(frozen=True)
class KnowledgeDocument:
    document_id: str
    title: str
    text: str
    source: str
    tenant_id: str = "default"
    product_area: str = ""
    source_path: str = ""
    source_commit: str = ""


@dataclass(frozen=True)
class SearchResult:
    document_id: str
    title: str
    source: str
    passage: str
    score: float
    tenant_id: str = "default"


@dataclass(frozen=True)
class DraftResponse:
    answer: str
    citations: tuple[SearchResult, ...]
    needs_human_review: bool
    review_reasons: tuple[str, ...]
    evidence_decision: str
    scope_route: str
    trajectory: tuple[str, ...] = ()
