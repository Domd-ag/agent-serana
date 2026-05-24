import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.memory import MemoryInjector, MemoryRetriever, ProfileFactsManager
from app.skills import SkillManager


async def init_db() -> AsyncSession:
    return AsyncSessionLocal()


async def test_profile_facts_integration(db: AsyncSession, user_id: str):
    print("\n" + "=" * 70)
    print("Profile facts integration test")
    print("=" * 70)

    facts_manager = ProfileFactsManager(db, user_id)

    print("\n1. Adding sample profile facts...")
    await facts_manager.add_fact(key="name", value="Zhang San", category="personal", source="user_explicit")
    await facts_manager.add_fact(
        key="favorite_language",
        value="Python",
        category="preferences",
        source="user_explicit",
    )
    await facts_manager.add_fact(key="location", value="Beijing", category="personal", source="user_explicit")
    print("   Facts added")

    print("\n2. Testing memory injection...")
    injector = MemoryInjector(db, user_id)
    context = await injector.inject_for_conversation(
        user_input="Recommend a programming language",
        include_facts=True,
        include_history=False,
    )
    print("   Injected context:")
    print(context)

    print("\n3. Testing memory retrieval...")
    retriever = MemoryRetriever(db, user_id)
    memories = await retriever.retrieve(query="Python", limit=3)
    print(f"   Found {len(memories)} related memories")
    for memory in memories:
        print(f"   - [{memory.relevance_score:.2f}] {memory.content}")


async def test_skill_system_integration(db: AsyncSession, user_id: str):
    print("\n" + "=" * 70)
    print("Skill system integration test")
    print("=" * 70)

    skill_manager = SkillManager()
    skill_manager.initialize()

    print("\n1. Listing all skills...")
    skills = skill_manager.list_skills()
    print(f"   Found {len(skills)} skills")
    for skill in skills:
        print(f"   - {skill.name} (v{skill.version}): {skill.description}")

    print("\n2. Listing tools for forge...")
    tools = skill_manager.get_tools_for_agent("forge")
    print(f"   Found {len(tools)} tools")
    for tool in tools:
        print(f"   - {tool.name}: {tool.description}")

    print("\n3. Calling local tools...")
    calc_add_func = skill_manager.get_tool_function("calculator", "add")
    if calc_add_func:
        result = await calc_add_func(a=10, b=5)
        print(f"   Calculator result: {result}")

    current_time_func = skill_manager.get_tool_function("time_manager", "get_current_time")
    if current_time_func:
        result = await current_time_func(timezone="Asia/Shanghai", format="time")
        print(f"   Current time result: {result}")


async def test_full_system_integration():
    print("\n" + "=" * 70)
    print("Serana full integration test")
    print("=" * 70)

    db = await init_db()
    try:
        user_id = "default-user"
        await test_profile_facts_integration(db, user_id)
        await test_skill_system_integration(db, user_id)
        print("\n" + "=" * 70)
        print("Integration test completed")
        print("=" * 70)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(test_full_system_integration())
