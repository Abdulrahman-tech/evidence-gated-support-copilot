"""Optional local semantic reranking for the BM25 retrieval candidate."""

from dataclasses import dataclass

from support_copilot.knowledge import KnowledgeBase, retrieval_is_confident
from support_copilot.models import KnowledgeDocument, SearchResult


@dataclass(frozen=True)
class HybridRetrieval:
    results: tuple[SearchResult, ...]
    lexical_confident: bool


def reciprocal_rank_fusion(
    document_ids: list[str],
    lexical_order: list[str],
    semantic_order: list[str],
    rank_constant: int = 60,
    semantic_weight: float = 1.0,
) -> list[tuple[str, float]]:
    if rank_constant < 0:
        raise ValueError("rank_constant cannot be negative")
    if semantic_weight < 0:
        raise ValueError("semantic_weight cannot be negative")
    lexical_ranks = {
        document_id: rank for rank, document_id in enumerate(lexical_order, 1)
    }
    semantic_ranks = {
        document_id: rank for rank, document_id in enumerate(semantic_order, 1)
    }
    fused = []
    for document_id in document_ids:
        score = 0.0
        if document_id in lexical_ranks:
            score += 1 / (rank_constant + lexical_ranks[document_id])
        if document_id in semantic_ranks:
            score += semantic_weight / (
                rank_constant + semantic_ranks[document_id]
            )
        fused.append((document_id, score))
    return sorted(fused, key=lambda item: (-item[1], item[0]))


class HybridKnowledgeBase:
    """Fuse BM25 and local sentence-embedding ranks while retaining the BM25 gate."""

    def __init__(
        self,
        documents: list[KnowledgeDocument],
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        rank_constant: int = 60,
        semantic_weight: float = 1.0,
    ) -> None:
        try:
            import numpy as np
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise RuntimeError(
                "hybrid retrieval requires the optional 'semantic' dependencies"
            ) from error

        self._np = np
        self._documents = documents
        self._rank_constant = rank_constant
        self._semantic_weight = semantic_weight
        self._documents_by_id = {
            document.document_id: document for document in documents
        }
        self._lexical = KnowledgeBase(documents)
        self._model = SentenceTransformer(model_name, local_files_only=True)
        self._document_vectors = self._model.encode(
            [f"{document.title}. {document.text}" for document in documents],
            normalize_embeddings=True,
        )

    def retrieve(self, query: str, limit: int = 3) -> HybridRetrieval:
        if limit <= 0:
            raise ValueError("limit must be greater than zero")
        lexical_results = self._lexical.search(query, limit=len(self._documents))
        query_vector = self._model.encode([query], normalize_embeddings=True)[0]
        similarities = self._np.asarray(self._document_vectors @ query_vector)
        semantic_indexes = self._np.argsort(-similarities)
        semantic_order = [
            self._documents[int(index)].document_id for index in semantic_indexes
        ]
        fused = reciprocal_rank_fusion(
            [document.document_id for document in self._documents],
            [result.document_id for result in lexical_results],
            semantic_order,
            rank_constant=self._rank_constant,
            semantic_weight=self._semantic_weight,
        )
        results = []
        for document_id, score in fused[:limit]:
            document = self._documents_by_id[document_id]
            results.append(
                SearchResult(
                    document_id=document.document_id,
                    title=document.title,
                    source=document.source,
                    passage=document.text,
                    score=round(score, 6),
                    tenant_id=document.tenant_id,
                )
            )
        return HybridRetrieval(
            results=tuple(results),
            lexical_confident=retrieval_is_confident(lexical_results),
        )
