#!/usr/bin/env python3
# Build HAWP test.json when each PNG has a same-name .geojson beside it
# Integer pixel coordinates; PNG+WLD worldfiles; no reprojection (shared EPSG).
# deps: rasterio, geopandas, shapely>=2, numpy, tqdm, pandas

import os
import json
import glob
from collections import OrderedDict

import numpy as np
import pandas as pd
import rasterio
from shapely.geometry import box, LineString, MultiLineString, GeometryCollection
import geopandas as gpd
from tqdm import tqdm

import warnings

warnings.filterwarnings('ignore', 'GeoSeries.notna', UserWarning)

# =========================
# CONFIG — EDIT ME
# =========================
TILES_DIR = r"outputs/test"         # folder containing 1.png, 1.wld, 1.geojson, etc.
OUT_JSON  = r"outputs/hawp/test.json"

COMMON_EPSG = "EPSG:5255"              # EPSG used by BOTH the PNG worldfiles and all per-tile GeoJSONs
INCLUDE_EMPTY_TILES = False             # include PNGs even if their matching .geojson is missing or empty

PNG_PATTERN = "*.png"                   # filter which PNGs to process
WORLD_FILE_REQUIRED = True              # warn/skip if .wld/.pgw missing
GEOJSON_REQUIRED     = False            # if True, skip tiles with no matching .geojson instead of writing empty
# Rounding mode for pixels: "round" | "floor" | "ceil"
PIXEL_ROUNDING_MODE = "round"
# =========================


def segmentize_lines(geom):
    """Yield 2-point LineStrings from LineString/MultiLineString/GeometryCollection."""
    if geom.is_empty:
        return
    if isinstance(geom, LineString):
        coords = list(geom.coords)
        for i in range(len(coords) - 1):
            yield LineString([coords[i], coords[i + 1]])
    elif isinstance(geom, MultiLineString):
        for g in geom.geoms:
            yield from segmentize_lines(g)
    elif isinstance(geom, GeometryCollection):
        for g in geom.geoms:
            if isinstance(g, (LineString, MultiLineString, GeometryCollection)):
                yield from segmentize_lines(g)


def to_pixel(transform_inv, x, y):
    """(col,row) in float from CRS coords using rasterio inverse affine."""
    col, row = transform_inv * (x, y)
    return float(col), float(row)


def qround(v):
    if PIXEL_ROUNDING_MODE == "floor":
        return int(np.floor(v))
    if PIXEL_ROUNDING_MODE == "ceil":
        return int(np.ceil(v))
    return int(round(v))


def quantize_and_clamp(col, row, width, height):
    """Round to integer pixels and clamp to [0..W-1], [0..H-1]."""
    ci = qround(col)
    ri = qround(row)
    if ci < 0: ci = 0
    if ri < 0: ri = 0
    if ci > width - 1: ci = width - 1
    if ri > height - 1: ri = height - 1
    return ci, ri


def has_worldfile(stem_path):
    """Check common PNG worldfile names next to the PNG stem."""
    pgw = stem_path + ".pgw"
    wld = stem_path + ".wld"
    return os.path.exists(pgw) or os.path.exists(wld)


def load_per_tile_geojson(geojson_path, epsg_str):
    """Load a single per-tile GeoJSON, keep line-like geometries, set CRS, return GeoDataFrame (possibly empty)."""
    if not os.path.exists(geojson_path):
        return gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs=epsg_str)
    gdf = gpd.read_file(geojson_path)
    if gdf.empty or "geometry" not in gdf.columns:
        return gdf.set_crs(epsg_str, allow_override=True)
    gdf = gdf[gdf.geometry.notnull()]
    gdf = gdf[gdf.geometry.geom_type.isin(["LineString", "MultiLineString"])]
    return gdf.set_crs(epsg_str, allow_override=True)


def main():
    png_paths = sorted(glob.glob(os.path.join(TILES_DIR, PNG_PATTERN)))
    if not png_paths:
        raise FileNotFoundError(f"No PNGs matching {PNG_PATTERN} found in {TILES_DIR}")

    out_records = []

    for png in tqdm(png_paths, desc="Processing tiles"):
        try:
            stem, _ = os.path.splitext(png)
            world_ok = has_worldfile(stem)
            if WORLD_FILE_REQUIRED and not world_ok:
                print(f"[WARN] Missing world file (.wld/.pgw) for: {os.path.basename(png)} — skipping")
                continue

            geojson_path = stem + ".geojson"
            if GEOJSON_REQUIRED and not os.path.exists(geojson_path):
                print(f"[WARN] Missing per-tile GeoJSON for: {os.path.basename(png)} — skipping")
                continue

            # Open raster (transform from worldfile). CRS is usually None; we *assume* COMMON_EPSG.
            with rasterio.open(png) as src:
                width, height = src.width, src.height
                transform = src.transform
                transform_inv = ~transform
                bounds = src.bounds
                tile_poly = box(bounds.left, bounds.bottom, bounds.right, bounds.top)

                # Load per-tile lines
                lines_gdf = load_per_tile_geojson(geojson_path, COMMON_EPSG)

                lines_segments_px = []
                junctions = []

                if not lines_gdf.empty:
                    # (Optional) clip to tile bounds to be safe
                    # Fast bbox filter first:
                    bbox_mask = lines_gdf.intersects(tile_poly)
                    cand = lines_gdf[bbox_mask]
                    for _, row in cand.iterrows():
                        geom = row.geometry
                        if geom is None or geom.is_empty:
                            continue
                        inter = geom.intersection(tile_poly)
                        if inter.is_empty:
                            continue

                        for seg in segmentize_lines(inter):
                            (x0, y0), (x1, y1) = list(seg.coords)[0], list(seg.coords)[-1]
                            c0, r0 = to_pixel(transform_inv, x0, y0)
                            c1, r1 = to_pixel(transform_inv, x1, y1)

                            c0i, r0i = quantize_and_clamp(c0, r0, width, height)
                            c1i, r1i = quantize_and_clamp(c1, r1, width, height)

                            # drop degenerate segments after rounding
                            if (c0i == c1i) and (r0i == r1i):
                                continue

                            lines_segments_px.append([c0i, r0i, c1i, r1i])
                            junctions.append((c0i, r0i))
                            junctions.append((c1i, r1i))

                if not lines_segments_px and not INCLUDE_EMPTY_TILES:
                    # no segments (missing or empty geojson) -> skip this tile
                    continue

                # Deduplicate integer junctions exactly
                seen = OrderedDict()
                for (x, y) in junctions:
                    if (x, y) not in seen:
                        seen[(x, y)] = [x, y]
                junc_list = list(seen.values())

                rec = {
                    "width": int(width),
                    "height": int(height),
                    "lines": lines_segments_px,
                    "junc": junc_list,
                    "filename": os.path.basename(png)
                }
                out_records.append(rec)

        except Exception as e:
            print(f"[WARN] Failed on tile {png}: {e}")

    # Write JSON
    output_dir = os.path.dirname(OUT_JSON)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out_records, f, ensure_ascii=False)

    print(f"Done. Wrote {len(out_records)} records to: {OUT_JSON}")


if __name__ == "__main__":
    main()
