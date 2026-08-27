"""OpenAI Responses API adapter for strict evidence verification."""

import json
from collections.abc import Mapping
from typing import Any

from support_copilot.evidence import (
    EVIDENCE_RESPONSE_SCHEMA,
    EVIDENCE_SYSTEM_INSTRUCTIONS,
    EvidenceVerification,
    StructuredEvidenceVerifier,
)
from support_copilot.models import SearchResult


class OpenAIEvidenceVerifier:
    """Use strict structured output, then apply the local evidence contract."""

    provider_name = "openai"

    def __init__(
        self,
        model: str,
        client: Any | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        if not model.strip():
            raise ValueError("OpenAI evidence verifier requires a model")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if client is None:
            try:
                from openai import OpenAI
            except ImportError as error:
                raise RuntimeError(
                    "OpenAI evidence verification requires the 'openai' extra"
                ) from error
            client = OpenAI(timeout=timeout_seconds, max_retries=2)
        self.client = client
        self.model = model
        self._structured = StructuredEvidenceVerifier(self._call_model)

    def _call_model(
        self,
        question: str,
        candidates: list[SearchResult],
    ) -> Mapping[str, object]:
        model_input = {
            "question": question,
            "candidates": [
                {
                    "document_id": candidate.document_id,
                    "title": candidate.title,
                    "passage": candidate.passage,
                }
                for candidate in candidates
            ],
        }
        response = self.client.responses.create(
            model=self.model,
            input=[
                {"role": "developer", "content": EVIDENCE_SYSTEM_INSTRUCTIONS},
                {
                    "role": "user",
                    "content": json.dumps(model_input, ensure_ascii=False),
                },
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "evidence_verification",
                    "strict": True,
                    "schema": EVIDENCE_RESPONSE_SCHEMA,
                }
            },
            max_output_tokens=700,
            store=False,
        )
        if getattr(response, "status", None) != "completed":
            raise RuntimeError("OpenAI evidence verification response was incomplete")
        output_text = getattr(response, "output_text", "")
        if not output_text:
            raise RuntimeError("OpenAI evidence verification returned no structured output")
        try:
            payload = json.loads(output_text)
        except json.JSONDecodeError as error:
            raise ValueError("OpenAI evidence verification returned invalid JSON") from error
        if not isinstance(payload, Mapping):
            raise ValueError("OpenAI evidence verification must return an object")
        return payload

    def verify(
        self,
        question: str,
        candidates: list[SearchResult],
    ) -> EvidenceVerification:
        return self._structured.verify(question, candidates)
