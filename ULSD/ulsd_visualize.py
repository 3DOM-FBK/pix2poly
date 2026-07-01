#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
JSON line viewer with middle-mouse zoom (wheel) and right-drag pan.
- Reads test.json-style items (filename, width, height, lines=[[p0,p1],...]).
- Loads each image from IMAGE_BASE_DIR (or absolute filename).
- Overlays line segments.
- Shows a fixed 900x900 non-resizable window.
- Controls:
    Mouse wheel (middle): zoom in/out around cursor
    Right mouse drag:     pan
    Enter / Space:        next image
    B:                    previous image
    Esc / q:              quit
"""

from pathlib import Path
import json
import cv2
import numpy as np

# =======================
# CONFIG — EDIT THESE
# =======================
JSON_PATH       = Path("outputs/ulsd/test.json")
IMAGE_BASE_DIR  = Path("outputs/test")   # base folder for images if JSON filenames are relative
WINDOW_TITLE    = "Line Viewer 1024x1024 (wheel to zoom, RMB to pan)"
WINDOW_SIZE     = 1024

# Drawing style
COLOR_LINE      = (0, 0, 255)
THICKNESS       = 5
ALPHA_OVERLAY   = 0.80
SHOW_ENDPOINTS  = True
COLOR_ENDPOINTS = (255, 0, 0)
R_ENDPOINTS     = 3

# HUD
SHOW_FILENAME   = True
TEXT_COLOR      = (255, 255, 255)
TEXT_SHADOW     = (0, 0, 0)
FONT_SCALE      = 0.5
FONT_THICK      = 1

# Image handling
AUTO_CONTRAST_16BIT = True  # stretch 16-bit images to 8-bit for viewing

# Zoom behavior
ZOOM_BASE       = 1.25   # per wheel notch
ZOOM_MIN_FIT    = 0.5    # allow zooming out to 50% of "fit" scale
ZOOM_MAX_MULT   = 16.0   # up to 16x over "fit" scale
# =======================


def read_image_for_display(path: Path) -> np.ndarray:
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(f"Could not read image: {path}")
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.dtype == np.uint16 and AUTO_CONTRAST_16BIT:
        img32 = img.astype(np.float32)
        for c in range(img32.shape[2]):
            ch = img32[:, :, c]
            lo, hi = np.percentile(ch, [2, 98])
            if hi <= lo:
                lo, hi = float(ch.min()), float(ch.max()) if ch.max() > ch.min() else (0.0, 65535.0)
            ch = np.clip((ch - lo) / max(1e-6, (hi - lo)), 0, 1) * 255.0
            img32[:, :, c] = ch
        img = img32.astype(np.uint8)
    elif img.dtype != np.uint8:
        img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    return img


def draw_lines(img: np.ndarray, segments) -> np.ndarray:
    """Draw [[(x0,y0),(x1,y1)], ...] with alpha overlay."""
    overlay = img.copy()
    for seg in segments:
        if not isinstance(seg, (list, tuple)) or len(seg) != 2:
            continue
        (x0, y0), (x1, y1) = seg
        p0 = (int(round(x0)), int(round(y0)))
        p1 = (int(round(x1)), int(round(y1)))
        cv2.line(overlay, p0, p1, COLOR_LINE, THICKNESS, cv2.LINE_AA)
        if SHOW_ENDPOINTS:
            cv2.circle(overlay, p0, R_ENDPOINTS, COLOR_ENDPOINTS, -1, lineType=cv2.LINE_AA)
            cv2.circle(overlay, p1, R_ENDPOINTS, COLOR_ENDPOINTS, -1, lineType=cv2.LINE_AA)
    return cv2.addWeighted(overlay, ALPHA_OVERLAY, img, 1.0 - ALPHA_OVERLAY, 0.0)


def annotate(img: np.ndarray, text: str, x: int = 8, y: int = 20) -> None:
    if not text:
        return
    cv2.putText(img, text, (x+1, y+1), cv2.FONT_HERSHEY_SIMPLEX, FONT_SCALE, TEXT_SHADOW, FONT_THICK, cv2.LINE_AA)
    cv2.putText(img, text, (x, y),     cv2.FONT_HERSHEY_SIMPLEX, FONT_SCALE, TEXT_COLOR,  FONT_THICK, cv2.LINE_AA)


def load_items(json_path: Path):
    data = json.loads(json_path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    for key in ("images", "data", "items"):
        if isinstance(data, dict) and key in data and isinstance(data[key], list):
            return data[key]
    raise ValueError("Unsupported JSON structure: expected a list of items or an 'images'/'data' list.")


def resolve_image_path(base_dir: Path, filename: str) -> Path:
    p = Path(filename)
    return p if p.is_absolute() else (base_dir / p)


class ViewerState:
    def __init__(self, img: np.ndarray):
        self.img = img  # pre-rendered with lines
        self.H, self.W = img.shape[:2]
        # Fit scale so the whole image fits inside WINDOW_SIZE x WINDOW_SIZE
        self.fit_scale = min(WINDOW_SIZE / self.W, WINDOW_SIZE / self.H)
        # Start at "fit"
        self.scale = self.fit_scale
        # Viewport top-left in image coords (float)
        view_dim = WINDOW_SIZE / self.scale
        self.off_x = max(0.0, (self.W - view_dim) / 2.0)
        self.off_y = max(0.0, (self.H - view_dim) / 2.0)
        # Panning
        self.panning = False
        self.pan_start = (0, 0)
        self.off_start = (self.off_x, self.off_y)

    def clamp_offset(self):
        view_dim = WINDOW_SIZE / self.scale
        max_x = max(0.0, self.W - view_dim)
        max_y = max(0.0, self.H - view_dim)
        self.off_x = float(np.clip(self.off_x, 0.0, max_x))
        self.off_y = float(np.clip(self.off_y, 0.0, max_y))

    def zoom_at(self, win_x: int, win_y: int, wheel_delta: int):
        # Convert wheel ticks to factor
        # OpenCV units: 120 per notch
        notches = wheel_delta / 120.0
        factor = (ZOOM_BASE ** notches)
        old_scale = self.scale
        # Clamp new scale
        min_scale = self.fit_scale * ZOOM_MIN_FIT
        max_scale = self.fit_scale * ZOOM_MAX_MULT
        new_scale = float(np.clip(old_scale * factor, min_scale, max_scale))
        if abs(new_scale - old_scale) < 1e-6:
            return
        # Image coord under cursor before zoom
        img_x = self.off_x + (win_x / old_scale)
        img_y = self.off_y + (win_y / old_scale)
        # Update scale
        self.scale = new_scale
        # Recompute offset so cursor stays over same image point
        self.off_x = img_x - (win_x / new_scale)
        self.off_y = img_y - (win_y / new_scale)
        self.clamp_offset()

    def start_pan(self, win_x: int, win_y: int):
        self.panning = True
        self.pan_start = (win_x, win_y)
        self.off_start = (self.off_x, self.off_y)

    def update_pan(self, win_x: int, win_y: int):
        if not self.panning:
            return
        dx = win_x - self.pan_start[0]
        dy = win_y - self.pan_start[1]
        # Convert window pixel delta to image coords via scale
        self.off_x = self.off_start[0] - dx / self.scale
        self.off_y = self.off_start[1] - dy / self.scale
        self.clamp_offset()

    def end_pan(self):
        self.panning = False

    def render(self) -> np.ndarray:
        """Return a 900x900 canvas from current viewport."""
        view_dim = int(round(WINDOW_SIZE / self.scale))
        # top-left (floored) and fractional remainders
        x0 = int(np.floor(self.off_x))
        y0 = int(np.floor(self.off_y))
        # Desired region [x0:x0+view_dim], [y0:y0+view_dim], clamp & pad if needed
        x1 = x0 + view_dim
        y1 = y0 + view_dim

        pad_left = max(0, -x0)
        pad_top  = max(0, -y0)
        pad_right = max(0, x1 - self.W)
        pad_bottom = max(0, y1 - self.H)

        x0c = max(0, x0)
        y0c = max(0, y0)
        x1c = min(self.W, x1)
        y1c = min(self.H, y1)

        roi = self.img[y0c:y1c, x0c:x1c]
        if any(v > 0 for v in (pad_left, pad_right, pad_top, pad_bottom)):
            roi = cv2.copyMakeBorder(
                roi, pad_top, pad_bottom, pad_left, pad_right,
                borderType=cv2.BORDER_CONSTANT, value=(0, 0, 0)
            )

        # Now roi should be view_dim x view_dim; resize to window
        if roi.shape[1] != view_dim or roi.shape[0] != view_dim:
            # safety, though it should match
            roi = cv2.resize(roi, (view_dim, view_dim), interpolation=cv2.INTER_LINEAR)
        canvas = cv2.resize(roi, (WINDOW_SIZE, WINDOW_SIZE), interpolation=cv2.INTER_LINEAR)
        return canvas


def main():
    items = load_items(JSON_PATH)
    n = len(items)
    if n == 0:
        print("No items in JSON.")
        return

    cv2.namedWindow(WINDOW_TITLE, cv2.WINDOW_AUTOSIZE)  # non-resizable
    print("Controls: wheel=zoom, right-drag=pan, Enter/Space=next, B=back, Esc/Q=quit")

    i = 0
    viewer = None  # type: ViewerState | None

    # mouse callback needs access to viewer; we'll capture it via a small closure
    state = {"viewer": None}

    def on_mouse(event, x, y, flags, userdata):
        v = state["viewer"]
        if v is None:
            return
        if event == cv2.EVENT_MOUSEWHEEL:
            delta = cv2.getMouseWheelDelta(flags)  # +120 or -120 per notch
            v.zoom_at(x, y, delta)
        elif event == cv2.EVENT_RBUTTONDOWN:
            v.start_pan(x, y)
        elif event == cv2.EVENT_MOUSEMOVE and (flags & cv2.EVENT_FLAG_RBUTTON):
            v.update_pan(x, y)
        elif event == cv2.EVENT_RBUTTONUP:
            v.end_pan()

    cv2.setMouseCallback(WINDOW_TITLE, on_mouse)

    while 0 <= i < n:
        item = items[i]
        fname = item.get("filename")
        lines = item.get("lines", [])

        try:
            img_path = resolve_image_path(IMAGE_BASE_DIR, fname)
            base_img = read_image_for_display(img_path)
            vis_img = draw_lines(base_img, lines)
            if SHOW_FILENAME:
                annotate(vis_img, f"[{i+1}/{n}] {img_path.name}  |  wheel=zoom, RMB=pan")
            viewer = ViewerState(vis_img)
            state["viewer"] = viewer
        except Exception as e:
            # show an error canvas but keep navigation working
            err = np.zeros((WINDOW_SIZE, WINDOW_SIZE, 3), dtype=np.uint8)
            annotate(err, f"Error: {e}")
            cv2.imshow(WINDOW_TITLE, err)
            key = cv2.waitKey(0) & 0xFF
            if key in (27, ord('q'), ord('Q')):
                break
            i += 1
            continue

        # per-image interactive loop
        while True:
            canvas = viewer.render()
            cv2.imshow(WINDOW_TITLE, canvas)
            key = cv2.waitKey(20) & 0xFF
            if key in (27, ord('q'), ord('Q')):
                i = n  # exit outer loop
                break
            if key in (13, 10, 32):  # Enter / Return / Space
                i += 1
                break
            if key in (ord('b'), ord('B')):
                i = max(0, i - 1)
                break
            # otherwise, keep updating (mouse events handled via callback)

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
