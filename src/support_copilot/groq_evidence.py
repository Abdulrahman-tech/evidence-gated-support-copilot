"""Groq adapter for strict evidence verification."""

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


DEFAULT_GROQ_MODEL = "openai/gpt-oss-20b"
DEFAULT_GROQ_SEED = 2755
DEFAULT_GROQ_TEMPERATURE = 0.0
DEFAULT_GROQ_MAX_RETRIES = 3


class GroqEvidenceVerifier:
    """Use Groq strict structured output, then apply the local contract."""

    provider_name = "groq"

    def __init__(
        self,
        model: str = DEFAULT_GROQ_MODEL,
        client: Any | None = None,
        timeout_seconds: float = 20.0,
        max_retries: int = DEFAULT_GROQ_MAX_RETRIES,
    ) -> None:
        if not model.strip():
            raise ValueError("Groq evidence verifier requires a model")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        if client is None:
            try:
                from groq import Groq
            except ImportError as error:
                raise RuntimeError(
                    "Groq evidence verification requires the 'groq' extra"
                ) from error
            client = Groq(timeout=timeout_seconds, max_retries=max_retries)
        self.client = client
        self.model = model
        self.last_system_fingerprint: str | None = None
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
        messages = [
            {"role": "system", "content": EVIDENCE_SYSTEM_INSTRUCTIONS},
            {
                "role": "user",
                "content": json.dumps(model_input, ensure_ascii=False),
            },
        ]

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "evidence_verification",
                    "strict": True,
                    "schema": EVIDENCE_RESPONSE_SCHEMA,
                },
            },
            max_completion_tokens=700,
            temperature=DEFAULT_GROQ_TEMPERATURE,
            seed=DEFAULT_GROQ_SEED,
        )
        self.last_system_fingerprint = getattr(response, "system_fingerprint", None)
        choices = getattr(response, "choices", ())
        if not choices:
            raise RuntimeError("Groq evidence verification returned no choices")
        choice = choices[0]
        if getattr(choice, "finish_reason", None) != "stop":
            raise RuntimeError("Groq evidence verification response was incomplete")
        content = getattr(getattr(choice, "message", None), "content", "")
        if not content:
            raise RuntimeError("Groq evidence verification returned no structured output")
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as error:
            raise ValueError("Groq evidence verification returned invalid JSON") from error
        if not isinstance(payload, Mapping):
            raise ValueError("Groq evidence verification must return an object")
        return payload

    def verify(
        self,
        question: str,
        candidates: list[SearchResult],
    ) -> EvidenceVerification:
        return self._structured.verify(question, candidates)
