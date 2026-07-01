import cv2
import numpy as np
from pathlib import Path
import glob

# ==== CONFIG ====
IMG_DIR = r"outputs/lcnn/images"          # folder with *_0.png, etc.
LABEL_SUFFIX = "_label.npz"                 # saved by your pipeline
IMG_GLOB = "*.png"                          # change if needed
SAVE_DIR = None                             # e.g., r"C:\tmp\overlays" or None to disable
SCALE_FROM_HEATMAP = 4.0                    # junc/lpos are in 128x128 → 512x512
DRAW_JUNCTIONS = True
LINE_THICK = 1
C_LINE = (0, 255, 0)                        # BGR
C_J1 = (0, 0, 255)
C_J2 = (255, 0, 0)

# =================

def draw_from_npz(img, npz_path):
    """Draw lpos lines (and junctions) from *_label.npz onto img (in place)."""
    d = np.load(str(npz_path))
    if "lpos" not in d:
        return img
    lpos = d["lpos"]  # shape [N,2,3], (y,x,t) in 128x128 space
    scale = SCALE_FROM_HEATMAP

    overlay = img.copy()
    for seg in lpos:
        (y1, x1, _) = seg[0]
        (y2, x2, _) = seg[1]
        p1 = (int(round(x1 * scale)), int(round(y1 * scale)))
        p2 = (int(round(x2 * scale)), int(round(y2 * scale)))
        cv2.line(overlay, p1, p2, C_LINE, LINE_THICK, cv2.LINE_AA)
        if DRAW_JUNCTIONS:
            cv2.circle(overlay, p1, 2, C_J1, -1, cv2.LINE_AA)
            cv2.circle(overlay, p2, 2, C_J2, -1, cv2.LINE_AA)
    return overlay

def main():
    img_paths = sorted(glob.glob(str(Path(IMG_DIR) / IMG_GLOB)))
    if not img_paths:
        print("No images found.")
        return

    if SAVE_DIR:
        Path(SAVE_DIR).mkdir(parents=True, exist_ok=True)

    i = 0
    cv2.namedWindow("overlay", cv2.WINDOW_NORMAL)

    while 0 <= i < len(img_paths):
        img_path = Path(img_paths[i])
        base = img_path.stem  # e.g., tile_r00001_c00045_0
        npz_path = img_path.with_name(base + LABEL_SUFFIX)

        img = cv2.imread(str(img_path), cv2.IMREAD_COLOR)
        if img is None:
            print(f"Failed to read: {img_path}")
            i += 1
            continue

        if npz_path.exists():
            vis = draw_from_npz(img, npz_path)
            title = f"{img_path.name}   [{i+1}/{len(img_paths)}]"
        else:
            vis = img
            title = f"{img_path.name} (NO LABEL)   [{i+1}/{len(img_paths)}]"

        cv2.imshow("overlay", vis)
        cv2.setWindowTitle("overlay", title)

        # Wait for a key: Enter/Return=next, Left/Right arrows, S=save, Esc/Q=quit
        k = cv2.waitKey(0) & 0xFF
        if k in (13, 10):            # Enter
            i += 1
        elif k == 81 or k == 2424832:  # Left (Linux/Win)
            i = max(i - 1, 0)
        elif k == 83 or k == 2555904:  # Right (Linux/Win)
            i = min(i + 1, len(img_paths) - 1)
        elif k in (ord('q'), 27):    # q or Esc
            break
        elif k in (ord('s'),):       # save overlay
            if SAVE_DIR:
                out_path = Path(SAVE_DIR) / (base + "_overlay.png")
                cv2.imwrite(str(out_path), vis)
                print(f"Saved {out_path}")
            else:
                print("Set SAVE_DIR to enable saving.")
        else:
            # default to next on any other key
            i += 1

    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
