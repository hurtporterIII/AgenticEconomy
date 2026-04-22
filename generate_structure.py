import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone
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
# Large runtime trees: still navigable via parent index.md; skipping avoids 10k+ churning stubs.
SKIP_INDEX_SUBTREES = {
    "storage",  # per-simulation runtime under frontend_server/storage
    "compressed_storage",
}
EXCLUDE_FILES = {
    ".DS_Store",
    "Thumbs.db",
}
SKIP_META_FOR_EXT = {".log", ".tmp"}

FOLDER_HINTS = {
    "backend": ("Backend simulation engine and API services.", ["backend", "api", "simulation"]),
    "frontend": ("Frontend runtime and UI assets.", ["frontend", "ui", "phaser"]),
    "generative_agents": ("Smallville/Generative Agents integration workspace.", ["smallville", "integration"]),
    "environment": ("Simulation environment and map runtime files.", ["environment", "map"]),
    "reverie": ("Original Reverie simulation runtime.", ["reverie", "simulation"]),
    "persona": ("Persona cognition, memory, and planning modules.", ["persona", "agents", "cognition"]),
    "cognitive_modules": ("Per-step cognitive pipelines (perceive/plan/act).", ["cognition", "planning"]),
    "memory_structures": ("Associative / scratch memory structures for personas.", ["memory", "persona"]),
    "prompt_template": ("LLM prompt templates for persona behaviors.", ["prompts", "llm", "persona"]),
    "backend_server": ("Reverie Python server (reverie.py) and persona runtime.", ["reverie", "server"]),
    "frontend_server": ("Django + Phaser environment server for Smallville map.", ["django", "phaser", "smallville"]),
    "translator": ("Django app: views, URLs, bridge to FastAPI.", ["django", "bridge", "api"]),
    "core": ("Core loop/state and shared runtime logic.", ["core", "engine"]),
    "agents": ("Role-specific agent behavior handlers.", ["agents", "behavior"]),
    "api": ("HTTP API endpoints and bridge interfaces.", ["api", "http"]),
    "tx": ("Transaction submission/inspection modules.", ["transactions", "arc", "usdc"]),
    "store": ("Runtime state storage and generated catalogs.", ["state", "storage"]),
    "templates": ("Frontend HTML templates and scripts.", ["templates", "frontend"]),
    "wallet_setup": ("Wallet provisioning and key material utilities.", ["wallets", "keys"]),
    "docs": ("Project documentation and architecture notes.", ["docs"]),
    "config": ("Configuration constants and pricing rules.", ["config"]),
}

EXT_HINTS = {
    ".py": ("Python logic file for runtime behavior.", ["python", "code"]),
    ".js": ("JavaScript runtime logic.", ["javascript", "code"]),
    ".ts": ("TypeScript source file.", ["typescript", "code"]),
    ".tsx": ("TypeScript React component.", ["typescript", "react"]),
    ".jsx": ("JavaScript React component.", ["javascript", "react"]),
    ".json": ("Structured data or configuration.", ["json", "data"]),
    ".md": ("Documentation or notes.", ["docs", "markdown"]),
    ".yaml": ("YAML configuration file.", ["config", "yaml"]),
    ".yml": ("YAML configuration file.", ["config", "yaml"]),
    ".toml": ("TOML configuration file.", ["config", "toml"]),
    ".ps1": ("PowerShell automation script.", ["powershell", "automation"]),
    ".sh": ("Shell automation script.", ["shell", "automation"]),
    ".txt": ("Plain text file.", ["text"]),
    ".html": ("HTML template or page.", ["html", "frontend"]),
    ".css": ("Stylesheet file.", ["css", "frontend"]),
    ".png": ("Image asset.", ["asset", "image"]),
    ".jpg": ("Image asset.", ["asset", "image"]),
    ".jpeg": ("Image asset.", ["asset", "image"]),
    ".svg": ("Vector image asset.", ["asset", "image"]),
    ".dat": ("Binary data artifact.", ["binary", "data"]),
    ".docx": ("Word document asset.", ["document"]),
}


def describe_file(name: str) -> str:
    ext = Path(name).suffix.lower()
    return EXT_HINTS.get(ext, ("General file artifact.", []))[0]


def describe_folder(name: str) -> str:
    lowered = name.lower()
    if lowered in FOLDER_HINTS:
        return FOLDER_HINTS[lowered][0]
    return f"Module folder for {name}."


def infer_tags(path: Path, is_dir: bool) -> list[str]:
    tags: set[str] = set()
    parts = [p.lower() for p in path.parts]
    for p in parts:
        if p in FOLDER_HINTS:
            tags.update(FOLDER_HINTS[p][1])
        if p in {"smallville", "bridge"}:
            tags.update({"smallville", "bridge"})
        if p in {"wallet", "wallets"}:
            tags.update({"wallets"})
    if is_dir:
        tags.add("folder")
    else:
        ext = path.suffix.lower()
        tags.add("file")
        tags.update(EXT_HINTS.get(ext, ("", []))[1])
    return sorted(tags)


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


def _path_contains_skip_segment(rel: Path) -> bool:
    parts = set(rel.parts)
    return bool(parts & SKIP_INDEX_SUBTREES)


def is_curated_index(index_path: Path) -> bool:
    """
    Hand-written navigation files use YAML frontmatter starting with '---'.
    Never overwrite those with auto-generated stubs.
    """
    try:
        if not index_path.is_file():
            return False
        with index_path.open("r", encoding="utf-8", errors="replace") as handle:
            first = handle.readline().strip()
        return first == "---"
    except OSError:
        return False


def write_meta(path: Path, name: str, is_dir: bool) -> None:
    stat = path.stat()
    rel = path.relative_to(ROOT)
    ext = path.suffix.lower() if not is_dir else ""
    meta = {
        "name": name,
        "type": "folder" if is_dir else "file",
        "description": describe_folder(name) if is_dir else describe_file(name),
        "path": str(path.resolve()),
        "relative_path": str(rel).replace("\\", "/"),
        "tags": infer_tags(path, is_dir),
        "modified_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }
    if not is_dir:
        meta["extension"] = ext
        meta["size_bytes"] = int(stat.st_size)
    else:
        meta["contains"] = {
            "folders": sum(1 for c in path.iterdir() if c.is_dir() and c.name not in EXCLUDE_DIRS),
            "files": sum(1 for c in path.iterdir() if c.is_file() and not should_skip_file(c)),
        }

    meta_path = path / ".meta.json" if is_dir else Path(str(path) + ".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def write_index(folder_path: Path, dirs: list[str], files: list[str]) -> None:
    index_path = folder_path / "index.md"
    rel_to_root = folder_path.relative_to(ROOT)
    if _path_contains_skip_segment(rel_to_root):
        return

    if is_curated_index(index_path):
        return

    rel = "." if folder_path == ROOT else str(folder_path.relative_to(ROOT)).replace("\\", "/")
    file_entries = [f for f in sorted(files) if f != "index.md"]
    ext_counts = Counter(Path(f).suffix.lower() or "<none>" for f in file_entries)
    lines = [f"# {folder_path.name}", "", f"Path: `{rel}`", ""]
    lines.append("## Summary")
    lines.append(f"- Subfolders: {len(dirs)}")
    lines.append(f"- Files: {len(file_entries)}")
    if ext_counts:
        top = ", ".join([f"{k}:{v}" for k, v in ext_counts.most_common(8)])
        lines.append(f"- File types: {top}")
    lines.append("")

    if dirs:
        lines.append("## Folders")
        for d in sorted(dirs):
            lines.append(f"- {d}: {describe_folder(d)}")
        lines.append("")

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
            and d not in SKIP_INDEX_SUBTREES
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

        rel_folder = current_path.relative_to(ROOT)
        skip_subtree = _path_contains_skip_segment(rel_folder)
        curated_index = is_curated_index(current_path / "index.md")

        if with_meta and not skip_subtree and not curated_index:
            write_meta(current_path, current_path.name, True)

        if not skip_subtree:
            write_index(current_path, dirs, clean_files)

        if with_meta:
            for file_name in clean_files:
                file_path = current_path / file_name
                if file_name == "index.md" and is_curated_index(file_path):
                    continue
                if skip_subtree:
                    continue
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
