#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Count lines in GeoJSON files and write a report.

- Looks for *.geojson in GEOJSON_DIR (optionally recursive)
- For each file, counts:
    COUNT_MODE = "features" -> number of line features (LineString + each part of MultiLineString)
    COUNT_MODE = "segments" -> total number of segments (edges) across all polylines
- Optionally include polygon rings as lines (outer + holes) if INCLUDE_POLYGON_RINGS=True
- Writes a text file with "filename - count" lines.
"""

from pathlib import Path
import json
from typing import Iterable, List

# ============ CONFIG — EDIT THESE ============
GEOJSON_DIR = Path("outputs/tiles_building")
OUTPUT_TXT  = Path("outputs/line_count.txt")

RECURSIVE = False                 # search subfolders
COUNT_MODE = "features"           # "features" or "segments"
INCLUDE_POLYGON_RINGS = False     # count polygon rings as lines too
# ============================================


def _iter_polylines_from_geom(geom: dict, include_polygons: bool) -> Iterable[List[List[float]]]:
    """Yield polylines (as lists of [x,y]) from a GeoJSON geometry."""
    gtype = geom.get("type")
    C = geom.get("coordinates")

    if gtype == "LineString":
        if isinstance(C, list) and len(C) >= 2:
            yield C
    elif gtype == "MultiLineString":
        for part in C or []:
            if isinstance(part, list) and len(part) >= 2:
                yield part
    elif include_polygons and gtype == "Polygon":
        # outer + holes as polylines
        for ring in C or []:
            if isinstance(ring, list) and len(ring) >= 2:
                yield ring
    elif include_polygons and gtype == "MultiPolygon":
        for poly in C or []:
            for ring in poly or []:
                if isinstance(ring, list) and len(ring) >= 2:
                    yield ring
    elif gtype == "GeometryCollection":
        for g in geom.get("geometries", []) or []:
            yield from _iter_polylines_from_geom(g, include_polygons)


def _count_in_geojson(path: Path, mode: str, include_polygons: bool) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))

    # Gather all polylines to count
    polylines: List[List[List[float]]] = []

    if data.get("type") == "FeatureCollection":
        for feat in data.get("features", []):
            geom = feat.get("geometry")
            if not isinstance(geom, dict):
                continue
            polylines.extend(_iter_polylines_from_geom(geom, include_polygons))
    elif isinstance(data, dict) and "type" in data:
        # single-geometry GeoJSON
        polylines.extend(_iter_polylines_from_geom(data, include_polygons))
    else:
        return 0

    if mode == "features":
        # Each polyline counts as 1 (each part of MultiLineString counts separately)
        return len(polylines)
    elif mode == "segments":
        # Sum edges; for closed rings (first==last) avoid double-counting the closing edge
        total = 0
        for line in polylines:
            n = len(line)
            if n < 2:
                continue
            # If ring and first equals last, segments are n-1-1
            is_closed = (line[0] == line[-1])
            segs = (n - 1) - (1 if is_closed else 0)
            total += max(0, segs)
        return total
    else:
        raise ValueError("COUNT_MODE must be 'features' or 'segments'")


def main():
    pattern = "**/*.geojson" if RECURSIVE else "*.geojson"
    files = sorted([p for p in GEOJSON_DIR.glob(pattern) if p.is_file()])

    if not files:
        print(f"No .geojson files found in {GEOJSON_DIR}")
        return

    lines = []
    grand_total = 0
    for p in files:
        try:
            cnt = _count_in_geojson(p, COUNT_MODE, INCLUDE_POLYGON_RINGS)
        except Exception as e:
            cnt = -1
            print(f"[WARN] Failed to read {p.name}: {e}")
        name = p.name
        lines.append(f"{name} - {cnt}")
        if cnt >= 0:
            grand_total += cnt

    OUTPUT_TXT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_TXT.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote report: {OUTPUT_TXT}")
    ok = sum(1 for l in lines if not l.endswith(" - -1"))
    print(f"Files processed: {ok}/{len(files)} | Grand total ({COUNT_MODE}): {grand_total}")


if __name__ == "__main__":
    main()
