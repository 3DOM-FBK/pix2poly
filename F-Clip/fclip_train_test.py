#!/usr/bin/env python3
# Build F-Clip test.json from PNG+WLD tiles and per-tile GeoJSON lines
# Integer pixel coordinates; no reprojection (shared EPSG).
# deps: rasterio, geopandas, shapely>=2, numpy, tqdm, orjson

import os
import glob
from collections import OrderedDict

import orjson
import numpy as np
import rasterio
from shapely.geometry import box, LineString, MultiLineString, GeometryCollection
import geopandas as gpd
from tqdm import tqdm

import warnings

warnings.filterwarnings('ignore', 'GeoSeries.notna', UserWarning)

# =========================
# CONFIG — EDIT ME
# =========================
PNG_DIR      = r"outputs/tiles_building"     # folder with .png (and .wld/.pgw next to them)
GEOJSON_DIR  = r"outputs/tiles_building"     # folder with per-tile .geojson
OUT_JSON     = r"outputs/fclip/train.json"

COMMON_EPSG  = "EPSG:7791"                     # EPSG used by ALL inputs
PNG_PATTERN  = "*.png"
REQUIRE_WORLDFILE = True
REQUIRE_GEOJSON   = False
INCLUDE_EMPTY_TILES = False

# Pixel rounding mode: "round" | "floor" | "ceil"
PIXEL_ROUNDING_MODE = "round"

# Cleaning options
DROP_ZERO_LENGTH = True
DROP_UNDIRECTED_DUPLICATES = True
# =========================


def segmentize(geom):
    """Yield 2-point LineStrings from LineString/MultiLineString/GeometryCollection."""
    if geom.is_empty:
        return
    if isinstance(geom, LineString):
        c = list(geom.coords)
        for i in range(len(c) - 1):
            yield LineString([c[i], c[i + 1]])
    elif isinstance(geom, MultiLineString):
        for g in geom.geoms:
            yield from segmentize(g)
    elif isinstance(geom, GeometryCollection):
        for g in geom.geoms:
            if isinstance(g, (LineString, MultiLineString, GeometryCollection)):
                yield from segmentize(g)


def find_worldfile(png_path):
    base, _ = os.path.splitext(png_path)
    for ext in (".pgw", ".wld"):
        p = base + ext
        if os.path.exists(p):
            return p
    return None


def qround(v):
    if PIXEL_ROUNDING_MODE == "floor":
        return int(np.floor(v))
    if PIXEL_ROUNDING_MODE == "ceil":
        return int(np.ceil(v))
    return int(round(v))


def quantize_and_clamp(col, row, width, height):
    """Round to integer pixels and clamp to [0..W-1], [0..H-1]."""
    ci = qround(col);  ri = qround(row)
    if ci < 0: ci = 0
    if ri < 0: ri = 0
    if ci > width - 1: ci = width - 1
    if ri > height - 1: ri = height - 1
    return ci, ri


def load_per_tile_geojson(geojson_path, epsg_str):
    """Return line-only GeoDataFrame (possibly empty), forcing CRS to epsg_str (no reprojection)."""
    if not os.path.exists(geojson_path):
        return gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs=epsg_str)
    gdf = gpd.read_file(geojson_path)
    if gdf.empty or "geometry" not in gdf.columns:
        return gdf.set_crs(epsg_str, allow_override=True)
    gdf = gdf[gdf.geometry.notnull()]
    gdf = gdf[gdf.geometry.geom_type.isin(["LineString", "MultiLineString"])]
    return gdf.set_crs(epsg_str, allow_override=True)


def undirected_key(x1, y1, x2, y2):
    """Canonical key for undirected segment."""
    a = (x1, y1); b = (x2, y2)
    return (a, b) if a <= b else (b, a)


def main():
    png_paths = sorted(glob.glob(os.path.join(PNG_DIR, PNG_PATTERN)))
    if not png_paths:
        raise FileNotFoundError(f"No PNGs matching {PNG_PATTERN} found in {PNG_DIR}")

    out_records = []

    for png in tqdm(png_paths, desc="Building F-Clip JSON (orjson)"):
        try:
            stem = os.path.splitext(os.path.basename(png))[0]
            geojson_path = os.path.join(GEOJSON_DIR, stem + ".geojson")
            wld_path = find_worldfile(png)

            if REQUIRE_WORLDFILE and not wld_path:
                print(f"[WARN] Missing world file for {stem}.png — skipping")
                continue
            if REQUIRE_GEOJSON and not os.path.exists(geojson_path):
                print(f"[WARN] Missing per-tile GeoJSON for {stem}.png — skipping")
                continue

            with rasterio.open(png) as src:
                W, H = src.width, src.height
                transform = src.transform
                transform_inv = ~transform
                bounds = src.bounds
                tile_poly = box(bounds.left, bounds.bottom, bounds.right, bounds.top)

                lines_gdf = load_per_tile_geojson(geojson_path, COMMON_EPSG)

                segs = []
                if not lines_gdf.empty:
                    mask = lines_gdf.intersects(tile_poly)
                    cand = lines_gdf[mask]
                    for _, row in cand.iterrows():
                        g = row.geometry
                        if g is None or g.is_empty:
                            continue
                        inter = g.intersection(tile_poly)
                        if inter.is_empty:
                            continue
                        for seg in segmentize(inter):
                            (x0, y0), (x1, y1) = list(seg.coords)[0], list(seg.coords)[-1]
                            c0, r0 = transform_inv * (x0, y0)
                            c1, r1 = transform_inv * (x1, y1)
                            c0i, r0i = quantize_and_clamp(c0, r0, W, H)
                            c1i, r1i = quantize_and_clamp(c1, r1, W, H)
                            if DROP_ZERO_LENGTH and (c0i == c1i and r0i == r1i):
                                continue
                            segs.append([c0i, r0i, c1i, r1i])

                if DROP_UNDIRECTED_DUPLICATES and segs:
                    kept = []
                    seen = set()
                    for x1, y1, x2, y2 in segs:
                        k = undirected_key(x1, y1, x2, y2)
                        if k in seen:
                            continue
                        seen.add(k)
                        kept.append([x1, y1, x2, y2])
                    segs = kept

                if not segs and not INCLUDE_EMPTY_TILES:
                    continue

                out_records.append({
                    "width": int(W),
                    "height": int(H),
                    "lines": segs,
                    "filename": f"{stem}.png"
                })

        except Exception as e:
            print(f"[WARN] Failed on {png}: {e}")

    # Write single JSON with orjson (bytes)
    output_dir = os.path.dirname(OUT_JSON)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(OUT_JSON, "wb") as f:
        f.write(orjson.dumps(
            out_records,
            option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS
        ))

    print(f"Done. Wrote {len(out_records)} items → {OUT_JSON}")


if __name__ == "__main__":
    main()
