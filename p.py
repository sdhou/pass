#!/usr/bin/env python3
"""
护照图片处理脚本
Passport Image Processor

功能:
1. 检测护照边框
2. 校正倾斜角度
3. 移除背景
4. 透视变换拉正护照

依赖安装:
pip install opencv-python-headless numpy --break-system-packages
"""

import argparse
import os

import cv2
import numpy as np


def find_passport_contour(img, is_dark=False):
    """
    检测护照轮廓

    参数:
        img: 输入图像
        is_dark: 是否为深色护照（如封面）
    返回:
        最大轮廓或None
    """
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    # 使用Canny边缘检测
    edges = cv2.Canny(blurred, 30, 100)

    # 膨胀边缘使其连接
    kernel = np.ones((5, 5), np.uint8)
    edges = cv2.dilate(edges, kernel, iterations=2)

    # 找轮廓
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return None

    # 找最大轮廓
    largest = max(contours, key=cv2.contourArea)

    # 如果轮廓面积太小，可能检测失败
    if cv2.contourArea(largest) < (h * w * 0.1):
        return None

    return largest


def order_points(pts):
    """
    按顺序排列四个角点: 左上、右上、右下、左下

    参数:
        pts: 四个点的数组
    返回:
        排序后的点数组
    """
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]  # 左上
    rect[2] = pts[np.argmax(s)]  # 右下
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]  # 右上
    rect[3] = pts[np.argmax(diff)]  # 左下
    return rect


def perspective_transform(img, pts):
    """
    透视变换，将护照拉正

    参数:
        img: 输入图像
        pts: 四个角点
    返回:
        变换后的图像
    """
    rect = order_points(pts.astype(np.float32))
    (tl, tr, br, bl) = rect

    # 计算新图像的宽度
    widthA = np.sqrt(((br[0] - bl[0]) ** 2) + ((br[1] - bl[1]) ** 2))
    widthB = np.sqrt(((tr[0] - tl[0]) ** 2) + ((tr[1] - tl[1]) ** 2))
    maxWidth = max(int(widthA), int(widthB))

    # 计算新图像的高度
    heightA = np.sqrt(((tr[0] - br[0]) ** 2) + ((tr[1] - br[1]) ** 2))
    heightB = np.sqrt(((tl[0] - bl[0]) ** 2) + ((tl[1] - bl[1]) ** 2))
    maxHeight = max(int(heightA), int(heightB))

    # 目标点
    dst = np.array(
        [[0, 0], [maxWidth - 1, 0], [maxWidth - 1, maxHeight - 1], [0, maxHeight - 1]],
        dtype=np.float32,
    )

    # 透视变换矩阵
    M = cv2.getPerspectiveTransform(rect, dst)

    # 执行透视变换
    warped = cv2.warpPerspective(img, M, (maxWidth, maxHeight))

    return warped


def get_bounding_box_crop(img):
    """
    使用边界框裁剪图像

    参数:
        img: 输入图像
    返回:
        裁剪后的图像和边界框
    """
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 30, 100)
    kernel = np.ones((5, 5), np.uint8)
    edges = cv2.dilate(edges, kernel, iterations=2)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return img, None

    largest = max(contours, key=cv2.contourArea)
    x, y, bw, bh = cv2.boundingRect(largest)

    # 添加小边距
    margin = 5
    x = max(0, x - margin)
    y = max(0, y - margin)
    bw = min(w - x, bw + 2 * margin)
    bh = min(h - y, bh + 2 * margin)

    cropped = img[y : y + bh, x : x + bw]
    return cropped, (x, y, bw, bh)


def process_passport_cover(input_path, output_path):
    """
    处理护照封面（深色，垂直方向）

    参数:
        input_path: 输入图片路径
        output_path: 输出图片路径
    返回:
        处理是否成功
    """
    print(f"\n处理护照封面: {os.path.basename(input_path)}")

    img = cv2.imread(input_path)
    if img is None:
        print(f"  错误：无法读取图片")
        return False

    h, w = img.shape[:2]
    print(f"  原始尺寸: {w}x{h}")

    # 找护照轮廓
    contour = find_passport_contour(img, is_dark=True)

    if contour is not None:
        # 获取最小外接矩形的角点
        rect = cv2.minAreaRect(contour)
        box = cv2.boxPoints(rect)
        box = np.int32(box)

        # 透视变换
        result = perspective_transform(img, box)
        rh, rw = result.shape[:2]

        # 封面应该是竖向（高>宽）
        if rw > rh:
            result = cv2.rotate(result, cv2.ROTATE_90_CLOCKWISE)
            rh, rw = result.shape[:2]
            print(f"  旋转90度使封面竖向")

        print(f"  输出尺寸: {rw}x{rh}")
    else:
        print(f"  使用边界框裁剪")
        result, bbox = get_bounding_box_crop(img)
        if bbox:
            print(f"  裁剪区域: {bbox}")

    cv2.imwrite(output_path, result, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    return True


def process_passport_pages(input_path, output_path):
    """
    处理护照内页（横向，包含两页）

    参数:
        input_path: 输入图片路径
        output_path: 输出图片路径
    返回:
        处理是否成功
    """
    print(f"\n处理护照内页: {os.path.basename(input_path)}")

    img = cv2.imread(input_path)
    if img is None:
        print(f"  错误：无法读取图片")
        return False

    h, w = img.shape[:2]
    print(f"  原始尺寸: {w}x{h}")

    # 找护照轮廓
    contour = find_passport_contour(img)

    if contour is not None:
        area = cv2.contourArea(contour)
        print(f"  检测到轮廓，面积: {area}")

        # 获取最小外接矩形的角点
        rect = cv2.minAreaRect(contour)
        box = cv2.boxPoints(rect)
        box = np.int32(box)

        # 透视变换
        result = perspective_transform(img, box)
        rh, rw = result.shape[:2]

        # 内页应该是横向（宽>高）
        if rh > rw:
            result = cv2.rotate(result, cv2.ROTATE_90_CLOCKWISE)
            rh, rw = result.shape[:2]
            print(f"  旋转90度使内页横向")

        print(f"  输出尺寸: {rw}x{rh}")
    else:
        print(f"  使用边界框裁剪")
        result, bbox = get_bounding_box_crop(img)
        if bbox:
            rh, rw = result.shape[:2]
            # 确保横向
            if rh > rw:
                result = cv2.rotate(result, cv2.ROTATE_90_CLOCKWISE)
            print(f"  裁剪区域: {bbox}")

    cv2.imwrite(output_path, result, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    return True


def main():
    """
    主函数
    """
    # 解析命令行参数
    parser = argparse.ArgumentParser(
        description="护照图片处理 - Passport Image Processor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python p.py --input ./uploads --output ./outputs
  python p.py -i /path/to/input -o /path/to/output
        """,
    )
    parser.add_argument("-i", "--input", required=True, help="输入图片目录路径")
    parser.add_argument("-o", "--output", required=True, help="输出图片目录路径")
    args = parser.parse_args()

    print("=" * 60)
    print("护照图片处理")
    print("Passport Image Processor")
    print("=" * 60)
    print("\n功能: 方向校正 + 背景移除 + 透视变换")

    # 从命令行参数获取路径
    input_dir = args.input
    output_dir = args.output

    print(f"\n输入目录: {input_dir}")
    print(f"输出目录: {output_dir}")

    os.makedirs(output_dir, exist_ok=True)

    # 处理文件
    files_to_process = [
        ("page_1.png", "page_1_final.png", "cover"),
        ("page_4.png", "page_4_final.png", "pages"),
        ("page_6.png", "page_6_final.png", "pages"),
    ]

    for input_name, output_name, page_type in files_to_process:
        input_path = os.path.join(input_dir, input_name)
        output_path = os.path.join(output_dir, output_name)

        if not os.path.exists(input_path):
            print(f"\n跳过 {input_name}: 文件不存在")
            continue

        if page_type == "cover":
            process_passport_cover(input_path, output_path)
        else:
            process_passport_pages(input_path, output_path)

    print("\n" + "=" * 60)
    print("处理完成!")
    print("=" * 60)

    # 显示输出文件信息
    print("\n输出文件:")
    for _, output_name, _ in files_to_process:
        output_path = os.path.join(output_dir, output_name)
        if os.path.exists(output_path):
            img = cv2.imread(output_path)
            if img is not None:
                h, w = img.shape[:2]
                size_kb = os.path.getsize(output_path) / 1024
                print(f"  {output_name}: {w}x{h} 像素, {size_kb:.1f} KB")


if __name__ == "__main__":
    main()
