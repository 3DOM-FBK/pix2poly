#!/usr/bin/env python3
# Merge multiple F-Clip train.json files into one (uses orjson)
# F-Clip record schema: {"width":int,"height":int,"lines":[[x1,y1,x2,y2],...],"filename":"*.png"}
# deps: orjson

import os
import orjson

# =========================
# CONFIG — EDIT ME
# =========================
INPUT_JSONS = [
    r"outputs/fclip/city_a.json",
    r"outputs/fclip/city_b.json",
    r"outputs/fclip/city_c.json",
]
OUT_JSON = r"outputs/fclip/merged.json"

# What to do if the same filename appears in multiple inputs:
#   "error"      -> stop with an error
#   "keep_first" -> keep the first occurrence, skip later ones
#   "keep_last"  -> later one overwrites the earlier one
#   "merge_lines"-> merge line arrays (dims must match); undirected duplicates removed
ON_FILENAME_COLLISION = "error"
# =========================


def validate_fclip_record(rec, src_name, idx):
    if not isinstance(rec, dict):
        raise ValueError(f"{src_name} item #{idx}: not an object")
    for k in ("width", "height", "lines", "filename"):
        if k not in rec:
            raise ValueError(f"{src_name} item #{idx}: missing '{k}'")
    w = int(rec["width"]); h = int(rec["height"])
    fn = str(rec["filename"])
    lines = rec["lines"]
    if not isinstance(lines, list):
        raise ValueError(f"{src_name} item #{idx}: 'lines' must be a list")

    # force ints
    fixed_lines = []
    for seg in lines:
        if not (isinstance(seg, (list, tuple)) and len(seg) == 4):
            raise ValueError(f"{src_name} item #{idx}: invalid line segment {seg}")
        x1, y1, x2, y2 = [int(seg[0]), int(seg[1]), int(seg[2]), int(seg[3])]
        fixed_lines.append([x1, y1, x2, y2])

    return {"width": w, "height": h, "lines": fixed_lines, "filename": fn}


def undirected_key(x1, y1, x2, y2):
    a = (x1, y1); b = (x2, y2)
    return (a, b) if a <= b else (b, a)


def merge_lines_undirected(lines_a, lines_b):
    kept, seen = [], set()
    for src in (lines_a, lines_b):
        for x1, y1, x2, y2 in src:
            k = undirected_key(x1, y1, x2, y2)
            if k not in seen:
                seen.add(k)
                kept.append([x1, y1, x2, y2])
    return kept


def main():
    merged = {}  # filename -> record
    total_in, total_kept, total_skipped = 0, 0, 0

    for path in INPUT_JSONS:
        if not os.path.exists(path):
            print(f"[WARN] missing file: {path} (skipping)")
            continue

        with open(path, "rb") as f:
            data = orjson.loads(f.read())

        if not isinstance(data, list):
            raise SystemExit(f"{path}: top-level JSON must be a list")

        src_name = os.path.basename(path)
        for idx, rec in enumerate(data):
            total_in += 1
            try:
                rec = validate_fclip_record(rec, src_name, idx)
            except ValueError as e:
                print(f"[WARN] {e} — skipping")
                total_skipped += 1
                continue

            fn = rec["filename"]
            if fn in merged:
                if ON_FILENAME_COLLISION == "error":
                    raise SystemExit(f"Filename collision: {fn} (from {src_name})")
                elif ON_FILENAME_COLLISION == "keep_first":
                    total_skipped += 1
                    continue
                elif ON_FILENAME_COLLISION == "keep_last":
                    merged[fn] = rec
                    total_kept += 1
                elif ON_FILENAME_COLLISION == "merge_lines":
                    prev = merged[fn]
                    if (prev["width"], prev["height"]) != (rec["width"], rec["height"]):
                        raise SystemExit(f"Dimension mismatch for {fn}: {prev['width']}x{prev['height']} vs {rec['width']}x{rec['height']}")
                    merged[fn] = {
                        "width": prev["width"],
                        "height": prev["height"],
                        "lines": merge_lines_undirected(prev["lines"], rec["lines"]),
                        "filename": fn,
                    }
                    total_kept += 1
                else:
                    raise SystemExit(f"Unknown ON_FILENAME_COLLISION='{ON_FILENAME_COLLISION}'")
            else:
                merged[fn] = rec
                total_kept += 1

    out_list = list(merged.values())
    out_list.sort(key=lambda r: r["filename"])

    output_dir = os.path.dirname(OUT_JSON)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(OUT_JSON, "wb") as f:
        f.write(orjson.dumps(out_list, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS))

    print("=== Merge summary ===")
    print(f"Input records:  {total_in}")
    print(f"Kept records:   {total_kept}")
    print(f"Skipped:        {total_skipped}")
    print(f"Output records: {len(out_list)}")
    print(f"Wrote: {OUT_JSON}")


if __name__ == "__main__":
    main()
