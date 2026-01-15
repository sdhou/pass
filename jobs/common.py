from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Optional

import cv2
import numpy as np
from shapely.geometry import Polygon


SUPPORTED_EXTS = {".png"}


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def iter_images(input_dir: str) -> list[str]:
    files: list[str] = []
    for name in sorted(os.listdir(input_dir)):
        _, ext = os.path.splitext(name)
        if ext.lower() in SUPPORTED_EXTS:
            files.append(name)
    return files


def imread(path: str) -> Optional[np.ndarray]:
    return cv2.imread(path)


def clamp_points(points: np.ndarray, w: int, h: int) -> np.ndarray:
    pts = points.astype(np.float32).copy()
    pts[:, 0] = np.clip(pts[:, 0], 0, max(0, w - 1))
    pts[:, 1] = np.clip(pts[:, 1], 0, max(0, h - 1))
    return pts


def order_quad_tl_tr_br_bl(points: np.ndarray) -> np.ndarray:
    """Return 4 points ordered TL,TR,BR,BL.

    Accepts any order; assumes points form a convex-ish quad.
    """

    pts = points.astype(np.float32)
    if pts.shape != (4, 2):
        raise ValueError(f"Expected (4,2), got {pts.shape}")

    s = pts[:, 0] + pts[:, 1]
    d = pts[:, 0] - pts[:, 1]

    tl = pts[int(np.argmin(s))]
    br = pts[int(np.argmax(s))]
    tr = pts[int(np.argmax(d))]
    bl = pts[int(np.argmin(d))]

    return np.stack([tl, tr, br, bl], axis=0)


def quad_polygon(points: np.ndarray) -> Polygon:
    pts = order_quad_tl_tr_br_bl(points)
    poly = Polygon([(float(x), float(y)) for x, y in pts])
    if not poly.is_valid:
        poly = poly.buffer(0)
    return poly


def quad_iou(a: np.ndarray, b: np.ndarray) -> float:
    pa = quad_polygon(a)
    pb = quad_polygon(b)
    if pa.is_empty or pb.is_empty:
        return 0.0
    inter = pa.intersection(pb).area
    union = pa.union(pb).area
    if union <= 0:
        return 0.0
    return float(inter / union)


def quad_area(points: np.ndarray) -> float:
    poly = quad_polygon(points)
    return float(poly.area)


def quad_area_ratio(points: np.ndarray, w: int, h: int) -> float:
    return quad_area(points) / float(max(1, w * h))


def is_self_intersecting(points: np.ndarray) -> bool:
    poly = quad_polygon(points)
    return not poly.is_valid


def draw_quad(
    img: np.ndarray,
    quad: np.ndarray,
    *,
    color: tuple[int, int, int],
    thickness: int = 4,
) -> np.ndarray:
    out = img.copy()
    pts = order_quad_tl_tr_br_bl(quad).astype(np.int32)
    cv2.polylines(out, [pts], isClosed=True, color=color, thickness=thickness)
    return out


def write_jsonl(path: str, rows: Iterable[dict[str, Any]]) -> None:
    ensure_dir(os.path.dirname(path) or ".")
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            rows.append(json.loads(s))
    return rows


@dataclass(frozen=True)
class GateResult:
    ok: bool
    reason: str
    score: float


def strict_quality_gate(
    *,
    quad: np.ndarray,
    w: int,
    h: int,
    min_area_ratio: float,
    max_area_ratio: float,
) -> GateResult:
    # Extremely conservative gate: prefer manual over wrong.
    pts = clamp_points(quad, w=w, h=h)
    area_ratio = quad_area_ratio(pts, w=w, h=h)

    if area_ratio < min_area_ratio:
        return GateResult(False, f"area_too_small:{area_ratio:.3f}", 0.0)
    if area_ratio > max_area_ratio:
        return GateResult(False, f"area_too_large:{area_ratio:.3f}", 0.0)

    ordered = order_quad_tl_tr_br_bl(pts)
    raw_poly = Polygon([(float(x), float(y)) for x, y in ordered])
    if raw_poly.is_empty or not raw_poly.is_valid:
        return GateResult(False, "invalid_polygon", 0.0)

    # Basic rectangularity: quad area vs minAreaRect area
    rect = cv2.minAreaRect(ordered.astype(np.float32))
    (rw, rh) = rect[1]
    rect_area = float(max(1.0, rw * rh))
    rectangularity = float(raw_poly.area / rect_area)
    if rectangularity < 0.70:
        return GateResult(False, f"not_rectangular:{rectangularity:.3f}", 0.0)

    score = float(
        min(
            1.0,
            (area_ratio - min_area_ratio)
            / max(1e-6, (max_area_ratio - min_area_ratio)),
        )
    )
    return GateResult(True, "ok", score)
