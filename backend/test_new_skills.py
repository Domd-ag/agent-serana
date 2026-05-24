import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))


async def test_time_manager():
    from skills_store.time_manager import (
        calculate_duration,
        get_current_time,
        get_day_info,
    )

    print("\n" + "=" * 70)
    print("Testing time_manager skill")
    print("=" * 70)

    result = await get_current_time(timezone="Asia/Shanghai", format="full")
    print(f"   Current time: {result['time_str']}")

    result = await get_day_info()
    print(f"   Weekday: {result['weekday']}")
    print(f"   Day index: {result['weekday_num']}")
    print(f"   Weekend: {result['is_weekend']}")

    result = await calculate_duration(
        start_time="2024-01-01 09:00:00",
        end_time="2024-01-01 17:30:00",
    )
    print(f"   Duration: {result['human_readable']}")


async def test_note_manager():
    from skills_store.note_manager import (
        create_note,
        get_note,
        list_notes,
        search_notes,
        update_note,
    )

    print("\n" + "=" * 70)
    print("Testing note_manager skill")
    print("=" * 70)

    note1 = await create_note(
        title="Serana project",
        content="A personal assistant project with memory, skills, and multi-agent orchestration.",
        tags=["project", "ai", "serana"],
    )
    note_id = note1["note_id"]
    print(f"   Created note: {note1['note']['title']}")

    await create_note(
        title="Python study notes",
        content="Review syntax, data structures, and more practice.",
        tags=["study", "python"],
    )

    result = await list_notes(limit=5)
    print(f"   Total notes: {result['total_count']}")

    result = await search_notes(keyword="Serana")
    print(f"   Search count: {result['count']}")

    updated = await update_note(
        note_id=note_id,
        content="A personal assistant project built with FastAPI and Android.",
    )
    print(f"   Updated note: {updated['note']['title']}")

    result = await get_note(note_id)
    print(f"   Loaded note title: {result['note']['title']}")


async def test_data_operations():
    from skills_store.data_operations import (
        base64_decode,
        base64_encode,
        extract_keywords,
        json_pretty,
        text_stats,
        word_frequency,
    )

    print("\n" + "=" * 70)
    print("Testing data_operations skill")
    print("=" * 70)

    sample_text = """
    Python is a high-level programming language known for its readable syntax.
    It is widely used for web development, data analysis, automation, and AI.
    """

    stats = await text_stats(sample_text)
    print(f"   Characters: {stats['characters']}")
    print(f"   Words: {stats['words']}")

    keywords = await extract_keywords(sample_text, limit=5)
    print(f"   Keywords: {', '.join(keywords['keywords'])}")

    freq = await word_frequency(sample_text, limit=5)
    print(f"   Top words: {freq['top_words']}")

    encode_result = await base64_encode("Hello, Serana!")
    print(f"   Encoded: {encode_result['encoded']}")

    decode_result = await base64_decode(encode_result["encoded"])
    print(f"   Decoded: {decode_result['decoded']}")

    json_result = await json_pretty('{"name":"Serana","version":"1.0"}', indent=2)
    print(f"   Pretty JSON success: {json_result['success']}")


async def main():
    print("\n" + "=" * 70)
    print("Serana local skill tests")
    print("=" * 70)

    await test_time_manager()
    await test_note_manager()
    await test_data_operations()

    print("\nInstalled local skills:")
    print("  1. calculator")
    print("  2. time_manager")
    print("  3. note_manager")
    print("  4. data_operations")


if __name__ == "__main__":
    asyncio.run(main())
