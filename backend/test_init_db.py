import asyncio
import sys
import traceback


async def test_init():
    try:
        print("Testing database import...")
        from app.core.init_db import main
        print("✓ Import successful")
        
        print("\nRunning database init...")
        await main()
        print("\n✓ Database init successful!")
    except Exception as e:
        print(f"\n✗ Error: {str(e)}")
        print("\nFull traceback:")
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_init())
