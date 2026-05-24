import asyncio
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__)))

from app.agents.serana.serana import SeranaAgent
from app.core import get_llm_gateway


async def test_agent():
    print("=" * 50)
    print("Testing LangGraph-based Serana Agent")
    print("=" * 50)

    gateway = get_llm_gateway()
    llm = gateway.get_llm(use_backend_default=True)
    agent = SeranaAgent(llm)

    test_goal = "Introduce yourself briefly"
    print(f"\nTesting with goal: {test_goal}")

    print("\n1. Testing execute method:")
    result = await agent.execute(test_goal)
    print(f"Success: {result.get('success')}")
    print(f"Summary: {str(result.get('summary'))[:100]}...")
    print(f"Thinking blocks: {len(result.get('thinking_blocks', []))}")
    print(f"Subtasks: {len(result.get('subtasks', []))}")

    print("\n2. Testing execute_stream method:")
    async for event in agent.execute_stream("Tell me what time it is right now"):
        print(f"Event: {event.get('type')}")
        if event.get("type") == "thinking_block":
            print(f"  - {event.get('content', {}).get('title')}")
        elif event.get("type") == "content":
            print(f"  Content char: {event.get('content')}")
        elif event.get("type") == "done":
            print(f"  Done! Session: {event.get('session_id')}")

    print("\n" + "=" * 50)
    print("Agent test completed")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(test_agent())
