
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

import asyncio
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_settings, get_default_user
from app.core.database import AsyncSessionLocal
from app.memory import (
    ProfileFactsManager,
    HistoryManager,
    MemoryRetriever,
    MemoryInjector,
)


async def init_db():
    """初始化数据库连接"""
    return AsyncSessionLocal()


async def test_profile_facts(db: AsyncSession, user_id: str):
    """测试 Profile Facts 管理"""
    print("\n" + "=" * 60)
    print("Testing Profile Facts Manager")
    print("=" * 60)
    
    manager = ProfileFactsManager(db, user_id)
    
    # 添加一些事实
    print("\n1. Adding profile facts...")
    await manager.add_fact(
        key="preferred_language",
        value="Python",
        category="preferences",
        source="user_explicit"
    )
    await manager.add_fact(
        key="location",
        value="北京",
        category="personal",
        source="user_explicit"
    )
    await manager.add_fact(
        key="hobbies",
        value="读书, 编程, 旅行",
        category="interests",
        source="user_explicit"
    )
    print("   ✓ Facts added")
    
    # 获取所有事实
    print("\n2. Getting all facts...")
    facts = await manager.get_all_facts()
    for fact in facts:
        print(f"   - {fact.key}: {fact.value}")
    
    # 获取特定事实
    print("\n3. Getting specific fact...")
    lang_fact = await manager.get_fact("preferred_language")
    if lang_fact:
        print(f"   ✓ Found: {lang_fact.key} = {lang_fact.value}")
    
    # 测试转换为上下文字符串
    print("\n4. Testing context string...")
    context_str = await manager.to_context_string()
    print(context_str)


async def test_memory_retriever(db: AsyncSession, user_id: str):
    """测试记忆检索器"""
    print("\n" + "=" * 60)
    print("Testing Memory Retriever")
    print("=" * 60)
    
    retriever = MemoryRetriever(db, user_id)
    
    # 测试检索
    print("\n1. Searching for 'Python'...")
    memories = await retriever.retrieve(query="Python", limit=5)
    print(f"   Found {len(memories)} relevant memories:")
    for m in memories:
        print(f"   [{m.relevance_score:.2f}] {m.content}")


async def test_memory_injector(db: AsyncSession, user_id: str):
    """测试记忆注入器"""
    print("\n" + "=" * 60)
    print("Testing Memory Injector")
    print("=" * 60)
    
    injector = MemoryInjector(db, user_id)
    
    # 测试对话注入
    print("\n1. Testing conversation injection...")
    context = await injector.inject_for_conversation(
        user_input="我想用 Python 写个程序",
        include_facts=True,
        include_history=False
    )
    print(context)


async def main():
    print("=" * 60)
    print("Serana Memory System Test")
    print("=" * 60)
    
    # 获取数据库会话
    db = await init_db()
    try:
        # 获取默认用户
        user = await get_default_user()
        print(f"\nTesting with user: {user.id}")
        
        # 运行测试
        await test_profile_facts(db, user.id)
        await test_memory_retriever(db, user.id)
        await test_memory_injector(db, user.id)
        
        print("\n" + "=" * 60)
        print("All memory system tests completed!")
        print("=" * 60)
        
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())

