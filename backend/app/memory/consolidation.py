from dataclasses import asdict, dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.memory.facts import ProfileFactsManager


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
    def __init__(self, db: AsyncSession, user_id: str):
        self.db = db
        self.user_id = user_id
        self.facts_manager = ProfileFactsManager(db, user_id)

    async def consolidate_chat_turn(
        self,
        *,
        user_input: str,
        session_id: Optional[str] = None,
    ) -> dict[str, object]:
        del session_id

        candidates = self._extract_candidates(user_input)
        saved: list[dict[str, str]] = []
        skipped: list[dict[str, str]] = []
        decisions: list[dict[str, object]] = []

        for candidate in candidates:
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
                decisions.append(asdict(decision))
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
            decisions.append(
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

        if saved:
            logger.info("Consolidated %s long-term memory candidates", len(saved))

        return {
            "candidate_count": len(candidates),
            "applied_count": len(saved),
            "saved": saved,
            "skipped": skipped,
            "decisions": decisions,
            "extractor_version": "v2",
        }

    def _extract_candidates(self, user_input: str) -> list[ConsolidationCandidate]:
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
    def _extract_after_prefix(text: str, prefixes: list[str]) -> str:
        for prefix in prefixes:
            if not text.startswith(prefix):
                continue
            value = text[len(prefix):].strip()
            value = value.strip(" ，。！？；：,.!?;:")
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
    def _normalize_value(value: str) -> str:
        return "".join(ch.lower() for ch in str(value).strip() if not ch.isspace())
