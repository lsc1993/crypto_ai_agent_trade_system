"""Request-local immutable evidence shared by fixed public collection paths."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pydantic import JsonValue

from app.agent.model import ModelEvidenceKind


@dataclass(frozen=True)
class FrozenResearchEvidence:
    id: UUID
    kind: ModelEvidenceKind
    source: str
    source_url: str
    observed_at: datetime
    fetched_at: datetime
    summary: str
    content: str
    payload: dict[str, JsonValue]
