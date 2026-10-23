"""Rooms from a scanned or photographed floor plan, on this machine.

The free vision models that read plans are rate-limited and slow; a plan an
architect photographs deserves an answer that does not depend on whether a
shared endpoint is up. Classical computer vision is enough for the common case
- dark walls on pale paper, text labels, a dimension string - and is
deterministic, so the same upload gives the same plan twice.

The pipeline, and what each step defends against:

1. Contrast is normalised and the image is capped at 2000 px on its long side.
2. OCR runs once on the whole image. Its boxes are used three ways: labels,
   a scale from size strings, and a mask so lettering is never mistaken for wall.
3. The image is deskewed from the dominant line angle, so a photo taken a
   degree off true still yields rectilinear rooms.
4. Wall thickness is measured, not assumed. Thin marks (dimension lines,
   noise, lettering) are then removed by their thinness.
5. Door gaps are bridged along straight walls with horizontal and vertical line
   closings, keeping only what is as thin as a wall: a closing wide enough to
   span a door would otherwise also fill the corridor beside it. (The vector
   reader, `recover`, follows each wall end instead; here the line kernels keep
   a corridor's fill and a door's strip in separate images, so they can be told
   apart.)
6. Rooms are the regions of paper the walls enclose.

Needs `opencv-python-headless` and `rapidocr-onnxruntime` (the `vision` extra).
Without them `parse_image_local` raises `LocalVisionUnavailable` and the
importer falls back to the remote vision model.
"""

from __future__ import annotations

import math
import re
import threading
from typing import Any

import numpy as np
from shapely.geometry import Point, Polygon

from aip.core.words import plural
from aip.domain.geometry import Vec2
from aip.engines.architecture.importer import ImportError_, ParsedRoom
from aip.engines.architecture.recover import label_rooms, rectify_polygons

#: Longest side the pipeline works at; larger scans are shrunk, which also
#: makes OCR and the morphology fast and wall thickness comparable.
MAX_SIDE = 2000

#: Confidence given to the geometry of a room read this way.
GEOMETRY_CONFIDENCE = 0.85

INSTALL_HINT = (
    "Reading images on this server needs the 'vision' extra: "
    "pip install 'aip[vision]' (opencv-python-headless and rapidocr-onnxruntime)."
)


class LocalVisionUnavailable(ImportError_):
    """OpenCV or the OCR engine is not installed."""


_ocr_lock = threading.Lock()
_ocr_engine: Any = None


def _ocr():
    """The OCR engine, built once: loading its models costs about two seconds."""
    global _ocr_engine
    with _ocr_lock:
        if _ocr_engine is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
            except ImportError as exc:
                raise LocalVisionUnavailable(INSTALL_HINT) from exc
            _ocr_engine = RapidOCR()
        return _ocr_engine


def local_vision_available() -> bool:
    try:
        import cv2  # noqa: F401
        import rapidocr_onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


# ---------------------------------------------------------------------------
# Image preparation
# ---------------------------------------------------------------------------


def _decode(data: bytes, cv2):
    arr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    if arr is None:
        raise ImportError_("The image could not be decoded. Upload a PNG, JPG or WebP file.")
    if arr.ndim == 3 and arr.shape[2] == 4:               # transparency becomes paper
        alpha = arr[:, :, 3:4].astype(np.float32) / 255.0
        arr = (arr[:, :, :3] * alpha + 255 * (1 - alpha)).astype(np.uint8)
    if arr.dtype != np.uint8:
        arr = cv2.normalize(arr, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    if arr.ndim == 2:
        arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
    h, w = arr.shape[:2]
    if max(h, w) > MAX_SIDE:
        k = MAX_SIDE / max(h, w)
        arr = cv2.resize(arr, (int(round(w * k)), int(round(h * k))), interpolation=cv2.INTER_AREA)
    return arr


def _dark_mask(gray, cv2):
    """Ink as 255, paper as 0: Otsu, or an adaptive threshold when Otsu finds no plausible split."""
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    thr, _ = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = np.where(blur < thr, 255, 0).astype(np.uint8)
    frac = float(mask.mean()) / 255.0
    if 0.004 < frac < 0.4:
        return mask
    # A washed-out photo can put Otsu's split inside the paper's own noise.
    block = max(31, (min(gray.shape) // 20) | 1)
    return cv2.adaptiveThreshold(blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                 cv2.THRESH_BINARY_INV, block, 12)


def _skew_angle(mask, cv2) -> float:
    """Degrees the plan is rotated by, from its long straight edges, in (-45, 45]."""
    edges = cv2.Canny(mask, 50, 150)
    side = min(mask.shape)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 720, threshold=60,
                            minLineLength=max(30, int(0.12 * side)), maxLineGap=8)
    if lines is None:
        return 0.0
    seg = lines.reshape(-1, 4).astype(float)
    dx, dy = seg[:, 2] - seg[:, 0], seg[:, 3] - seg[:, 1]
    length = np.hypot(dx, dy)
    ang = np.degrees(np.arctan2(dy, dx))
    ang = (ang + 45.0) % 90.0 - 45.0                      # fold: a vertical wall is 0 too
    hist, edges_ = np.histogram(ang, bins=360, range=(-45, 45), weights=length)
    peak = (edges_[int(np.argmax(hist))] + edges_[int(np.argmax(hist)) + 1]) / 2
    near = np.abs(ang - peak) <= 1.0
    if not near.any():
        return 0.0
    return float(np.average(ang[near], weights=length[near]))


def _rotate(img, angle: float, cv2, border):
    """Rotate by `angle` degrees counter-clockwise on a canvas big enough to keep every corner."""
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    cos, sin = abs(m[0, 0]), abs(m[0, 1])
    nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
    m[0, 2] += nw / 2 - w / 2
    m[1, 2] += nh / 2 - h / 2
    out = cv2.warpAffine(img, m, (nw, nh), flags=cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_CONSTANT, borderValue=border)
    return out, m


# ---------------------------------------------------------------------------
# Walls
# ---------------------------------------------------------------------------


def _wall_thickness(mask, cv2) -> float:
    """Typical thickness of the thinner walls, in pixels, from the distance transform's ridge.

    Partitions are thinner than the outer wall and there is often as much
    of one as the other, so the median flips between the two. The 30th
    percentile of the ridge values lands on the partitions, which is the safe
    side: an opening sized to them keeps every wall. Marks one or two pixels
    thick (dimension lines, specks) are left out of the count when there is
    anything thicker.
    """
    dt = cv2.distanceTransform(mask, cv2.DIST_L2, 3)
    ridge = (dt == cv2.dilate(dt, np.ones((3, 3), np.uint8))) & (dt >= 1)
    values = dt[ridge]
    if values.size == 0:
        return 1.0
    strong = values[values >= 1.5]
    if strong.size >= 0.3 * values.size:
        values = strong
    return max(1.0, 2.0 * float(np.percentile(values, 30)))


def _keep_main_components(mask, cv2, fraction: float = 0.1):
    """Drop every component smaller than `fraction` of the largest, and a page-sized frame."""
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 1:
        return mask
    areas = stats[1:, cv2.CC_STAT_AREA]
    h, w = mask.shape
    keep = np.zeros(n, bool)
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        frame = bw >= 0.97 * w and bh >= 0.97 * h
        keep[i] = area >= fraction * areas.max() and not frame
    return np.where(keep[labels], 255, 0).astype(np.uint8)


def _thin_fill(wall, k: int, t: float, cv2):
    """Door gaps along straight walls, bridged: what a line closing adds that is only wall-thick."""
    side = int(3 * t) + 1
    square = np.ones((side, side), np.uint8)
    out = wall.copy()
    for kernel in (np.ones((1, k), np.uint8), np.ones((k, 1), np.uint8)):
        closed = cv2.morphologyEx(wall, cv2.MORPH_CLOSE, kernel)
        fill = cv2.subtract(closed, wall)
        thick = cv2.morphologyEx(fill, cv2.MORPH_OPEN, square)
        out = cv2.bitwise_or(out, cv2.subtract(fill, thick))
    return out


# ---------------------------------------------------------------------------
# Scale from the drawing's own writing
# ---------------------------------------------------------------------------

_FT_IN = r"(\d+)\s*['′]\s*-?\s*(\d+(?:\.\d+)?)?\s*[\"″]?"
_METRIC = r"(\d+(?:[.,]\d+)?)\s*(?:m|mm|cm)?"


def _to_metres(token: str) -> float | None:
    """One length as written on a plan: 4.6, 4.6m, 15'6", 4600."""
    token = token.strip().replace(",", ".")
    m = re.fullmatch(_FT_IN, token)
    if m:
        return (int(m.group(1)) + float(m.group(2) or 0) / 12.0) * 0.3048
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(mm|cm|m)?", token, re.I)
    if not m:
        return None
    value, unit = float(m.group(1)), (m.group(2) or "").lower()
    if unit == "mm":
        return value / 1000.0
    if unit == "cm":
        return value / 100.0
    if unit == "m":
        return value
    if "." not in m.group(1) and value >= 100:             # a bare integer that large is millimetres
        return value / 1000.0
    return value


def _size_string(text: str) -> tuple[float, float] | None:
    """A room's stated size, "4.6 x 5.0" or 15'6" x 12'0", in metres."""
    t = re.sub(r"[×*X�]", "x", text.strip()).replace("’", "'").replace("''", '"')
    t = re.sub(r"\s+", " ", t)
    parts = re.split(r"\s*x\s*", t, maxsplit=1, flags=re.I)
    if len(parts) != 2:
        return None
    a, b = _to_metres(parts[0]), _to_metres(parts[1])
    if a is None or b is None or a <= 0 or b <= 0:
        return None
    return a, b


def _dimension_string(text: str) -> float | None:
    """A long dimension, "12000", "12.0 m", 40'-0", in metres; not a room size."""
    t = text.strip()
    if re.search(r"[xX×]", t):
        return None
    if re.fullmatch(r"\d{4,6}", t):
        return int(t) / 1000.0
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*m", t, re.I)
    if m:
        return float(m.group(1))
    if re.fullmatch(_FT_IN, t):
        return _to_metres(t)
    return None


def _ppm_from_sizes(rooms: list[tuple[Polygon, list[tuple[float, float]]]]) -> list[float]:
    """Pixels per metre from each room whose stated size agrees with its drawn size."""
    estimates: list[float] = []
    for poly, sizes in rooms:
        x0, y0, x1, y1 = poly.bounds
        w, h = x1 - x0, y1 - y0
        for a, b in sizes:
            best = None
            for p, q in ((a, b), (b, a)):
                r1, r2 = w / p, h / q
                spread = max(r1, r2) / max(min(r1, r2), 1e-9)
                if best is None or spread < best[0]:
                    best = (spread, math.sqrt(r1 * r2))
            if best and best[0] <= 1.25 and 8.0 <= best[1] <= 600.0:
                estimates.append(best[1])
    return estimates


def _robust(values: list[float]) -> tuple[float, int]:
    """Median of the values that agree with the median, and how many agree."""
    med = float(np.median(values))
    agree = [v for v in values if abs(v - med) <= 0.2 * med]
    return float(np.median(agree)), len(agree)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def parse_image_local(data: bytes) -> tuple[list[ParsedRoom], list[str], dict[str, object]]:
    """Rooms from a floor-plan image using OpenCV and OCR, with no network.

    Returns the rooms as fractions of the building's longer side (y up, origin
    at the building's lower left) so that `assemble` can scale them like the
    vision model's, plus a meta dict. When the drawing states its own scale the
    meta carries `px_per_m`, `building_w_m`, `building_h_m` and `extent_m`
    (the metres the longer side spans) so the plan can be sized without being
    told the plot. Fewer than two rooms means the image was not readable this
    way and the caller should try something else.
    """
    try:
        import cv2
    except ImportError as exc:
        raise LocalVisionUnavailable(INSTALL_HINT) from exc

    image = _decode(data, cv2)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    paper = int(np.median(gray))
    # Stretch the ink-to-paper range before thresholding so a washed-out photo
    # gets the same footing as a crisp scan.
    lo, hi = np.percentile(gray, [0.5, 99.5])
    if hi - lo > 8:
        gray = np.clip((gray.astype(np.float32) - lo) * 255.0 / (hi - lo), 0, 255).astype(np.uint8)
        paper = int(np.median(gray))

    ocr = _ocr()
    result, _ = ocr(image)
    items: list[tuple[np.ndarray, str, float]] = []
    for box, text, score in result or []:
        pts = np.array(box, dtype=np.float32).reshape(-1, 2)
        if text.strip():
            items.append((pts, text.strip(), float(score)))

    meta: dict[str, object] = {"model": "local-cv", "north": "unknown", "px_per_m": None}
    warnings: list[str] = []

    mask0 = _dark_mask(gray, cv2)
    angle = _skew_angle(mask0, cv2)
    if abs(angle) > 0.3:
        gray, m = _rotate(gray, angle, cv2, paper)
        items = [(cv2.transform(p.reshape(-1, 1, 2), m).reshape(-1, 2), t, s) for p, t, s in items]
        warnings.append(f"The image was rotated {angle:+.1f} degrees to square it up.")
    height, width = gray.shape
    dark = _dark_mask(gray, cv2)

    # Lettering is not wall. Erase the OCR boxes, then give back whatever long
    # straight run passed through them (a label that straddles a wall).
    boxes = np.zeros_like(dark)
    for pts, _, _ in items:
        cv2.fillPoly(boxes, [np.round(pts).astype(np.int32)], 255)
    boxes = cv2.dilate(boxes, np.ones((3, 3), np.uint8))
    run = 25
    keep_h = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((1, run), np.uint8))
    keep_v = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((run, 1), np.uint8))
    ink = cv2.bitwise_or(cv2.bitwise_and(dark, cv2.bitwise_not(boxes)),
                         cv2.bitwise_or(keep_h, keep_v))
    ink = cv2.bitwise_and(ink, dark)

    t = _wall_thickness(ink, cv2)
    if t > 5:
        side = max(3, int(0.7 * t) | 1)
        wall = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((side, side), np.uint8))
    else:
        wall = ink            # too thin to open without eating the walls; components are filtered below
    wall = _keep_main_components(wall, cv2)
    ys, xs = np.nonzero(wall)
    if xs.size == 0:
        warnings.append("No walls were found in the image.")
        return [], warnings, meta
    bx0, bx1, by0, by1 = xs.min(), xs.max(), ys.min(), ys.max()
    extent_px = max(bx1 - bx0, by1 - by0)

    k = int(max(0.10 * extent_px, 3 * t))
    wall = _thin_fill(wall, k, t, cv2)

    n, labels, stats, _ = cv2.connectedComponentsWithStats(cv2.bitwise_not(wall), connectivity=4)
    building_area = float((bx1 - bx0 + 1) * (by1 - by0 + 1))
    grow = max(1, int(round(t / 2)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1))
    outlines: list[list[Vec2]] = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if x == 0 or y == 0 or x + w >= width or y + h >= height:
            continue                                        # the paper outside the building
        if area < 0.01 * building_area:
            continue
        room = cv2.dilate(np.where(labels == i, 255, 0).astype(np.uint8), kernel)
        contours, _ = cv2.findContours(room, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if not contours:
            continue
        c = max(contours, key=cv2.contourArea)
        approx = cv2.approxPolyDP(c, 0.01 * cv2.arcLength(c, True), True).reshape(-1, 2)
        if len(approx) >= 3:
            # y up from here on: flip once, now.
            outlines.append([Vec2(float(px), float(height - py)) for px, py in approx])
    outlines = rectify_polygons(outlines, tol=max(2.0, t / 2))
    outlines = [o for o in outlines if len(o) >= 3]
    if len(outlines) < 2:
        warnings.append(
            f"Only {plural(len(outlines), 'enclosed room')} {'was' if len(outlines) == 1 else 'were'} found in the image; the walls may have "
            f"gaps wider than a door, or the contrast may be too low."
        )
        return [], warnings, meta

    # Text: anchor each at its box centre, y up.
    labels_found = [(text, Vec2(float(pts[:, 0].mean()), float(height - pts[:, 1].mean())))
                    for pts, text, _ in items]
    scores = [score for _, _, score in items]
    rooms, label_warnings = label_rooms(outlines, labels_found, scores,
                                        geometry_confidence=GEOMETRY_CONFIDENCE)
    warnings += label_warnings

    all_pts = [(p.x, p.y) for o in outlines for p in o]
    x0, x1 = min(p[0] for p in all_pts), max(p[0] for p in all_pts)
    y0, y1 = min(p[1] for p in all_pts), max(p[1] for p in all_pts)
    long_side = max(x1 - x0, y1 - y0)

    # Scale: room size strings first (many independent readings), then a
    # dimension string measured against the dimension line beside it.
    shapes = [Polygon([(p.x, p.y) for p in o]) for o in outlines]
    per_room: list[tuple[Polygon, list[tuple[float, float]]]] = []
    for shape in shapes:
        sizes = []
        for (_, text, _), (_, at) in zip(items, labels_found, strict=True):
            size = _size_string(text)
            if size and shape.covers(Point(at.x, at.y)):
                sizes.append(size)
        per_room.append((shape, sizes))
    from_sizes = _ppm_from_sizes(per_room)
    ppm = None
    how = ""
    if len(from_sizes) >= 3:
        ppm, agree = _robust(from_sizes)
        how = f"from the size strings of {agree} rooms"
    if ppm is None:
        measured = _ppm_from_dimension_line(items, dark, wall, height, cv2)
        if measured:
            ppm, how = measured, "from a dimension string and the dimension line beside it"
    if ppm is None and from_sizes:
        ppm, agree = _robust(from_sizes)
        how = f"from the size string of {plural(agree, 'room')}"
    if ppm is None:
        ppm = _ppm_from_dimension_text(items, x1 - x0, y1 - y0)
        if ppm:
            how = "assuming the dimension string spans the building (no dimension line was found)"

    if ppm and 2.0 <= (x1 - x0) / ppm <= 300 and 2.0 <= (y1 - y0) / ppm <= 300:
        meta.update(px_per_m=round(float(ppm), 3), building_w_m=round(float((x1 - x0) / ppm), 2),
                    building_h_m=round(float((y1 - y0) / ppm), 2), extent_m=round(float(long_side / ppm), 3))
        warnings.append(
            f"Scale read {how}: {ppm:.1f} px per metre, a building of "
            f"{meta['building_w_m']} x {meta['building_h_m']} m."
        )
    else:
        warnings.append(
            "No dimension string or room size could be read for scale, so the plan is fitted to "
            "the plot size you give. Enter the plot width and depth for correct areas and cost."
        )

    # Fractions of the longer side, origin at the building's lower left: the
    # same frame the vision reader's answers are put into.
    for room in rooms:
        room.polygon = [Vec2((p.x - x0) / long_side, (p.y - y0) / long_side) for p in room.polygon]
    warnings.insert(
        0, f"Rooms were read from the image on this server (wall detection and OCR, no model): "
           f"{len(rooms)} rooms. Door gaps were treated as closed and doors and windows are not read."
    )
    return rooms, warnings, meta


def _ppm_from_dimension_line(items, dark, wall, height: int, cv2) -> float | None:
    """Pixels per metre from a dimension string and the straight line drawn beside it."""
    candidates = [(pts, _dimension_string(text)) for pts, text, _ in items]
    candidates = [(pts, length) for pts, length in candidates if length and length >= 1.0]
    if not candidates:
        return None
    thin = cv2.bitwise_and(dark, cv2.bitwise_not(cv2.dilate(wall, np.ones((5, 5), np.uint8))))
    n, _, stats, _ = cv2.connectedComponentsWithStats(thin, connectivity=8)
    best: tuple[float, float] | None = None
    for pts, length in candidates:
        cx, cy = float(pts[:, 0].mean()), float(pts[:, 1].mean())
        text_h = float(pts[:, 1].max() - pts[:, 1].min())
        for i in range(1, n):
            x, y, w, h, _a = stats[i]
            long_, short = max(w, h), min(w, h)
            if long_ < 40 or long_ < 12 * max(short, 1):
                continue
            horizontal = w >= h
            within = (x - 5 <= cx <= x + w + 5 and abs(cy - (y + h / 2)) <= 6 * max(text_h, 10)) if horizontal \
                else (y - 5 <= cy <= y + h + 5 and abs(cx - (x + w / 2)) <= 6 * max(text_h, 10))
            if not within:
                continue
            dist = abs(cy - (y + h / 2)) if horizontal else abs(cx - (x + w / 2))
            if best is None or dist < best[0]:
                best = (dist, long_ / length)
    return best[1] if best else None


def _ppm_from_dimension_text(items, width_px: float, height_px: float) -> float | None:
    """Last resort: take a dimension string to be the building's overall length."""
    for pts, text, _ in items:
        length = _dimension_string(text)
        if length and length >= 1.0:
            horizontal = (pts[:, 0].max() - pts[:, 0].min()) >= (pts[:, 1].max() - pts[:, 1].min())
            return (width_px if horizontal else height_px) / length
    return None
