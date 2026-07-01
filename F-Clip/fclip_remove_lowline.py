#!/usr/bin/env python3
# Filter tiles with too-few lines (<= 3) from a JSON file using orjson.

import orjson
from pathlib import Path

IN_JSON  = r"outputs/fclip/train_raw.json"
OUT_JSON = r"outputs/fclip/train.json"
MIN_LINES = 3  # keep samples with at least this many lines

def count_lines(sample) -> int:
    """Return the number of line segments in a sample."""
    lines = sample.get("lines", [])
    # Lines may be list of [x1,y1,x2,y2] or list of dicts; both count as items.
    return len(lines)

def filter_list(samples):
    kept = [s for s in samples if count_lines(s) >= MIN_LINES]
    return kept, len(samples) - len(kept)

def main():
    data = orjson.loads(Path(IN_JSON).read_bytes())

    removed = 0
    changed = False

    if isinstance(data, list):
        data, removed = filter_list(data)
        changed = True
    elif isinstance(data, dict):
        # Find the list that actually holds the samples (common keys below).
        candidate_keys = ["images", "data", "samples", "tiles", "annotations"]
        for k in candidate_keys:
            v = data.get(k, None)
            if isinstance(v, list) and v and isinstance(v[0], dict) and "lines" in v[0]:
                filtered, rem = filter_list(v)
                data[k] = filtered
                removed += rem
                changed = True
                break
        # If none of the keys matched but the dict itself looks like a sample, wrap in list logic
        if not changed and "lines" in data:
            # Single-sample file → drop file if it has too few lines
            if count_lines(data) < MIN_LINES:
                data = None
                removed = 1
                changed = True

    # Write result
    if data is None:
        # Write an empty list to indicate nothing left
        out_bytes = orjson.dumps([], option=orjson.OPT_INDENT_2)
    else:
        out_bytes = orjson.dumps(data, option=orjson.OPT_INDENT_2)

    out_path = Path(OUT_JSON)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(out_bytes)

    total = "unknown"
    if isinstance(data, list):
        total = len(data) + removed
    elif isinstance(data, dict):
        for k in ["images", "data", "samples", "tiles", "annotations"]:
            if isinstance(data.get(k), list):
                total = len(data[k]) + removed
                break

    print(f"Removed {removed} samples with <= {MIN_LINES-1} lines (from {total}).")
    print(f"Wrote: {OUT_JSON}")

if __name__ == "__main__":
    main()
