#!/usr/bin/env python
"""passport_processor.py

根据 `prompt/p.md` 的需求处理护照双页扫描件：
- 跳过深色封皮（首页/底页）
- 以护照外轮廓为主进行透视拉正（先几何、后方向）
- 以页码数字为主要证据选择方向（可选 OCR 辅助）
- 小角度去斜（deskew）
- 保守裁剪背景（绝不切到护照内容）

用法:
  python passport_processor.py -i ./img -o ./img-out
  python passport_processor.py -i ./img -o ./img-out --debug-dir ./img-out/debug
  python passport_processor.py -i ./img -o ./img-out --no-ocr

说明:
- 默认启用 PaddleOCR（若不可用会自动降级为非 OCR 评分）。
- OCR 仅用于方向/去斜的“证据打分”，裁剪始终以几何护照区域为准。
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np


SUPPORTED_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}


@dataclass(frozen=True)
class Quad:
    pts: np.ndarray  # shape (4,2) float32


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _iter_images(input_dir: str) -> list[str]:
    files: list[str] = []
    for name in sorted(os.listdir(input_dir)):
        _, ext = os.path.splitext(name)
        if ext.lower() in SUPPORTED_EXTS:
            files.append(name)
    return files


def _imread(path: str) -> Optional[np.ndarray]:
    img = cv2.imread(path)
    return img


def _resize_max(img: np.ndarray, max_side: int) -> np.ndarray:
    h, w = img.shape[:2]
    m = max(h, w)
    if m <= max_side:
        return img
    scale = max_side / float(m)
    return cv2.resize(
        img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA
    )


def _order_points(pts: np.ndarray) -> np.ndarray:
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def _four_point_transform(img: np.ndarray, pts: np.ndarray) -> np.ndarray:
    rect = _order_points(pts.astype(np.float32))
    (tl, tr, br, bl) = rect

    width_a = np.hypot(br[0] - bl[0], br[1] - bl[1])
    width_b = np.hypot(tr[0] - tl[0], tr[1] - tl[1])
    max_width = int(max(width_a, width_b))

    height_a = np.hypot(tr[0] - br[0], tr[1] - br[1])
    height_b = np.hypot(tl[0] - bl[0], tl[1] - bl[1])
    max_height = int(max(height_a, height_b))

    max_width = max(10, max_width)
    max_height = max(10, max_height)

    dst = np.array(
        [
            [0, 0],
            [max_width - 1, 0],
            [max_width - 1, max_height - 1],
            [0, max_height - 1],
        ],
        dtype=np.float32,
    )

    M = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(
        img, M, (max_width, max_height), borderValue=(255, 255, 255)
    )
    return warped


def _rotate_90(img: np.ndarray, k: int) -> np.ndarray:
    # k: 0,1,2,3 for 0/90/180/270 clockwise
    if k % 4 == 0:
        return img
    if k % 4 == 1:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if k % 4 == 2:
        return cv2.rotate(img, cv2.ROTATE_180)
    return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)


def _rotate_small(img: np.ndarray, angle_deg: float) -> np.ndarray:
    if abs(angle_deg) < 1e-6:
        return img
    h, w = img.shape[:2]
    center = (w / 2.0, h / 2.0)
    M = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
    cos = abs(M[0, 0])
    sin = abs(M[0, 1])
    new_w = int((h * sin) + (w * cos))
    new_h = int((h * cos) + (w * sin))
    M[0, 2] += (new_w / 2.0) - center[0]
    M[1, 2] += (new_h / 2.0) - center[1]
    return cv2.warpAffine(img, M, (new_w, new_h), borderValue=(255, 255, 255))


def _sample_background_lab(img_lab: np.ndarray) -> Tuple[np.ndarray, float]:
    # 双页护照经常铺满画面，四角可能就是护照页而不是背景。
    # 因此用“边缘条带 + 选最亮一部分”来估计背景色，更稳。
    h, w = img_lab.shape[:2]
    s = int(max(10, min(h, w) * 0.06))

    strips = [
        img_lab[0:s, :],
        img_lab[h - s : h, :],
        img_lab[:, 0:s],
        img_lab[:, w - s : w],
    ]

    samples = np.concatenate([t.reshape(-1, 3) for t in strips], axis=0).astype(
        np.float32
    )
    L = samples[:, 0]

    cutoff = float(np.percentile(L, 75))
    bright = samples[L >= cutoff]
    if bright.shape[0] < max(500, int(samples.shape[0] * 0.05)):
        bright = samples

    bg = np.median(bright, axis=0)

    d = np.linalg.norm(samples - bg, axis=1)
    # 扫描仪背景会有偏黄/污渍：阈值取更保守的分位数
    thresh = float(max(6.0, np.percentile(d, 90) + 3.0))
    return bg, thresh


def _fill_holes(mask: np.ndarray) -> np.ndarray:
    # mask: 0/255 uint8
    h, w = mask.shape[:2]
    inv = cv2.bitwise_not(mask)
    flood = inv.copy()
    ff_mask = np.zeros((h + 2, w + 2), np.uint8)
    cv2.floodFill(flood, ff_mask, (0, 0), 0)
    holes = cv2.bitwise_not(flood)
    return cv2.bitwise_or(mask, holes)


def _passport_mask_edges(img: np.ndarray) -> np.ndarray:
    # 纯边缘 fallback：当背景采样失败、mask 过大/过小时使用。
    # 关键：抑制“画布边界”被当成护照外框（否则会导致 mask 接近整幅图）。
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)

    edges = cv2.Canny(blur, 25, 90)
    k = int(np.clip(min(h, w) * 0.008, 3, 7))
    edges = cv2.dilate(edges, np.ones((k, k), np.uint8), iterations=2)

    border = int(np.clip(min(h, w) * 0.02, 15, 60))
    edges[:border, :] = 0
    edges[h - border : h, :] = 0
    edges[:, :border] = 0
    edges[:, w - border : w] = 0

    close_k = int(np.clip(min(h, w) * 0.02, 11, 41))
    if close_k % 2 == 0:
        close_k += 1
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (close_k, close_k))
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return edges

    best = None
    best_score = -1.0

    img_area = float(h * w)
    tol = border

    for c in contours:
        area = float(cv2.contourArea(c))
        if area < img_area * 0.06:
            continue

        x, y, cw, ch = cv2.boundingRect(c)
        touch = 0
        if x <= tol:
            touch += 1
        if y <= tol:
            touch += 1
        if x + cw >= w - tol:
            touch += 1
        if y + ch >= h - tol:
            touch += 1

        # 很可能是整张扫描画布的边框：跳过，去找内部真正的护照轮廓
        if touch >= 3 and (area / img_area) > 0.80:
            continue

        rect = cv2.minAreaRect(c)
        (rw, rh) = rect[1]
        rect_area = float(rw * rh) if (rw > 1 and rh > 1) else 0.0
        if rect_area <= 0:
            continue

        rectangularity = area / rect_area
        if rectangularity < 0.30:
            continue

        score = area * rectangularity
        score *= 1.0 - 0.12 * touch

        if score > best_score:
            best_score = score
            best = rect

    if best is None:
        best = cv2.minAreaRect(max(contours, key=cv2.contourArea))

    box = cv2.boxPoints(best).astype(np.int32)
    out = np.zeros((h, w), dtype=np.uint8)
    cv2.fillConvexPoly(out, box, 255)
    return out


def _passport_mask(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)

    bg, bg_thresh = _sample_background_lab(lab)
    delta = np.linalg.norm(lab.astype(np.float32) - bg, axis=2)
    fg = (delta > bg_thresh).astype(np.uint8) * 255

    # 边缘用于补全轮廓，但必须屏蔽旋转后画布边界
    edges = cv2.Canny(gray, 25, 80)
    k = int(np.clip(min(h, w) * 0.008, 3, 7))
    edges = cv2.dilate(edges, np.ones((k, k), np.uint8), iterations=1)

    border = int(np.clip(min(h, w) * 0.01, 10, 40))
    edges[:border, :] = 0
    edges[h - border : h, :] = 0
    edges[:, :border] = 0
    edges[:, w - border : w] = 0

    mask = cv2.bitwise_or(fg, edges)
    mask[:border, :] = 0
    mask[h - border : h, :] = 0
    mask[:, :border] = 0
    mask[:, w - border : w] = 0

    close_k = int(np.clip(min(h, w) * 0.02, 11, 41))
    if close_k % 2 == 0:
        close_k += 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_k, close_k))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)

    # 再次清掉边界（close/open 可能把边界重新“抹上去”）
    mask[:border, :] = 0
    mask[h - border : h, :] = 0
    mask[:, :border] = 0
    mask[:, w - border : w] = 0

    open_k = int(np.clip(min(h, w) * 0.008, 3, 15))
    if open_k % 2 == 0:
        open_k += 1
    kernel2 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_k, open_k))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel2, iterations=1)

    mask[:border, :] = 0
    mask[h - border : h, :] = 0
    mask[:, :border] = 0
    mask[:, w - border : w] = 0

    mask = _fill_holes(mask)

    num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if num <= 1:
        # 失败：fallback
        return _passport_mask_edges(img)

    # 不直接取“最大连通域”：有些扫描会把画布边界连成一个大块。
    # 这里按面积从大到小找一个更像“护照外框”的连通域。
    areas = stats[1:, cv2.CC_STAT_AREA].astype(np.float32)
    order = np.argsort(-areas) + 1

    tol = border
    img_area = float(h * w)

    for idx in order:
        area = float(stats[idx, cv2.CC_STAT_AREA])
        area_ratio = area / img_area

        x = int(stats[idx, cv2.CC_STAT_LEFT])
        y = int(stats[idx, cv2.CC_STAT_TOP])
        cw = int(stats[idx, cv2.CC_STAT_WIDTH])
        ch = int(stats[idx, cv2.CC_STAT_HEIGHT])

        touch = 0
        if x <= tol:
            touch += 1
        if y <= tol:
            touch += 1
        if x + cw >= w - tol:
            touch += 1
        if y + ch >= h - tol:
            touch += 1

        # 典型误判：把整张画布当成护照
        if touch >= 3 and area_ratio > 0.85:
            continue

        # bbox 矩形度太差也跳过
        bbox_area = float(max(1, cw * ch))
        rectangularity = area / bbox_area
        if rectangularity < 0.18:
            continue

        # 面积过小多半是噪声
        if area_ratio < 0.03:
            continue

        out = np.where(labels == idx, 255, 0).astype(np.uint8)
        return out

    return _passport_mask_edges(img)


def _largest_contour(mask: np.ndarray) -> Optional[np.ndarray]:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    return max(contours, key=cv2.contourArea)


def _contour_to_quad(contour: np.ndarray) -> Optional[Quad]:
    hull = cv2.convexHull(contour)
    peri = cv2.arcLength(hull, True)

    # 尝试把外轮廓逼近到 4 边形
    for eps_ratio in (0.01, 0.02, 0.03, 0.04, 0.06, 0.08):
        approx = cv2.approxPolyDP(hull, eps_ratio * peri, True)
        if len(approx) == 4:
            pts = approx.reshape(4, 2).astype(np.float32)
            return Quad(pts=_order_points(pts))

    # fallback：最小外接旋转矩形
    rect = cv2.minAreaRect(hull)
    box = cv2.boxPoints(rect).astype(np.float32)
    return Quad(pts=_order_points(box))


def _deskew_by_min_area_rect(img: np.ndarray, contour: np.ndarray) -> np.ndarray:
    # 扫描件通常没有明显透视畸变，主要是整体旋转倾斜；
    # 这里用“外接矩形长边方向”求旋转角，避免误用 rect[2] 导致 90/180 乱转和拉伸错觉。
    rect = cv2.minAreaRect(contour)
    box = cv2.boxPoints(rect).astype(np.float32)
    tl, tr, br, bl = _order_points(box)

    v1 = tr - tl
    v2 = br - tr
    len1 = float(np.hypot(v1[0], v1[1]))
    len2 = float(np.hypot(v2[0], v2[1]))
    v = v1 if len1 >= len2 else v2

    ang = float(np.degrees(np.arctan2(v[1], v[0])))
    while ang <= -90:
        ang += 180
    while ang > 90:
        ang -= 180

    # 注意：图像坐标系 y 向下，atan2 得到的角度与数学坐标相反。
    # 为把长边拉平，应按 ang 同号旋转。
    rot = ang
    if abs(rot) < 0.15:
        return img

    return _rotate_small(img, rot)


def _deskew_border_hough(img: np.ndarray) -> float:
    # 只用护照外边缘的线段估计小角度倾斜，避免护照内部纹理/文字干扰。
    mask = _passport_mask(img)
    contour = _largest_contour(mask)
    if contour is None:
        return 0.0

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    border = cv2.morphologyEx(mask, cv2.MORPH_GRADIENT, np.ones((7, 7), np.uint8))
    border = cv2.dilate(border, np.ones((9, 9), np.uint8), iterations=1)

    edges = cv2.Canny(gray, 40, 120)
    edges = cv2.bitwise_and(edges, border)

    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180.0,
        threshold=60,
        minLineLength=int(min(img.shape[:2]) * 0.25),
        maxLineGap=15,
    )

    if lines is None:
        return 0.0

    angles: list[float] = []
    for l in lines:
        x1, y1, x2, y2 = l[0]
        ang = float(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
        while ang <= -90:
            ang += 180
        while ang > 90:
            ang -= 180
        # 只采样接近水平的边缘线
        if abs(ang) < 12:
            angles.append(ang)

    if len(angles) < 4:
        return 0.0

    median = float(np.median(np.array(angles, dtype=np.float32)))
    if abs(median) < 0.15 or abs(median) > 4.0:
        return 0.0

    return median


def _is_dark_cover(img: np.ndarray, mask: np.ndarray) -> bool:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    v = hsv[:, :, 2]
    inside = v[mask > 0]
    if inside.size == 0:
        return False

    mean_v = float(np.mean(inside))
    dark_ratio = float(np.mean(inside < 85))

    # 双页摊开时封皮也可能面积很大，因此不再使用面积比
    if mean_v < 90 and dark_ratio > 0.55:
        return True
    if mean_v < 70 and dark_ratio > 0.40:
        return True
    return False


class _OCR:
    def __init__(self, lang: str = "en") -> None:
        from paddleocr import PaddleOCR  # type: ignore
        import logging

        logging.getLogger("ppocr").setLevel(logging.ERROR)
        self._ocr = PaddleOCR(
            use_angle_cls=False, lang=lang, show_log=False, det_limit_side_len=960
        )

    def run(self, img_bgr: np.ndarray):
        # PaddleOCR 支持 BGR/RGB numpy；这里统一转 RGB
        rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        return self._ocr.ocr(rgb, det=True, rec=True, cls=False)


def _box_angle_deg(box: np.ndarray) -> float:
    # box: 4 points (x,y)
    p0 = box[0]
    p1 = box[1]
    ang = float(np.degrees(np.arctan2(p1[1] - p0[1], p1[0] - p0[0])))
    # normalize to [-90,90]
    while ang <= -90:
        ang += 180
    while ang > 90:
        ang -= 180
    return ang


def _page_number_score_no_ocr(img: np.ndarray) -> float:
    # 非 OCR 版本：仅统计“疑似数字小块”在四角边缘条带的数量
    h, w = img.shape[:2]
    band = int(max(40, min(h, w) * 0.12))

    bands = [
        (0, 0, w, band),  # top
        (0, h - band, w, h),  # bottom
        (0, 0, band, h),  # left
        (w - band, 0, w, h),  # right
    ]

    score = 0.0
    for x1, y1, x2, y2 in bands:
        roi = img[y1:y2, x1:x2]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        # 黑帽增强浅底深字
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 5))
        bh = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, k)
        _, bw = cv2.threshold(bh, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        bw = cv2.morphologyEx(
            bw, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1
        )

        num, _, stats, _ = cv2.connectedComponentsWithStats(bw, connectivity=8)
        for i in range(1, num):
            x, y, cw, ch, area = stats[i]
            if area < 20 or area > (roi.shape[0] * roi.shape[1]) * 0.01:
                continue
            ar = ch / float(cw + 1)
            if ar < 0.5 or ar > 6.0:
                continue
            # 靠近 roi 的两端更可能是页码
            cx = x + cw / 2.0
            end_bias = 1.0
            if roi.shape[1] >= roi.shape[0]:
                # top/bottom band
                end_bias = (
                    1.5
                    if (cx < roi.shape[1] * 0.25 or cx > roi.shape[1] * 0.75)
                    else 1.0
                )
            score += 0.15 * end_bias

    return score


def _page_number_score_ocr(img: np.ndarray, ocr: _OCR) -> float:
    h, w = img.shape[:2]
    band = int(max(50, min(h, w) * 0.12))

    # 四个条带：页码可能在顶部或底部，也可能靠近左右边缘
    bands = [
        ("top", 0, 0, w, band),
        ("bottom", 0, h - band, w, h),
        ("left", 0, 0, band, h),
        ("right", w - band, 0, w, h),
    ]

    total = 0.0

    for _, x1, y1, x2, y2 in bands:
        roi = img[y1:y2, x1:x2]
        roi_small = _resize_max(roi, 900)

        try:
            result = ocr.run(roi_small)
        except Exception:
            continue

        if not result or not result[0]:
            continue

        scale_x = roi.shape[1] / float(roi_small.shape[1])
        scale_y = roi.shape[0] / float(roi_small.shape[0])

        for line in result[0]:
            box = np.array(line[0], dtype=np.float32)
            text = str(line[1][0])
            conf = float(line[1][1])

            digits = "".join([c for c in text if c.isdigit()])
            if len(digits) == 0 or len(digits) > 3 or conf < 0.55:
                continue

            box[:, 0] *= scale_x
            box[:, 1] *= scale_y

            ang = _box_angle_deg(box)
            ang_score = max(0.0, 1.0 - (abs(ang) / 30.0))

            cx = float(np.mean(box[:, 0])) + x1
            cy = float(np.mean(box[:, 1])) + y1

            dx = min(cx, w - cx) / float(w)
            dy = min(cy, h - cy) / float(h)
            dist = float(np.hypot(dx, dy))
            corner_score = max(0.0, 1.0 - dist / 0.35)

            total += (
                (1.0 + 0.8 * len(digits))
                * conf
                * (0.4 + 0.6 * corner_score)
                * (0.4 + 0.6 * ang_score)
            )

    return total


def _deskew_page_number_ocr(img: np.ndarray, ocr: _OCR) -> float:
    # 用页码数字的文字框角度估计倾斜：把角度对齐到最近的 0° 或 ±90°。
    h, w = img.shape[:2]
    band = int(max(50, min(h, w) * 0.12))

    bands = [
        (0, 0, w, band),  # top
        (0, h - band, w, h),  # bottom
        (0, 0, band, h),  # left
        (w - band, 0, w, h),  # right
    ]

    skews: list[float] = []

    for x1, y1, x2, y2 in bands:
        roi = img[y1:y2, x1:x2]
        roi_small = _resize_max(roi, 900)

        try:
            result = ocr.run(roi_small)
        except Exception:
            continue

        if not result or not result[0]:
            continue

        scale_x = roi.shape[1] / float(roi_small.shape[1])
        scale_y = roi.shape[0] / float(roi_small.shape[0])

        for line in result[0]:
            box = np.array(line[0], dtype=np.float32)
            text = str(line[1][0])
            conf = float(line[1][1])

            digits = "".join([c for c in text if c.isdigit()])
            if len(digits) == 0 or len(digits) > 3 or conf < 0.60:
                continue

            box[:, 0] *= scale_x
            box[:, 1] *= scale_y

            ang = _box_angle_deg(box)
            # 选择最近的“轴向角度”作为目标：0 或 ±90
            if abs(ang) <= 45:
                base = 0.0
            else:
                base = 90.0 if ang > 0 else -90.0

            skews.append(ang - base)

    if len(skews) < 2:
        return 0.0

    median = float(np.median(np.array(skews, dtype=np.float32)))
    if abs(median) < 0.15 or abs(median) > 4.0:
        return 0.0

    return median


def _text_horizontalness_score(img: np.ndarray) -> float:
    # 无 OCR 情况下，用“横向文字/纹理”的强度来判断 0/90/180/270。
    # 护照页内文字大多是水平排版；错误旋转 90° 时会表现为竖向结构更强。
    img_small = _resize_max(img, 1200)
    gray = cv2.cvtColor(img_small, cv2.COLOR_BGR2GRAY)

    s = min(gray.shape[:2])
    thickness = int(np.clip(s * 0.01, 3, 9))
    length = int(np.clip(s * 0.08, 31, 121))

    k_h = cv2.getStructuringElement(cv2.MORPH_RECT, (length, thickness))
    k_v = cv2.getStructuringElement(cv2.MORPH_RECT, (thickness, length))

    bh_h = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, k_h)
    bh_v = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, k_v)

    # 经验上：竖向核会在“文字水平排布”时得到更强响应（因为字形的竖笔画更多）。
    # 因此用 (vertical - horizontal) 作为“更像正确方向(文字水平)”的打分。
    return float(np.mean(bh_v) - np.mean(bh_h))


def _fold_verticalness_score(img: np.ndarray) -> float:
    # 双页摊开时，中缝（两页之间的折痕/阴影）通常是一条“靠近中心的长竖线”。
    # 正确方向：中缝应更像竖线；旋转90后则更像横线。
    img_small = _resize_max(img, 1400)
    gray = cv2.cvtColor(img_small, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]

    s = min(h, w)
    thickness = int(np.clip(s * 0.01, 3, 9))
    length = int(np.clip(s * 0.25, 80, 260))

    k_v = cv2.getStructuringElement(cv2.MORPH_RECT, (thickness, length))
    k_h = cv2.getStructuringElement(cv2.MORPH_RECT, (length, thickness))

    bh_v = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, k_v)
    bh_h = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, k_h)

    cx1 = int(w * 0.40)
    cx2 = int(w * 0.60)
    cy1 = int(h * 0.40)
    cy2 = int(h * 0.60)

    # 竖线：看中心竖带的列峰值
    v_band = bh_v[:, cx1:cx2]
    v_profile = np.mean(v_band, axis=0)
    v_strength = float(np.max(v_profile) - np.mean(v_profile))

    # 横线：看中心横带的行峰值
    h_band = bh_h[cy1:cy2, :]
    h_profile = np.mean(h_band, axis=1)
    h_strength = float(np.max(h_profile) - np.mean(h_profile))

    return v_strength - h_strength


def _estimate_orientation_no_ocr(img: np.ndarray) -> int:
    # 返回 k: 0/1/2/3 表示顺时针旋转 0/90/180/270
    best_k = 0
    best_score = -1e9

    for k in (0, 1, 2, 3):
        cand = _rotate_90(img, k)
        h, w = cand.shape[:2]

        score = 0.0
        # 轻微偏好横画布，但允许中间态是竖画布（后续会裁剪/再横置）
        score += 1.0 if w >= h else 0.0

        score += 200.0 * _text_horizontalness_score(cand)
        score += 80.0 * _fold_verticalness_score(cand)
        # 页码弱证据（防止极端情况下黑帽失灵）
        score += 0.3 * min(15.0, _page_number_score_no_ocr(cand))

        if score > best_score:
            best_score = score
            best_k = k

    return best_k


def _estimate_orientation(img: np.ndarray, ocr: Optional[_OCR]) -> int:
    # 优先用页码数字（OCR）作为证据；若页码证据不足则降级为非 OCR 打分。
    if ocr is None:
        return _estimate_orientation_no_ocr(img)

    best_k = 0
    best_score = -1e9
    best_ocr_score = 0.0

    for k in (0, 1, 2, 3):
        cand = _rotate_90(img, k)
        h, w = cand.shape[:2]

        ocr_score = _page_number_score_ocr(cand, ocr)
        best_ocr_score = max(best_ocr_score, ocr_score)

        score = 0.0
        score += 1.0 if w >= h else 0.0
        score += ocr_score

        if score > best_score:
            best_score = score
            best_k = k

    # 页码证据不足：不强行依赖 OCR（避免误旋转）
    if best_ocr_score < 1.0:
        return _estimate_orientation_no_ocr(img)

    return best_k


def _passport_long_axis_angle(img: np.ndarray) -> Optional[float]:
    mask = _passport_mask(img)
    contour = _largest_contour(mask)
    if contour is None:
        return None

    rect = cv2.minAreaRect(contour)
    box = cv2.boxPoints(rect).astype(np.float32)
    tl, tr, br, bl = _order_points(box)

    v1 = tr - tl
    v2 = br - tr
    len1 = float(np.hypot(v1[0], v1[1]))
    len2 = float(np.hypot(v2[0], v2[1]))
    v = v1 if len1 >= len2 else v2

    ang = float(np.degrees(np.arctan2(v[1], v[0])))
    while ang <= -90:
        ang += 180
    while ang > 90:
        ang -= 180
    return ang


def _ensure_landscape(img: np.ndarray, ocr: Optional[_OCR]) -> np.ndarray:
    # 这里只保证“输出画布横置”。
    # 护照内部方向由 `_estimate_orientation`（OCR or 黑帽文字方向）决定。
    h, w = img.shape[:2]
    if w >= h:
        return img

    cand_cw = _rotate_90(img, 1)
    cand_ccw = _rotate_90(img, 3)

    if ocr is not None:
        s_cw = _page_number_score_ocr(cand_cw, ocr)
        s_ccw = _page_number_score_ocr(cand_ccw, ocr)

        # OCR 没有给出足够页码证据时，用非 OCR 方向特征做兜底
        if max(s_cw, s_ccw) < 1.0:
            s_cw = _text_horizontalness_score(cand_cw) + 0.4 * _fold_verticalness_score(
                cand_cw
            )
            s_ccw = _text_horizontalness_score(
                cand_ccw
            ) + 0.4 * _fold_verticalness_score(cand_ccw)
    else:
        s_cw = _text_horizontalness_score(cand_cw) + 0.4 * _fold_verticalness_score(
            cand_cw
        )
        s_ccw = _text_horizontalness_score(cand_ccw) + 0.4 * _fold_verticalness_score(
            cand_ccw
        )

    return cand_cw if s_cw >= s_ccw else cand_ccw


def _deskew_hough(img: np.ndarray) -> float:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 50, 140)

    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180.0, threshold=120, minLineLength=120, maxLineGap=10
    )
    if lines is None:
        return 0.0

    angles: list[float] = []
    for l in lines:
        x1, y1, x2, y2 = l[0]
        ang = float(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
        while ang <= -90:
            ang += 180
        while ang > 90:
            ang -= 180
        if abs(ang) < 20:
            angles.append(ang)

    if len(angles) < 8:
        return 0.0

    median = float(np.median(np.array(angles, dtype=np.float32)))
    if abs(median) < 0.2 or abs(median) > 6.0:
        return 0.0
    return median


def _deskew_ocr(img: np.ndarray, ocr: _OCR) -> float:
    img_small = _resize_max(img, 1200)

    try:
        result = ocr.run(img_small)
    except Exception:
        return 0.0

    if not result or not result[0]:
        return 0.0

    scale_x = img.shape[1] / float(img_small.shape[1])
    scale_y = img.shape[0] / float(img_small.shape[0])

    angles: list[float] = []
    for line in result[0]:
        box = np.array(line[0], dtype=np.float32)
        text = str(line[1][0])
        conf = float(line[1][1])

        clean = "".join([c for c in text if c.isalnum()])
        if conf < 0.60 or len(clean) < 4:
            continue

        box[:, 0] *= scale_x
        box[:, 1] *= scale_y

        ang = _box_angle_deg(box)
        if abs(ang) < 20:
            angles.append(ang)

    if len(angles) < 6:
        return 0.0

    median = float(np.median(np.array(angles, dtype=np.float32)))
    if abs(median) < 0.2 or abs(median) > 6.0:
        return 0.0
    return median


def _safe_crop(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    mask = _passport_mask(img)

    # 保守策略：轻微膨胀护照区域，宁可多留背景也不切到内容
    dilate_k = int(np.clip(min(h, w) * 0.015, 9, 41))
    if dilate_k % 2 == 0:
        dilate_k += 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate_k, dilate_k))
    mask = cv2.dilate(mask, kernel, iterations=1)

    contour = _largest_contour(mask)
    if contour is None:
        return img

    contour_area = float(cv2.contourArea(contour))
    area_ratio = contour_area / float(h * w)
    # 过小/过大都更像 mask 失真：直接不裁剪
    if area_ratio < 0.12 or area_ratio > 0.995:
        return img

    rect = cv2.minAreaRect(contour)
    (rw, rh) = rect[1]
    rect_area = float(rw * rh) if (rw > 1 and rh > 1) else 0.0
    if rect_area <= 0:
        return img

    rectangularity = contour_area / rect_area
    if rectangularity < 0.25:
        return img

    x, y, cw, ch = cv2.boundingRect(cv2.convexHull(contour))

    margin = int(max(25, min(h, w) * 0.03))
    x1 = max(0, x - margin)
    y1 = max(0, y - margin)
    x2 = min(w, x + cw + margin)
    y2 = min(h, y + ch + margin)

    if x1 == 0 and y1 == 0 and x2 == w and y2 == h:
        return img

    crop_area = float((x2 - x1) * (y2 - y1))
    if crop_area > float(h * w) * 0.985:
        return img

    return img[y1:y2, x1:x2]


def process_image(
    img: np.ndarray,
    ocr: Optional[_OCR],
    debug_dir: Optional[str],
    stem: str,
) -> Tuple[Optional[np.ndarray], str]:
    mask = _passport_mask(img)

    if debug_dir:
        cv2.imwrite(os.path.join(debug_dir, f"{stem}_01_mask.png"), mask)

    if _is_dark_cover(img, mask):
        return None, "cover"

    contour = _largest_contour(mask)
    if contour is None:
        rectified = img.copy()
    else:
        rectified = _deskew_by_min_area_rect(img, contour)

    if debug_dir:
        cv2.imwrite(os.path.join(debug_dir, f"{stem}_02_rectified.png"), rectified)

    k = _estimate_orientation(rectified, ocr)
    oriented = _rotate_90(rectified, k)

    if debug_dir:
        cv2.imwrite(os.path.join(debug_dir, f"{stem}_03_oriented.png"), oriented)

    # 小角度去斜：优先用页码数字（更贴合需求），否则用护照外边缘
    if ocr is not None:
        skew = _deskew_page_number_ocr(oriented, ocr)
        if abs(skew) < 0.15:
            skew = _deskew_border_hough(oriented)
    else:
        skew = _deskew_border_hough(oriented)

    deskewed = _rotate_small(oriented, skew) if abs(skew) > 0 else oriented

    if debug_dir:
        cv2.imwrite(os.path.join(debug_dir, f"{stem}_04_deskewed.png"), deskewed)

    aligned = _ensure_landscape(deskewed, ocr)

    # 最终微调：用护照外框长边角度再去斜一次（解决 ~2-4° 残留歪斜）
    # 只接受小角度，避免引入 90° 级别误旋转。
    edge_ang = _passport_long_axis_angle(aligned)
    if edge_ang is not None and 0.2 < abs(edge_ang) < 8.0:
        aligned = _rotate_small(aligned, edge_ang)
        aligned = _ensure_landscape(aligned, ocr)

    if debug_dir:
        cv2.imwrite(os.path.join(debug_dir, f"{stem}_05_aligned.png"), aligned)

    # 保守裁剪：在方向修正后再裁剪，避免裁完后画布竖向
    cropped = _safe_crop(aligned)

    # 裁剪后再兜底一次（裁剪会显著减少背景，有助于更准判断护照长边方向）
    cropped = _ensure_landscape(cropped, ocr)

    # 裁剪后再微调一次（裁剪后边缘更干净，更容易估角）
    edge_ang2 = _passport_long_axis_angle(cropped)
    if edge_ang2 is not None and 0.2 < abs(edge_ang2) < 8.0:
        cropped = _rotate_small(cropped, edge_ang2)
        cropped = _ensure_landscape(cropped, ocr)

    return cropped, "ok"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Passport double-page scan processor")
    parser.add_argument("-i", "--input", required=True, help="输入图片目录")
    parser.add_argument("-o", "--output", required=True, help="输出图片目录")
    parser.add_argument("--debug-dir", default=None, help="保存中间过程图像的目录")
    parser.add_argument(
        "--no-ocr", action="store_true", help="禁用 OCR（会降级为非 OCR 打分）"
    )
    parser.add_argument("--ocr-lang", default="en", help="PaddleOCR 语言（默认 en）")
    parser.add_argument(
        "--max-files", type=int, default=0, help="最多处理多少张（0=不限制）"
    )
    args = parser.parse_args(argv)

    input_dir = args.input
    output_dir = args.output
    debug_dir = args.debug_dir
    use_ocr = not args.no_ocr

    if not os.path.isdir(input_dir):
        print(f"输入目录不存在: {input_dir}", file=sys.stderr)
        return 2

    _ensure_dir(output_dir)
    if debug_dir:
        _ensure_dir(debug_dir)

    files = _iter_images(input_dir)
    if args.max_files and args.max_files > 0:
        files = files[: args.max_files]

    if not files:
        print("输入目录中没有可处理的图片")
        return 0

    ocr_obj: Optional[_OCR] = None
    if use_ocr:
        try:
            ocr_obj = _OCR(lang=args.ocr_lang)
        except Exception as e:
            ocr_obj = None
            print(f"警告：OCR 不可用，已降级为非 OCR 模式: {e}", file=sys.stderr)

    skipped = 0
    processed = 0

    for name in files:
        in_path = os.path.join(input_dir, name)
        stem, _ = os.path.splitext(name)
        out_path = os.path.join(output_dir, f"{stem}_final.png")

        img = _imread(in_path)
        if img is None:
            print(f"跳过（无法读取）: {name}")
            continue

        result, status = process_image(
            img=img,
            ocr=ocr_obj,
            debug_dir=debug_dir,
            stem=stem,
        )

        if status == "cover":
            skipped += 1
            print(f"跳过封皮: {name}")
            continue

        if result is None:
            print(f"处理失败: {name}")
            continue

        cv2.imwrite(out_path, result, [cv2.IMWRITE_PNG_COMPRESSION, 3])
        processed += 1
        print(f"输出: {out_path}")

    print(f"完成：输出 {processed} 张，跳过封皮 {skipped} 张")
    if ocr_obj is not None:
        print("注意：OCR 已启用；如首次运行会加载/缓存模型，耗时会更长")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
