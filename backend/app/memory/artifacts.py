from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Iterable, Optional

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import MemoryArtifact as DBMemoryArtifact


VALID_ARTIFACT_KINDS = {"fact", "preference", "summary", "episode"}


@dataclass
class MemoryArtifactCandidate:
    kind: str
    content: str
    title: str = ""
    key: str = ""
    value: str = ""
    category: str = ""
    confidence: float = 0.8
    source: str = "consolidation"
    evidence: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def normalized_kind(self) -> str:
        kind = self.kind.strip().lower()
        if kind == "profile":
            return "fact"
        if kind == "pref":
            return "preference"
        return kind

    def normalized_content(self) -> str:
        content = self.content.strip()
        if content:
            return content
        if self.key.strip() and self.value.strip():
            return f"{self.key.strip()}: {self.value.strip()}"
        return self.value.strip()


@dataclass
class MemoryArtifactDecision:
    action: str
    kind: str
    content: str
    reason: str
    artifact_id: str = ""
    confidence: float = 0.0


class MemoryArtifactManager:
    """Stores high-density memory artifacts separate from raw chat messages."""

    def __init__(self, db: AsyncSession, user_id: str):
        self.db = db
        self.user_id = user_id

    async def process_candidates(
        self,
        candidates: Iterable[MemoryArtifactCandidate],
        *,
        session_id: Optional[str] = None,
    ) -> list[MemoryArtifactDecision]:
        decisions: list[MemoryArtifactDecision] = []
        for candidate in candidates:
            decision = await self.process_candidate(candidate, session_id=session_id)
            decisions.append(decision)
        return decisions

    async def process_candidate(
        self,
        candidate: MemoryArtifactCandidate,
        *,
        session_id: Optional[str] = None,
    ) -> MemoryArtifactDecision:
        kind = candidate.normalized_kind()
        content = candidate.normalized_content()
        confidence = max(0.0, min(float(candidate.confidence or 0.0), 1.0))

        if kind not in VALID_ARTIFACT_KINDS:
            return MemoryArtifactDecision(
                action="discard",
                kind=kind,
                content=content,
                reason="unsupported_kind",
                confidence=confidence,
            )
        if not content:
            return MemoryArtifactDecision(
                action="discard",
                kind=kind,
                content="",
                reason="empty_content",
                confidence=confidence,
            )
        sanitized_content = self._sanitize_content(content)
        if not sanitized_content:
            return MemoryArtifactDecision(
                action="discard",
                kind=kind,
                content=content[:200],
                reason="raw_transcript_or_prompt_fragment",
                confidence=confidence,
            )
        content = sanitized_content
        if confidence < 0.25:
            return MemoryArtifactDecision(
                action="discard",
                kind=kind,
                content=content,
                reason="low_confidence",
                confidence=confidence,
            )

        if kind == "summary" and session_id:
            existing = await self.get_session_summary(session_id)
            if existing:
                existing.content = content
                existing.title = candidate.title.strip() or existing.title or "会话摘要"
                existing.confidence = confidence
                existing.source = candidate.source
                existing.artifact_metadata = self._metadata_json(candidate)
                decision = MemoryArtifactDecision(
                    action="update",
                    kind=kind,
                    content=content,
                    reason="session_summary_refreshed",
                    artifact_id=str(existing.id),
                    confidence=confidence,
                )
                await self.db.flush()
                return decision

        duplicate = await self.find_exact_active(kind=kind, content=content, session_id=session_id)
        if duplicate:
            return MemoryArtifactDecision(
                action="skip",
                kind=kind,
                content=content,
                reason="duplicate_content",
                artifact_id=str(duplicate.id),
                confidence=confidence,
            )

        artifact = DBMemoryArtifact(
            user_id=self.user_id,
            session_id=session_id,
            kind=kind,
            title=candidate.title.strip() or self._default_title(kind),
            content=content,
            artifact_metadata=self._metadata_json(candidate),
            confidence=confidence,
            source=candidate.source,
            is_active=True,
        )
        self.db.add(artifact)
        await self.db.flush()
        return MemoryArtifactDecision(
            action="add",
            kind=kind,
            content=content,
            reason="accepted",
            artifact_id=str(artifact.id),
            confidence=confidence,
        )

    async def get_session_summary(self, session_id: str) -> DBMemoryArtifact | None:
        result = await self.db.execute(
            select(DBMemoryArtifact)
            .where(
                DBMemoryArtifact.user_id == self.user_id,
                DBMemoryArtifact.session_id == session_id,
                DBMemoryArtifact.kind == "summary",
                DBMemoryArtifact.is_active.is_(True),
            )
            .order_by(desc(DBMemoryArtifact.updated_at), desc(DBMemoryArtifact.created_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def find_exact_active(
        self,
        *,
        kind: str,
        content: str,
        session_id: Optional[str] = None,
    ) -> DBMemoryArtifact | None:
        conditions = [
            DBMemoryArtifact.user_id == self.user_id,
            DBMemoryArtifact.kind == kind,
            DBMemoryArtifact.content == content,
            DBMemoryArtifact.is_active.is_(True),
        ]
        if session_id and kind in {"summary", "episode"}:
            conditions.append(DBMemoryArtifact.session_id == session_id)
        result = await self.db.execute(
            select(DBMemoryArtifact)
            .where(and_(*conditions))
            .order_by(desc(DBMemoryArtifact.updated_at), desc(DBMemoryArtifact.created_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def search(
        self,
        *,
        query: str,
        kinds: list[str],
        limit: int = 5,
        session_id: Optional[str] = None,
    ) -> list[DBMemoryArtifact]:
        safe_kinds = [kind for kind in kinds if kind in VALID_ARTIFACT_KINDS]
        if not safe_kinds:
            return []
        conditions = [
            DBMemoryArtifact.user_id == self.user_id,
            DBMemoryArtifact.kind.in_(safe_kinds),
            DBMemoryArtifact.is_active.is_(True),
        ]
        if session_id:
            conditions.append(DBMemoryArtifact.session_id == session_id)
        result = await self.db.execute(
            select(DBMemoryArtifact)
            .where(and_(*conditions))
            .order_by(desc(DBMemoryArtifact.updated_at), desc(DBMemoryArtifact.created_at))
            .limit(80)
        )
        artifacts = list(result.scalars().all())
        scored = [
            (self.score_text(query, f"{artifact.title or ''} {artifact.content}"), artifact)
            for artifact in artifacts
        ]
        scored = [(score, artifact) for score, artifact in scored if score >= 0.2]
        scored.sort(key=lambda item: (item[0], item[1].updated_at or item[1].created_at or datetime.min), reverse=True)
        return [artifact for _, artifact in scored[: max(1, limit)]]

    @staticmethod
    def score_text(query: str, content: str) -> float:
        normalized_query = MemoryArtifactManager._normalize(query)
        normalized_content = MemoryArtifactManager._normalize(content)
        if not normalized_query or not normalized_content:
            return 0.0
        if normalized_query in normalized_content:
            return 1.0

        tokens = MemoryArtifactManager._tokens(normalized_query)
        if not tokens:
            return 0.0
        matches = sum(1 for token in tokens if token in normalized_content)
        return matches / len(tokens)

    @staticmethod
    def _normalize(value: str) -> str:
        return str(value or "").strip().lower()

    @staticmethod
    def _tokens(value: str) -> list[str]:
        text = MemoryArtifactManager._normalize(value)
        raw_tokens = [token for token in text.replace("，", " ").replace("。", " ").split() if token]
        if len(raw_tokens) > 1:
            return raw_tokens
        if len(raw_tokens) == 1 and raw_tokens[0] != text:
            return raw_tokens
        return [text[index : index + 2] for index in range(0, max(len(text) - 1, 0))]

    @staticmethod
    def _default_title(kind: str) -> str:
        return {
            "fact": "用户事实",
            "preference": "用户偏好",
            "summary": "会话摘要",
            "episode": "经历片段",
        }.get(kind, "记忆")

    @staticmethod
    def _sanitize_content(content: str) -> str:
        text = str(content or "").strip()
        if not text:
            return ""
        lowered = text.lower()
        blocked_fragments = (
            "extract memory candidates now",
            "conversation window:",
            "return json only",
            "memory extractor for serana",
        )
        if any(fragment in lowered for fragment in blocked_fragments):
            return ""
        raw_role_lines = sum(
            1
            for line in text.splitlines()
            if line.strip().lower().startswith(("user:", "assistant:", "system:"))
        )
        if raw_role_lines >= 2:
            return ""
        text = re.sub(r"(?im)^\s*(user|assistant|system):\s*", "", text)
        return text.strip()

    @staticmethod
    def _metadata_json(candidate: MemoryArtifactCandidate) -> str:
        metadata = dict(candidate.metadata or {})
        if candidate.key:
            metadata["key"] = candidate.key
        if candidate.value:
            metadata["value"] = candidate.value
        if candidate.category:
            metadata["category"] = candidate.category
        if candidate.evidence:
            metadata["evidence"] = candidate.evidence
        return json.dumps(metadata, ensure_ascii=False)


def candidate_asdict(candidate: MemoryArtifactCandidate) -> dict[str, Any]:
    return asdict(candidate)
