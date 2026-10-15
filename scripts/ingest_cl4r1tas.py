#!/usr/bin/env python3
"""
Ingest CL4R1T4S system prompts into MemPalace as reference material.

Usage:
  python scripts/ingest_cl4r1tas.py --dry-run
  python scripts/ingest_cl4r1tas.py --palace ~/.mempalace
"""

import argparse
import os
from pathlib import Path

# NOTE: the `mempalace` package (and its `chromadb` dependency) is imported
# lazily inside the non-dry-run paths below, so `--dry-run` works on a machine
# without the mempalace checkout / chromadb installed.


def find_prompt_files(root: Path):
    # Adjust to your CL4R1T4S layout, e.g. ANTHROPIC/, OPENAI/, etc.
    files = []
    for p in root.rglob("*.md"):
        if "system" in p.name.lower() or "prompt" in p.name.lower():
            files.append(p)
    return files


def ingest(root: Path, palace_path: str, dry_run: bool = False):
    files = find_prompt_files(root)
    print(f"Found {len(files)} CL4R1T4S prompt files")

    # Defer the vector-DB connection until a non-dry-run write is actually
    # performed, so `--dry-run` works without chromadb (or a live palace).
    col = None
    if not dry_run:
        from mempalace.backends.chroma import ChromaBackend  # deferred (heavy dep)
        backend = ChromaBackend()
        col = backend.get_collection(palace_path, collection_name="mempalace_drawers", create=True)

    for path in files:
        content = path.read_text(encoding="utf-8", errors="replace")
        wing = "cl4r1tas"
        room = path.parent.name
        drawer_id = f"cl4r1tas:{wing}:{room}:{path.stem}"

        meta = {
            "wing": wing,
            "room": room,
            "source_file": str(path),
            "file_type": "markdown",
            "type": "system_prompt",
        }

        if dry_run:
            print(f"[DRY-RUN] Would file: {drawer_id} ({len(content)} chars)")
            continue

        col.upsert(ids=[drawer_id], documents=[content], metadatas=[meta])
        print(f"Filed: {drawer_id}")


def main():
    parser = argparse.ArgumentParser(description="Ingest CL4R1T4S prompts into MemPalace")
    parser.add_argument("--root", default="CL4R1T4S", help="Root directory of CL4R1T4S")
    parser.add_argument("--palace", default=None, help="Palace path (default: from config)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be filed")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    if args.palace:
        palace_path = os.path.expanduser(args.palace)
    elif args.dry_run:
        palace_path = None  # dry-run never touches the palace
    else:
        from mempalace.config import MempalaceConfig  # deferred (heavy dep)
        palace_path = MempalaceConfig().palace_path

    ingest(root, palace_path, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
