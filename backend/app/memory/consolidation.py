from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.memory.artifacts import (
    MemoryArtifactCandidate,
    MemoryArtifactDecision,
    MemoryArtifactManager,
    candidate_asdict,
)
from app.memory.facts import ProfileFactsManager
from app.memory.history import HistoryManager


logger = get_logger(__name__)


@dataclass
class ConsolidationCandidate:
    key: str
    value: str
    category: str
    source: str = "consolidation"
    confidence: float = 0.85
    evidence: str = ""


@dataclass
class ConsolidationDecision:
    action: str
    key: str
    value: str
    category: str
    reason: str
    confidence: float
    evidence: str = ""


class MemoryConsolidationService:
    """Extracts durable memory artifacts from chat turns.

    The service follows a Sebastian-style shape: first produce candidate artifacts
    from the conversation window, then validate/resolve/persist them through local
    managers. LLM output never mutates storage directly.
    """

    def __init__(self, db: AsyncSession, user_id: str):
        self.db = db
        self.user_id = user_id
        self.facts_manager = ProfileFactsManager(db, user_id)
        self.history_manager = HistoryManager(db, user_id)
        self.artifacts = MemoryArtifactManager(db, user_id)

    async def consolidate_chat_turn(
        self,
        *,
        user_input: str,
        session_id: Optional[str] = None,
        assistant_content: str = "",
        llm: BaseChatModel | None = None,
    ) -> dict[str, object]:
        messages = []
        if session_id:
            messages = await self.history_manager.get_messages_by_session(session_id, limit=16)

        artifact_candidates = await self._extract_artifact_candidates(
            user_input=user_input,
            assistant_content=assistant_content,
            session_id=session_id,
            messages=messages,
            llm=llm,
        )
        profile_candidates = self._profile_candidates_from_artifacts(artifact_candidates)

        saved: list[dict[str, str]] = []
        skipped: list[dict[str, str]] = []
        profile_decisions: list[dict[str, object]] = []

        for candidate in profile_candidates:
            existing = await self.facts_manager.get_fact(candidate.key)
            normalized_existing = self._normalize_value(existing.value) if existing else ""
            normalized_candidate = self._normalize_value(candidate.value)

            if existing and normalized_existing == normalized_candidate:
                decision = ConsolidationDecision(
                    action="skip",
                    key=candidate.key,
                    value=candidate.value,
                    category=candidate.category,
                    reason="duplicate_value",
                    confidence=candidate.confidence,
                    evidence=candidate.evidence,
                )
                skipped.append(
                    {
                        "key": candidate.key,
                        "value": candidate.value,
                        "category": candidate.category,
                        "reason": "duplicate_value",
                    }
                )
                profile_decisions.append(asdict(decision))
                continue

            fact = await self.facts_manager.add_fact(
                key=candidate.key,
                value=candidate.value,
                category=candidate.category,
                source=candidate.source,
                confidence=candidate.confidence,
            )
            saved.append(
                {
                    "key": fact.key,
                    "value": fact.value,
                    "category": fact.category or "",
                }
            )
            profile_decisions.append(
                asdict(
                    ConsolidationDecision(
                        action="save",
                        key=fact.key,
                        value=fact.value,
                        category=fact.category or "",
                        reason="stable_signal_detected",
                        confidence=candidate.confidence,
                        evidence=candidate.evidence,
                    )
                )
            )

        artifact_decisions = await self.artifacts.process_candidates(
            artifact_candidates,
            session_id=session_id,
        )

        if saved:
            logger.info("Consolidated %s long-term profile memory candidates", len(saved))
        accepted_artifacts = [
            decision for decision in artifact_decisions if decision.action in {"add", "update"}
        ]
        if accepted_artifacts:
            logger.info("Consolidated %s memory artifacts", len(accepted_artifacts))

        return {
            "candidate_count": len(profile_candidates),
            "artifact_candidate_count": len(artifact_candidates),
            "applied_count": len(saved) + len(accepted_artifacts),
            "saved": saved,
            "skipped": skipped,
            "decisions": profile_decisions,
            "artifact_candidates": [candidate_asdict(candidate) for candidate in artifact_candidates],
            "artifact_decisions": [asdict(decision) for decision in artifact_decisions],
            "extractor_version": "v3_artifact_consolidation",
        }

    async def _extract_artifact_candidates(
        self,
        *,
        user_input: str,
        assistant_content: str,
        session_id: Optional[str],
        messages: list[Any],
        llm: BaseChatModel | None,
    ) -> list[MemoryArtifactCandidate]:
        if llm is not None:
            llm_candidates = await self._extract_with_llm(
                llm,
                user_input=user_input,
                assistant_content=assistant_content,
                messages=messages,
            )
            if llm_candidates is not None:
                return llm_candidates

        return self._extract_with_rules(
            user_input=user_input,
            assistant_content=assistant_content,
            session_id=session_id,
            messages=messages,
        )

    async def _extract_with_llm(
        self,
        llm: BaseChatModel,
        *,
        user_input: str,
        assistant_content: str,
        messages: list[Any],
    ) -> list[MemoryArtifactCandidate] | None:
        window = self._conversation_window_text(
            messages,
            fallback_user=user_input,
            fallback_assistant=assistant_content,
        )
        try:
            response = await asyncio.wait_for(
                llm.ainvoke(
                    [
                        SystemMessage(
                            content=(
                                "You are a memory extractor for Serana. Extract only durable, useful memory artifacts. "
                                "Return JSON only with this schema: "
                                '{"artifacts":[{"kind":"fact|preference|summary|episode","title":"","content":"",'
                                '"key":"","value":"","category":"","confidence":0.0,"evidence":""}]}. '
                                "Use summary for a high-density session summary, episode for a concrete event or task outcome, "
                                "fact/preference for stable user information. Do not copy raw user:/assistant: transcripts. "
                                'If nothing is durable or useful, return {"artifacts":[]}.'
                            )
                        ),
                        HumanMessage(
                            content=(
                                f"Conversation window:\n{window}\n\n"
                                "Extract memory candidates now."
                            )
                        ),
                    ]
                ),
                timeout=30,
            )
        except TimeoutError:
            logger.warning("LLM memory extraction timed out; falling back to rule extraction")
            return None
        except Exception:
            logger.exception("LLM memory extraction failed")
            return None

        parsed = self._parse_json_object(str(response.content))
        raw_artifacts = parsed.get("artifacts") if isinstance(parsed, dict) else None
        if not isinstance(raw_artifacts, list):
            return None

        candidates: list[MemoryArtifactCandidate] = []
        for raw in raw_artifacts:
            if not isinstance(raw, dict):
                continue
            candidate = self._candidate_from_mapping(raw, source="llm_consolidation")
            if candidate:
                candidates.append(candidate)
        return candidates

    def _extract_with_rules(
        self,
        *,
        user_input: str,
        assistant_content: str,
        session_id: Optional[str],
        messages: list[Any],
    ) -> list[MemoryArtifactCandidate]:
        del session_id
        candidates: list[MemoryArtifactCandidate] = []

        for profile_candidate in self._extract_profile_candidates(user_input):
            kind = "preference" if profile_candidate.category == "preference" else "fact"
            candidates.append(
                MemoryArtifactCandidate(
                    kind=kind,
                    title="用户偏好" if kind == "preference" else "用户事实",
                    key=profile_candidate.key,
                    value=profile_candidate.value,
                    category=profile_candidate.category,
                    content=f"{profile_candidate.key}: {profile_candidate.value}",
                    confidence=profile_candidate.confidence,
                    source=profile_candidate.source,
                    evidence=profile_candidate.evidence,
                )
            )

        summary = self._build_rule_summary(messages, user_input=user_input, assistant_content=assistant_content)
        if summary:
            candidates.append(
                MemoryArtifactCandidate(
                    kind="summary",
                    title="会话摘要",
                    content=summary,
                    confidence=0.72,
                    source="rule_consolidation",
                )
            )

        episode = self._build_rule_episode(user_input=user_input, assistant_content=assistant_content)
        if episode:
            candidates.append(
                MemoryArtifactCandidate(
                    kind="episode",
                    title=self._episode_title(user_input),
                    content=episode,
                    confidence=0.68,
                    source="rule_consolidation",
                    evidence=user_input,
                )
            )

        return candidates

    def _profile_candidates_from_artifacts(
        self,
        candidates: list[MemoryArtifactCandidate],
    ) -> list[ConsolidationCandidate]:
        profile_candidates: list[ConsolidationCandidate] = []
        for candidate in candidates:
            kind = candidate.normalized_kind()
            if kind not in {"fact", "preference"}:
                continue
            key = candidate.key.strip() or self._infer_profile_key(candidate)
            value = candidate.value.strip() or candidate.normalized_content()
            if not key or not value:
                continue
            profile_candidates.append(
                ConsolidationCandidate(
                    key=key,
                    value=value,
                    category=candidate.category.strip() or ("preference" if kind == "preference" else "profile"),
                    source=candidate.source,
                    confidence=candidate.confidence,
                    evidence=candidate.evidence,
                )
            )
        return profile_candidates

    def _extract_profile_candidates(self, user_input: str) -> list[ConsolidationCandidate]:
        text = user_input.strip()
        if not text:
            return []

        candidates: list[ConsolidationCandidate] = []

        preference_value = self._extract_after_prefix(
            text,
            ["我平时喜欢", "我通常喜欢", "我一般喜欢", "我喜欢"],
        )
        if preference_value:
            candidates.append(
                ConsolidationCandidate(
                    key=self._infer_preference_key(preference_value),
                    value=preference_value,
                    category="preference",
                    evidence=text,
                )
            )

        stronger_preference = self._extract_after_prefix(text, ["我更偏好", "我偏好"])
        if stronger_preference:
            candidates.append(
                ConsolidationCandidate(
                    key=self._infer_preference_key(stronger_preference),
                    value=stronger_preference,
                    category="preference",
                    evidence=text,
                )
            )

        home_city = self._extract_after_prefix(text, ["我住在"])
        if home_city:
            candidates.append(
                ConsolidationCandidate(
                    key="home_city",
                    value=home_city,
                    category="profile",
                    confidence=0.8,
                    evidence=text,
                )
            )

        deduped: dict[str, ConsolidationCandidate] = {}
        for candidate in candidates:
            deduped[candidate.key] = candidate
        return list(deduped.values())

    @staticmethod
    def _candidate_from_mapping(raw: dict[str, Any], *, source: str) -> MemoryArtifactCandidate | None:
        content = str(raw.get("content") or raw.get("summary") or "").strip()
        key = str(raw.get("key") or "").strip()
        value = str(raw.get("value") or "").strip()
        if not content and not value:
            return None
        try:
            confidence = float(raw.get("confidence") or 0.75)
        except (TypeError, ValueError):
            confidence = 0.75
        return MemoryArtifactCandidate(
            kind=str(raw.get("kind") or "").strip().lower(),
            title=str(raw.get("title") or "").strip(),
            content=content,
            key=key,
            value=value,
            category=str(raw.get("category") or "").strip(),
            confidence=confidence,
            source=source,
            evidence=str(raw.get("evidence") or "").strip(),
            metadata=dict(raw.get("metadata") or {}) if isinstance(raw.get("metadata"), dict) else {},
        )

    @staticmethod
    def _parse_json_object(raw_text: str) -> dict[str, Any]:
        text = str(raw_text or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text)
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                return {}
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _conversation_window_text(
        messages: list[Any],
        *,
        fallback_user: str,
        fallback_assistant: str,
    ) -> str:
        if messages:
            lines = []
            for message in messages[-16:]:
                role = str(getattr(message, "role", "") or "message")
                content = str(getattr(message, "content", "") or "").strip()
                if content:
                    lines.append(f"{role}: {content[:1200]}")
            if lines:
                return "\n".join(lines)
        return f"user: {fallback_user}\nassistant: {fallback_assistant}"

    @staticmethod
    def _build_rule_summary(messages: list[Any], *, user_input: str, assistant_content: str) -> str:
        meaningful_messages = [
            message
            for message in messages
            if str(getattr(message, "content", "") or "").strip()
        ]
        if len(meaningful_messages) >= 4:
            user_messages = [
                str(getattr(message, "content", "") or "").strip()
                for message in meaningful_messages
                if getattr(message, "role", "") == "user" and str(getattr(message, "content", "") or "").strip()
            ]
            assistant_messages = [
                str(getattr(message, "content", "") or "").strip()
                for message in meaningful_messages
                if getattr(message, "role", "") == "assistant" and str(getattr(message, "content", "") or "").strip()
            ]
            if user_messages or assistant_messages:
                latest_user = user_messages[-1] if user_messages else user_input
                latest_assistant = assistant_messages[-1] if assistant_messages else assistant_content
                return (
                    f"用户最近关注：{latest_user[:180]}。"
                    f"Serana 已回应/处理：{latest_assistant[:260]}。"
                )
        return ""

    @staticmethod
    def _build_rule_episode(*, user_input: str, assistant_content: str) -> str:
        if (
            not user_input
            or not assistant_content
            or len(assistant_content.strip()) < 24
            or not MemoryConsolidationService._looks_like_episode(user_input)
        ):
            return ""
        return f"用户请求：{user_input[:240]}。处理结果：{assistant_content[:420]}。"

    @staticmethod
    def _looks_like_episode(user_input: str) -> bool:
        text = str(user_input or "").strip().lower()
        if len(text) < 8:
            return False
        task_markers = (
            "帮我",
            "计划",
            "整理",
            "生成",
            "实现",
            "修复",
            "安装",
            "配置",
            "决定",
            "选择",
            "购买",
            "预订",
            "学习",
            "旅行",
            "项目",
            "任务",
            "完成",
            "build",
            "create",
            "fix",
            "plan",
            "install",
            "configure",
        )
        return any(marker in text for marker in task_markers)

    @staticmethod
    def _episode_title(user_input: str) -> str:
        title = str(user_input or "").strip().replace("\n", " ")
        return title[:40] or "经历片段"

    @staticmethod
    def _extract_after_prefix(text: str, prefixes: list[str]) -> str:
        for prefix in prefixes:
            if not text.startswith(prefix):
                continue
            value = text[len(prefix) :].strip()
            value = value.strip(" ，。！；：?.!?;:")
            if value:
                return value
        return ""

    @staticmethod
    def _infer_preference_key(value: str) -> str:
        lowered = value.lower()
        if any(token in value for token in ["咖啡", "茶", "饮料", "拿铁", "美式"]) or any(
            token in lowered for token in ["coffee", "tea", "drink", "latte", "espresso"]
        ):
            return "preferred_drink"
        if any(token in value for token in ["早餐", "面", "米饭", "沙拉", "面包"]) or any(
            token in lowered for token in ["breakfast", "rice", "salad", "bread", "noodle"]
        ):
            return "preferred_food"
        return "preferred_item"

    @staticmethod
    def _infer_profile_key(candidate: MemoryArtifactCandidate) -> str:
        if candidate.category:
            return candidate.category
        content = candidate.normalized_content().lower()
        if "住在" in content or "home" in content:
            return "home_city"
        if candidate.normalized_kind() == "preference":
            return MemoryConsolidationService._infer_preference_key(content)
        return "profile_fact"

    @staticmethod
    def _normalize_value(value: str) -> str:
        return "".join(ch.lower() for ch in str(value).strip() if not ch.isspace())
