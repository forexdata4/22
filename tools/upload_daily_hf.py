#!/usr/bin/env python3
"""Upload daily BarReplay BIN files to a Hugging Face dataset in one batch.

Existing index.txt rows are retained. The current batch is merged into the index
and uploaded with one upload_folder call to avoid one commit per day.
"""
from __future__ import annotations

import argparse
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download

DAILY_RE = re.compile(r"^(?P<symbol>.+?)_(?P<day>\d{4}-\d{2}-\d{2})\.BIN$", re.I)


@dataclass(frozen=True)
class Entry:
    symbol: str
    path: str
    day: str
    size: int
    source: Path | None = None


def retry(label, fn, attempts=5):
    delay = 5
    last = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            last = exc
            if attempt < attempts:
                print(f"{label} failed ({exc}); retrying in {delay}s...")
                time.sleep(delay)
                delay = min(delay * 2, 60)
    raise RuntimeError(f"{label} failed after {attempts} attempts: {last}")


def read_existing(repo_id: str, token: str):
    entries: dict[str, Entry] = {}
    symbol_meta: dict[str, tuple[str, str]] = {}
    try:
        with tempfile.TemporaryDirectory() as td:
            path = hf_hub_download(
                repo_id=repo_id,
                repo_type="dataset",
                filename="index.txt",
                token=token,
                local_dir=td,
            )
            text = Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        print(f"No existing index.txt loaded ({exc}); creating a new catalog.")
        return entries, symbol_meta

    for line in text.splitlines():
        parts = line.split("|")
        if line.startswith("SYM|") and len(parts) >= 5:
            symbol_meta[parts[1].upper()] = (parts[2], parts[4])
        elif line.startswith("FILE|") and len(parts) >= 4:
            try:
                rel, day, size = parts[1], parts[2], int(parts[3])
            except ValueError:
                continue
            if "/" not in rel:
                continue
            folder, name = rel.split("/", 1)
            match = DAILY_RE.match(name)
            if not match:
                continue
            symbol = match.group("symbol").upper()
            normalized = f"{symbol}/{symbol}_{match.group('day')}.BIN"
            entries[normalized] = Entry(symbol, normalized, day, size)
    return entries, symbol_meta


def local_entries(source_dir: Path) -> dict[str, Entry]:
    entries: dict[str, Entry] = {}
    for path in source_dir.rglob("*"):
        if not path.is_file() or path.suffix.upper() != ".BIN":
            continue
        match = DAILY_RE.match(path.name)
        if not match:
            continue
        symbol = match.group("symbol").upper()
        day = match.group("day")
        rel = f"{symbol}/{symbol}_{day}.BIN"
        entries[rel] = Entry(symbol, rel, day, path.stat().st_size, path)
    return entries


def build_index(entries: dict[str, Entry], symbol_meta: dict[str, tuple[str, str]]) -> str:
    grouped: dict[str, list[Entry]] = {}
    for entry in entries.values():
        grouped.setdefault(entry.symbol, []).append(entry)
    lines = ["BRIDX1"]
    for symbol in sorted(grouped):
        display, digits = symbol_meta.get(symbol, (symbol, "5"))
        lines.append(f"SYM|{symbol}|{display}|0|{digits}")
        for entry in sorted(grouped[symbol], key=lambda item: item.day):
            lines.append(f"FILE|{entry.path}|{entry.day}|{entry.size}")
    return "\n".join(lines) + "\n"


def upload(source_dir: Path, repo_id: str, token: str, symbol: str, digits: str) -> None:
    if not token:
        raise SystemExit("error: HF_TOKEN is required")
    local = local_entries(source_dir)
    if not local:
        raise SystemExit(f"error: no daily BIN files found in {source_dir}")

    api = HfApi(token=token)
    api.create_repo(repo_id=repo_id, repo_type="dataset", exist_ok=True, private=False)
    existing, meta = read_existing(repo_id, token)
    symbol = symbol.upper()
    old_display = meta.get(symbol, (symbol, digits))[0]
    meta[symbol] = (old_display, digits)

    changed = {
        rel: entry
        for rel, entry in local.items()
        if rel not in existing or existing[rel].size != entry.size
    }
    merged = dict(existing)
    merged.update(local)

    with tempfile.TemporaryDirectory() as td:
        stage = Path(td) / "stage"
        stage.mkdir()
        for rel, entry in changed.items():
            destination = stage / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Hard links avoid copying large files when runner filesystem allows it.
            try:
                os.link(entry.source, destination)
            except OSError:
                destination.write_bytes(entry.source.read_bytes())
        (stage / "index.txt").write_text(build_index(merged, meta), encoding="utf-8")
        print(f"Uploading {len(changed)} changed daily BIN file(s) + index.txt to {repo_id}")
        retry(
            "Hugging Face upload_folder",
            lambda: api.upload_folder(
                repo_id=repo_id,
                repo_type="dataset",
                folder_path=stage,
                path_in_repo="",
                token=token,
                commit_message=f"Migrate {symbol} annual BIN to daily files ({len(changed)} changed)",
            ),
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("--repo-id", default=os.getenv("HF_DATASET", "Esmaeil9ss/Tickdata"))
    parser.add_argument("--token", default=os.getenv("HF_TOKEN"))
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--digits", default="5")
    args = parser.parse_args()
    upload(args.source_dir, args.repo_id, args.token, args.symbol, args.digits)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
