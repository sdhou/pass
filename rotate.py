#!/usr/bin/env python3
"""
图片角度调整脚本
- 护照首页/末页（黑色封面）: 竖着摆正（纵向）
- 护照中间页（内容页）: 水平摆正（横向）
"""

import os
import glob
import cv2
import numpy as np
from PIL import Image
import pytesseract


def is_cover_page(image):
    """检测是否是护照封面页（黑色封面）"""
    # 转换为numpy数组
    img_array = np.array(image)

    # 转换为灰度图
    if len(img_array.shape) == 3:
        gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    else:
        gray = img_array

    # 计算平均亮度
    mean_brightness = np.mean(gray)

    # 如果平均亮度很低（深色），很可能是封面
    # 护照封面通常是深色的（黑色、深蓝色等）
    is_dark = mean_brightness < 100  # 阈值可以调整

    return is_dark


def get_text_confidence(image):
    """获取图片的文字识别置信度，用于判断文字方向是否正确"""
    try:
        # 使用pytesseract检测图片中的文字
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)

        # 计算平均置信度（过滤掉-1的值）
        confidences = [int(conf) for conf in data['conf'] if int(conf) > 0]

        if confidences:
            avg_confidence = sum(confidences) / len(confidences)
            text_count = len([text for text in data['text'] if text.strip()])
            return avg_confidence, text_count
        else:
            return 0, 0
    except:
        return 0, 0


def find_best_rotation(image, is_cover):
    """
    尝试不同角度，找到最佳旋转角度
    - 封面页：目标是竖着（height > width）
    - 内容页：目标是水平（width > height）
    """
    angles = [0, 90, 180, 270]
    best_angle = 0
    best_score = -1

    width, height = image.size

    for angle in angles:
        rotated = image.rotate(angle, expand=True, fillcolor='white')
        rot_width, rot_height = rotated.size

        # 根据页面类型计算得分
        if is_cover:
            # 封面页：竖着摆正（height > width）
            aspect_ratio = rot_height / rot_width if rot_width > 0 else 0
            # 纵向图片的宽高比应该 > 1
            orientation_score = aspect_ratio if aspect_ratio > 1 else 1 / aspect_ratio if aspect_ratio > 0 else 0
        else:
            # 内容页：水平摆正（width > height）
            aspect_ratio = rot_width / rot_height if rot_height > 0 else 0
            # 横向图片的宽高比应该 > 1
            orientation_score = aspect_ratio if aspect_ratio > 1 else 1 / aspect_ratio if aspect_ratio > 0 else 0

        # 尝试OCR检测文字置信度
        try:
            confidence, text_count = get_text_confidence(rotated)
            # 综合评分：方向得分 + OCR置信度
            score = orientation_score * 100 + confidence * 0.5 + text_count * 0.1
        except:
            # 如果OCR失败，只用方向得分
            score = orientation_score * 100

        if score > best_score:
            best_score = score
            best_angle = angle

    return best_angle


def detect_and_rotate_image(image_path):
    """智能检测页面类型并旋转到正确方向"""
    print(f"正在处理: {image_path}")

    # 读取图片
    image = Image.open(image_path)
    original_width, original_height = image.size

    # 检测页面类型
    is_cover = is_cover_page(image)
    page_type = "封面页" if is_cover else "内容页"
    target_orientation = "竖向" if is_cover else "横向"
    print(f"  检测到: {page_type}，目标方向: {target_orientation}")

    # 找到最佳旋转角度
    best_angle = find_best_rotation(image, is_cover)

    if best_angle != 0:
        print(f"  需要旋转: {best_angle}度")
        image = image.rotate(best_angle, expand=True, fillcolor='white')
        final_width, final_height = image.size
        print(f"  原始尺寸: {original_width}x{original_height}")
        print(f"  旋转后尺寸: {final_width}x{final_height}")
    else:
        print(f"  图片方向正确，无需旋转")

    # 微调倾斜角度（针对小角度倾斜）
    image = fine_tune_rotation(image)

    # 保存旋转后的图片
    image.save(image_path, 'PNG')
    print(f"  已保存: {image_path}")

    return image


def fine_tune_rotation(image):
    """微调图片的倾斜角度（处理小角度倾斜）"""
    try:
        # 转换为OpenCV格式
        img_array = np.array(image)
        img_cv = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)

        # 转换为灰度图
        gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)

        # 边缘检测
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)

        # 使用霍夫变换检测直线
        lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=100,
                                minLineLength=100, maxLineGap=10)

        if lines is not None and len(lines) > 10:  # 需要足够的直线
            # 计算所有直线的角度
            angles = []
            for line in lines:
                x1, y1, x2, y2 = line[0]
                angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
                angles.append(angle)

            # 找到中位数角度
            median_angle = np.median(angles)

            # 调整角度到[-45, 45]范围
            if median_angle < -45:
                median_angle += 90
            elif median_angle > 45:
                median_angle -= 90

            # 如果角度偏差超过阈值，则微调
            if abs(median_angle) > 0.5:
                print(f"  微调倾斜角度: {median_angle:.2f}度")
                image = image.rotate(-median_angle, expand=True, fillcolor='white')
    except Exception as e:
        # 微调失败不影响主流程
        pass

    return image


def rotate_all_images():
    """处理img目录下所有图片"""
    # 获取所有PNG图片
    image_files = sorted(glob.glob('img/*.png'))

    if not image_files:
        print("错误: img/ 目录下没有找到图片文件")
        print("请先运行 split.py 将PDF转换为图片")
        return

    print(f"找到 {len(image_files)} 张图片")
    print("\n===== 开始调整图片角度 =====\n")

    for image_path in image_files:
        detect_and_rotate_image(image_path)
        print()

    print(f"✓ 完成! 共处理 {len(image_files)} 张图片")


if __name__ == '__main__':
    rotate_all_images()
