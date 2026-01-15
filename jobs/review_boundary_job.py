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
    clamp_points,
    draw_quad,
    ensure_dir,
    imread,
    order_quad_tl_tr_br_bl,
    read_jsonl,
    write_jsonl,
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


class ClickState:
    def __init__(self) -> None:
        self.points: list[tuple[int, int]] = []

    def reset(self) -> None:
        self.points = []


def _mouse_cb(event: int, x: int, y: int, _flags: int, state: ClickState) -> None:
    if event == cv2.EVENT_LBUTTONDOWN:
        if len(state.points) < 4:
            state.points.append((int(x), int(y)))


def _render(
    img: np.ndarray,
    *,
    qwen_quad: Optional[np.ndarray],
    cv_quad: Optional[np.ndarray],
    chosen_quad: Optional[np.ndarray],
    manual_points: list[tuple[int, int]],
) -> np.ndarray:
    out = img
    if qwen_quad is not None:
        out = draw_quad(out, qwen_quad, color=(255, 0, 0), thickness=3)  # blue
    if cv_quad is not None:
        out = draw_quad(out, cv_quad, color=(0, 255, 0), thickness=3)  # green
    if chosen_quad is not None:
        out = draw_quad(out, chosen_quad, color=(0, 0, 255), thickness=4)  # red

    if manual_points:
        out2 = out.copy()
        for x, y in manual_points:
            cv2.circle(out2, (x, y), 6, (0, 0, 255), -1)
        if len(manual_points) == 4:
            pts = np.array(manual_points, dtype=np.float32)
            out2 = draw_quad(out2, pts, color=(0, 0, 255), thickness=4)
        out = out2

    return out


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Review a boundary job; choose qwen/cv/manual quad"
    )
    p.add_argument(
        "--job",
        required=True,
        help="jobs/make_boundary_job.py 输出的 run 目录（包含 needs_manual.jsonl）",
    )
    p.add_argument(
        "--input",
        default="needs_manual.jsonl",
        help="输入 jsonl（默认 needs_manual.jsonl）",
    )
    p.add_argument(
        "--output",
        default="labels.jsonl",
        help="输出 labels jsonl（默认 labels.jsonl）",
    )

    args = p.parse_args(argv)

    run_dir = str(args.job)
    in_jsonl = os.path.join(run_dir, str(args.input))
    out_jsonl = os.path.join(run_dir, str(args.output))

    rows = read_jsonl(in_jsonl)
    ensure_dir(run_dir)

    labels: list[dict[str, Any]] = []

    win = "review"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)

    state = ClickState()
    cv2.setMouseCallback(win, _mouse_cb, state)

    idx = 0
    while idx < len(rows):
        row = rows[idx]
        img_path = row.get("image")
        if not isinstance(img_path, str) or not os.path.isfile(img_path):
            idx += 1
            continue

        img = imread(img_path)
        if img is None:
            idx += 1
            continue

        h, w = img.shape[:2]

        qwen_quad = _as_quad(row.get("qwen_quad"))
        cv_quad = _as_quad(row.get("cv_quad"))

        chosen: Optional[np.ndarray] = None
        chosen_method: str = ""

        state.reset()

        while True:
            manual_quad = None
            if len(state.points) == 4:
                manual_quad = np.array(state.points, dtype=np.float32)

            vis = _render(
                img,
                qwen_quad=qwen_quad,
                cv_quad=cv_quad,
                chosen_quad=chosen,
                manual_points=state.points,
            )

            title = f"{idx + 1}/{len(rows)}: {os.path.basename(img_path)}  [1]=qwen [2]=cv [m]=manual [r]=reset [s]=save [n]=skip [q]=quit"
            cv2.setWindowTitle(win, title)
            cv2.imshow(win, vis)

            key = cv2.waitKey(20) & 0xFF
            if key == ord("q"):
                cv2.destroyAllWindows()
                write_jsonl(out_jsonl, labels)
                return 0

            if key == ord("n"):
                chosen = None
                chosen_method = "skip"
                break

            if key == ord("1") and qwen_quad is not None:
                chosen = order_quad_tl_tr_br_bl(qwen_quad)
                chosen_method = "qwen"

            if key == ord("2") and cv_quad is not None:
                chosen = order_quad_tl_tr_br_bl(cv_quad)
                chosen_method = "cv"

            if key == ord("m"):
                chosen = None
                chosen_method = "manual"
                state.reset()

            if key == ord("r"):
                state.reset()

            if key == ord("s"):
                if chosen_method == "manual":
                    if manual_quad is None:
                        continue
                    chosen = order_quad_tl_tr_br_bl(manual_quad)

                if chosen is None:
                    continue

                chosen = clamp_points(chosen, w=w, h=h)
                out_pts = chosen.astype(int)

                labels.append(
                    {
                        "image": img_path,
                        "quad": [[int(x), int(y)] for x, y in out_pts],
                        "method": chosen_method or "manual",
                    }
                )
                break

        idx += 1

    cv2.destroyAllWindows()
    write_jsonl(out_jsonl, labels)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
