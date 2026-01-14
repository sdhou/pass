#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path

from pdf2image import convert_from_path


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def list_pdf_files(pdf_dir: Path) -> list[Path]:
    return sorted(
        [p for p in pdf_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"]
    )


def convert_pdf_to_images(pdf_path: Path, img_root: Path, *, dpi: int) -> int:
    images = convert_from_path(str(pdf_path), dpi=dpi)

    ensure_directory(img_root)

    prefix = pdf_path.stem
    for i, image in enumerate(images, 1):
        output_path = img_root / f"{prefix}_page_{i}.png"
        image.save(output_path, "PNG")

    return len(images)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="将PDF转换成图片")
    parser.add_argument("--pdf-dir", default="pdf", help="PDF目录（默认：pdf）")
    parser.add_argument("--img-dir", default="img", help="输出图片目录（默认：img）")
    parser.add_argument("--dpi", type=int, default=300, help="转换DPI（默认：300）")
    parser.add_argument(
        "pdf_path", nargs="?", help="可选：单个PDF路径（优先于 --pdf-dir）"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    img_root = Path(args.img_dir)

    if args.pdf_path:
        pdf_path = Path(args.pdf_path)
        if not pdf_path.exists() or not pdf_path.is_file():
            print(f"错误: 找不到PDF文件 {pdf_path}")
            return 1

        print(f"正在转换PDF: {pdf_path}")
        page_count = convert_pdf_to_images(pdf_path, img_root, dpi=args.dpi)
        print(f"共转换 {page_count} 页")
        print(f"\n✓ 完成! 共保存 {page_count} 张图片到 {img_root}/")
        return 0

    pdf_dir = Path(args.pdf_dir)
    if not pdf_dir.exists() or not pdf_dir.is_dir():
        print(f"错误: 找不到PDF目录 {pdf_dir}")
        return 1

    pdf_files = list_pdf_files(pdf_dir)
    if not pdf_files:
        print(f"未找到PDF文件: {pdf_dir}/")
        return 0

    total_pdfs = 0
    total_pages = 0

    for pdf_path in pdf_files:
        print(f"正在转换PDF: {pdf_path}")
        page_count = convert_pdf_to_images(pdf_path, img_root, dpi=args.dpi)
        print(f"共转换 {page_count} 页，输出到 {img_root}/")
        total_pdfs += 1
        total_pages += page_count

    print(
        f"\n✓ 完成! 共处理 {total_pdfs} 个PDF，保存 {total_pages} 张图片到 {img_root}/"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
