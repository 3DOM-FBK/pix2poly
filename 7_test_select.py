#!/usr/bin/env python3
import random
import re
from pathlib import Path
from typing import List, Tuple, Optional

# === USER SETTINGS ===
INPUT_FILE = "outputs/line_count.txt"     # file with lines like: tile_x.geojson - 49
TARGET_SUM = 592           # set to about 10% of total line count for a 90/10 split
RANDOM_SEED = 0             # change for different random valid subsets
SAVE_PATH: Optional[str] = "outputs/test.txt"  # set to None to skip saving
# ======================

LINE_RE = re.compile(r'^\s*(.+?)\s*-\s*(-?\d+)\s*$')

def parse_file(path: str) -> List[Tuple[str, int]]:
    items = []
    with open(path, 'r', encoding='utf-8') as f:
        for ln, line in enumerate(f, 1):
            m = LINE_RE.match(line)
            if not m:
                # skip non-matching lines (e.g., "............")
                continue
            name, num = m.group(1), int(m.group(2))
            items.append((name.strip(), num))
    return items

def subset_sum_exact(items: List[Tuple[str, int]], target: int, seed: int = None):
    """
    Returns list of indices of `items` whose values sum to `target`, or None if impossible.
    1D DP with backpointers (O(n*target) time, O(target) memory). Assumes non-negative counts.
    """
    if seed is not None:
        random.seed(seed)

    order = list(range(len(items)))
    random.shuffle(order)

    values = [items[i][1] for i in order]
    if any(v < 0 for v in values):
        raise ValueError("Negative counts are not supported by this DP method.")

    if target < 0:
        return None

    reachable = [False] * (target + 1)
    parent   = [-1] * (target + 1)  # previous sum
    picked   = [-1] * (target + 1)  # which shuffled index created this sum

    reachable[0] = True

    for k, val in enumerate(values):
        # update from high to low to avoid using an item multiple times in this step
        for s in range(target, val - 1, -1):
            if not reachable[s] and reachable[s - val]:
                reachable[s] = True
                parent[s] = s - val
                picked[s] = k
        if reachable[target]:
            break

    if not reachable[target]:
        return None

    # backtrack to recover chosen indices in original ordering
    s = target
    chosen_order_indices = []
    while s != 0:
        k = picked[s]
        if k == -1:
            return None
        chosen_order_indices.append(order[k])
        s = parent[s]

    chosen_order_indices.reverse()
    return chosen_order_indices

def main():
    items = parse_file(INPUT_FILE)
    if not items:
        print("No valid 'name - number' lines found.")
        return

    result_indices = subset_sum_exact(items, TARGET_SUM, seed=RANDOM_SEED)
    if result_indices is None:
        print(f"No exact subset sums to {TARGET_SUM}.")
        return

    chosen = [items[i] for i in result_indices]
    total = sum(v for _, v in chosen)

    print(f"Found {len(chosen)} tiles summing to {total}:")
    # for name, val in chosen:
        # print(f"{name} - {val}")

    if SAVE_PATH:
        save_path = Path(SAVE_PATH)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with save_path.open("w", encoding="utf-8") as f:
            for name, val in chosen:
                f.write(f"{name} - {val}\n")
        print(f"\nSaved selection to: {save_path}")

if __name__ == "__main__":
    main()
