#!/usr/bin/env python3
# Merge multiple HAWP-style test.json files into a single test.json
# deps: none (stdlib)

import os
import json
from collections import OrderedDict

# =========================
# CONFIG — EDIT ME
# =========================
INPUT_JSONS = [
    r"outputs/hawp/city_a_test.json",
    r"outputs/hawp/city_b_test.json",
    r"outputs/hawp/city_c_test.json",
]

# Optional filename prefixes to prepend to each record's "filename".
# Leave as [] or None to skip. If provided, length must match INPUT_JSONS.
# Example: ["A_", "B_", "C_"]
FILENAME_PREFIXES = []  # or [] to disable

# What to do if (after optional prefixing) two records share the same "filename"
# Options: "keep_first" | "keep_last" | "error"
ON_FILENAME_COLLISION = "keep_first"

# Sort merged records by filename before writing?
SORT_BY_FILENAME = True

# Output file
OUT_JSON = r"outputs/hawp/test_merged.json"
# =========================


def validate_record(rec, idx, src):
    """Basic structural checks; returns normalized record or raises ValueError."""
    if not isinstance(rec, dict):
        raise ValueError(f"{src}: item #{idx} is not an object")
    for k in ("width", "height", "lines", "junc", "filename"):
        if k not in rec:
            raise ValueError(f"{src}: item #{idx} missing key '{k}'")
    if not isinstance(rec["lines"], list) or not isinstance(rec["junc"], list):
        raise ValueError(f"{src}: item #{idx} 'lines'/'junc' must be lists")
    # Ensure ints in lines/junc (best-effort)
    def to_int4(seg):
        if len(seg) != 4:
            raise ValueError(f"{src}: line segment does not have 4 values: {seg}")
        return [int(seg[0]), int(seg[1]), int(seg[2]), int(seg[3])]
    def to_int2(pt):
        if len(pt) != 2:
            raise ValueError(f"{src}: junction does not have 2 values: {pt}")
        return [int(pt[0]), int(pt[1])]

    rec["width"]  = int(rec["width"])
    rec["height"] = int(rec["height"])
    rec["lines"]  = [to_int4(s) for s in rec["lines"]]
    rec["junc"]   = [to_int2(p) for p in rec["junc"]]
    rec["filename"] = str(rec["filename"])
    return rec


def main():
    if FILENAME_PREFIXES and len(FILENAME_PREFIXES) != len(INPUT_JSONS):
        raise SystemExit("FILENAME_PREFIXES length must match INPUT_JSONS (or leave it empty).")

    merged = OrderedDict()  # filename -> record
    total_in, total_kept, total_skipped = 0, 0, 0

    for fi, path in enumerate(INPUT_JSONS):
        prefix = (FILENAME_PREFIXES[fi] if FILENAME_PREFIXES else "")
        if not os.path.exists(path):
            print(f"[WARN] missing file: {path} (skipping)")
            continue

        with open(path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except Exception as e:
                raise SystemExit(f"Failed to read {path}: {e}")

        if not isinstance(data, list):
            raise SystemExit(f"{path} must contain a top-level list of records")

        for idx, rec in enumerate(data):
            total_in += 1
            try:
                rec = validate_record(rec, idx, os.path.basename(path))
            except ValueError as ve:
                print(f"[WARN] {ve} — skipping this record")
                total_skipped += 1
                continue

            # apply optional filename prefix
            if prefix:
                rec = dict(rec)  # shallow copy
                rec["filename"] = prefix + rec["filename"]

            key = rec["filename"]
            if key in merged:
                if ON_FILENAME_COLLISION == "keep_first":
                    total_skipped += 1
                    continue
                elif ON_FILENAME_COLLISION == "keep_last":
                    merged[key] = rec
                    total_kept += 1  # counts as kept (overwrite)
                elif ON_FILENAME_COLLISION == "error":
                    raise SystemExit(f"Filename collision on '{key}' from {path}")
            else:
                merged[key] = rec
                total_kept += 1

    records = list(merged.values())
    if SORT_BY_FILENAME:
        records.sort(key=lambda r: r["filename"])

    output_dir = os.path.dirname(OUT_JSON)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False)

    print("=== Merge summary ===")
    print(f"Input records:     {total_in}")
    print(f"Kept records:      {total_kept}")
    print(f"Skipped (invalid/dups): {total_skipped}")
    print(f"Output records:    {len(records)}")
    print(f"Wrote: {OUT_JSON}")


if __name__ == "__main__":
    main()
