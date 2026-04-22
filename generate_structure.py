import argparse
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent
EXCLUDE_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".project",
    ".vscode",
}
EXCLUDE_FILES = {
    ".DS_Store",
    "Thumbs.db",
}
SKIP_META_FOR_EXT = {".log", ".tmp"}


def describe_file(name: str) -> str:
    ext = Path(name).suffix.lower()
    return {
        ".py": "Python logic file for system behavior.",
        ".js": "Frontend JavaScript logic.",
        ".json": "Structured data or configuration.",
        ".md": "Documentation file.",
        ".yaml": "Configuration settings.",
        ".yml": "Configuration settings.",
        ".ps1": "PowerShell automation script.",
        ".txt": "Text file.",
    }.get(ext, "General file.")


def describe_folder(name: str) -> str:
    return f"Module for {name}."


def is_hidden(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts if part not in {".", ".."})


def should_skip_file(path: Path) -> bool:
    name = path.name
    if name in EXCLUDE_FILES:
        return True
    if name.endswith(".meta.json") or name.endswith(".meta.json.meta.json"):
        return True
    if path.suffix.lower() in SKIP_META_FOR_EXT:
        return True
    return False


def write_meta(path: Path, name: str, is_dir: bool) -> None:
    meta = {
        "name": name,
        "type": "folder" if is_dir else "file",
        "description": describe_folder(name) if is_dir else describe_file(name),
        "path": str(path),
    }

    meta_path = path / ".meta.json" if is_dir else Path(str(path) + ".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def write_index(folder_path: Path, dirs: list[str], files: list[str]) -> None:
    index_path = folder_path / "index.md"

    lines = [f"# {folder_path.name}", ""]

    if dirs:
        lines.append("## Folders")
        for d in sorted(dirs):
            lines.append(f"- {d}: {describe_folder(d)}")
        lines.append("")

    file_entries = [f for f in sorted(files) if f != "index.md"]
    if file_entries:
        lines.append("## Files")
        for f in file_entries:
            lines.append(f"- {f}: {describe_file(f)}")

    index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(root: Path, with_meta: bool, include_hidden: bool) -> None:
    for current_root, dirs, files in os.walk(root):
        current_path = Path(current_root)

        dirs[:] = [
            d
            for d in dirs
            if d not in EXCLUDE_DIRS
            and (include_hidden or not d.startswith("."))
        ]

        if not include_hidden and is_hidden(current_path.relative_to(root)):
            continue

        clean_files = []
        for file_name in files:
            file_path = current_path / file_name
            if should_skip_file(file_path):
                continue
            if not include_hidden and file_name.startswith("."):
                continue
            clean_files.append(file_name)

        if with_meta:
            write_meta(current_path, current_path.name, True)

        write_index(current_path, dirs, clean_files)

        if with_meta:
            for file_name in clean_files:
                file_path = current_path / file_name
                write_meta(file_path, file_name, False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate index.md and .meta.json files.")
    parser.add_argument("--root", default=str(ROOT), help="Root folder to index.")
    parser.add_argument("--no-meta", action="store_true", help="Generate only index.md files.")
    parser.add_argument(
        "--include-hidden",
        action="store_true",
        help="Include hidden files/folders (off by default).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    root_path = Path(args.root).resolve()
    run(root_path, with_meta=not args.no_meta, include_hidden=args.include_hidden)
    print(f"Structure indexed successfully: {root_path}")
