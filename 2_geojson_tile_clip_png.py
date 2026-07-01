#!/usr/bin/env python3
"""
Clip a GeoJSON by the bounding box of each tiled image, outputting linework.

- Reads all *.png files in TILES_DIR that have a matching .wld (world file).
- (Optional) Falls back to .pgw if ALLOW_PGW_FALLBACK=True.
- Builds the affine transform from the world file (handles UL pixel center -> corner).
- Computes each tile's geographic bounds (bbox).
- Clips/cuts input linework to the bbox (lines are split at borders).
- If input contains polygons, uses polygon boundaries before clipping to avoid
  creating artificial tile-border cut lines.
- Writes one GeoJSON (or GPKG) per tile.

Dependencies:
    pip install geopandas shapely rasterio tqdm pyproj
"""

import os
import json
from glob import glob
from typing import Tuple, Optional

import rasterio
from rasterio.transform import Affine, array_bounds
from shapely.geometry import box
from shapely.ops import unary_union
import geopandas as gpd
from tqdm import tqdm
from pyproj import CRS

# =========================
# User settings
# =========================
TILES_DIR         = r"outputs/tiles_png"  # folder with .png + .wld
INPUT_GEOJSON     = r"data/linework/roof_lines.geojson"  # linework or polygons with CRS
OUTPUT_DIR        = r"outputs/geojson_tiles"
RASTER_EPSG       = 7791                     # CRS of the tiles (world files don't carry CRS)
OUTPUT_FORMAT     = "GeoJSON"                # "GeoJSON" or "GPKG"
OUTPUT_SUFFIX     = ""                       # appended to tile basename (e.g., "_lines")
WRITE_EMPTY_FILES = False                    # if False, skip writing when no intersections

# Worldfile handling
REQUIRE_WLD            = True                # require .wld to exist for each .png
ALLOW_PGW_FALLBACK     = True                # if no .wld, try .pgw
ALLOW_TFW_FALLBACK     = False               # last resort (not typical for PNG)
# =========================


def find_worldfile_for_png(png_path: str) -> Optional[str]:
    base = os.path.splitext(png_path)[0]
    candidates = []
    if REQUIRE_WLD:
        candidates.append(base + ".wld")
    if ALLOW_PGW_FALLBACK:
        candidates.append(base + ".pgw")
    if ALLOW_TFW_FALLBACK:
        candidates.append(base + ".tfw")
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def read_worldfile_to_affine(wld_path: str) -> Affine:
    """
    Read an ESRI world file (.wld/.pgw/.tfw) and return an Affine transform.
    World file lines: A, D, B, E, C, F where C,F are the CENTER of UL pixel.
    GDAL/rasterio expect C,F for the UL CORNER, so shift by half a pixel.
    """
    with open(wld_path, "r") as f:
        vals = []
        for _ in range(6):
            line = f.readline()
            if not line:
                break
            s = line.strip()
            if s:
                vals.append(float(s))
    if len(vals) != 6:
        raise ValueError(f"Invalid world file (needs 6 numbers): {wld_path}")
    A, D, B, E, C_center, F_center = vals
    C_corner = C_center - (A / 2.0) - (B / 2.0)
    F_corner = F_center - (D / 2.0) - (E / 2.0)
    return Affine(A, B, C_corner, D, E, F_corner)


def tile_bounds(width: int, height: int, transform: Affine) -> Tuple[float, float, float, float]:
    """Return (minx, miny, maxx, maxy) in the tile's CRS."""
    minx, miny, maxx, maxy = array_bounds(height, width, transform)
    return (minx, miny, maxx, maxy)


def geometry_to_linework(geom):
    """
    Return geometry as linework:
      - LineString/MultiLineString: unchanged
      - Polygon/MultiPolygon: boundary only
      - GeometryCollection: recursively keep linework parts
      - Other geometry types: dropped
    """
    if geom is None or geom.is_empty:
        return None

    gtype = geom.geom_type
    if gtype in ("LineString", "MultiLineString"):
        return geom
    if gtype in ("Polygon", "MultiPolygon"):
        boundary = geom.boundary
        return None if boundary.is_empty else boundary
    if gtype == "GeometryCollection":
        parts = []
        for part in geom.geoms:
            line_part = geometry_to_linework(part)
            if line_part is not None and not line_part.is_empty:
                parts.append(line_part)
        if not parts:
            return None
        merged = unary_union(parts)
        return None if merged.is_empty else merged
    return None


def write_empty_output(base: str, columns, raster_crs):
    empty = gpd.GeoDataFrame(columns=columns, geometry=[], crs=raster_crs)
    if OUTPUT_FORMAT == "GeoJSON":
        out_path = os.path.join(OUTPUT_DIR, f"{base}{OUTPUT_SUFFIX}.geojson")
        empty.to_file(out_path, driver="GeoJSON")
    else:
        out_path = os.path.join(OUTPUT_DIR, f"{base}{OUTPUT_SUFFIX}.gpkg")
        empty.to_file(out_path, driver="GPKG", layer="lines")


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Load and reproject input linework once to the raster CRS
    raster_crs = CRS.from_epsg(RASTER_EPSG)
    gdf = gpd.read_file(INPUT_GEOJSON)
    if gdf.crs is None:
        raise ValueError("Input GeoJSON has no CRS. Please define it (or re-save with a CRS).")
    if gdf.crs != raster_crs:
        gdf = gdf.to_crs(raster_crs)

    # Find PNG tiles
    png_paths = sorted(glob(os.path.join(TILES_DIR, "*.png")))
    if not png_paths:
        raise FileNotFoundError(f"No .png files found in {TILES_DIR}")

    # Pair only those with a matching world file
    pairs = []
    for png in png_paths:
        wld = find_worldfile_for_png(png)
        if wld:
            pairs.append((png, wld))
    if not pairs:
        raise FileNotFoundError("Found .png files but none had a matching .wld/.pgw/.tfw (per settings).")

    pbar = tqdm(pairs, desc="Clipping by tile", unit="tile")
    for png_path, wld_path in pbar:
        base = os.path.splitext(os.path.basename(png_path))[0]

        # Open PNG to get width/height
        with rasterio.open(png_path) as src:
            width, height = src.width, src.height

        # Transform from world file
        transform = read_worldfile_to_affine(wld_path)
        minx, miny, maxx, maxy = tile_bounds(width, height, transform)

        bbox_poly = box(minx, miny, maxx, maxy)

        # Fast bbox candidate filter (uses spatial index if available)
        if hasattr(gdf, "sindex") and gdf.sindex:
            cand_idx = list(gdf.sindex.intersection(bbox_poly.bounds))
            candidates = gdf.iloc[cand_idx]
        else:
            candidates = gdf  # fallback

        if candidates.empty:
            if WRITE_EMPTY_FILES:
                write_empty_output(base, candidates.columns, raster_crs)
            continue

        # Convert polygons to boundaries before clipping.
        # This prevents added seam lines along tile borders.
        candidates = candidates.copy()
        candidates["geometry"] = candidates.geometry.apply(geometry_to_linework)
        candidates = candidates[candidates.geometry.notna()]
        candidates = candidates[~candidates.geometry.is_empty]

        if candidates.empty:
            if WRITE_EMPTY_FILES:
                write_empty_output(base, gdf.columns, raster_crs)
            continue

        # Intersect (cut at bbox)
        clipped = gpd.overlay(
            candidates,
            gpd.GeoDataFrame(geometry=[bbox_poly], crs=raster_crs),
            how="intersection",
        )

        if clipped.empty and not WRITE_EMPTY_FILES:
            continue

        if clipped.empty and WRITE_EMPTY_FILES:
            write_empty_output(base, gdf.columns, raster_crs)
            continue

        # Explode MultiLineStrings into individual lines (optional but handy)
        clipped = clipped.explode(index_parts=False, ignore_index=True)
        clipped = clipped[clipped.geom_type.isin(["LineString", "MultiLineString"])]

        # Write result (GeoJSON in raster CRS for direct alignment with tiles)
        if OUTPUT_FORMAT == "GeoJSON":
            out_path = os.path.join(OUTPUT_DIR, f"{base}{OUTPUT_SUFFIX}.geojson")
            clipped.to_file(out_path, driver="GeoJSON")
        else:
            out_path = os.path.join(OUTPUT_DIR, f"{base}{OUTPUT_SUFFIX}.gpkg")
            clipped.to_file(out_path, driver="GPKG", layer="lines")

    print(f"Done. Wrote clipped layers to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
