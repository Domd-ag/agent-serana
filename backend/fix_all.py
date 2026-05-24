
import os

# Find all Python files in backend directory
backend_dir = r"d:\agent-serana\backend"

for root, dirs, files in os.walk(backend_dir):
    for file in files:
        if file.endswith(".py") and not file.startswith("fix"):
            filepath = os.path.join(root, file)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check if there are any HTML encoded characters
                if "-&gt;" in content:
                    print(f"Found problem in {filepath}, fixing...")
                    
                    # Replace all HTML encoded characters
                    new_content = content.replace("-&gt;", "-&gt;")
                    # Wait, no, wait, let's use the actual characters
                    new_content = content.replace("-&gt;", "-&gt;")
                    
                    # Wait let's do this right
                    new_content = content.replace("-&gt;", "-&gt;")
                    
                    # Wait I think it's actually &gt; so replacing &gt; with >!
                    new_content = content.replace("&gt;", ">")
                    
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(new_content)
                    
                    print(f"Fixed {filepath}")
            except Exception as e:
                print(f"Error processing {filepath}: {e}")

print("Done!")
