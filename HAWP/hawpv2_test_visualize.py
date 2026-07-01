#!/usr/bin/env python3
# View HAWP test.json annotations with OpenCV
# Controls: Enter = next image, Esc = exit
# deps: opencv-python, pillow (only if you want to load non-ASCII paths reliably on Windows — not required here)

import os
import json
import cv2
import numpy as np

# =========================
# CONFIG — EDIT ME
# =========================
IMAGES_DIR   = r"outputs/test"           # folder containing PNG tiles
TEST_JSON    = r"outputs/hawp/test.json" # HAWP-style JSON
DRAW_JUNCTIONS = True                   # show junction points
LINE_COLOR     = (0, 0, 255)          # BGR (red-ish)
LINE_THICKNESS = 2
JUNC_COLOR     = (255, 0, 0)         # BGR (cyan-ish)
JUNC_RADIUS    = 3
TEXT_COLOR     = (255, 255, 255)        # overlay text (filename, counts)
# =========================

def put_text(img, text, org, color=(255,255,255), scale=0.5, thickness=1):
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0,0,0), thickness+2, cv2.LINE_AA)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA)

def draw_overlay(base_bgr, rec):
    img = base_bgr.copy()
    lines = rec.get("lines", [])
    juncs = rec.get("junc", [])
    # draw lines
    for (x1,y1,x2,y2) in lines:
        cv2.line(img, (int(x1),int(y1)), (int(x2),int(y2)), LINE_COLOR, LINE_THICKNESS, cv2.LINE_AA)
    # draw junctions
    if DRAW_JUNCTIONS:
        for (x,y) in juncs:
            cv2.circle(img, (int(x),int(y)), JUNC_RADIUS, JUNC_COLOR, -1, cv2.LINE_AA)
    # header text
    h = img.shape[0]
    pad = 6
    cv2.rectangle(img, (0,0), (img.shape[1], 22), (0,0,0), -1)
    info = f"{rec.get('filename','?')}  |  lines: {len(lines)}  junc: {len(juncs)}"
    put_text(img, info, (pad, 16), TEXT_COLOR, 0.5, 1)
    return img

def main():
    with open(TEST_JSON, "r", encoding="utf-8") as f:
        records = json.load(f)

    if not records:
        print("Empty JSON.")
        return

    i = 0
    total = len(records)
    cv2.namedWindow("HAWP Preview", cv2.WINDOW_AUTOSIZE)

    while 0 <= i < total:
        rec = records[i]
        fname = rec.get("filename")
        if not fname:
            print(f"[WARN] Missing filename at index {i}; skipping.")
            i += 1
            continue

        im_path = os.path.join(IMAGES_DIR, fname)
        img = cv2.imread(im_path, cv2.IMREAD_COLOR)
        if img is None:
            print(f"[WARN] Cannot read image: {im_path}; skipping.")
            i += 1
            continue

        # Optional sanity: if JSON width/height differ, we stick with image size (PNG is ground-truth for display)
        overlay = draw_overlay(img, rec)
        cv2.imshow("HAWP Preview", overlay)

        key = cv2.waitKeyEx(0)
        k = key & 0xFFFF  # normalize
        if k in (27,):                  # Esc
            break
        elif k in (13, 10):             # Enter (CR/LF)
            i += 1
        elif k in (2555904, 83):        # Right arrow (Win/Linux) fallback
            i += 1
        elif k in (2424832, 81):        # Left arrow (Win/Linux) fallback
            i -= 1
        else:
            # any other key: also advance (or change to 'pass' if you want no-op)
            i += 1

    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
