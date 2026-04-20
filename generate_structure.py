import os
import json

ROOT = r"C:\Users\Admin\Desktop\HACKATHON\COmpatetion Folder\AgenticEconomy"
EXCLUDE = {".git", "__pycache__", "node_modules"}

def describe_file(name):
    ext = os.path.splitext(name)[1]
    return {
        ".py": "Python logic file for system behavior.",
        ".js": "Frontend JavaScript logic.",
        ".json": "Structured data or configuration.",
        ".md": "Documentation file.",
        ".yaml": "Configuration settings.",
        ".log": "System event log."
    }.get(ext, "General file.")

def describe_folder(name):
    return f"Module for {name}."

def write_meta(path, name, is_dir):
    meta = {
        "name": name,
        "type": "folder" if is_dir else "file",
        "description": describe_folder(name) if is_dir else describe_file(name),
        "path": path
    }

    meta_path = os.path.join(path, ".meta.json") if is_dir else path + ".meta.json"

    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

def write_index(folder_path, dirs, files):
    index_path = os.path.join(folder_path, "index.md")

    content = f"# {os.path.basename(folder_path)}\n\n"

    if dirs:
        content += "## Folders\n"
        for d in dirs:
            content += f"- {d}: {describe_folder(d)}\n"
        content += "\n"

    if files:
        content += "## Files\n"
        for f in files:
            if f == "index.md":
                continue
            content += f"- {f}: {describe_file(f)}\n"

    with open(index_path, "w") as f:
        f.write(content)

def run():
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in EXCLUDE]

        write_meta(root, os.path.basename(root), True)
        write_index(root, dirs, files)

        for file in files:
            write_meta(os.path.join(root, file), file, False)

if __name__ == "__main__":
    run()
    print("Structure indexed successfully.")
