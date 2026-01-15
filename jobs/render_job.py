#!/usr/bin/env python
from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Optional

# Allow running as `python jobs/...py`
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import cv2
import numpy as np

from jobs.common import (
    draw_quad,
    ensure_dir,
    imread,
    order_quad_tl_tr_br_bl,
    read_jsonl,
)


def _as_quad(value: Any) -> Optional[np.ndarray]:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 4:
        return None
    pts: list[list[float]] = []
    for p in value:
        if not isinstance(p, list) or len(p) < 2:
            return None
        pts.append([float(p[0]), float(p[1])])
    return np.array(pts, dtype=np.float32)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Render final masks from a job run")
    p.add_argument(
        "--job",
        required=True,
        help="run 目录（包含 accepted.jsonl / labels.jsonl 等）",
    )
    p.add_argument(
        "--labels",
        default="labels.jsonl",
        help="人工审核输出（默认 labels.jsonl）",
    )
    p.add_argument(
        "--accepted",
        default="accepted.jsonl",
        help="自动接受输出（默认 accepted.jsonl）",
    )
    p.add_argument(
        "--output",
        default="",
        help="输出目录（默认 <job>/final_masks）",
    )

    args = p.parse_args(argv)

    run_dir = str(args.job)
    out_dir = str(args.output).strip() or os.path.join(run_dir, "final_masks")
    ensure_dir(out_dir)

    # Base: auto accepted
    items: dict[str, np.ndarray] = {}

    accepted_path = os.path.join(run_dir, str(args.accepted))
    if os.path.isfile(accepted_path):
        for row in read_jsonl(accepted_path):
            img_path = row.get("image")
            quad = _as_quad(row.get("final_quad"))
            if isinstance(img_path, str) and quad is not None:
                items[img_path] = order_quad_tl_tr_br_bl(quad)

    # Override/add: manual labels
    labels_path = os.path.join(run_dir, str(args.labels))
    if os.path.isfile(labels_path):
        for row in read_jsonl(labels_path):
            img_path = row.get("image")
            quad = _as_quad(row.get("quad"))
            if isinstance(img_path, str) and quad is not None:
                items[img_path] = order_quad_tl_tr_br_bl(quad)

    if not items:
        print("No quads found to render")
        return 0

    for img_path, quad in items.items():
        img = imread(img_path)
        if img is None:
            continue
        out = draw_quad(img, quad, color=(0, 0, 255), thickness=4)
        stem = os.path.splitext(os.path.basename(img_path))[0]
        out_path = os.path.join(out_dir, f"{stem}_mask.png")
        cv2.imwrite(out_path, out, [cv2.IMWRITE_PNG_COMPRESSION, 3])

    print(f"Wrote: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
