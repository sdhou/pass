#!/usr/bin/env python3
"""
背景删除脚本
删除 img/ 目录下每页护照图片的多余背景
"""

import os
import glob
import cv2
import numpy as np
from PIL import Image


def remove_background(image_path, border_size=50):
    """删除多余背景，保留护照主体"""
    print(f"正在处理: {image_path}")

    # 读取图片
    image = Image.open(image_path)

    # 转换为numpy数组
    img_array = np.array(image)
    img_cv = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)

    # 转换为灰度图
    gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)

    # 二值化
    _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)

    # 形态学操作，去除噪声
    kernel = np.ones((5, 5), np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)

    # 查找轮廓
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if contours:
        # 找到最大的轮廓（假设是护照）
        max_contour = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(max_contour)

        # 添加边距
        x = max(0, x - border_size)
        y = max(0, y - border_size)
        w = min(img_array.shape[1] - x, w + 2 * border_size)
        h = min(img_array.shape[0] - y, h + 2 * border_size)

        # 裁剪图片
        cropped = img_array[y:y+h, x:x+w]
        print(f"  裁剪区域: ({x}, {y}, {w}, {h})")

        # 保存裁剪后的图片
        result_image = Image.fromarray(cropped)
        result_image.save(image_path, 'PNG', quality=95)
        print(f"  已保存: {image_path}")
    else:
        print("  未找到明显轮廓，保持原样")


def remove_background_all_images():
    """处理img目录下所有图片"""
    # 获取所有PNG图片
    image_files = sorted(glob.glob('img/*.png'))

    if not image_files:
        print("错误: img/ 目录下没有找到图片文件")
        print("请先运行 split.py 将PDF转换为图片")
        return

    print(f"找到 {len(image_files)} 张图片")
    print("\n===== 开始删除多余背景 =====\n")

    for image_path in image_files:
        remove_background(image_path)
        print()

    print(f"✓ 完成! 共处理 {len(image_files)} 张图片")


if __name__ == '__main__':
    remove_background_all_images()
