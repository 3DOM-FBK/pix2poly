## Codes for paper "From Pixels to Polylines: Extracting Vectorized LOD2.2 Roof Structures from Aerial Imagery with Line Segment Detection Networks" for ISPRS 2026 Congress.

![alt text](comparison.png)


The root scripts prepare the tiled image/vector data shared by all networks.
The `ULSD`, `HAWP`, `F-Clip`, and `L-CNN` folders contain network-specific
converters, mergers, filters, and visualization helpers.

## Installation

Create a Python environment and install the geospatial dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

GDAL/Fiona/GeoPandas can be easier to install with conda on some machines:

```bash
conda create -n lod22-prep python=3.10 geopandas rasterio shapely pyproj fiona pyogrio pillow opencv tqdm orjson numpy pandas
conda activate lod22-prep
```

## Expected Data Layout

The scripts use relative example paths so the repository can be cloned anywhere:

```text
data/
  raw/
    orthophoto.tif
  linework/
    roof_lines.geojson
    roof_lines.shp
outputs/
  tiles_png/
  geojson_tiles/
  tiles_building/
  test/
```

Edit the config block at the top of each script for your dataset paths, EPSG
codes, and output folders.

## Repository Layout

```text
.
|-- 1_overlapped_ortho_tiler_png.py
|-- 2_geojson_tile_clip_png.py
|-- 2_geojson_tile_clip_jpg.py
|-- 3_split_building_tiles.py
|-- 4_move_geojson_wld.py
|-- 6_count_lines.py
|-- 7_test_select.py
|-- 8_move_testfiles.py
|-- ULSD/
|   |-- ulsd.py
|   `-- ulsd_visualize.py
|-- HAWP/
|-- F-Clip/
`-- L-CNN/
```

Scripts `1` to `8` are shared preprocessing utilities. The subfolders contain
the final JSON converters and visualization/merge helpers for each network.

## Common Preprocessing Workflow

Run these shared steps first. They prepare the image tiles, per-tile GeoJSON
linework, world files, and train/test split used by all network-specific
exporters.

1. `1_overlapped_ortho_tiler_png.py`
   Tiles the true orthophoto into non-overlapping 512 x 512 PNG tiles and writes
   matching `.wld` world files.

2. `2_geojson_tile_clip_png.py`
   Clips roof linework or polygon boundaries to each PNG tile and writes one
   GeoJSON per tile. Use `2_geojson_tile_clip_jpg.py` for JPEG tiles.

3. `3_split_building_tiles.py`
   Separates tiles into `tiles_building`, `tiles_lowline`, and `tiles_empty`.
   This script is safe by default: `DRY_RUN=True` and `COPY_INSTEAD_OF_MOVE=True`.

4. `4_move_geojson_wld.py`
   Moves matching GeoJSON and world files beside selected PNG tiles. This is
   also dry-run by default.

5. `6_count_lines.py`
   Counts line features or segments and writes `outputs/line_count.txt`.

6. `7_test_select.py`
   Selects a subset of tiles whose line count matches `TARGET_SUM`. Set
   `TARGET_SUM` to about 10% of the total line count for a 90/10 train-test
   split.

7. `8_move_testfiles.py`
   Moves the selected test files to `outputs/test`. This is dry-run by default.

8. Check that each selected tile has matching image, world file, and GeoJSON
   files with the same stem, for example:

```text
tile_r00001_c00002.png
tile_r00001_c00002.wld
tile_r00001_c00002.geojson
```

After this common preparation, choose the exporter for the target network.

## Network-Specific Workflows

### ULSD

9. `ULSD/ulsd.py`
   Converts tiled GeoJSON linework into ULSD-style pixel-coordinate JSON. Run it
   once for train and once for test by editing `GEOJSON_DIR`, `RASTER_DIR`, and
   `OUTPUT_JSON`.

10. `ULSD/ulsd_visualize.py`
    Opens a visual checker for the generated ULSD JSON labels and images.

### HAWP

9. `HAWP/hawpv2_train.py`
   Builds HAWP-style `train.json` from train tiles, world files, and per-tile
   GeoJSON files.

10. `HAWP/hawpv2_test.py`
    Builds HAWP-style `test.json` from the selected test tiles.

11. Optional helpers:
    `HAWP/hawpv2_train_json_merge.py` and `HAWP/hawpv2_test_json_merge.py` merge
    multiple city/dataset JSON files; `HAWP/hawpv2_train_visualize.py` and
    `HAWP/hawpv2_test_visualize.py` inspect the generated labels.

### F-Clip

9. `F-Clip/fclip_train_test.py`
   Builds F-Clip-style JSON from tiles, world files, and per-tile GeoJSON files.
   Run it once per split by editing `PNG_DIR`, `GEOJSON_DIR`, and `OUT_JSON`.

10. Optional helpers:
    `F-Clip/fclip_remove_lowline.py` filters samples with too few line segments,
    `F-Clip/fclip_json_merge.py` merges multiple JSON files, and
    `F-Clip/fclip_visualization.py` inspects the generated labels.

### L-CNN

9. `L-CNN/L-CNN.py`
   Builds L-CNN-style merged JSON from per-tile GeoJSON and world files. Run it
   once per split by editing `GJSON_GLOB`, `WLD_FOLDER`, and `OUTPUT_JSON`.

10. `L-CNN/L-CNN_visualization.py`
    Visualizes L-CNN image/label outputs, especially `*_label.npz` files created
    after the L-CNN preprocessing pipeline.

## Network-Specific Converters

- `ULSD/ulsd.py` builds ULSD-style JSON files.
- `HAWP/hawpv2_train.py` and `HAWP/hawpv2_test.py` build HAWP-style JSON files.
- `F-Clip/fclip_train_test.py` builds F-Clip-style JSON files.
- `L-CNN/L-CNN.py` builds an L-CNN-style merged JSON file.
- Merge and visualization helpers are included in each network folder.

## Original Network Repositories

This repository contains data preparation, conversion, merge, and visualization
helpers. For the original model implementations, training code, and model-level
documentation, see:

- ULSD-ISPRS: <https://github.com/lh9171338/ULSD-ISPRS/>
- HAWP: <https://github.com/cherubicXN/hawp>
- F-Clip: <https://github.com/Delay-Xili/F-Clip>
- L-CNN: <https://github.com/zhou13/lcnn>

## Notes

- Data, generated labels, and large raster/vector outputs are ignored by git.
- World files store the upper-left pixel center. The converters shift this to
  the upper-left pixel corner before converting world coordinates to pixel
  coordinates, matching rasterio image-coordinate conventions.
- The scripts keep explicit config blocks rather than a shared project config,
  so each network export can be reproduced independently.
- Add a `LICENSE` file before making the repository public if one has not been
  chosen yet.
