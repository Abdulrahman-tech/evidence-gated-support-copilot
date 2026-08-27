"""Grounded customer-support drafting with measurable retrieval quality."""

from support_copilot.copilot import SupportCopilot
from support_copilot.evidence import EvidenceDecision, EvidenceVerification
from support_copilot.knowledge import KnowledgeBase
from support_copilot.models import DraftResponse, KnowledgeDocument

__all__ = [
    "DraftResponse",
    "EvidenceDecision",
    "EvidenceVerification",
    "KnowledgeBase",
    "KnowledgeDocument",
    "SupportCopilot",
]
