from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import dataclass
from typing import Any, Optional

import cv2
import fitz  # PyMuPDF
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse


_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import mask  # noqa: E402
import qwen  # noqa: E402


app = FastAPI(title="Passport Boundary Backend")


DATA_ROOT = os.path.join(os.path.dirname(__file__), "data")
RUNS_ROOT = os.path.join(DATA_ROOT, "runs")


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _read_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    if not isinstance(obj, dict):
        raise ValueError("json root must be object")
    return obj


def _write_json(path: str, obj: dict[str, Any]) -> None:
    _ensure_dir(os.path.dirname(path) or ".")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def _order_quad_tl_tr_br_bl(points: np.ndarray) -> np.ndarray:
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


def _clamp_points(points: np.ndarray, w: int, h: int) -> np.ndarray:
    pts = points.astype(np.float32).copy()
    pts[:, 0] = np.clip(pts[:, 0], 0, max(0, w - 1))
    pts[:, 1] = np.clip(pts[:, 1], 0, max(0, h - 1))
    return pts


def _draw_quad(
    img: np.ndarray, quad: np.ndarray, color: tuple[int, int, int]
) -> np.ndarray:
    out = img.copy()
    pts = _order_quad_tl_tr_br_bl(quad).astype(np.int32)
    cv2.polylines(out, [pts], isClosed=True, color=color, thickness=4)
    return out


def _make_run_id() -> str:
    return uuid.uuid4().hex[:12]


def _run_dir(run_id: str) -> str:
    return os.path.join(RUNS_ROOT, run_id)


def _page_image_path(run_id: str, page_number: int) -> str:
    return os.path.join(_run_dir(run_id), "pages", f"{page_number}.png")


def _page_meta_path(run_id: str, page_number: int) -> str:
    return os.path.join(_run_dir(run_id), "pages", f"{page_number}.json")


def _page_mask_path(run_id: str, page_number: int) -> str:
    return os.path.join(_run_dir(run_id), "masks", f"{page_number}_mask.png")


def _make_candidates(
    *,
    img: np.ndarray,
    api_key: str,
    base_url: str,
    model: str,
    json_mode: bool,
    timeout_s: float,
    max_tokens: int,
) -> dict[str, Any]:
    h, w = img.shape[:2]

    cv_quad = None
    try:
        box = mask._detect_passport_box(img)
        if box is not None:
            cv_quad = _order_quad_tl_tr_br_bl(box).astype(np.int32)
    except Exception as e:
        cv_quad = None

    qwen_quad = None
    qwen_err = None
    if api_key:
        try:
            # reuse qwen.py internals
            req_img = img
            data_url = qwen._encode_image_data_url_png(req_img)
            prompt_text = qwen._default_prompt(img_w=w, img_h=h)

            resp = qwen._call_openai_compatible(
                base_url=base_url,
                api_key=api_key,
                model=model,
                image_data_url=data_url,
                prompt_text=prompt_text,
                timeout_s=timeout_s,
                max_tokens=max_tokens,
                json_mode=json_mode,
            )

            geom = qwen._extract_points_from_model_text(resp.content_text)
            if geom is not None:
                pts = qwen._to_pixel_points(geom=geom, img_w=w, img_h=h)
                if pts is not None and pts.shape == (4, 2):
                    qwen_quad = _order_quad_tl_tr_br_bl(pts).astype(np.int32)
        except Exception as e:
            qwen_err = f"{type(e).__name__}: {e}"

    out: dict[str, Any] = {
        "qwen": {
            "quad": None if qwen_quad is None else qwen_quad.astype(int).tolist(),
            "error": qwen_err,
        },
        "cv": {
            "quad": None if cv_quad is None else cv_quad.astype(int).tolist(),
            "error": None,
        },
    }
    return out


def _pdf_to_images(pdf_path: str, pages_dir: str) -> int:
    _ensure_dir(pages_dir)
    with open(pdf_path, "rb") as f:
        data = f.read()

    doc = fitz.open(stream=data, filetype="pdf")
    page_count = doc.page_count
    if page_count <= 0:
        raise ValueError("empty pdf")

    zoom = 2.0  # ~144 dpi -> ~288 dpi
    mat = fitz.Matrix(zoom, zoom)

    for i in range(page_count):
        page = doc.load_page(i)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        out_path = os.path.join(pages_dir, f"{i + 1}.png")
        pix.save(out_path)

    return page_count


@app.post("/api/runs")
async def create_run(file: UploadFile = File(...)) -> dict[str, Any]:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF is supported")

    _ensure_dir(RUNS_ROOT)
    run_id = _make_run_id()
    run_dir = _run_dir(run_id)

    pages_dir = os.path.join(run_dir, "pages")
    masks_dir = os.path.join(run_dir, "masks")
    _ensure_dir(pages_dir)
    _ensure_dir(masks_dir)

    pdf_path = os.path.join(run_dir, "input.pdf")
    content = await file.read()
    with open(pdf_path, "wb") as f:
        f.write(content)

    # Load env from repo root .env (optional)
    qwen._load_env_file(os.path.join(_REPO_ROOT, ".env"))

    base_url = qwen._default_base_url("cn")
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    model = (
        os.getenv("DASHSCOPE_MODEL", qwen.DEFAULT_MODEL).strip() or qwen.DEFAULT_MODEL
    )

    page_count = _pdf_to_images(pdf_path, pages_dir=pages_dir)

    for page_number in range(1, page_count + 1):
        img_path = _page_image_path(run_id, page_number)
        img = cv2.imread(img_path)
        if img is None:
            continue

        # IMPORTANT: do NOT call Qwen for every page on upload.
        # We only compute CV candidate now; Qwen candidate is computed on-demand
        # when user opens a page in the UI.
        candidates = _make_candidates(
            img=img,
            api_key="",
            base_url=base_url,
            model=model,
            json_mode=False,
            timeout_s=120.0,
            max_tokens=512,
        )
        candidates["qwen"]["error"] = "skipped_on_upload"

        meta = {
            "page_number": page_number,
            "image": img_path,
            "candidates": candidates,
            "label": None,
            "status": "pending",
        }
        _write_json(_page_meta_path(run_id, page_number), meta)

        # Save a visualization for humans (not required by API)
        vis = img
        if candidates.get("qwen", {}).get("quad") is not None:
            vis = _draw_quad(
                vis, np.array(candidates["qwen"]["quad"], dtype=np.float32), (255, 0, 0)
            )
        if candidates.get("cv", {}).get("quad") is not None:
            vis = _draw_quad(
                vis, np.array(candidates["cv"]["quad"], dtype=np.float32), (0, 255, 0)
            )
        cv2.imwrite(os.path.join(run_dir, "pages", f"{page_number}_viz.png"), vis)

    return {"run_id": run_id}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    run_dir = _run_dir(run_id)
    if not os.path.isdir(run_dir):
        raise HTTPException(status_code=404, detail="Run not found")

    pages_dir = os.path.join(run_dir, "pages")
    pages = []
    for name in sorted(os.listdir(pages_dir)):
        if not name.endswith(".json"):
            continue
        meta = _read_json(os.path.join(pages_dir, name))
        pages.append(
            {
                "page_number": meta.get("page_number"),
                "status": meta.get("status"),
            }
        )

    return {"run_id": run_id, "pages": pages}


@app.get("/api/runs/{run_id}/pages")
def list_pages(run_id: str) -> dict[str, Any]:
    run_dir = _run_dir(run_id)
    pages_dir = os.path.join(run_dir, "pages")
    if not os.path.isdir(pages_dir):
        raise HTTPException(status_code=404, detail="Run not found")

    pages: list[dict[str, Any]] = []
    for name in sorted(os.listdir(pages_dir)):
        if not name.endswith(".json"):
            continue
        meta = _read_json(os.path.join(pages_dir, name))
        pn_raw = meta.get("page_number")
        if pn_raw is None:
            continue
        pn = int(pn_raw)
        pages.append(
            {
                "page_number": pn,
                "status": meta.get("status", "pending"),
            }
        )

    return {"pages": pages}


@app.get("/api/runs/{run_id}/pages/{page_number}/image")
def get_page_image(run_id: str, page_number: int) -> FileResponse:
    path = _page_image_path(run_id, page_number)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(path, media_type="image/png")


@app.get("/api/runs/{run_id}/pages/{page_number}/viz")
def get_page_viz(run_id: str, page_number: int) -> dict[str, Any]:
    meta_path = _page_meta_path(run_id, page_number)
    if not os.path.isfile(meta_path):
        raise HTTPException(status_code=404, detail="Page not found")

    meta = _read_json(meta_path)
    c = meta.get("candidates", {})

    # Compute Qwen candidate on-demand (network call) to avoid paying the
    # cost for all pages upfront.
    qwen_part = c.get("qwen", {}) if isinstance(c, dict) else {}
    qwen_quad = qwen_part.get("quad") if isinstance(qwen_part, dict) else None
    qwen_err = qwen_part.get("error") if isinstance(qwen_part, dict) else None

    if qwen_quad is None and qwen_err == "skipped_on_upload":
        qwen._load_env_file(os.path.join(_REPO_ROOT, ".env"))
        api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
        model = (
            os.getenv("DASHSCOPE_MODEL", qwen.DEFAULT_MODEL).strip()
            or qwen.DEFAULT_MODEL
        )
        if api_key:
            img_path = _page_image_path(run_id, page_number)
            img = cv2.imread(img_path)
            if img is not None:
                candidates_new = _make_candidates(
                    img=img,
                    api_key=api_key,
                    base_url=qwen._default_base_url("cn"),
                    model=model,
                    json_mode=False,
                    timeout_s=120.0,
                    max_tokens=512,
                )
                if isinstance(c, dict):
                    c["qwen"] = candidates_new.get("qwen", {})
                    meta["candidates"] = c
                    _write_json(meta_path, meta)

    # Build candidate list for UI drawing: [qwen, cv]
    candidates: list[list[list[int]]] = []
    c = meta.get("candidates", {})
    if isinstance(c, dict):
        q = c.get("qwen", {}).get("quad")
        if isinstance(q, list):
            candidates.append(q)
        cvq = c.get("cv", {}).get("quad")
        if isinstance(cvq, list):
            candidates.append(cvq)

    return {
        "candidates": candidates,
        "status": meta.get("status"),
        "label": meta.get("label"),
    }


@app.post("/api/runs/{run_id}/pages/{page_number}/label")
async def save_label(
    run_id: str, page_number: int, payload: dict[str, Any]
) -> dict[str, Any]:
    meta_path = _page_meta_path(run_id, page_number)
    if not os.path.isfile(meta_path):
        raise HTTPException(status_code=404, detail="Page not found")

    points = payload.get("points")
    if not isinstance(points, list) or len(points) != 4:
        raise HTTPException(status_code=400, detail="points must be 4 points")

    pts: list[list[float]] = []
    for p in points:
        if not isinstance(p, list) or len(p) < 2:
            raise HTTPException(status_code=400, detail="invalid point")
        pts.append([float(p[0]), float(p[1])])

    img_path = _page_image_path(run_id, page_number)
    img = cv2.imread(img_path)
    if img is None:
        raise HTTPException(status_code=500, detail="failed to read image")

    h, w = img.shape[:2]
    quad = _order_quad_tl_tr_br_bl(np.array(pts, dtype=np.float32))
    quad = _clamp_points(quad, w=w, h=h)

    meta = _read_json(meta_path)
    meta["label"] = {"quad": quad.astype(float).tolist()}
    meta["status"] = "labelled"
    _write_json(meta_path, meta)

    out = _draw_quad(img, quad, (0, 0, 255))
    mask_path = _page_mask_path(run_id, page_number)
    _ensure_dir(os.path.dirname(mask_path))
    cv2.imwrite(mask_path, out, [cv2.IMWRITE_PNG_COMPRESSION, 3])

    return {"ok": True, "mask": f"/api/runs/{run_id}/pages/{page_number}/mask"}


@app.get("/api/runs/{run_id}/pages/{page_number}/mask")
def get_page_mask(run_id: str, page_number: int) -> FileResponse:
    path = _page_mask_path(run_id, page_number)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Mask not found")
    return FileResponse(path, media_type="image/png")
