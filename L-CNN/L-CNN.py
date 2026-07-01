"""
GeoJSON → Pixel reprojection for L-CNN/HAWP lines (single merged JSON)

What this does
--------------
- Reads many *.geojson files (LineString / MultiLineString), with a matching *.wld per tile.
- (Optional) Reprojects from EPSG_INPUT → EPSG_WORLD via pyproj.
- Converts world coords to pixel coords using the inverse affine from the worldfile (handles rotation/skew).
- Streams a SINGLE JSON file (e.g., train.json) of the form:
  [
    {"width":512,"height":512,"lines":[[x1,y1,x2,y2],...],"filename":"<stem>.png"},
    ...
  ]

Why streaming?
--------------
- Avoids holding 30k+ payloads in memory. Writes one JSON array where each element is a tile.

Edit the CONFIG section and run.
"""

from __future__ import annotations

import os
import glob
from pathlib import Path
from typing import List, Tuple

import numpy as np
from tqdm import tqdm
import orjson

# Optional GeoPandas fallback for odd GeoJSONs
try:
    import geopandas as gpd  # type: ignore
    GEOPANDAS_OK = True
except Exception:
    GEOPANDAS_OK = False


# ============================== CONFIG (EDIT) =============================== #

# --- CRS settings ---
EPSG_INPUT = 7791   # EPSG of input GeoJSON coordinates
EPSG_WORLD = 7791   # EPSG of the raster/worldfile (the pixel grid's CRS)

# If EPSGs differ, we’ll reproject using pyproj
_NEED_REPROJ = EPSG_INPUT != EPSG_WORLD
if _NEED_REPROJ:
    from pyproj import Transformer
    TRANSFORMER = Transformer.from_crs(EPSG_INPUT, EPSG_WORLD, always_xy=True)

# --- Paths ---
WLD_FOLDER     = r"outputs/tiles_building"
GJSON_GLOB     = r"outputs/tiles_building/*.geojson"
OUTPUT_JSON    = r"outputs/lcnn/train.json"

# --- Output metadata ---
WIDTH  = 512
HEIGHT = 512

# --- Pixel post-processing ---
ROUND_PIXELS: int | None = 0   # 0 for ints, 10 for 10 decimals, None to skip rounding
CLIP_NONNEG = False            # clamp negatives to 0 if True

# --- Reader options ---
FORCE_GEOPANDAS_READER = False
os.environ.setdefault("GEOPANDAS_IO_ENGINE", "pyogrio")

# --- Include tiles with no lines? (empty "lines": []) ---
INCLUDE_EMPTY_TILES = True


# ============================= GeoJSON utilities ============================ #

def _extract_segments_pure_orjson(geojson_path: Path) -> List[Tuple[float, float, float, float]]:
    """
    Fast GeoJSON reader (no GeoPandas). Returns segments as (x1, y1, x2, y2).
    Each LineString/MultiLineString is split into all consecutive 2-point
    segments, matching the HAWP/F-Clip converters.
    """
    with geojson_path.open("rb") as fh:
        data = orjson.loads(fh.read())

    segments: List[Tuple[float, float, float, float]] = []

    def handle_coords_line(coords: list) -> List[Tuple[float, float, float, float]]:
        out: List[Tuple[float, float, float, float]] = []
        if not isinstance(coords, list) or len(coords) < 2:
            return out
        for c0, c1 in zip(coords[:-1], coords[1:]):
            if not (
                isinstance(c0, (list, tuple))
                and isinstance(c1, (list, tuple))
                and len(c0) >= 2
                and len(c1) >= 2
            ):
                continue
            out.append((float(c0[0]), float(c0[1]), float(c1[0]), float(c1[1])))
        return out

    def handle_geometry(geom: dict):
        if not isinstance(geom, dict):
            return
        gtype = geom.get("type")
        if gtype == "LineString":
            segments.extend(handle_coords_line(geom.get("coordinates", [])))
        elif gtype == "MultiLineString":
            mcoords = geom.get("coordinates", [])
            if isinstance(mcoords, list):
                for ls in mcoords:
                    segments.extend(handle_coords_line(ls))

    # FeatureCollection
    if isinstance(data, dict) and data.get("type") == "FeatureCollection":
        feats = data.get("features", [])
        if isinstance(feats, list):
            for feat in feats:
                if isinstance(feat, dict):
                    handle_geometry(feat.get("geometry"))
        return segments

    # Single Feature
    if isinstance(data, dict) and data.get("type") == "Feature":
        handle_geometry(data.get("geometry"))
        return segments

    # Bare geometry
    if isinstance(data, dict) and data.get("type") in ("LineString", "MultiLineString"):
        handle_geometry(data)
        return segments

    return segments


def _extract_segments_geopandas(geojson_path: Path) -> List[Tuple[float, float, float, float]]:
    """GeoPandas-based extractor. Slower but robust to odd files."""
    if not GEOPANDAS_OK:
        raise RuntimeError("GeoPandas not available, and pure-orjson reader failed.")
    try:
        gdf = gpd.read_file(geojson_path, engine="pyogrio")
    except Exception:
        gdf = gpd.read_file(geojson_path)

    segs: List[Tuple[float, float, float, float]] = []
    def add_linestring(ls) -> None:
        coords = list(ls.coords)
        if len(coords) < 2:
            return
        for c0, c1 in zip(coords[:-1], coords[1:]):
            (x1, y1) = c0[0:2]
            (x2, y2) = c1[0:2]
            segs.append((float(x1), float(y1), float(x2), float(y2)))

    for g in gdf.geometry.values:
        if g is None:
            continue
        gt = g.geom_type
        if gt == "LineString":
            add_linestring(g)
        elif gt == "MultiLineString":
            for ls in g.geoms:
                add_linestring(ls)
    return segs


def extract_segments(geojson_path: Path) -> List[Tuple[float, float, float, float]]:
    """Try fast pure-orjson reader first; fall back to GeoPandas if needed/forced."""
    if not FORCE_GEOPANDAS_READER:
        try:
            return _extract_segments_pure_orjson(geojson_path)
        except Exception:
            pass
    return _extract_segments_geopandas(geojson_path)


# =============================== Core routine =============================== #

def make_payload_for_tile(
    wldfile: Path,
    geojson_path: Path,
    *,
    width: int,
    height: int,
    round_pixels: int | None,
    clip_nonneg: bool,
) -> dict:
    """
    Build the per-tile JSON object:
      {"width":W,"height":H,"lines":[[x1,y1,x2,y2],...],"filename":"<stem>.png"}
    Returns the dict (caller will serialize/write).
    """
    # Read worldfile: A, D, B, E, C, F
    with wldfile.open("r") as f:
        vals = [float(line.strip()) for line in f.readlines()[:6]]
    if len(vals) != 6:
        raise ValueError(f"Worldfile {wldfile} must have 6 lines; got {len(vals)}.")
    A, D, B, E, C_center, F_center = vals
    C = C_center - (A / 2.0) - (B / 2.0)
    F = F_center - (D / 2.0) - (E / 2.0)

    # Inverse affine for world → pixel (handles rotation/skew)
    det = A * E - B * D
    if det == 0:
        raise ValueError(f"Singular transform in worldfile {wldfile} (A*E - B*D == 0).")
    inv = np.array([[ E, -B],
                    [-D,  A]], dtype=np.float64) / det
    offset = np.array([C, F], dtype=np.float64)

    # Extract world segments (EPSG_INPUT)
    segs = extract_segments(geojson_path)

    # Reproject if needed to EPSG_WORLD
    if segs:
        arr = np.asarray(segs, dtype=np.float64)  # (N,4)

        if _NEED_REPROJ:
            x1, y1 = TRANSFORMER.transform(arr[:, 0], arr[:, 1])
            x2, y2 = TRANSFORMER.transform(arr[:, 2], arr[:, 3])
            starts = np.stack([x1, y1], axis=1)
            ends   = np.stack([x2, y2], axis=1)
        else:
            starts = arr[:, 0:2]
            ends   = arr[:, 2:4]

        # World → Pixel (vectorized)
        u = starts - offset
        v = ends   - offset
        pix_start = u @ inv.T
        pix_end   = v @ inv.T

        if clip_nonneg:
            np.maximum(pix_start, 0, out=pix_start)
            np.maximum(pix_end, 0, out=pix_end)

        if isinstance(round_pixels, int):
            pix_start = np.round(pix_start, round_pixels)
            pix_end   = np.round(pix_end, round_pixels)

        lines = np.hstack([pix_start, pix_end]).tolist()
    else:
        lines = []

    return {
        "width": width,
        "height": height,
        "lines": lines,
        "filename": f"{wldfile.stem}.png",
    }


# ============================== Batch + Writer =============================== #

def write_merged_json(
    gjson_glob: str | Path,
    wld_folder: str | Path,
    output_json: str | Path,
    *,
    width: int,
    height: int,
    round_pixels: int | None,
    clip_nonneg: bool,
    include_empty_tiles: bool,
) -> None:
    """
    Stream all tile payloads into a single JSON array (output_json).
    """
    files = sorted(glob.glob(str(gjson_glob)))
    if not files:
        print(f"No GeoJSON files found for pattern: {gjson_glob}")
        return

    wld_folder = Path(wld_folder)
    output_json = Path(output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)

    errors: list[tuple[str, str]] = []
    first = True

    with output_json.open("wb") as fh:
        fh.write(b"[")
        pbar = tqdm(total=len(files), desc="Merging to single JSON", ncols=125)

        for g in files:
            gpath = Path(g)
            wld = wld_folder / (gpath.stem + ".wld")
            try:
                payload = make_payload_for_tile(
                    wldfile=wld,
                    geojson_path=gpath,
                    width=width,
                    height=height,
                    round_pixels=round_pixels,
                    clip_nonneg=clip_nonneg,
                )
                if include_empty_tiles or payload["lines"]:
                    if not first:
                        fh.write(b",")
                    fh.write(orjson.dumps(payload))
                    first = False
            except Exception as e:
                errors.append((gpath.name, str(e)))
            finally:
                pbar.update(1)

        pbar.close()
        fh.write(b"]")

    if errors:
        print("\nCompleted with errors on the following files:")
        for name, msg in errors:
            print(f" - {name}: {msg}")
    else:
        print(f"\nWrote merged JSON: {output_json}")


# ================================== MAIN ==================================== #

if __name__ == "__main__":
    write_merged_json(
        gjson_glob=GJSON_GLOB,
        wld_folder=WLD_FOLDER,
        output_json=OUTPUT_JSON,
        width=WIDTH,
        height=HEIGHT,
        round_pixels=ROUND_PIXELS,
        clip_nonneg=CLIP_NONNEG,
        include_empty_tiles=INCLUDE_EMPTY_TILES,
    )
