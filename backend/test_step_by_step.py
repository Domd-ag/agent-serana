import sys
import traceback

print("=== Step 1: Import app.core ===")
try:
    import app.core
    print("✓ app.core imported")
    print("  Contents:", dir(app.core))
except Exception as e:
    print("✗ Failed to import app.core")
    traceback.print_exc()
    sys.exit(1)

print("\n=== Step 2: Check what's in app.api ===")
try:
    import app.api
    print("✓ app.api imported")
except Exception as e:
    print("✗ Failed to import app.api")
    print("  Error:", e)
    traceback.print_exc()

print("\n=== Step 3: Import each API module ===")
modules = ["chat", "skills", "memory", "llm", "goals", "agents"]
for mod in modules:
    try:
        __import__(f"app.api.{mod}")
        print(f"✓ app.api.{mod} imported")
    except Exception as e:
        print(f"✗ Failed to import app.api.{mod}")
        print("  Error:", e)
        traceback.print_exc()
