#!/usr/bin/env python3
"""
PDF转图片脚本
将护照 pdf/1.pdf 每页转成图片存入 img/ 目录下
"""

import os
import sys
from pdf2image import convert_from_path


def ensure_img_directory():
    """确保img目录存在"""
    if not os.path.exists('img'):
        os.makedirs('img')
        print("已创建 img/ 目录")


def convert_pdf_to_images(pdf_path='pdf/1.pdf'):
    """将PDF每页转换为图片并保存到img目录"""
    if not os.path.exists(pdf_path):
        print(f"错误: 找不到文件 {pdf_path}")
        sys.exit(1)

    # 确保输出目录存在
    ensure_img_directory()

    print(f"正在转换PDF: {pdf_path}")
    # 转换PDF为图片，设置300 DPI以保证质量
    images = convert_from_path(pdf_path, dpi=300)
    print(f"共转换 {len(images)} 页")

    # 保存每一页图片
    for i, image in enumerate(images, 1):
        output_path = f'img/page_{i}.png'
        image.save(output_path, 'PNG')
        print(f"已保存: {output_path}")

    print(f"\n✓ 完成! 共保存 {len(images)} 张图片到 img/ 目录")


if __name__ == '__main__':
    convert_pdf_to_images()
