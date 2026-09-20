#!/usr/bin/env python3
"""Split one BarReplay bin_v1 annual BIN into daily BIN files.

Input format is the project's concatenated hourly block format:
    uint32 count
    int64[count] timestamp_ms
    float64[count] bid
    float64[count] ask
All values are little-endian. Output files keep exactly the same block format.
"""
from __future__ import annotations

import argparse
import struct
from array import array
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HEADER = struct.Struct("<I")
ITEM_SIZE = 8
BYTES_PER_TICK = 24
MAX_TICKS_PER_BLOCK = 20_000_000
MIN_TIMESTAMP_MS = 631152000000   # 1990-01-01 UTC
MAX_TIMESTAMP_MS = 4133980800000  # 2101-01-01 UTC


def read_exact(f, size: int, label: str) -> bytes:
    data = f.read(size)
    if len(data) != size:
        raise ValueError(f"truncated {label}: expected {size:,} bytes, got {len(data):,}")
    return data


def timestamps_from_le(data: bytes) -> array:
    values = array("q")
    values.frombytes(data)
    if struct.pack("=I", 1) != struct.pack("<I", 1):
        values.byteswap()
    return values


def utc_day(timestamp_ms: int) -> str:
    if not MIN_TIMESTAMP_MS <= timestamp_ms < MAX_TIMESTAMP_MS:
        raise ValueError(f"invalid timestamp_ms: {timestamp_ms}")
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).date().isoformat()


def append_segment(
    output_dir: Path,
    symbol: str,
    day: str,
    ts_bytes: bytes,
    bid_bytes: bytes,
    ask_bytes: bytes,
    start: int,
    end: int,
) -> None:
    count = end - start
    if count <= 0:
        return
    path = output_dir / symbol / f"{symbol}_{day}.BIN"
    path.parent.mkdir(parents=True, exist_ok=True)
    lo, hi = start * ITEM_SIZE, end * ITEM_SIZE
    with path.open("ab", buffering=16 * 1024 * 1024) as out:
        out.write(HEADER.pack(count))
        out.write(ts_bytes[lo:hi])
        out.write(bid_bytes[lo:hi])
        out.write(ask_bytes[lo:hi])


def split_file(source: Path, output_dir: Path, symbol: str) -> tuple[int, int, int]:
    if not source.is_file():
        raise FileNotFoundError(source)
    symbol = symbol.strip().upper()
    if not symbol or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for ch in symbol):
        raise ValueError(f"invalid symbol: {symbol!r}")

    # Refuse accidental duplicate appends when rerun into a non-empty symbol folder.
    symbol_dir = output_dir / symbol
    if symbol_dir.exists() and any(symbol_dir.glob("*.BIN")):
        raise RuntimeError(f"output already contains BIN files: {symbol_dir}")

    blocks = ticks = 0
    daily_ticks: dict[str, int] = defaultdict(int)
    previous_ts: int | None = None

    with source.open("rb", buffering=16 * 1024 * 1024) as f:
        while True:
            header = f.read(HEADER.size)
            if not header:
                break
            if len(header) != HEADER.size:
                raise ValueError(f"truncated block header at byte {f.tell() - len(header):,}")
            count = HEADER.unpack(header)[0]
            if count == 0 or count > MAX_TICKS_PER_BLOCK:
                raise ValueError(f"invalid tick count {count:,} in block {blocks + 1}")

            ts_bytes = read_exact(f, count * ITEM_SIZE, "timestamp column")
            bid_bytes = read_exact(f, count * ITEM_SIZE, "bid column")
            ask_bytes = read_exact(f, count * ITEM_SIZE, "ask column")
            ts = timestamps_from_le(ts_bytes)
            if len(ts) != count:
                raise ValueError("timestamp column length mismatch")

            # A normal block is one UTC hour. Segmenting by day also safely handles
            # a malformed block that happens to cross midnight.
            segment_start = 0
            segment_day = utc_day(ts[0])
            for i, value in enumerate(ts):
                if previous_ts is not None and value < previous_ts:
                    raise ValueError(
                        f"timestamps are not chronological in block {blocks + 1}: "
                        f"{value} < {previous_ts}"
                    )
                previous_ts = value
                day = utc_day(value)
                if day != segment_day:
                    append_segment(
                        output_dir, symbol, segment_day,
                        ts_bytes, bid_bytes, ask_bytes, segment_start, i,
                    )
                    daily_ticks[segment_day] += i - segment_start
                    segment_start = i
                    segment_day = day

            append_segment(
                output_dir, symbol, segment_day,
                ts_bytes, bid_bytes, ask_bytes, segment_start, count,
            )
            daily_ticks[segment_day] += count - segment_start
            blocks += 1
            ticks += count

    if blocks == 0:
        raise ValueError(f"no bin_v1 blocks found in {source}")

    total_size = source.stat().st_size
    expected_size = blocks * HEADER.size + ticks * BYTES_PER_TICK
    if total_size != expected_size:
        raise ValueError(
            f"size validation failed: source={total_size:,}, parsed={expected_size:,}"
        )

    print(f"Parsed {source.name}: {blocks:,} blocks, {ticks:,} ticks")
    print(f"Created {len(daily_ticks):,} daily BIN file(s) in {symbol_dir}")
    for day in sorted(daily_ticks):
        print(f"  {day}: {daily_ticks[day]:,} ticks")
    return blocks, ticks, len(daily_ticks)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="Annual .BIN file")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--output", type=Path, default=Path("daily-output"))
    args = parser.parse_args()
    split_file(args.source, args.output, args.symbol)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
