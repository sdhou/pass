#!/usr/bin/env python
"""mask.py

根据 prompt/img-mask.md：框出护照区域并输出图片。

用法：
  python mask.py -i img -o img-out/mask
  python mask.py -i img/1_page_2.png -o img-out/mask

输出：
  [输入文件名]_mask.png
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional, Tuple

import cv2
import numpy as np


SUPPORTED_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}


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
    return cv2.imread(path)


def _resize_max(img: np.ndarray, max_side: int) -> np.ndarray:
    h, w = img.shape[:2]
    m = max(h, w)
    if m <= max_side:
        return img
    scale = max_side / float(m)
    return cv2.resize(
        img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA
    )


def _sample_background_lab(img_lab: np.ndarray) -> tuple[np.ndarray, float]:
    # 用“边缘条带 + 选最亮部分”估计背景色（扫描背景可能偏黄/有污渍）。
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

        # 很可能是整张扫描画布的边框：跳过
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

    # close/open 可能把边界重新“抹上去”
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
        return _passport_mask_edges(img)

    # 避免把整张画布当成护照
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

        if touch >= 3 and area_ratio > 0.85:
            continue

        bbox_area = float(max(1, cw * ch))
        rectangularity = area / bbox_area
        if rectangularity < 0.18:
            continue

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


def _text_content_bbox(img: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    # 参考 passport_processor.py：用黑帽（浅底深字）提取内容密度，再用投影确定 bbox。
    img_small = _resize_max(img, 1600)
    gray = cv2.cvtColor(img_small, cv2.COLOR_BGR2GRAY)

    s = min(gray.shape[:2])
    kx = int(np.clip(s * 0.018, 25, 61))
    ky = int(np.clip(s * 0.006, 7, 21))
    if kx % 2 == 0:
        kx += 1
    if ky % 2 == 0:
        ky += 1

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kx, ky))
    bh = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, kernel)
    _, bw = cv2.threshold(bh, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)

    row = (bw > 0).mean(axis=1)
    col = (bw > 0).mean(axis=0)

    # 自适应阈值：避免背景杂点把 bbox 拉到整张画布
    thr_row = max(0.006, 0.15 * float(np.percentile(row, 95)))
    thr_col = max(0.006, 0.12 * float(np.percentile(col, 95)))

    ys = np.where(row > thr_row)[0]
    xs = np.where(col > thr_col)[0]
    if xs.size == 0 or ys.size == 0:
        return None

    x1s = int(xs[0])
    x2s = int(xs[-1]) + 1
    y1s = int(ys[0])
    y2s = int(ys[-1]) + 1

    scale_x = img.shape[1] / float(img_small.shape[1])
    scale_y = img.shape[0] / float(img_small.shape[0])

    x1 = int(round(x1s * scale_x))
    x2 = int(round(x2s * scale_x))
    y1 = int(round(y1s * scale_y))
    y2 = int(round(y2s * scale_y))

    x1 = max(0, min(img.shape[1] - 1, x1))
    x2 = max(1, min(img.shape[1], x2))
    y1 = max(0, min(img.shape[0] - 1, y1))
    y2 = max(1, min(img.shape[0], y2))

    if x2 <= x1 or y2 <= y1:
        return None

    return x1, y1, x2, y2


def _bbox_to_box(x1: int, y1: int, x2: int, y2: int) -> np.ndarray:
    return np.array(
        [[x1, y1], [x2 - 1, y1], [x2 - 1, y2 - 1], [x1, y2 - 1]], dtype=np.int32
    )


def _detect_passport_box(img: np.ndarray) -> Optional[np.ndarray]:
    # 返回 4 个点的 box（int32, shape (4,2)）
    h, w = img.shape[:2]

    # 优先使用内容密度 bbox：对“护照占上半部 + 下方大量空白背景”的情况更稳。
    tb = _text_content_bbox(img)
    if tb is not None:
        x1t, y1t, x2t, y2t = tb
        tb_area_ratio = float((x2t - x1t) * (y2t - y1t)) / float(h * w)

        if tb_area_ratio >= 0.20:
            # 用 tb 做一个更大的 ROI，再在 ROI 内用 mask 细化边界
            roi_pad = int(np.clip(min(h, w) * 0.08, 80, 260))
            rx1 = max(0, x1t - roi_pad)
            ry1 = max(0, y1t - roi_pad)
            rx2 = min(w, x2t + roi_pad)
            ry2 = min(h, y2t + roi_pad)

            roi = img[ry1:ry2, rx1:rx2]
            if roi.size > 0:
                roi_small = _resize_max(roi, 1400)
                sx = roi.shape[1] / float(roi_small.shape[1])
                sy = roi.shape[0] / float(roi_small.shape[0])

                msk = _passport_mask(roi_small)
                cnt = _largest_contour(msk)
                if cnt is not None:
                    x, y, cw, ch = cv2.boundingRect(cv2.convexHull(cnt))
                    area_ratio = float(cw * ch) / float(
                        roi_small.shape[0] * roi_small.shape[1]
                    )

                    # 过小说明误抓到印章/贴纸；过大说明仍然框到整块背景
                    if 0.20 <= area_ratio <= 0.98:
                        x1 = int(round(rx1 + x * sx))
                        y1 = int(round(ry1 + y * sy))
                        x2 = int(round(rx1 + (x + cw) * sx))
                        y2 = int(round(ry1 + (y + ch) * sy))

                        pad = int(np.clip(min(h, w) * 0.015, 12, 60))
                        x1 = max(0, x1 - pad)
                        y1 = max(0, y1 - pad)
                        x2 = min(w, x2 + pad)
                        y2 = min(h, y2 + pad)

                        if x2 > x1 and y2 > y1:
                            # refinement 有时会只抓到单页；此时用 tb bbox 更稳。
                            if (x2 - x1) >= int(0.75 * (x2t - x1t)):
                                return _bbox_to_box(x1, y1, x2, y2)

            # ROI 细化失败：回退为 tb bbox（加小 padding）
            pad = int(np.clip(min(h, w) * 0.02, 18, 80))
            x1 = max(0, x1t - pad)
            y1 = max(0, y1t - pad)
            x2 = min(w, x2t + pad)
            y2 = min(h, y2t + pad)
            return _bbox_to_box(x1, y1, x2, y2)

    # fallback：使用护照 mask + minAreaRect
    img_small = _resize_max(img, 1600)
    scale_x = img.shape[1] / float(img_small.shape[1])
    scale_y = img.shape[0] / float(img_small.shape[0])

    mask = _passport_mask(img_small)
    contour = _largest_contour(mask)
    if contour is None:
        return None

    rect = cv2.minAreaRect(contour)
    box = cv2.boxPoints(rect).astype(np.float32)
    box[:, 0] *= scale_x
    box[:, 1] *= scale_y
    return box.astype(np.int32)


def _draw_red_box(img: np.ndarray, box: np.ndarray) -> np.ndarray:
    out = img.copy()
    cv2.polylines(out, [box], isClosed=True, color=(0, 0, 255), thickness=4)
    return out


def process_one(input_path: str, output_dir: str) -> int:
    img = _imread(input_path)
    if img is None:
        print(f"跳过（无法读取）: {input_path}", file=sys.stderr)
        return 1

    box = _detect_passport_box(img)
    if box is None:
        print(f"警告：未检测到护照区域: {input_path}", file=sys.stderr)
        out = img
    else:
        out = _draw_red_box(img, box)

    stem = os.path.splitext(os.path.basename(input_path))[0]
    out_path = os.path.join(output_dir, f"{stem}_mask.png")
    ok = cv2.imwrite(out_path, out, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    if not ok:
        print(f"写入失败: {out_path}", file=sys.stderr)
        return 2

    print(f"输出: {out_path}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Draw passport region box in red")
    p.add_argument("-i", "--input", required=True, help="输入图片或目录")
    p.add_argument("-o", "--output", required=True, help="输出目录")
    args = p.parse_args(argv)

    input_path = args.input
    output_dir = args.output

    _ensure_dir(output_dir)

    if os.path.isdir(input_path):
        files = _iter_images(input_path)
        if not files:
            print("输入目录中没有可处理的图片")
            return 0
        rc = 0
        for name in files:
            in_path = os.path.join(input_path, name)
            rc = max(rc, process_one(in_path, output_dir))
        return rc

    if os.path.isfile(input_path):
        return process_one(input_path, output_dir)

    print(f"输入路径不存在: {input_path}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
