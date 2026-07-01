#!/usr/bin/env python3
"""
Clip a line Shapefile by the bounding box of each tiled JPG image.

- Reads all *.jpg / *.jpeg files in TILES_DIR that have a matching .wld (world file).
- (Optional) Falls back to .jgw / .jpgw if enabled.
- Builds the affine transform from the world file (handles UL pixel center -> corner).
- Computes each tile's geographic bounds (bbox).
- Reads CRS automatically from input Shapefile (.prj).
- Keeps output in the same CRS as input.
- Writes one LineString GeoJSON per tile.

Dependencies:
    pip install geopandas shapely rasterio tqdm pyproj
"""

import os
from glob import glob
from typing import Tuple, Optional

import rasterio
from rasterio.transform import Affine, array_bounds
from shapely.geometry import box
import geopandas as gpd
from tqdm import tqdm

# =========================
# User settings
# =========================
TILES_DIR         = r"outputs/tiles_jpg"  # folder with .jpg/.jpeg + .wld
INPUT_SHP         = r"data/linework/roof_lines.shp"  # line shapefile input
OUTPUT_DIR        = r"outputs/geojson_tiles"
OUTPUT_SUFFIX     = ""                       # appended to tile basename (e.g., "_lines")
WRITE_EMPTY_FILES = False                    # if False, skip writing when no intersections

# Worldfile handling for JPG/JPEG
REQUIRE_WLD            = True                # require .wld to exist first
ALLOW_JGW_FALLBACK     = True                # try .jgw if no .wld
ALLOW_JPGW_FALLBACK    = True                # try .jpgw if no .wld/.jgw
ALLOW_JPEGW_FALLBACK   = False               # rare, but some tools use .jpegw
# =========================


def find_worldfile_for_image(img_path: str) -> Optional[str]:
    """
    Find the matching world file for a JPG/JPEG tile.
    Priority is controlled by the settings above.
    """
    base = os.path.splitext(img_path)[0]
    candidates = []

    if REQUIRE_WLD:
        candidates.append(base + ".wld")
    if ALLOW_JGW_FALLBACK:
        candidates.append(base + ".jgw")
    if ALLOW_JPGW_FALLBACK:
        candidates.append(base + ".jpgw")
    if ALLOW_JPEGW_FALLBACK:
        candidates.append(base + ".jpegw")

    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def read_worldfile_to_affine(wld_path: str) -> Affine:
    """
    Read an ESRI world file (.wld/.jgw/.jpgw/...) and return an Affine transform.
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


def write_empty_output(base: str, columns, input_crs):
    empty = gpd.GeoDataFrame(columns=columns, geometry=[], crs=input_crs)
    out_path = os.path.join(OUTPUT_DIR, f"{base}{OUTPUT_SUFFIX}.geojson")
    empty.to_file(out_path, driver="GeoJSON")


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Load input line shapefile and keep its CRS for outputs.
    gdf = gpd.read_file(INPUT_SHP)

    if gdf.crs is None:
        raise ValueError("Input shapefile has no CRS. Please define .prj / CRS.")
    input_crs = gdf.crs

    # Keep valid line geometries only.
    gdf = gdf[gdf.geometry.notna()]
    gdf = gdf[~gdf.geometry.is_empty]
    gdf = gdf[gdf.geom_type.isin(["LineString", "MultiLineString"])].copy()
    if gdf.empty:
        raise ValueError("Input shapefile has no LineString/MultiLineString geometries.")

    # Find JPG/JPEG tiles
    jpg_paths = sorted(glob(os.path.join(TILES_DIR, "*.jpg")))
    jpeg_paths = sorted(glob(os.path.join(TILES_DIR, "*.jpeg")))
    img_paths = sorted(set(jpg_paths + jpeg_paths))

    if not img_paths:
        raise FileNotFoundError(f"No .jpg/.jpeg files found in {TILES_DIR}")

    # Pair only those with a matching world file
    pairs = []
    for img in img_paths:
        wld = find_worldfile_for_image(img)
        if wld:
            pairs.append((img, wld))

    if not pairs:
        raise FileNotFoundError(
            "Found .jpg/.jpeg files but none had a matching .wld/.jgw/.jpgw/.jpegw (per settings)."
        )

    pbar = tqdm(pairs, desc="Clipping by tile", unit="tile")
    for img_path, wld_path in pbar:
        base = os.path.splitext(os.path.basename(img_path))[0]

        # Open JPG/JPEG to get width/height
        with rasterio.open(img_path) as src:
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
                write_empty_output(base, candidates.columns, input_crs)
            continue

        # Intersect (cut at bbox)
        clipped = gpd.overlay(
            candidates,
            gpd.GeoDataFrame(geometry=[bbox_poly], crs=input_crs),
            how="intersection",
        )

        if clipped.empty and not WRITE_EMPTY_FILES:
            continue

        if clipped.empty and WRITE_EMPTY_FILES:
            write_empty_output(base, gdf.columns, input_crs)
            continue

        # Explode MultiLineStrings and keep only LineString output.
        clipped = clipped.explode(index_parts=False, ignore_index=True)
        clipped = clipped[clipped.geom_type == "LineString"].copy()

        if clipped.empty and not WRITE_EMPTY_FILES:
            continue

        if clipped.empty and WRITE_EMPTY_FILES:
            write_empty_output(base, gdf.columns, input_crs)
            continue

        # Write GeoJSON in the same CRS as input shapefile.
        out_path = os.path.join(OUTPUT_DIR, f"{base}{OUTPUT_SUFFIX}.geojson")
        clipped.to_file(out_path, driver="GeoJSON")

    epsg = input_crs.to_epsg()
    epsg_txt = f"EPSG:{epsg}" if epsg is not None else str(input_crs)
    print(f"Done. Wrote clipped LineString GeoJSON files to: {OUTPUT_DIR}")
    print(f"Output CRS: {epsg_txt}")


if __name__ == "__main__":
    main()
