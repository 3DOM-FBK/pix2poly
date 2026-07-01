#!/usr/bin/env python3
import re
import shutil
from pathlib import Path
from typing import Set, List

# ========== USER SETTINGS ==========
INPUT_FILE   = "outputs/test.txt"
SOURCE_ROOT  = Path("outputs/tiles_building")  # searched recursively
DEST_DIR     = Path("outputs/test")            # all found files moved here (flat)
EXTENSIONS   = [".geojson", ".png", ".wld"]
RECURSIVE    = True                  # search subfolders
OVERWRITE    = False                 # overwrite if same filename exists in DEST_DIR
DRY_RUN      = True                  # inspect actions first; set False to move
# ===================================

LINE_RE = re.compile(r'^\s*(.+?)\.geojson\s*-\s*(-?\d+)\s*$')  # capture basename before .geojson

def read_basenames(txt_path: Path) -> Set[str]:
    basenames = set()
    with txt_path.open("r", encoding="utf-8") as f:
        for line in f:
            m = LINE_RE.match(line)
            if m:
                basenames.add(m.group(1).strip())
    return basenames

def find_matches(root: Path, basename: str, ext: str) -> List[Path]:
    pattern = f"{basename}{ext}"
    if RECURSIVE:
        return list(root.rglob(pattern))
    else:
        return list(root.glob(pattern))

def ensure_dest(dest: Path):
    dest.mkdir(parents=True, exist_ok=True)

def move_file(src: Path, dest_dir: Path):
    target = dest_dir / src.name
    if target.exists():
        if OVERWRITE:
            if not DRY_RUN:
                # remove existing file before moving
                target.unlink()
        else:
            print(f"SKIP (exists): {target}")
            return
    print(f"MOVE: {src}  ->  {target}")
    if not DRY_RUN:
        shutil.move(str(src), str(target))

def main():
    if DRY_RUN:
        print(f"DRY RUN: would create destination if needed: {DEST_DIR}")
    else:
        ensure_dest(DEST_DIR)

    basenames = read_basenames(Path(INPUT_FILE))
    if not basenames:
        print("No basenames parsed from input file. Check format like: 'tile_x.geojson - 45'")
        return

    total_requested = 0
    total_found = 0
    total_moved = 0

    for base in sorted(basenames):
        for ext in EXTENSIONS:
            total_requested += 1
            matches = find_matches(SOURCE_ROOT, base, ext)
            if not matches:
                print(f"NOT FOUND: {base}{ext}")
                continue

            total_found += len(matches)
            if len(matches) > 1:
                print(f"WARN: multiple matches for {base}{ext}:")
                for m in matches:
                    print(f"  - {m}")

            for m in matches:
                move_file(m, DEST_DIR)
                total_moved += 1

    print("\n=== SUMMARY ===")
    print(f"Basenames listed: {len(basenames)}")
    print(f"Files requested (3 per base): {total_requested}")
    print(f"Files found: {total_found}")
    print(f"Files moved: {total_moved}")
    if DRY_RUN:
        print("DRY RUN: no files were actually moved.")

if __name__ == "__main__":
    main()
