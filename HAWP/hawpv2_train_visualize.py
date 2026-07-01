#!/usr/bin/env python3
"""
Visualize HAWP-style train.json over PNG tiles.

Controls:
  • ENTER: next tile
  • ESC:   exit
Optional:
  • 'b'   : go back one tile
  • 's'   : save current overlay next to the image (adds _vis.png)
"""

import os
import json
import cv2
import numpy as np

# ====== USER SETTINGS ======
IMAGE_DIR   = r"outputs/tiles_building"      # folder with images (.png)
JSON_PATH   = r"outputs/hawp/train.json"     # path to your train.json
START_INDEX = 0                             # start from this item index

DRAW_POINTS       = True                    # draw junction dots
DRAW_POINT_IDS    = False                   # label each junction with its index
POINT_RADIUS      = 2                       # px
LINE_THICKNESS    = 2                       # px
POS_COLOR         = (0, 255, 0)             # BGR for edges_positive (green)
NEG_COLOR         = (0, 0, 255)             # BGR for edges_negative if present (red)
POINT_COLOR       = (255, 0, 0)             # BGR for junction dots (blue)
TEXT_COLOR        = (255, 255, 255)         # BGR for overlay text (white)

AUTO_FIT_MAX      = 1400                    # auto-resize long side to this (0 = no resize)
WINDOW_NAME       = "train.json viewer"
# ===========================


def safe_int_pt(pt):
    # pt = [x, y] in pixel coords (may be float) -> ints
    return (int(round(pt[0])), int(round(pt[1])))

def overlay_text(img, lines, org=(10, 20), line_h=18):
    # Draw multiple lines of text
    for i, t in enumerate(lines):
        y = org[1] + i * line_h
        cv2.putText(img, t, (org[0], y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, TEXT_COLOR, 1, cv2.LINE_AA)

def auto_fit(image):
    if AUTO_FIT_MAX <= 0:
        return image
    h, w = image.shape[:2]
    scale = min(1.0, AUTO_FIT_MAX / max(h, w))
    if scale < 1.0:
        new_w = int(w * scale)
        new_h = int(h * scale)
        return cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
    return image

def draw_edges(img, junctions, edges, color):
    for e in edges:
        if not isinstance(e, (list, tuple)) or len(e) != 2:
            continue
        i, j = e
        # guard against bad indices
        if i < 0 or j < 0 or i >= len(junctions) or j >= len(junctions):
            continue
        p1 = safe_int_pt(junctions[i])
        p2 = safe_int_pt(junctions[j])
        if p1 == p2:
            continue
        cv2.line(img, p1, p2, color, LINE_THICKNESS, cv2.LINE_AA)

def draw_points(img, junctions):
    for idx, pt in enumerate(junctions):
        p = safe_int_pt(pt)
        cv2.circle(img, p, POINT_RADIUS, POINT_COLOR, -1, lineType=cv2.LINE_AA)
        if DRAW_POINT_IDS:
            cv2.putText(img, str(idx), (p[0]+3, p[1]-3),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, POINT_COLOR, 1, cv2.LINE_AA)

def main():
    # Load json
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and "root" in data:
        items = data["root"]   # just in case you kept a "root" wrapper
    else:
        items = data           # typical: list of objects

    n = len(items)
    if n == 0:
        print("No items in JSON.")
        return

    print(f"Loaded {n} items from {JSON_PATH}")
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)

    i = max(0, min(START_INDEX, n - 1))
    while 0 <= i < n:
        item = items[i]
        fname = item.get("filename", "")
        img_path = os.path.join(IMAGE_DIR, fname)
        img = cv2.imread(img_path, cv2.IMREAD_COLOR)

        if img is None:
            print(f"[{i+1}/{n}] Missing image: {img_path}")
            i += 1
            continue

        # Copy for drawing
        vis = img.copy()

        junctions = item.get("junctions", [])
        epos = item.get("edges_positive", [])
        eneg = item.get("edges_negative", [])

        # Draw positives then (optional) negatives
        draw_edges(vis, junctions, epos, POS_COLOR)
        if isinstance(eneg, list) and len(eneg) > 0:
            draw_edges(vis, junctions, eneg, NEG_COLOR)

        if DRAW_POINTS:
            draw_points(vis, junctions)

        # Overlay info
        overlay_text(vis, [
            f"{i+1}/{n}  {fname}",
            f"junctions: {len(junctions)}  pos: {len(epos)}  neg: {len(eneg) if isinstance(eneg, list) else 0}",
            "ENTER=next  ESC=exit  b=back  s=save"
        ], org=(10, 22), line_h=20)

        vis_show = auto_fit(vis)
        cv2.imshow(WINDOW_NAME, vis_show)

        key = cv2.waitKey(0) & 0xFF
        if key == 27:  # ESC
            break
        elif key in (13, 10):  # ENTER
            i += 1
        elif key == ord('b'):
            i = max(0, i - 1)
        elif key == ord('s'):
            out_path = os.path.splitext(img_path)[0] + "_vis.png"
            # Save the original-resolution visualization
            cv2.imwrite(out_path, vis)
            print(f"Saved: {out_path}")
        else:
            # any other key behaves like next
            i += 1

    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
