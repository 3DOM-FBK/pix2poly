#!/usr/bin/env python3
"""
Generate HAWPv2-style train.json from per-tile .geojson + .wld + .png.

Output structure per item:
{
  "width": 512, "height": 512,
  "edges_negative": [],
  "edges_positive": [[0,1],[1,2],...],
  "junctions": [[x0,y0],[x1,y1],...],
  "filename": "tile_name.png"
}

Assumptions:
- One .geojson per tile (same stem as .png/.wld).
- .wld defines the geotransform (but not CRS).
- You set EPSG_* for the raster/tile CRS below.
- .geojson geometries can be Polygon/MultiPolygon or LineString/MultiLineString.
- Coordinates in the .geojson may be in any CRS; we reproject to EPSG_RASTER.
"""

import json
import math
import os
import glob

from collections import defaultdict

import numpy as np
from PIL import Image
from shapely.geometry import shape, LineString, Polygon, MultiPolygon, MultiLineString
from shapely.ops import transform as shp_transform
from shapely.geometry.base import BaseGeometry
from pyproj import Transformer, CRS
import fiona

# ================== USER CONFIG ==================
IMAGE_DIR = r"outputs/tiles_building"       # folder with .png and .wld
GEOJSON_DIR = r"outputs/tiles_building"     # folder with .geojson
OUTPUT_JSON = r"outputs/hawp/train.json"

# Raster CRS (since worldfiles lack CRS). Change this as needed.
EPSG_RASTER = 7791   # e.g., 3857, 32633, 4326, etc.

# If your GeoJSON has its own CRS, set it here; otherwise leave None and we’ll
# try reading from file. If file has no crs, we assume it's already EPSG_RASTER.
# Examples: 4326, 3857, 32633, ...
EPSG_GEOJSON_OVERRIDE = None

# Include polygon interior rings (holes) as edges?
INCLUDE_HOLES = False

# Pixel rounding: HAWP expects pixel coords; we round to nearest int and clamp.
ROUND_TO_INT = True

# =================================================


def read_worldfile(wld_path):
    """
    Parse a 6-line ESRI worldfile:
      A, D, B, E, C, F  (note: order differs from GDAL doc variables)
    C and F in world files are the center of the upper-left pixel. Convert
    them to the upper-left corner before inverting so labels use rasterio's
    image-coordinate convention.
    Returns an affine 6-tuple (a, b, d, e, xoff, yoff) such that:
      x_world = a*col + b*row + xoff
      y_world = d*col + e*row + yoff
    and the inverse for world->pixel.
    """
    with open(wld_path, "r") as f:
        vals = [float(line.strip()) for line in f.readlines()]
    if len(vals) != 6:
        raise ValueError(f"Invalid worldfile (expected 6 lines): {wld_path}")
    A, D, B, E, C_center, F_center = vals
    C = C_center - (A / 2.0) - (B / 2.0)
    F = F_center - (D / 2.0) - (E / 2.0)
    # Affine as (a, b, d, e, xoff, yoff)
    return (A, B, D, E, C, F)


def inv_affine(a, b, d, e, xoff, yoff):
    """
    Invert 2x2 matrix [[a, b], [d, e]] and return function for world->pixel.
    """
    det = a * e - b * d
    if det == 0:
        raise ValueError("Non-invertible worldfile transform (det=0).")
    inv_a =  e / det
    inv_b = -b / det
    inv_d = -d / det
    inv_e =  a / det

    def world_to_pixel(x, y):
        # Solve [col,row]^T = inv([[a,b],[d,e]]) * ([x,y]^T - [xoff,yoff]^T)
        dx = x - xoff
        dy = y - yoff
        col = inv_a * dx + inv_b * dy
        row = inv_d * dx + inv_e * dy
        return col, row

    return world_to_pixel


def clamp_and_round(x, y, width, height):
    if ROUND_TO_INT:
        x = int(round(x))
        y = int(round(y))
    # clamp to image bounds
    x = max(0, min(width - 1, x))
    y = max(0, min(height - 1, y))
    return x, y


def undirected_key(p1, p2):
    # canonical ordering to deduplicate reversed duplicates
    return (p1, p2) if p1 <= p2 else (p2, p1)


def geom_to_lines(geom: BaseGeometry):
    """
    Yield LineStrings for Polygon/MultiPolygon/LineString/MultiLineString.
    - For polygons, convert each ring to a closed LineString; we then split
      to edge segments later.
    """
    if geom.is_empty:
        return
    if isinstance(geom, Polygon):
        yield LineString(geom.exterior.coords)
        if INCLUDE_HOLES:
            for r in geom.interiors:
                yield LineString(r.coords)
    elif isinstance(geom, MultiPolygon):
        for poly in geom.geoms:
            yield from geom_to_lines(poly)
    elif isinstance(geom, LineString):
        yield geom
    elif isinstance(geom, MultiLineString):
        for ln in geom.geoms:
            yield ln
    else:
        # Try to extract boundary if possible (e.g., from unknown types)
        try:
            b = geom.boundary
            if isinstance(b, (LineString, MultiLineString)):
                yield from geom_to_lines(b)
        except Exception:
            return


def main():
    # Gather stems present in both folders
    pngs = {os.path.splitext(os.path.basename(p))[0]: p
            for p in glob.glob(os.path.join(IMAGE_DIR, "*.png"))}
    wlds = {os.path.splitext(os.path.basename(p))[0]: p
            for p in glob.glob(os.path.join(IMAGE_DIR, "*.wld"))}
    gjs  = {os.path.splitext(os.path.basename(p))[0]: p
            for p in glob.glob(os.path.join(GEOJSON_DIR, "*.geojson"))}

    common = sorted(set(pngs) & set(wlds) & set(gjs))
    if not common:
        raise SystemExit("No matching {stem}.png/.wld/.geojson triplets found.")

    raster_crs = CRS.from_epsg(EPSG_RASTER)

    items = []

    for stem in common:
        png_path = pngs[stem]
        wld_path = wlds[stem]
        gj_path  = gjs[stem]

        # Image size
        with Image.open(png_path) as im:
            width, height = im.size

        # Worldfile transform + inverse
        a, b, d, e, xoff, yoff = read_worldfile(wld_path)
        world_to_pixel = inv_affine(a, b, d, e, xoff, yoff)

        # GeoJSON CRS + transformer -> raster CRS
        with fiona.open(gj_path, "r") as src:
            gj_crs = None
            if EPSG_GEOJSON_OVERRIDE is not None:
                gj_crs = CRS.from_epsg(EPSG_GEOJSON_OVERRIDE)
            elif src.crs_wkt:
                gj_crs = CRS.from_wkt(src.crs_wkt)
            elif src.crs:
                try:
                    gj_crs = CRS(src.crs)
                except Exception:
                    gj_crs = None

            if gj_crs is None:
                # Assume already in raster CRS
                transformer = None
            else:
                if gj_crs == raster_crs:
                    transformer = None
                else:
                    transformer = Transformer.from_crs(gj_crs, raster_crs, always_xy=True).transform

            # Collect segments (as pixel endpoints), dedup undirected
            seg_keys = set()
            segments = []

            for feat in src:
                geom = shape(feat["geometry"]) if feat["geometry"] else None
                if geom is None or geom.is_empty:
                    continue

                if transformer is not None:
                    geom = shp_transform(transformer, geom)
                for ln in geom_to_lines(geom):
                    coords = list(ln.coords)
                    if len(coords) < 2:
                        continue
                    # Build consecutive segments (wrap-around for closed rings already present in coords)
                    for (x1w, y1w), (x2w, y2w) in zip(coords[:-1], coords[1:]):
                        # Convert world -> pixel
                        x1p, y1p = world_to_pixel(x1w, y1w)
                        x2p, y2p = world_to_pixel(x2w, y2w)

                        # Round & clamp
                        x1p, y1p = clamp_and_round(x1p, y1p, width, height)
                        x2p, y2p = clamp_and_round(x2p, y2p, width, height)

                        # Drop zero-length after rounding
                        if x1p == x2p and y1p == y2p:
                            continue

                        p1 = (float(x1p), float(y1p))
                        p2 = (float(x2p), float(y2p))
                        key = undirected_key(p1, p2)
                        if key in seg_keys:
                            continue
                        seg_keys.add(key)
                        segments.append((p1, p2))

        # Build junction list and edges_positive as index pairs
        j_index = {}
        junctions = []
        edges_positive = []

        def get_idx(pt):
            if pt not in j_index:
                j_index[pt] = len(junctions)
                junctions.append([pt[0], pt[1]])
            return j_index[pt]

        for p1, p2 in segments:
            i = get_idx(p1)
            j = get_idx(p2)
            if i == j:
                continue
            edges_positive.append([i, j])

        item = {
            "width": width,
            "height": height,
            "edges_negative": [],
            "edges_positive": edges_positive,
            "junctions": junctions,
            "filename": f"{stem}.png",
        }
        items.append(item)

    # Write array of items
    output_dir = os.path.dirname(OUTPUT_JSON)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False)

    print(f"Wrote {len(items)} items to {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
