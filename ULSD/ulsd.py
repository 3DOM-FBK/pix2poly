#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Batch: GeoJSON (projected) -> pixel segments JSON (test.json style).
- Finds *.geojson in GEOJSON_DIR
- For each, uses matching <name>.png and <name>.wld in RASTER_DIR
- Outputs a single JSON array with objects:
  { "filename": "<name>.<OUTPUT_IMAGE_EXT>", "height": H, "width": W,
    "lines": [ [[x0,y0],[x1,y1]], ... ], "type": "pinhole" }
"""

from pathlib import Path
import json
import math

# =======================
# CONFIG — EDIT THESE
# =======================

# DO IT TWICE: first for train, then for test

GEOJSON_DIR = Path("outputs/test")     # where *.geojson live
OUTPUT_JSON = Path("outputs/ulsd/test.json")

# GEOJSON_DIR = Path("outputs/tiles_building")
# OUTPUT_JSON = Path("outputs/ulsd/train.json")

RASTER_DIR  = GEOJSON_DIR    # same names: <name>.png + <name>.wld

# Filename to write in JSON ("filename" field)
OUTPUT_IMAGE_EXT = ".png"   # use ".png" or ".jpg" etc., independent of source
ROUND_PIXELS     = True     # round to nearest integer
CLAMP_TO_IMAGE   = True     # clamp pixel coords into [0..W-1]/[0..H-1]
INCLUDE_HOLES    = True     # for polygons, include interior rings as lines
TYPE_FIELD       = "pinhole"
# =======================


def find_image_pair(stem: str):
    """Return (png_path, wld_path) if both exist in RASTER_DIR, else (None, None)."""
    png = None
    for ext in (".png", ".PNG"):
        p = (RASTER_DIR / f"{stem}{ext}")
        if p.exists():
            png = p
            break
    wld = RASTER_DIR / f"{stem}.wld"
    if png is None or not wld.exists():
        return None, None
    return png, wld


def read_image_size(path: Path):
    """Get (width, height)."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.width, im.height
    except Exception:
        try:
            import rasterio
            with rasterio.open(path) as ds:
                return ds.width, ds.height
        except Exception as e:
            raise RuntimeError(f"Cannot read size for {path}: {e}")


def read_wld(wld_path: Path):
    """
    Read 6-line world file:
    A, D, B, E, C, F
    C and F in world files are the center of the upper-left pixel. Convert
    them to the upper-left corner so pixel labels use the same convention as
    rasterio image coordinates.
    Return (A,B,C,D,E,F)
    """
    vals = [float(x.strip()) for x in wld_path.read_text().splitlines()[:6]]
    if len(vals) < 6:
        raise ValueError(f"Invalid world file (needs 6 numbers): {wld_path}")
    A, D, B, E, C_center, F_center = vals  # note order
    C = C_center - (A / 2.0) - (B / 2.0)
    F = F_center - (D / 2.0) - (E / 2.0)
    return A, B, C, D, E, F


def map_to_pixel(x_map: float, y_map: float, A, B, C, D, E, F):
    """
    Invert:
      [x_map - C]   [A  B] [col]
      [y_map - F] = [D  E] [row]
    """
    dx = x_map - C
    dy = y_map - F
    det = A * E - B * D
    if abs(det) < 1e-12:
        raise ValueError("Non-invertible worldfile transform (det≈0).")
    col = ( E*dx - B*dy) / det
    row = (-D*dx + A*dy) / det
    return col, row


def clamp_xy(x, y, W, H):
    return max(0, min(W - 1, x)), max(0, min(H - 1, y))


def _iter_polylines_from_geom(geom):
    """Yield polylines (list of [x,y]) from a GeoJSON geometry."""
    gtype = geom.get("type")
    C = geom.get("coordinates")
    if gtype == "LineString":
        if len(C) >= 2:
            yield C
    elif gtype == "MultiLineString":
        for line in C:
            if len(line) >= 2:
                yield line
    elif gtype == "Polygon":
        rings = C or []
        if rings:
            yield rings[0]
            if INCLUDE_HOLES:
                for r in rings[1:]:
                    yield r
    elif gtype == "MultiPolygon":
        for P in C or []:
            rings = P or []
            if rings:
                yield rings[0]
                if INCLUDE_HOLES:
                    for r in rings[1:]:
                        yield r
    elif gtype == "GeometryCollection":
        for g in geom.get("geometries", []):
            yield from _iter_polylines_from_geom(g)
    # Points ignored


def world_polyline_to_pixel_segments(polyline, wld_params, W, H):
    """Convert a polyline in map coords to list of pixel segments [[p0,p1], [p1,p2], ...]."""
    A, B, C, D, E, F = wld_params
    pix = []
    for x, y in polyline:
        cx, cy = map_to_pixel(float(x), float(y), A, B, C, D, E, F)
        if ROUND_PIXELS:
            cx, cy = int(round(cx)), int(round(cy))
        if CLAMP_TO_IMAGE:
            cx, cy = clamp_xy(cx, cy, W, H)
        pix.append([cx, cy])

    segs = []
    for i in range(len(pix) - 1):
        if pix[i] != pix[i + 1]:  # skip zero-length
            segs.append([pix[i], pix[i + 1]])
    return segs


def geojson_to_pixel_segments(geojson_path: Path, wld_params, W, H):
    data = json.loads(geojson_path.read_text(encoding="utf-8"))
    segs_all = []

    if data.get("type") == "FeatureCollection":
        for feat in data.get("features", []):
            geom = feat.get("geometry")
            if not geom:
                continue
            for pl in _iter_polylines_from_geom(geom):
                segs_all.extend(world_polyline_to_pixel_segments(pl, wld_params, W, H))
    elif data.get("type") in ("LineString", "MultiLineString", "Polygon", "MultiPolygon", "GeometryCollection"):
        for pl in _iter_polylines_from_geom(data):
            segs_all.extend(world_polyline_to_pixel_segments(pl, wld_params, W, H))
    # else: ignore
    return segs_all


def main():
    out_items = []
    missing = []

    for gj_path in sorted(GEOJSON_DIR.glob("*.geojson")):
        stem = gj_path.stem
        png_path, wld_path = find_image_pair(stem)
        if not png_path or not wld_path:
            missing.append(stem)
            continue

        W, H = read_image_size(png_path)
        wld_params = read_wld(wld_path)

        segs = geojson_to_pixel_segments(gj_path, wld_params, W, H)

        out_items.append({
            "filename": f"{stem}{OUTPUT_IMAGE_EXT}",
            "height": H,
            "width":  W,
            "lines":  segs,
            "type":   TYPE_FIELD,
        })

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(out_items, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote {len(out_items)} items -> {OUTPUT_JSON}")
    if missing:
        print("Missing pairs (no .png and/or .wld):", ", ".join(missing))


if __name__ == "__main__":
    main()
