#!/usr/bin/env python3
# View dataset annotations with OpenCV
# Controls: Enter/Right -> next, Left -> previous, Esc -> exit
# Lines = blue, Junctions = red

import os
import json
import cv2

# =========================
# CONFIG — EDIT ME
# =========================
IMAGES_DIR = r"outputs/tiles_building"          # folder with PNGs
DATA_JSON  = r"outputs/fclip/train.json"        # HAWP or F-Clip style JSON
DRAW_JUNCS = True                        # show junctions (if absent, computed from lines)
LINE_THICKNESS = 2
JUNC_RADIUS    = 2
WINDOW_NAME    = "Preview"
# =========================

BLUE = (255, 0, 0)   # BGR
RED  = (0, 0, 255)   # BGR
WHITE= (255,255,255)
BLACK= (0,0,0)

def put_text(img, text, org, color=WHITE, scale=0.5, thickness=1):
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, BLACK, thickness+2, cv2.LINE_AA)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color,  thickness,  cv2.LINE_AA)

def compute_junc_from_lines(lines):
    seen = set()
    out = []
    for x1,y1,x2,y2 in lines:
        for pt in ((int(x1),int(y1)), (int(x2),int(y2))):
            if pt not in seen:
                seen.add(pt); out.append(pt)
    return out

def draw_overlay(img_bgr, rec):
    img = img_bgr.copy()
    lines = rec.get("lines", [])
    # Draw lines (blue)
    for x1,y1,x2,y2 in lines:
        cv2.line(img, (int(x1),int(y1)), (int(x2),int(y2)), BLUE, LINE_THICKNESS, cv2.LINE_AA)

    # Junctions: use provided 'junc' or compute from lines
    if DRAW_JUNCS:
        juncs = rec.get("junc")
        if juncs is None:
            juncs = compute_junc_from_lines(lines)
        for x,y in juncs:
            cv2.circle(img, (int(x),int(y)), JUNC_RADIUS, RED, -1, cv2.LINE_AA)

    # Header strip
    h, w = img.shape[:2]
    cv2.rectangle(img, (0,0), (w, 22), BLACK, -1)
    info = f"{rec.get('filename','?')} | lines: {len(lines)} | junc: {len(rec.get('junc', [])) if rec.get('junc') is not None else 'auto'}"
    put_text(img, info, (6, 16), WHITE, 0.5, 1)

    return img

def main():
    # Load JSON
    with open(DATA_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list) or not data:
        print("JSON must be a non-empty list of records."); return

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)  # resizable
    i, n = 0, len(data)

    while 0 <= i < n:
        rec = data[i]
        fname = rec.get("filename")
        if not fname:
            print(f"[WARN] Missing filename at index {i}; skipping.")
            i += 1; continue

        path = os.path.join(IMAGES_DIR, fname)
        img = cv2.imread(path, cv2.IMREAD_COLOR)
        if img is None:
            print(f"[WARN] Cannot read image: {path}; skipping.")
            i += 1; continue

        overlay = draw_overlay(img, rec)
        cv2.imshow(WINDOW_NAME, overlay)

        k = cv2.waitKeyEx(0) & 0xFFFF
        if k == 27:            # Esc
            break
        elif k in (13,10):     # Enter
            i += 1
        elif k in (2555904,83):   # Right arrow
            i += 1
        elif k in (2424832,81):   # Left arrow
            i -= 1
        else:
            # any other key = next
            i += 1

    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
