#!/usr/bin/env python3
"""
Move GeoJSONs (and matching world files) whose basename matches PNG filenames.

Steps:
1) Read all .png files in PNG_DIR.
2) For each PNG, take the stem => <name>.geojson and <name>.wld (and optionally <name>.pgw).
3) Find those files in GEOJSON_DIR (for .geojson) and WORLD_DIR (for .wld/.pgw), optionally recursive.
4) Move matched files to DEST_DIR (created if missing).

Configure paths & flags in the CONFIG section below.
"""

from pathlib import Path
from collections import defaultdict
import shutil

# === CONFIG ===
PNG_DIR       = Path("outputs/tiles_building")
GEOJSON_DIR   = Path("outputs/geojson_tiles")

DEST_DIR      = PNG_DIR
WORLD_DIR     = PNG_DIR

RECURSIVE         = True      # Search subfolders for PNG/GeoJSON/World files
CASE_INSENSITIVE  = True      # Match names case-insensitively
DRY_RUN           = True      # inspect actions first; set False to move files
OVERWRITE         = False     # True: overwrite existing files in DEST_DIR
INCLUDE_PGW       = True      # Also move <name>.pgw if present (common PNG worldfile extension)
# ==============

def collect_files(root: Path, pattern: str, recursive: bool):
    return list(root.rglob(pattern) if recursive else root.glob(pattern))

def safe_move(src: Path, dest: Path, *, overwrite: bool, dry_run: bool) -> str:
    if dest.exists():
        if overwrite:
            if dry_run:
                return f"[dry-run] Overwrite: {dest} with {src}"
            dest.unlink()
            shutil.move(str(src), str(dest))
            return f"Overwrote: {dest.name}"
        else:
            return f"Skip (exists): {dest}"
    else:
        if dry_run:
            return f"[dry-run] Move: {src} -> {dest}"
        shutil.move(str(src), str(dest))
        return f"Moved: {src.name}"

def main():
    # Validate directories
    for pth, label in [(PNG_DIR, "PNG"), (GEOJSON_DIR, "GeoJSON"), (WORLD_DIR, "World"), (DEST_DIR, "Destination")]:
        if label != "Destination" and not pth.is_dir():
            raise SystemExit(f"{label} directory not found: {pth}")
    if not DEST_DIR.exists():
        if DRY_RUN:
            print(f"[dry-run] Would create destination: {DEST_DIR}")
        else:
            DEST_DIR.mkdir(parents=True, exist_ok=True)

    # 1) Read PNGs
    pngs = collect_files(PNG_DIR, "*.png", RECURSIVE)
    if not pngs:
        print("No PNG files found.")
        return

    # Build target stems from PNG names
    target_stems = {p.stem for p in pngs}
    if CASE_INSENSITIVE:
        target_stems = {s.lower() for s in target_stems}

    # 3) Index GeoJSONs
    geojson_files = collect_files(GEOJSON_DIR, "*.geojson", RECURSIVE)
    index_geo = defaultdict(list)  # stem -> [paths]
    for gj in geojson_files:
        key = gj.stem.lower() if CASE_INSENSITIVE else gj.stem
        index_geo[key].append(gj)

    # Index world files
    world_patterns = ["*.wld"] + (["*.pgw"] if INCLUDE_PGW else [])
    world_files = []
    for pat in world_patterns:
        world_files.extend(collect_files(WORLD_DIR, pat, RECURSIVE))

    index_wld = defaultdict(list)  # stem -> [paths]
    for wf in world_files:
        key = wf.stem.lower() if CASE_INSENSITIVE else wf.stem
        index_wld[key].append(wf)

    # 4) Move matches
    moved_geo = 0
    moved_wld = 0
    overwritten_geo = 0
    overwritten_wld = 0
    skipped_dupes_geo = 0
    missing_geo = []
    missing_wld = []

    for stem in sorted(target_stems):
        # GeoJSON
        g_matches = index_geo.get(stem, [])
        if not g_matches:
            missing_geo.append(stem)
        elif len(g_matches) > 1:
            print(f"Warning: multiple GeoJSONs found for '{stem}':")
            for m in g_matches:
                print(f"  - {m}")
            skipped_dupes_geo += 1
        else:
            src = g_matches[0]
            dest = DEST_DIR / src.name
            msg = safe_move(src, dest, overwrite=OVERWRITE, dry_run=DRY_RUN)
            print(msg)
            if msg.startswith("Moved:"):
                moved_geo += 1
            elif msg.startswith("Overwrote:"):
                moved_geo += 1
                overwritten_geo += 1

        # World files (.wld / .pgw)
        w_matches = index_wld.get(stem, [])
        if not w_matches:
            # only mark missing if we expected one (harmless if not all PNGs have worldfiles)
            missing_wld.append(stem)
        else:
            for wf in w_matches:
                dest = DEST_DIR / wf.name
                msg = safe_move(wf, dest, overwrite=OVERWRITE, dry_run=DRY_RUN)
                print(msg)
                if msg.startswith("Moved:"):
                    moved_wld += 1
                elif msg.startswith("Overwrote:"):
                    moved_wld += 1
                    overwritten_wld += 1

    # Summary
    print("\n=== Summary ===")
    print(f"PNGs scanned: {len(pngs)}")
    print(f"Unique stems: {len(target_stems)}")
    print(f"GeoJSONs scanned: {len(geojson_files)}")
    print(f"World files scanned: {len(world_files)}")
    print(f"GeoJSONs moved: {moved_geo}  (overwritten: {overwritten_geo})")
    print(f"World files moved: {moved_wld}  (overwritten: {overwritten_wld})")
    if skipped_dupes_geo:
        print(f"Skipped due to duplicate GeoJSON stems: {skipped_dupes_geo}")
    if missing_geo:
        print(f"Missing GeoJSONs for {len(missing_geo)} stems (first 20): {', '.join(missing_geo[:20])}")
    if missing_wld:
        # Many PNGs may not have worldfiles; this is informational.
        print(f"No worldfile found for {len(missing_wld)} stems (first 20): {', '.join(missing_wld[:20])}")
    if DRY_RUN:
        print("Dry run: no files were changed.")

if __name__ == "__main__":
    main()
