#!/usr/bin/env python3
"""
Ingest Awesome-Redteam cheatsheets and tips into MemPalace.

Usage:
  python scripts/ingest_awesome_redteam.py --dry-run
  python scripts/ingest_awesome_redteam.py --palace ~/.mempalace
"""

import argparse
import os
from pathlib import Path

from mempalace.backends.chroma import ChromaBackend
from mempalace.config import MempalaceConfig


def find_md_files(root: Path):
    cheatsheets = root / "cheatsheets"
    tips = root / "tips"
    files = []
    for d in [cheatsheets, tips]:
        if not d.exists():
            continue
        for p in d.rglob("*.md"):
            files.append(p)
    return files


def ingest(root: Path, palace_path: str, dry_run: bool = False):
    backend = ChromaBackend()
    col = backend.get_collection(palace_path, collection_name="mempalace_drawers", create=True)

    files = find_md_files(root)
    print(f"Found {len(files)} Markdown files in Awesome-Redteam")

    for path in files:
        content = path.read_text(encoding="utf-8", errors="replace")
        wing = "awesome_redteam"
        room = path.parent.name
        drawer_id = f"ar:{wing}:{room}:{path.stem}"

        meta = {
            "wing": wing,
            "room": room,
            "source_file": str(path),
            "file_type": "markdown",
        }

        if dry_run:
            print(f"[DRY-RUN] Would file: {drawer_id} ({len(content)} chars)")
            continue

        col.upsert(ids=[drawer_id], documents=[content], metadatas=[meta])
        print(f"Filed: {drawer_id}")


def main():
    parser = argparse.ArgumentParser(description="Ingest Awesome-Redteam into MemPalace")
    parser.add_argument("--root", default="Awesome-Redteam", help="Root directory of Awesome-Redteam")
    parser.add_argument("--palace", default=None, help="Palace path (default: from config)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be filed")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path

    ingest(root, palace_path, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
