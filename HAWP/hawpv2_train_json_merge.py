#!/usr/bin/env python3
# Merge multiple HAWP-style train.json files into a single train.json
# deps: stdlib only

import os
import json
from collections import OrderedDict

# =========================
# CONFIG — EDIT ME
# =========================
INPUT_JSONS = [
    r"outputs/hawp/city_a_train.json",
    r"outputs/hawp/city_b_train.json",
    r"outputs/hawp/city_c_train.json",
]

# Optional filename prefixes to prepend to each record's "filename".
# Leave as [] or None to skip. If provided, length must match INPUT_JSONS.
FILENAME_PREFIXES = []  # or [] to disable

# What to do if (after optional prefixing) two records share the same "filename"
# Options: "keep_first" | "keep_last" | "error"
ON_FILENAME_COLLISION = "keep_first"

# Sort merged records by filename before writing?
SORT_BY_FILENAME = True

# Output file
OUT_JSON = r"outputs/hawp/train_merged.json"

# Cleaning: remove duplicate undirected edges and self-loops
DEDUP_EDGES = False
# =========================


def _to_int2(pt, src, idx):
    if not (isinstance(pt, (list, tuple)) and len(pt) == 2):
        raise ValueError(f"{src}: item #{idx} has a bad junction (need [x,y]): {pt}")
    return [int(round(pt[0])), int(round(pt[1]))]

def _to_int2_pair(e, src, idx):
    if not (isinstance(e, (list, tuple)) and len(e) == 2):
        raise ValueError(f"{src}: item #{idx} has a bad edge (need [i,j]): {e}")
    return [int(e[0]), int(e[1])]

def _undirected_key(i, j):
    return (i, j) if i <= j else (j, i)

def validate_and_clean_record(rec, idx, src):
    """
    Basic structural checks + light cleaning:
      - width/height int
      - junctions: list[[x,y]]
      - edges_positive: list[[i,j]] within index range, no self-loops
      - edges_negative: list (kept as-is; usually empty)
      - filename: str
      - (optional) dedup undirected edges
    Returns normalized record or raises ValueError.
    """
    need = ("width", "height", "junctions", "edges_positive", "edges_negative", "filename")
    for k in need:
        if k not in rec:
            raise ValueError(f"{src}: item #{idx} missing key '{k}'")

    W = int(rec["width"])
    H = int(rec["height"])
    J_raw = rec["junctions"]
    EP_raw = rec["edges_positive"]
    EN_raw = rec["edges_negative"]
    FN = str(rec["filename"])

    if not isinstance(J_raw, list) or not isinstance(EP_raw, list) or not isinstance(EN_raw, list):
        raise ValueError(f"{src}: item #{idx} lists must be lists")

    # junctions -> ints
    J = [_to_int2(p, src, idx) for p in J_raw]
    nJ = len(J)

    # edges_positive -> ints + validate
    EP = []
    dropped_oob = dropped_self = 0
    for e in EP_raw:
        i, j = _to_int2_pair(e, src, idx)
        if i == j:
            dropped_self += 1
            continue
        if i < 0 or j < 0 or i >= nJ or j >= nJ:
            dropped_oob += 1
            continue
        EP.append([i, j])

    # dedup undirected
    if DEDUP_EDGES:
        seen = set()
        EP2 = []
        for i, j in EP:
            key = _undirected_key(i, j)
            if key in seen:
                continue
            seen.add(key)
            EP2.append([i, j])
        EP = EP2

    rec_out = {
        "width": W,
        "height": H,
        "junctions": J,
        "edges_positive": EP,
        "edges_negative": EN_raw,  # keep as given (often [])
        "filename": FN,
    }

    # If everything got dropped somehow, you can choose to error out:
    # if len(EP) == 0:
    #     raise ValueError(f"{src}: item #{idx} has no valid positive edges after cleaning")

    return rec_out


def main():
    if FILENAME_PREFIXES and len(FILENAME_PREFIXES) != len(INPUT_JSONS):
        raise SystemExit("FILENAME_PREFIXES length must match INPUT_JSONS (or leave it empty).")

    merged = OrderedDict()  # filename -> record
    total_in = total_kept = total_skipped = 0

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
                rec = validate_and_clean_record(rec, idx, os.path.basename(path))
            except ValueError as ve:
                print(f"[WARN] {ve} — skipping this record")
                total_skipped += 1
                continue

            # apply optional filename prefix
            if prefix:
                rec = dict(rec)
                rec["filename"] = prefix + rec["filename"]

            key = rec["filename"]
            if key in merged:
                if ON_FILENAME_COLLISION == "keep_first":
                    total_skipped += 1
                    continue
                elif ON_FILENAME_COLLISION == "keep_last":
                    merged[key] = rec
                    total_kept += 1  # overwrite counts as kept
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

    print("=== Merge summary (train.json) ===")
    print(f"Input records:         {total_in}")
    print(f"Kept records:          {total_kept}")
    print(f"Skipped (invalid/dups):{total_skipped}")
    print(f"Output records:        {len(records)}")
    print(f"Wrote: {OUT_JSON}")


if __name__ == "__main__":
    main()
