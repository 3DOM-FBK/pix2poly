#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Match .geojson basenames to .png/.wld and move/copy matches.

Now also:
- tiles that DO have a matching .geojson AND >= MIN_LINES  -> DEST_DIR/tiles_building
- tiles that DO have a matching .geojson AND <  MIN_LINES  -> DEST_DIR/tiles_lowline
- tiles that DO NOT have a matching .geojson               -> DEST_DIR/tiles_empty
"""

from pathlib import Path
import shutil
import sys
import json

# =======================
# CONFIG — EDIT THESE
# =======================

MIN_LINES = 10  # minimum line features required for building tiles

GEOJSON_DIR = Path("outputs/geojson_tiles")
RASTER_DIR  = Path("outputs/tiles_png")
DEST_DIR    = RASTER_DIR

COPY_INSTEAD_OF_MOVE = True   # safer default for public runs; set False to move
OVERWRITE            = False  # True to overwrite existing files in destination
DRY_RUN              = True   # inspect the summary first; set False to write files

RECURSIVE_GEOJSON    = False  # Search GEOJSON_DIR recursively
RECURSIVE_RASTERS    = False  # Search RASTER_DIR recursively

# Only these suffixes will be moved/copied for each matching basename:
WANTED_SUFFIXES = {".png", ".wld", ".jpg"}  # add ".tif"/".tiff" if needed
# =======================


def index_geojsons(geojson_dir: Path, recursive: bool) -> dict[str, Path]:
    """Map stem_lower -> Path for .geojson files (first hit wins)."""
    pattern = "**/*.geojson" if recursive else "*.geojson"
    idx: dict[str, Path] = {}
    for p in geojson_dir.glob(pattern):
        if p.is_file():
            key = p.stem.lower()
            idx.setdefault(key, p)
    return idx


def index_rasters(raster_dir: Path, recursive: bool, wanted: set[str]) -> dict[tuple[str, str], Path]:
    """Map (stem_lower, suffix_lower) -> Path for wanted suffixes."""
    pattern = "**/*" if recursive else "*"
    idx: dict[tuple[str, str], Path] = {}
    for p in raster_dir.glob(pattern):
        if p.is_file():
            sfx = p.suffix.lower()
            if sfx in wanted:
                key = (p.stem.lower(), sfx)
                idx.setdefault(key, p)  # first hit wins
    return idx


def ensure_dest(dest: Path, dry_run: bool = False):
    if dry_run:
        return
    dest.mkdir(parents=True, exist_ok=True)


def move_or_copy(src: Path, dst: Path, do_copy: bool, overwrite: bool, dry_run: bool):
    if dst.exists():
        if overwrite:
            if dry_run:
                print(f"[DRY] overwrite {dst}")
            else:
                if dst.is_file():
                    dst.unlink()
                else:
                    raise RuntimeError(f"Destination exists and is not a file: {dst}")
        else:
            print(f"[SKIP] Exists at destination: {dst.name}")
            return

    action = "COPY" if do_copy else "MOVE"
    if dry_run:
        print(f"[DRY] {action}: {src} -> {dst}")
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if do_copy:
            shutil.copy2(src, dst)
        else:
            shutil.move(str(src), str(dst))
        print(f"[{action}] {src.name}")


def process_group(stems: set[str], dest_folder: Path, raster_index: dict[tuple[str, str], Path],
                  overwrite: bool, dry_run: bool, do_copy: bool) -> tuple[int, int]:
    """
    Move/copy all wanted files for each stem into dest_folder.
    Returns (files_moved, stems_with_missing_any_suffix)
    """
    ensure_dest(dest_folder, dry_run=dry_run)
    moved = 0
    missing_count = 0
    for stem in sorted(stems):
        have_any = False
        missing_any = False
        for sfx in sorted(WANTED_SUFFIXES):  # stable order
            src = raster_index.get((stem, sfx.lower()))
            if src is None:
                missing_any = True
                continue
            have_any = True
            dst = dest_folder / src.name
            before = dst.exists()
            move_or_copy(src, dst, do_copy=do_copy, overwrite=overwrite, dry_run=dry_run)
            if dry_run:
                moved += 1
            else:
                if overwrite or not before:
                    moved += 1
        if have_any and missing_any:
            missing_count += 1
    return moved, missing_count


def count_lines_in_geojson(gj_path: Path) -> int:
    """
    Count 'lines' in a GeoJSON. We treat:
      - LineString -> 1 line
      - MultiLineString -> number of parts
    Other geometry types are ignored.
    """
    try:
        with gj_path.open("r", encoding="utf-8") as f:
            gj = json.load(f)
    except Exception as e:
        print(f"[WARN] Failed to read {gj_path}: {e}")
        return 0

    features = gj.get("features", [])
    total = 0
    for feat in features:
        geom = feat.get("geometry") or {}
        gtyp = (geom.get("type") or "").lower()
        if gtyp == "linestring":
            total += 1
        elif gtyp == "multilinestring":
            coords = geom.get("coordinates") or []
            total += len(coords)
    return total


def main():
    # Basic checks
    for d in (GEOJSON_DIR, RASTER_DIR):
        if not d.exists() or not d.is_dir():
            print(f"Error: not a directory: {d}", file=sys.stderr)
            sys.exit(2)

    # Prepare destination subfolders
    DEST_BUILDING = DEST_DIR / "tiles_building"
    DEST_EMPTY    = DEST_DIR / "tiles_empty"
    DEST_LOWLINE  = DEST_DIR / "tiles_lowline"
    ensure_dest(DEST_DIR, dry_run=DRY_RUN)
    ensure_dest(DEST_BUILDING, dry_run=DRY_RUN)
    ensure_dest(DEST_EMPTY, dry_run=DRY_RUN)
    ensure_dest(DEST_LOWLINE, dry_run=DRY_RUN)

    # Collect sets
    geo_idx      = index_geojsons(GEOJSON_DIR, RECURSIVE_GEOJSON)
    raster_index = index_rasters(RASTER_DIR, RECURSIVE_RASTERS, {s.lower() for s in WANTED_SUFFIXES})
    raster_stems = {stem for (stem, _sfx) in raster_index.keys()}

    if not raster_stems:
        print("No raster files (wanted suffixes) found in RASTER_DIR. Nothing to do.")
        return

    # Partition raster stems
    stems_with_geo = {s for s in raster_stems if s in geo_idx}
    stems_empty    = raster_stems - stems_with_geo

    # Further split stems_with_geo by line count
    stems_lowline = set()
    stems_building = set()
    for stem in stems_with_geo:
        gj_path = geo_idx[stem]
        n_lines = count_lines_in_geojson(gj_path)
        if n_lines < MIN_LINES:
            stems_lowline.add(stem)
        else:
            stems_building.add(stem)

    moved_bld, miss_bld = process_group(
        stems_building, DEST_BUILDING, raster_index,
        overwrite=OVERWRITE, dry_run=DRY_RUN, do_copy=COPY_INSTEAD_OF_MOVE
    )
    moved_low, miss_low = process_group(
        stems_lowline, DEST_LOWLINE, raster_index,
        overwrite=OVERWRITE, dry_run=DRY_RUN, do_copy=COPY_INSTEAD_OF_MOVE
    )
    moved_emp, miss_emp = process_group(
        stems_empty, DEST_EMPTY, raster_index,
        overwrite=OVERWRITE, dry_run=DRY_RUN, do_copy=COPY_INSTEAD_OF_MOVE
    )

    print("\n=== Summary ===")
    print(f"GeoJSON files indexed:             {len(geo_idx)}")
    print(f"Raster tile stems found:           {len(raster_stems)}")
    print(f"  ↳ with .geojson:                 {len(stems_with_geo)}")
    print(f"      • building (>= {MIN_LINES}): {len(stems_building)}")
    print(f"      • lowline   (<  {MIN_LINES}): {len(stems_lowline)}")
    print(f"  ↳ empty (no .geojson):           {len(stems_empty)}")
    print(f"Files moved/copied (building):     {moved_bld}  (stems missing a partner: {miss_bld})")
    print(f"Files moved/copied (lowline):      {moved_low}  (stems missing a partner: {miss_low})")
    print(f"Files moved/copied (empty):        {moved_emp}  (stems missing a partner: {miss_emp})")


if __name__ == "__main__":
    main()
