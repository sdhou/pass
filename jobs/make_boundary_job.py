#!/usr/bin/env python
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any, Optional

# Allow running as `python jobs/...py`
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import cv2
import numpy as np

import mask
import qwen
from jobs.common import (
    GateResult,
    clamp_points,
    draw_quad,
    ensure_dir,
    imread,
    iter_images,
    order_quad_tl_tr_br_bl,
    quad_area_ratio,
    quad_iou,
    strict_quality_gate,
    write_jsonl,
)


def _resize_max(img: np.ndarray, max_side: int) -> np.ndarray:
    if max_side <= 0:
        return img
    h, w = img.shape[:2]
    m = max(h, w)
    if m <= max_side:
        return img
    scale = max_side / float(m)
    return cv2.resize(
        img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA
    )


def _as_list(points: Optional[np.ndarray]) -> Optional[list[list[int]]]:
    if points is None:
        return None
    pts = points.astype(int)
    return [[int(x), int(y)] for x, y in pts]


def _pick_safer_quad(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    # Prefer larger area to avoid cutting off passport.
    # When they agree strongly, this is usually safe.
    pa = float(cv2.contourArea(a.reshape(-1, 1, 2)))
    pb = float(cv2.contourArea(b.reshape(-1, 1, 2)))
    return a if pa >= pb else b


def _qwen_candidate_quad(
    *,
    img: np.ndarray,
    base_url: str,
    api_key: str,
    model: str,
    timeout_s: float,
    max_tokens: int,
    json_mode: bool,
    request_max_side: int,
    prompt_text: str,
    refine_rotated: bool,
) -> Optional[np.ndarray]:
    orig_h, orig_w = img.shape[:2]

    req_img = _resize_max(img, request_max_side)
    req_h, req_w = req_img.shape[:2]

    sx = orig_w / float(req_w)
    sy = orig_h / float(req_h)

    data_url = qwen._encode_image_data_url_png(req_img)

    effective_prompt = prompt_text.strip() or qwen._default_prompt(
        img_w=req_w, img_h=req_h
    )

    resp = qwen._call_openai_compatible(
        base_url=base_url,
        api_key=api_key,
        model=model,
        image_data_url=data_url,
        prompt_text=effective_prompt,
        timeout_s=timeout_s,
        max_tokens=max_tokens,
        json_mode=json_mode,
    )

    geom = qwen._extract_points_from_model_text(resp.content_text)
    if geom is None:
        return None

    pts_req = qwen._to_pixel_points(geom=geom, img_w=req_w, img_h=req_h)
    if pts_req is None:
        return None

    pts = pts_req.astype(np.float32)
    pts[:, 0] *= sx
    pts[:, 1] *= sy
    pts = clamp_points(pts, w=orig_w, h=orig_h)
    pts_int = pts.astype(np.int32)

    if refine_rotated and not qwen._geom_prefers_quad(geom):
        x1, y1, x2, y2 = qwen._bbox_from_points(pts_int)
        pad = int(np.clip(min(orig_h, orig_w) * 0.02, 12, 80))
        rx1 = max(0, x1 - pad)
        ry1 = max(0, y1 - pad)
        rx2 = min(orig_w - 1, x2 + pad)
        ry2 = min(orig_h - 1, y2 + pad)

        roi = img[ry1 : ry2 + 1, rx1 : rx2 + 1]
        box_roi = qwen._refine_rotated_box_from_roi(roi)
        if box_roi is not None:
            box_roi = box_roi.copy()
            box_roi[:, 0] += rx1
            box_roi[:, 1] += ry1
            pts_int = box_roi

    return order_quad_tl_tr_br_bl(pts_int).astype(np.int32)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Create a conservative boundary job (prefer manual over wrong)"
    )
    p.add_argument("-i", "--input", default="img", help="输入目录（仅处理 .png）")
    p.add_argument(
        "-o",
        "--output",
        default="",
        help="输出 run 目录（默认自动生成 jobs/runs/<timestamp>）",
    )

    p.add_argument("--region", choices=["cn", "intl"], default="cn")
    p.add_argument("--base-url", default="")
    p.add_argument("--env-file", default=".env")
    p.add_argument("--no-env-file", action="store_true")
    p.add_argument("--api-key", default="")

    p.add_argument("--model", default=qwen.DEFAULT_MODEL)
    p.add_argument("--json-mode", action="store_true")
    p.add_argument("--timeout", type=float, default=120.0)
    p.add_argument("--max-tokens", type=int, default=512)

    p.add_argument(
        "--request-max-side",
        type=int,
        default=1600,
        help="发给 VLM 的最大边长（0=不缩放）",
    )
    p.add_argument(
        "--no-refine-rotated",
        action="store_true",
        help="关闭 ROI 旋转框细化（默认开启）",
    )

    p.add_argument(
        "--prompt",
        default="",
        help="自定义 VLM 提示词（为空则用 qwen.py 内置提示词）",
    )

    # Conservative thresholds: tune per dataset.
    p.add_argument("--min-area-ratio", type=float, default=0.30)
    p.add_argument("--max-area-ratio", type=float, default=0.98)
    p.add_argument("--min-iou", type=float, default=0.90)
    p.add_argument(
        "--no-auto-accept",
        action="store_true",
        help="禁用自动接受（全部进入 needs_manual，宁可人工也不误裁）",
    )

    args = p.parse_args(argv)

    input_dir = args.input
    if not os.path.isdir(input_dir):
        print(f"输入目录不存在: {input_dir}", file=sys.stderr)
        return 2

    if not bool(args.no_env_file):
        qwen._load_env_file(str(args.env_file))

    base_url = args.base_url.strip() or qwen._default_base_url(args.region)
    env_key = "DASHSCOPE_API_KEY_INTL" if args.region == "intl" else "DASHSCOPE_API_KEY"
    api_key = (
        str(args.api_key).strip()
        or os.getenv(env_key, "").strip()
        or os.getenv("DASHSCOPE_API_KEY", "").strip()
    )
    if not api_key:
        print(
            "缺少 API Key：请设置 DASHSCOPE_API_KEY 或传入 --api-key", file=sys.stderr
        )
        return 2

    model = str(args.model).strip()
    if not model:
        print("缺少模型：请传入 --model", file=sys.stderr)
        return 2

    run_dir = args.output.strip()
    if not run_dir:
        ts = time.strftime("%Y%m%d_%H%M%S")
        run_dir = os.path.join("jobs", "runs", ts)

    ensure_dir(run_dir)
    viz_dir = os.path.join(run_dir, "viz")
    ensure_dir(viz_dir)

    names = iter_images(input_dir)
    if not names:
        print("输入目录中没有 .png")
        return 0

    rows: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    needs_manual: list[dict[str, Any]] = []

    for name in names:
        in_path = os.path.join(input_dir, name)
        img = imread(in_path)
        if img is None:
            continue

        h, w = img.shape[:2]

        qwen_quad = None
        qwen_gate = GateResult(False, "no_candidate", 0.0)
        cv_quad = None
        cv_gate = GateResult(False, "no_candidate", 0.0)

        try:
            qwen_quad = _qwen_candidate_quad(
                img=img,
                base_url=base_url,
                api_key=api_key,
                model=model,
                timeout_s=float(args.timeout),
                max_tokens=int(args.max_tokens),
                json_mode=bool(args.json_mode),
                request_max_side=int(args.request_max_side),
                prompt_text=str(args.prompt),
                refine_rotated=not bool(args.no_refine_rotated),
            )
        except Exception as e:
            qwen_quad = None
            qwen_gate = GateResult(False, f"qwen_error:{type(e).__name__}", 0.0)

        if qwen_quad is not None:
            qwen_gate = strict_quality_gate(
                quad=qwen_quad,
                w=w,
                h=h,
                min_area_ratio=float(args.min_area_ratio),
                max_area_ratio=float(args.max_area_ratio),
            )

        try:
            cv_quad = mask._detect_passport_box(img)
        except Exception as e:
            cv_quad = None
            cv_gate = GateResult(False, f"cv_error:{type(e).__name__}", 0.0)

        if cv_quad is not None:
            cv_quad = order_quad_tl_tr_br_bl(cv_quad).astype(np.int32)
            cv_gate = strict_quality_gate(
                quad=cv_quad,
                w=w,
                h=h,
                min_area_ratio=float(args.min_area_ratio),
                max_area_ratio=float(args.max_area_ratio),
            )

        iou = None
        if qwen_quad is not None and cv_quad is not None:
            iou = quad_iou(qwen_quad, cv_quad)

        auto_accept = False
        final_quad = None
        final_reason = ""

        if (
            not bool(args.no_auto_accept)
            and qwen_quad is not None
            and cv_quad is not None
            and qwen_gate.ok
            and cv_gate.ok
            and iou is not None
            and iou >= float(args.min_iou)
        ):
            auto_accept = True
            final_quad = _pick_safer_quad(qwen_quad, cv_quad)
            final_reason = f"auto_consensus_iou:{iou:.3f}"

        # Visualize candidates for review.
        vis = img
        if qwen_quad is not None:
            vis = draw_quad(vis, qwen_quad, color=(255, 0, 0), thickness=3)  # blue
        if cv_quad is not None:
            vis = draw_quad(vis, cv_quad, color=(0, 255, 0), thickness=3)  # green
        if final_quad is not None:
            vis = draw_quad(vis, final_quad, color=(0, 0, 255), thickness=4)  # red

        out_viz_path = os.path.join(viz_dir, f"{os.path.splitext(name)[0]}_viz.png")
        cv2.imwrite(out_viz_path, vis, [cv2.IMWRITE_PNG_COMPRESSION, 3])

        row: dict[str, Any] = {
            "image": in_path,
            "viz": out_viz_path,
            "w": w,
            "h": h,
            "qwen_quad": _as_list(qwen_quad),
            "qwen_gate": {
                "ok": qwen_gate.ok,
                "reason": qwen_gate.reason,
                "score": qwen_gate.score,
            },
            "cv_quad": _as_list(cv_quad),
            "cv_gate": {
                "ok": cv_gate.ok,
                "reason": cv_gate.reason,
                "score": cv_gate.score,
            },
            "iou": None if iou is None else float(iou),
            "auto_accept": auto_accept,
            "final_quad": _as_list(final_quad),
            "final_reason": final_reason,
        }
        rows.append(row)

        if auto_accept:
            accepted.append(row)
        else:
            needs_manual.append(row)

        print(f"{name}: auto={auto_accept} iou={iou}")

    write_jsonl(os.path.join(run_dir, "cases.jsonl"), rows)
    write_jsonl(os.path.join(run_dir, "accepted.jsonl"), accepted)
    write_jsonl(os.path.join(run_dir, "needs_manual.jsonl"), needs_manual)

    print(f"Run dir: {run_dir}")
    print(f"Accepted: {len(accepted)}")
    print(f"Needs manual: {len(needs_manual)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
