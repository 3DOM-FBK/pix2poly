#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
from pathlib import Path
import numpy as np
import rasterio
from rasterio.windows import Window
from rasterio.transform import Affine
from tqdm import tqdm   # pip install tqdm

# ========= CONFIG — EDIT THESE =========
INPUT_TIF      = r"data/raw/orthophoto.tif"
OUTPUT_DIR     = r"outputs/tiles_png"
TILE_SIZE      = 512
OVERLAP_PX     = 0                    # stride = TILE_SIZE - OVERLAP_PX
FILENAME_STYLE = "rowcol"             # "rowcol" or "coords"
PAD_VALUE      = 0                    # padding if src.nodata is None

# Georeferencing for INPUT_TIF
USE_TFW                 = True        # prefer <tif>.tfw if present
REQUIRE_UNCOMPRESSED_IN = False       # raise if input TIFF compressed

# Outputs
WRITE_WLD      = True                 # write <tile>.wld
ALSO_WRITE_PGW = False                # also write <tile>.pgw
WRITE_PRJ      = False                 # write <tile>.prj if CRS available
DELETE_AUX_XML = True                 # remove any accidental *.aux.xml (belt & suspenders)

# PNG + dtype handling
FORCE_UINT8    = False                # force 8-bit PNG; else keep uint16 where possible
PCT_CLIP       = (2, 98)              # percentiles for float→uint8 scaling
# ======================================

os.makedirs(OUTPUT_DIR, exist_ok=True)
stride = TILE_SIZE - OVERLAP_PX
if stride <= 0:
    raise ValueError("OVERLAP_PX must be smaller than TILE_SIZE.")

def read_tfw_to_affine(tfw_path: Path) -> Affine:
    vals = [float(x.strip()) for x in tfw_path.read_text().splitlines()[:6]]
    if len(vals) < 6:
        raise ValueError(f"Invalid TFW: {tfw_path}")
    A, D, B, E, C, F = vals  # TFW order
    # convert center → corner
    c_corner = C - 0.5 * A - 0.5 * B
    f_corner = F - 0.5 * D - 0.5 * E
    return Affine(A, B, c_corner, D, E, f_corner)

def write_world_files(path_no_ext: str, transform: Affine, *, wld=True, pgw=False):
    A = transform.a; B = transform.b; D = transform.d; E = transform.e
    C = transform.c + A/2.0 + B/2.0
    F = transform.f + D/2.0 + E/2.0
    content = f"{A:.12f}\n{D:.12f}\n{B:.12f}\n{E:.12f}\n{C:.12f}\n{F:.12f}\n"
    if wld:
        with open(path_no_ext + ".wld", "w", newline="\n") as f:
            f.write(content)
    if pgw:
        with open(path_no_ext + ".pgw", "w", newline="\n") as f:
            f.write(content)

def write_prj(prj_path: str, crs):
    try:
        if crs:
            with open(prj_path, "w", encoding="utf-8") as f:
                f.write(crs.to_wkt())
    except Exception:
        pass

def _percentile_scale_to_uint8(arr: np.ndarray, pct_low=2, pct_high=98) -> np.ndarray:
    out = np.empty((arr.shape[0], arr.shape[1], arr.shape[2]), dtype=np.uint8)
    for b in range(arr.shape[0]):
        band = arr[b].astype(np.float32, copy=False)
        lo, hi = np.percentile(band, [pct_low, pct_high])
        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
            lo, hi = float(np.min(band)), float(np.max(band))
            if hi <= lo:
                out[b].fill(0); continue
        band = np.clip((band - lo) / max(1e-6, hi - lo), 0.0, 1.0) * 255.0
        out[b] = band.astype(np.uint8)
    return out

def _ensure_png_compatible(data: np.ndarray, force_uint8=False, pct_clip=(2,98)) -> tuple[np.ndarray, str]:
    dt = data.dtype
    if force_uint8:
        if dt != np.uint8:
            data = _percentile_scale_to_uint8(data, pct_clip[0], pct_clip[1])
        return data, "uint8"
    if dt == np.uint8:
        return data, "uint8"
    if dt == np.uint16:
        return data, "uint16"
    # float/int32 → uint8
    data = _percentile_scale_to_uint8(data, pct_clip[0], pct_clip[1])
    return data, "uint8"

def main():
    tif_path = Path(INPUT_TIF)
    tfw_path = tif_path.with_suffix(".tfw")

    # Disable GDAL PAM so no *.aux.xml is written
    with rasterio.Env(GDAL_PAM_ENABLED="NO"):
        with rasterio.open(tif_path) as src:
            if REQUIRE_UNCOMPRESSED_IN:
                comp = (src.profile.get("compress") or src.profile.get("compression") or "").lower()
                if comp and comp != "none":
                    raise RuntimeError(f"Input TIFF is compressed (compress={comp}).")

            W, H = src.width, src.height
            base_transform = read_tfw_to_affine(tfw_path) if (USE_TFW and tfw_path.exists()) else src.transform
            crs = src.crs
            pad_val = src.nodata if src.nodata is not None else PAD_VALUE

            xs = list(range(0, W, stride))
            ys = list(range(0, H, stride))
            total_tiles = len(xs) * len(ys)

            total = 0
            with tqdm(total=total_tiles, desc="Tiling (TIFF→PNG, no aux.xml)", unit="tile") as pbar:
                y_index = 0
                for y0 in ys:
                    x_index = 0
                    for x0 in xs:
                        window = Window(x0, y0, TILE_SIZE, TILE_SIZE)
                        transform = rasterio.windows.transform(window, base_transform)

                        data = src.read(
                            window=window,
                            boundless=True,
                            fill_value=pad_val,
                            out_shape=(src.count, TILE_SIZE, TILE_SIZE)
                        )
                        data, out_dtype = _ensure_png_compatible(
                            data, force_uint8=FORCE_UINT8, pct_clip=PCT_CLIP
                        )

                        if FILENAME_STYLE == "coords":
                            ulx, uly = transform.c, transform.f
                            name = f"tile_ULX_{ulx:.3f}_ULY_{uly:.3f}.png"
                        else:
                            name = f"tile_r{y_index:05d}_c{x_index:05d}.png"

                        out_path = os.path.join(OUTPUT_DIR, name)

                        # IMPORTANT: do NOT pass transform/crs to PNG writer → avoids .aux.xml
                        profile = {
                            "driver": "PNG",
                            "width": TILE_SIZE,
                            "height": TILE_SIZE,
                            "count": data.shape[0],
                            "dtype": out_dtype,
                        }
                        with rasterio.open(out_path, "w", **profile) as dst:
                            dst.write(data)

                        # Sidecar georef
                        base_no_ext = os.path.splitext(out_path)[0]
                        if WRITE_WLD or ALSO_WRITE_PGW:
                            write_world_files(base_no_ext, transform, wld=WRITE_WLD, pgw=ALSO_WRITE_PGW)
                        if WRITE_PRJ and crs:
                            write_prj(base_no_ext + ".prj", crs)

                        # Just in case: delete any stray aux.xml
                        if DELETE_AUX_XML:
                            aux = out_path + ".aux.xml"
                            if os.path.exists(aux):
                                try:
                                    os.remove(aux)
                                except OSError:
                                    pass

                        total += 1
                        x_index += 1
                        pbar.update(1)
                    y_index += 1

    print(f"Done. Wrote {total} PNG tiles (with .wld) to: {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
