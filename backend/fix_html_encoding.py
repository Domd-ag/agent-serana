import os

# Find all Python files in backend directory
backend_dir = r"d:\agent-serana\backend"

count = 0
for root, dirs, files in os.walk(backend_dir):
    for file in files:
        if file.endswith(".py") and not file.startswith("fix"):
            filepath = os.path.join(root, file)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check if there are any HTML encoded characters
                if "&gt;" in content or "&lt;" in content or "&amp;" in content:
                    print(f"Found HTML encoding in {filepath}, fixing...")
                    count += 1
                    
                    # Replace all HTML encoded characters
                    new_content = content
                    new_content = new_content.replace("&gt;", ">")
                    new_content = new_content.replace("&lt;", "<")
                    new_content = new_content.replace("&amp;", "&")
                    
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(new_content)
                    
                    print(f"Fixed {filepath}")
            except Exception as e:
                print(f"Error processing {filepath}: {e}")

if count > 0:
    print(f"\nDone! Fixed {count} files.")
else:
    print("\nNo HTML encoding issues found in any .py files!")
