import unittest
import uuid

from sqlalchemy import func, select

from app.api.chat import _delete_session_data
from app.core.database import AsyncSessionLocal
from app.core.init_db import main as init_db_main
from app.core.models import ChatSession, MemoryArtifact, User, WorkingMemory
from app.memory import MemoryService


class FakeResponse:
    def __init__(self, content: str):
        self.content = content


class EmptyArtifactsLLM:
    async def ainvoke(self, messages):
        return FakeResponse('{"artifacts":[]}')


class MemoryStabilityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db_main()
        self.user_id = str(uuid.uuid4())

    async def test_valid_empty_llm_extraction_does_not_fall_back_to_rule_noise(self):
        async with AsyncSessionLocal() as session:
            session.add(User(id=self.user_id, name="Memory Test User"))
            await session.flush()
            service = MemoryService(session, self.user_id)

            result = await service.consolidate_chat_turn(
                user_input="帮我看看这个普通问题",
                session_id="empty-artifacts-session",
                assistant_content="这是一段足够长、但没有必要长期保存的普通回答内容。",
                llm=EmptyArtifactsLLM(),
            )

            self.assertEqual(result["artifact_candidate_count"], 0)
            self.assertEqual(result["applied_count"], 0)

    async def test_profile_artifact_refreshes_instead_of_leaving_stale_preference(self):
        async with AsyncSessionLocal() as session:
            session.add(User(id=self.user_id, name="Memory Test User"))
            await session.flush()
            service = MemoryService(session, self.user_id)

            await service.consolidate_chat_turn(
                user_input="我喜欢手冲咖啡。",
                session_id="preference-session-a",
            )
            second = await service.consolidate_chat_turn(
                user_input="我喜欢绿茶。",
                session_id="preference-session-b",
            )

            result = await session.execute(
                select(MemoryArtifact).where(
                    MemoryArtifact.user_id == self.user_id,
                    MemoryArtifact.kind == "preference",
                    MemoryArtifact.is_active.is_(True),
                )
            )
            artifacts = list(result.scalars().all())
            self.assertEqual(len(artifacts), 1)
            self.assertIn("绿茶", artifacts[0].content)
            self.assertIsNone(artifacts[0].session_id)
            self.assertTrue(
                any(
                    decision["reason"] == "profile_artifact_refreshed"
                    for decision in second["artifact_decisions"]
                )
            )

    async def test_deleting_session_removes_scoped_memory(self):
        async with AsyncSessionLocal() as session:
            session.add(User(id=self.user_id, name="Memory Test User"))
            chat_session = ChatSession(user_id=self.user_id, title="Scoped memory")
            session.add(chat_session)
            await session.flush()
            session.add(
                MemoryArtifact(
                    user_id=self.user_id,
                    session_id=chat_session.id,
                    kind="summary",
                    title="会话摘要",
                    content="只属于当前会话的摘要。",
                )
            )
            session.add(
                WorkingMemory(
                    user_id=self.user_id,
                    scope="conversation",
                    session_id=chat_session.id,
                    key="temporary",
                    content="只属于当前会话的临时状态。",
                )
            )
            await session.flush()

            deleted = await _delete_session_data(session, [chat_session.id])

            artifact_count = await session.scalar(
                select(func.count()).select_from(MemoryArtifact).where(
                    MemoryArtifact.session_id == chat_session.id
                )
            )
            working_count = await session.scalar(
                select(func.count()).select_from(WorkingMemory).where(
                    WorkingMemory.session_id == chat_session.id
                )
            )
            self.assertEqual(deleted, 1)
            self.assertEqual(artifact_count, 0)
            self.assertEqual(working_count, 0)


if __name__ == "__main__":
    unittest.main()
