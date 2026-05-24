import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from app.skills import SkillManager


async def test_skill_system():
    print("=" * 60)
    print("Testing Skill System")
    print("=" * 60)

    print("\n1. Initializing SkillManager...")
    manager = SkillManager()
    manager.initialize()
    print(f"   Loaded {len(manager.skills)} skills")

    print("\n2. Listing skills:")
    skills = manager.list_skills()
    for skill in skills:
        print(f"   - {skill.name} v{skill.version}: {skill.description}")

    print("\n3. Testing get_skill:")
    calculator_skill = manager.get_skill("calculator")
    if calculator_skill:
        print("   Got calculator skill")
        print(f"   - Author: {calculator_skill.author}")
        print(f"   - Agent type: {calculator_skill.agent_type}")
        print(f"   - Tools: {[t.name for t in calculator_skill.manifest.tools]}")

    print("\n4. Testing tool functions:")
    add_tool = manager.get_tool_function("calculator", "add")
    if add_tool:
        result = await add_tool(a=5, b=3)
        print(f"   Calculator add: 5 + 3 = {result.get('result')}")

    multiply_tool = manager.get_tool_function("calculator", "multiply")
    if multiply_tool:
        result = await multiply_tool(a=4, b=7)
        print(f"   Calculator multiply: 4 * 7 = {result.get('result')}")

    current_time_tool = manager.get_tool_function("time_manager", "get_current_time")
    if current_time_tool:
        result = await current_time_tool(timezone="Asia/Shanghai", format="time")
        print(f"   Current time: {result.get('time_str')}")

    print("\n5. Testing get_tools_for_agent:")
    forge_tools = manager.get_tools_for_agent("forge")
    print(f"   Tools for forge agent: {[t.name for t in forge_tools]}")

    all_tools = manager.get_tools_for_agent("all")
    print(f"   Tools for all agents: {[t.name for t in all_tools]}")

    print("\n6. Testing enable/disable:")
    if manager.disable_skill("calculator"):
        print("   Disabled calculator")
        all_tools_after = manager.get_tools_for_agent("all")
        print(f"   Tools after disable: {[t.name for t in all_tools_after]}")

    if manager.enable_skill("calculator"):
        print("   Enabled calculator")

    print("\n" + "=" * 60)
    print("Skill system test completed")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_skill_system())
