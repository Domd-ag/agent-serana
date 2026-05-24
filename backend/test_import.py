import sys
import traceback

print("Python version:", sys.version)
print("Python path:", sys.path)

try:
    print("\nTrying to import app.main...")
    from app.main import app
    print("✓ Import successful!")
    print("App object:", app)
except Exception as e:
    print("✗ Error importing app.main:", str(e))
    print("\nTraceback:")
    traceback.print_exc()
