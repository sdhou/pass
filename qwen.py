#!/usr/bin/env python
"""qwen.py

调用 Qwen3-VL-Plus（OpenAI 兼容接口）定位图片中的护照区域，并用红线框出。

用法：
  python qwen.py -i img -o img-out/qwen
  python qwen.py -i img/1_page_2.png -o img-out/qwen

输入限制：
- 仅支持 PNG（.png）

说明：
- 默认使用百炼（DashScope）OpenAI 兼容接口：
  - cn:   https://dashscope.aliyuncs.com/compatible-mode/v1
  - intl: https://dashscope-intl.aliyuncs.com/compatible-mode/v1
- API Key 默认读取环境变量：DASHSCOPE_API_KEY（也会自动读取当前目录的 .env，不覆盖已设置的环境变量）

输出：
- [输入文件名]_mask.png
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from dataclasses import dataclass
from typing import Any, Optional

import cv2
import numpy as np
import requests


SUPPORTED_EXTS = {".png"}

DEFAULT_MODEL = "qwen3-vl-plus"


@dataclass(frozen=True)
class ModelResponse:
    content_text: str
    raw_json: dict[str, Any]


def _strip_wrapping_quotes(value: str) -> str:
    v = value.strip()
    if len(v) >= 2 and (
        (v[0] == '"' and v[-1] == '"') or (v[0] == "'" and v[-1] == "'")
    ):
        return v[1:-1]
    return v


def _load_env_file(path: str) -> None:
    # 轻量 .env 解析：不依赖 python-dotenv。
    # 规则：只设置当前进程中未定义的环境变量（不覆盖外部传入的 env）。
    if not path:
        return
    if not os.path.isfile(path):
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue

                # 支持：export KEY=VALUE
                if line.startswith("export "):
                    line = line[len("export ") :].strip()

                m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
                if not m:
                    continue

                key = m.group(1)
                val = _strip_wrapping_quotes(m.group(2))

                # 去掉行尾注释：KEY=VAL # comment
                if "#" in val and not (val.startswith('"') or val.startswith("'")):
                    val = val.split("#", 1)[0].rstrip()

                if key and key not in os.environ:
                    os.environ[key] = val
    except Exception:
        # .env 解析失败不应阻塞主流程
        return


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


def _encode_image_data_url_png(img_bgr: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", img_bgr, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    if not ok:
        raise RuntimeError("Failed to encode image")

    b64 = base64.b64encode(buf.tobytes()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _default_base_url(region: str) -> str:
    if region == "intl":
        return "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    return "https://dashscope.aliyuncs.com/compatible-mode/v1"


def _call_openai_compatible(
    *,
    base_url: str,
    api_key: str,
    model: str,
    image_data_url: str,
    prompt_text: str,
    timeout_s: float,
    max_tokens: int,
    json_mode: bool,
) -> ModelResponse:
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload: dict[str, Any] = {
        "model": model,
        "temperature": 0,
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "system",
                "content": "You are an expert document detector. Return only JSON.",
            },
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                    {"type": "text", "text": prompt_text},
                ],
            },
        ],
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    res = requests.post(url, headers=headers, json=payload, timeout=timeout_s)
    data = res.json() if res.content else None
    if not res.ok:
        msg = None
        if isinstance(data, dict):
            msg = (
                data.get("error", {}) if isinstance(data.get("error"), dict) else {}
            ).get("message")
        raise RuntimeError(msg or f"HTTP {res.status_code}: request failed")

    if not isinstance(data, dict):
        raise RuntimeError("Unexpected response JSON")

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("No choices in response")
    msg_obj = choices[0].get("message")
    if not isinstance(msg_obj, dict):
        raise RuntimeError("Missing message in response")

    content_text = msg_obj.get("content")
    if not isinstance(content_text, str) or not content_text.strip():
        raise RuntimeError("Empty model content")

    return ModelResponse(content_text=content_text, raw_json=data)


def _try_json_loads(text: str) -> Optional[Any]:
    try:
        return json.loads(text)
    except Exception:
        return None


def _extract_first_json(text: str) -> Optional[Any]:
    s = text.strip()
    if s.startswith("{") or s.startswith("["):
        parsed = _try_json_loads(s)
        if parsed is not None:
            return parsed

    # Fast path: look for fenced code blocks
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, flags=re.IGNORECASE)
    if m:
        parsed = _try_json_loads(m.group(1).strip())
        if parsed is not None:
            return parsed

    # Bracket-balance scan for the first JSON object/array
    for opener, closer in [("{", "}"), ("[", "]")]:
        start = text.find(opener)
        if start < 0:
            continue
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue

            if ch == '"':
                in_str = True
                continue

            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    cand = text[start : i + 1]
                    parsed = _try_json_loads(cand)
                    if parsed is not None:
                        return parsed
                    break

    return None


def _parse_numbers_as_bbox(text: str) -> Optional[list[float]]:
    # <box>(x1,y1),(x2,y2)</box>
    m = re.search(
        r"<box>\s*\(\s*([\d.]+)\s*,\s*([\d.]+)\s*\)\s*,\s*\(\s*([\d.]+)\s*,\s*([\d.]+)\s*\)\s*</box>",
        text,
        flags=re.IGNORECASE,
    )
    if m:
        return [float(m.group(i)) for i in range(1, 5)]

    # [x1, y1, x2, y2]
    m2 = re.search(
        r"\[\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*\]",
        text,
    )
    if m2:
        return [float(m2.group(i)) for i in range(1, 5)]

    return None


def _normalize_mode(values: list[float]) -> str:
    mx = max(values) if values else 0.0
    if mx <= 1.5:
        return "unit"
    if mx <= 1000.5:
        return "k1000"
    return "pixel"


def _points_from_bbox(values: list[float]) -> list[tuple[float, float]]:
    x1, y1, x2, y2 = values
    return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]


def _coerce_geometry(obj: Any) -> Optional[dict[str, Any]]:
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, list) and obj:
        # Try find the most plausible dict item
        for item in obj:
            if isinstance(item, dict):
                return item
    return None


def _extract_points_from_model_text(text: str) -> Optional[dict[str, Any]]:
    parsed = _extract_first_json(text)
    obj = _coerce_geometry(parsed)
    if obj is not None:
        return obj

    bbox = _parse_numbers_as_bbox(text)
    if bbox is not None:
        return {"bbox_2d": bbox}

    return None


def _to_pixel_points(
    *,
    geom: dict[str, Any],
    img_w: int,
    img_h: int,
) -> Optional[np.ndarray]:
    points: Optional[list[tuple[float, float]]] = None

    for key in ("quad_2d", "polygon", "points"):
        val = geom.get(key)
        if isinstance(val, list) and len(val) >= 4:
            cand: list[tuple[float, float]] = []
            ok = True
            for p in val[:4]:
                if not (isinstance(p, list) or isinstance(p, tuple)) or len(p) < 2:
                    ok = False
                    break
                cand.append((float(p[0]), float(p[1])))
            if ok:
                points = cand
                break

    if points is None:
        for key in ("bbox_2d", "bbox"):
            val = geom.get(key)
            if isinstance(val, list) and len(val) >= 4:
                nums = [float(v) for v in val[:4]]
                points = _points_from_bbox(nums)
                break

    if points is None:
        return None

    flat = [v for xy in points for v in xy]
    mode = _normalize_mode(flat)

    pts_px: list[list[float]] = []
    for x, y in points:
        if mode == "unit":
            px = x * float(img_w)
            py = y * float(img_h)
        elif mode == "k1000":
            px = x / 1000.0 * float(img_w)
            py = y / 1000.0 * float(img_h)
        else:
            px = x
            py = y
        pts_px.append([px, py])

    pts = np.array(pts_px, dtype=np.float32)
    pts[:, 0] = np.clip(pts[:, 0], 0, max(0, img_w - 1))
    pts[:, 1] = np.clip(pts[:, 1], 0, max(0, img_h - 1))
    return pts.astype(np.int32)


def _draw_red_box(img: np.ndarray, box: np.ndarray) -> np.ndarray:
    out = img.copy()
    cv2.polylines(out, [box], isClosed=True, color=(0, 0, 255), thickness=4)
    return out


def _geom_prefers_quad(geom: dict[str, Any]) -> bool:
    for key in ("quad_2d", "polygon", "points"):
        val = geom.get(key)
        if isinstance(val, list) and len(val) >= 4:
            return True
    return False


def _bbox_from_points(points: np.ndarray) -> tuple[int, int, int, int]:
    xs = points[:, 0]
    ys = points[:, 1]
    x1 = int(np.min(xs))
    y1 = int(np.min(ys))
    x2 = int(np.max(xs))
    y2 = int(np.max(ys))
    return x1, y1, x2, y2


def _refine_rotated_box_from_roi(roi: np.ndarray) -> Optional[np.ndarray]:
    # 使用 OpenCV 从 ROI 内估计护照的旋转外接矩形（用于纠正扫描歪斜）。
    h, w = roi.shape[:2]
    if h < 30 or w < 30:
        return None

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 40, 140)

    k = int(np.clip(min(h, w) * 0.01, 3, 7))
    edges = cv2.dilate(edges, np.ones((k, k), np.uint8), iterations=2)

    border = int(np.clip(min(h, w) * 0.03, 12, 60))
    edges[:border, :] = 0
    edges[h - border : h, :] = 0
    edges[:, :border] = 0
    edges[:, w - border : w] = 0

    close_k = int(np.clip(min(h, w) * 0.03, 11, 41))
    if close_k % 2 == 0:
        close_k += 1
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (close_k, close_k))
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    roi_area = float(h * w)
    best_rect = None
    best_score = -1.0

    for c in contours:
        area = float(cv2.contourArea(c))
        if area < roi_area * 0.08:
            continue

        rect = cv2.minAreaRect(c)
        (rw, rh) = rect[1]
        if rw < 2 or rh < 2:
            continue

        rect_area = float(rw * rh)
        rectangularity = area / rect_area if rect_area > 0 else 0.0
        if rectangularity < 0.25:
            continue

        long_side = max(rw, rh)
        short_side = max(1.0, min(rw, rh))
        aspect = float(long_side / short_side)
        # 护照整体通常是长方形；过于极端一般是误检。
        if aspect < 1.10 or aspect > 4.50:
            continue

        score = area * rectangularity
        if score > best_score:
            best_score = score
            best_rect = rect

    if best_rect is None:
        best_rect = cv2.minAreaRect(max(contours, key=cv2.contourArea))

    box = cv2.boxPoints(best_rect).astype(np.int32)
    return box


def _default_prompt(*, img_w: int, img_h: int) -> str:
    # 目标：框“整本护照本体”的最外轮廓（封皮/纸张边缘），而不是内页信息区。
    # 要求像素坐标；但为兼容不同模型输出，脚本也会自动识别 0-1000 / 0-1 的归一化坐标。
    return (
        f"请在图片中定位‘整本护照本体’（护照这本书/打开的整本护照）的最外边缘轮廓，图片可能是扫描件且可能歪斜。"
        f"图片尺寸为 {img_w}x{img_h}（宽x高）。"
        "重要：请框到护照的外边界（封皮/纸张裁切边缘），宁可略大一点，也不要只框到内页信息区域。"
        "不要只框照片区、不要只框MRZ、不要只框文本信息页的内框。"
        "只输出 JSON，不要输出任何解释文字。"
        '优先输出：{"bbox_2d": [x1, y1, x2, y2]}（像素坐标，整数）。'
        '如果能提供更贴合歪斜的结果，也可以输出：{"quad_2d": [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]}（四个角点）。'
    )


def process_one(
    *,
    input_path: str,
    output_dir: str,
    base_url: str,
    api_key: str,
    model: str,
    prompt_text: str,
    request_max_side: int,
    timeout_s: float,
    max_tokens: int,
    json_mode: bool,
    refine_rotated: bool,
    save_json_dir: Optional[str],
) -> int:
    img = _imread(input_path)
    if img is None:
        print(f"跳过（无法读取）: {input_path}", file=sys.stderr)
        return 1

    orig_h, orig_w = img.shape[:2]

    req_img = _resize_max(img, request_max_side)
    req_h, req_w = req_img.shape[:2]
    sx = orig_w / float(req_w)
    sy = orig_h / float(req_h)

    data_url = _encode_image_data_url_png(req_img)

    effective_prompt = prompt_text.strip() or _default_prompt(img_w=req_w, img_h=req_h)

    resp = _call_openai_compatible(
        base_url=base_url,
        api_key=api_key,
        model=model,
        image_data_url=data_url,
        prompt_text=effective_prompt,
        timeout_s=timeout_s,
        max_tokens=max_tokens,
        json_mode=json_mode,
    )

    geom = _extract_points_from_model_text(resp.content_text)
    if geom is None:
        print(f"警告：模型输出无法解析为坐标: {input_path}", file=sys.stderr)
        out = img
    else:
        pts_req = _to_pixel_points(geom=geom, img_w=req_w, img_h=req_h)
        if pts_req is None:
            print(f"警告：坐标字段缺失或格式不正确: {input_path}", file=sys.stderr)
            out = img
        else:
            pts = pts_req.astype(np.float32)
            pts[:, 0] *= sx
            pts[:, 1] *= sy
            pts[:, 0] = np.clip(pts[:, 0], 0, max(0, orig_w - 1))
            pts[:, 1] = np.clip(pts[:, 1], 0, max(0, orig_h - 1))
            pts_int = pts.astype(np.int32)

            if refine_rotated and not _geom_prefers_quad(geom):
                x1, y1, x2, y2 = _bbox_from_points(pts_int)
                pad = int(np.clip(min(orig_h, orig_w) * 0.02, 12, 80))

                rx1 = max(0, x1 - pad)
                ry1 = max(0, y1 - pad)
                rx2 = min(orig_w - 1, x2 + pad)
                ry2 = min(orig_h - 1, y2 + pad)

                roi = img[ry1 : ry2 + 1, rx1 : rx2 + 1]
                box_roi = _refine_rotated_box_from_roi(roi)
                if box_roi is not None:
                    box_roi = box_roi.copy()
                    box_roi[:, 0] += rx1
                    box_roi[:, 1] += ry1
                    pts_int = box_roi

            out = _draw_red_box(img, pts_int)

    if save_json_dir:
        _ensure_dir(save_json_dir)
        stem = os.path.splitext(os.path.basename(input_path))[0]
        json_path = os.path.join(save_json_dir, f"{stem}.json")
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(resp.raw_json, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"警告：无法写入响应 JSON: {json_path}: {e}", file=sys.stderr)

    stem = os.path.splitext(os.path.basename(input_path))[0]
    out_path = os.path.join(output_dir, f"{stem}_mask.png")
    ok = cv2.imwrite(out_path, out, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    if not ok:
        print(f"写入失败: {out_path}", file=sys.stderr)
        return 2

    print(f"输出: {out_path}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Call Qwen3-VL-Plus to locate passport area and draw red box"
    )
    p.add_argument(
        "-i",
        "--input",
        default="img",
        help="输入 PNG 图片或目录（默认：img；仅处理 .png）",
    )
    p.add_argument(
        "-o", "--output", default="img-out/qwen", help="输出目录（默认：img-out/qwen）"
    )

    p.add_argument(
        "--region",
        choices=["cn", "intl"],
        default="cn",
        help="百炼地域（影响 base_url 默认值）",
    )
    p.add_argument(
        "--base-url",
        default="",
        help="覆盖 OpenAI 兼容接口 base_url（默认按 region 选择）",
    )
    p.add_argument(
        "--api-key",
        default="",
        help="API Key（默认读取环境变量 DASHSCOPE_API_KEY / DASHSCOPE_API_KEY_INTL）",
    )
    p.add_argument(
        "--env-file",
        default=".env",
        help="可选：读取环境变量文件（默认：.env；不会覆盖已设置的环境变量）",
    )
    p.add_argument(
        "--no-env-file",
        action="store_true",
        help="禁用自动读取 .env",
    )
    p.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="模型名称（默认：qwen3-vl-plus）",
    )

    p.add_argument(
        "--prompt",
        default="",
        help="自定义提示词（默认使用内置提示词，要求输出 bbox JSON）",
    )
    p.add_argument(
        "--json-mode",
        action="store_true",
        help="启用 OpenAI 结构化输出（response_format=json_object）；若模型不支持可关闭",
    )
    p.add_argument(
        "--no-refine-rotated",
        action="store_true",
        help="关闭 OpenCV 旋转框细化（默认开启；用于处理扫描歪斜）",
    )

    p.add_argument(
        "--request-max-side",
        type=int,
        default=1600,
        help="发给模型的最大边长（缩放后推理；0=不缩放）",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="请求超时（秒）",
    )
    p.add_argument(
        "--max-tokens",
        type=int,
        default=512,
        help="模型最大输出 token",
    )
    p.add_argument(
        "--save-json-dir",
        default="",
        help="保存原始响应 JSON 的目录（可选）",
    )

    args = p.parse_args(argv)

    input_path: str = args.input
    output_dir: str = args.output

    if not bool(args.no_env_file):
        _load_env_file(str(args.env_file))

    base_url = args.base_url.strip() or _default_base_url(args.region)

    env_key_name = (
        "DASHSCOPE_API_KEY_INTL" if args.region == "intl" else "DASHSCOPE_API_KEY"
    )
    api_key = (
        args.api_key.strip()
        or os.getenv(env_key_name, "").strip()
        or os.getenv("DASHSCOPE_API_KEY", "").strip()
    )
    if not api_key:
        print(
            "缺少 API Key：请设置环境变量 DASHSCOPE_API_KEY（intl 可用 DASHSCOPE_API_KEY_INTL）或传入 --api-key",
            file=sys.stderr,
        )
        return 2

    model = args.model.strip()
    if not model:
        print("缺少模型名称：请传入 --model", file=sys.stderr)
        return 2

    prompt_text = args.prompt.strip()

    _ensure_dir(output_dir)

    save_json_dir: Optional[str] = args.save_json_dir.strip() or None

    if os.path.isdir(input_path):
        files = _iter_images(input_path)
        if not files:
            print("输入目录中没有可处理的图片")
            return 0

        rc = 0
        for name in files:
            in_path = os.path.join(input_path, name)
            rc = max(
                rc,
                process_one(
                    input_path=in_path,
                    output_dir=output_dir,
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                    prompt_text=prompt_text,
                    request_max_side=int(args.request_max_side),
                    timeout_s=float(args.timeout),
                    max_tokens=int(args.max_tokens),
                    json_mode=bool(args.json_mode),
                    refine_rotated=not bool(args.no_refine_rotated),
                    save_json_dir=save_json_dir,
                ),
            )
        return rc

    if os.path.isfile(input_path):
        _, ext = os.path.splitext(input_path)
        if ext.lower() != ".png":
            print(f"仅支持 PNG 输入，收到: {input_path}", file=sys.stderr)
            return 2

        return process_one(
            input_path=input_path,
            output_dir=output_dir,
            base_url=base_url,
            api_key=api_key,
            model=model,
            prompt_text=prompt_text,
            request_max_side=int(args.request_max_side),
            timeout_s=float(args.timeout),
            max_tokens=int(args.max_tokens),
            json_mode=bool(args.json_mode),
            refine_rotated=not bool(args.no_refine_rotated),
            save_json_dir=save_json_dir,
        )

    print(f"输入路径不存在: {input_path}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
