#!/usr/bin/env python3
"""
护照图片处理脚本
Passport Image Processor

功能:
1. 检测并删除深色封皮（首页和底页）
2. 精细角度校正（不仅仅是90度旋转）
3. 透视变换拉正护照
4. 安全裁剪背景（不切到护照内容）

依赖安装:
pip install opencv-python-headless numpy --break-system-packages
"""

import argparse
import os

import cv2
import numpy as np


def is_dark_cover(img):
    """
    检测是否为深色封皮（首页或底页）

    封皮特征：
    1. 深色占主导（平均亮度低）
    2. 颜色饱和度低（接近黑色）
    3. 面积相对较小（单本护照 vs 双页展开）

    参数:
        img: 输入图像
    返回:
        True 表示是深色封皮，False 表示是内页
    """
    h, w = img.shape[:2]

    # 转换为HSV颜色空间
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    # 检测护照区域（非白色背景区域）
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 白色背景阈值
    _, bg_mask = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)

    # 护照区域（非白色区域）
    passport_mask = cv2.bitwise_not(bg_mask)

    # 形态学操作清理mask
    kernel = np.ones((15, 15), np.uint8)
    passport_mask = cv2.morphologyEx(passport_mask, cv2.MORPH_CLOSE, kernel)
    passport_mask = cv2.morphologyEx(passport_mask, cv2.MORPH_OPEN, kernel)

    # 找护照区域轮廓
    contours, _ = cv2.findContours(
        passport_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    if not contours:
        return False

    # 获取最大轮廓
    largest = max(contours, key=cv2.contourArea)
    passport_area = cv2.contourArea(largest)

    # 创建护照区域mask
    roi_mask = np.zeros((h, w), dtype=np.uint8)
    cv2.drawContours(roi_mask, [largest], -1, 255, -1)

    # 计算护照区域的平均亮度
    v_channel = hsv[:, :, 2]
    passport_pixels = v_channel[roi_mask > 0]

    if len(passport_pixels) == 0:
        return False

    avg_brightness = np.mean(passport_pixels)
    dark_ratio = np.sum(passport_pixels < 80) / len(passport_pixels)

    # 获取护照的宽高比
    rect = cv2.minAreaRect(largest)
    rect_w, rect_h = rect[1]
    aspect_ratio = max(rect_w, rect_h) / (min(rect_w, rect_h) + 1)

    # 计算护照区域相对于整个图像的面积比例
    img_area = h * w
    area_ratio = passport_area / img_area

    print(f"    亮度分析: 平均亮度={avg_brightness:.1f}, 暗色比例={dark_ratio:.2f}")
    print(f"    几何分析: 面积比={area_ratio:.3f}, 宽高比={aspect_ratio:.2f}")

    # 封皮判断条件：
    # 1. 平均亮度低于80 或 暗色像素占比超过70%
    # 2. 宽高比接近护照封面（约1.4左右）
    # 3. 面积较小（单本护照通常占图像面积的20%以下）
    is_dark = avg_brightness < 80 or dark_ratio > 0.70
    is_small_area = area_ratio < 0.35  # 内页展开通常面积更大
    is_cover_aspect = aspect_ratio < 2.0  # 封面宽高比小于2

    # 综合判断
    if is_dark and is_small_area and is_cover_aspect:
        return True

    # 如果非常暗，即使面积大一点也认为是封皮
    if avg_brightness < 50 and dark_ratio > 0.85:
        return True

    return False


def find_passport_contour(img):
    """
    检测护照轮廓

    参数:
        img: 输入图像
    返回:
        最大轮廓或None
    """
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    # 使用Canny边缘检测
    edges = cv2.Canny(blurred, 30, 100)

    # 使用更大的kernel和更多迭代次数来连接分散的边缘
    kernel = np.ones((15, 15), np.uint8)
    edges = cv2.dilate(edges, kernel, iterations=5)

    # 闭运算填充内部空隙
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=3)

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


def detect_fine_angle(img):
    """
    使用霍夫变换检测图像中的主要线条方向，计算精细的旋转角度

    参数:
        img: 输入图像
    返回:
        需要旋转的角度（度）
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 边缘检测
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)

    # 霍夫线变换检测线条
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180, threshold=100, minLineLength=100, maxLineGap=10
    )

    if lines is None:
        return 0

    angles = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        # 计算线条角度
        angle = np.arctan2(y2 - y1, x2 - x1) * 180 / np.pi

        # 只考虑接近水平或垂直的线条
        # 水平线：角度接近0度或180度
        # 垂直线：角度接近90度或-90度
        if abs(angle) < 30 or abs(angle) > 150:
            # 接近水平的线
            if angle > 90:
                angle -= 180
            elif angle < -90:
                angle += 180
            angles.append(angle)
        elif 60 < abs(angle) < 120:
            # 接近垂直的线，转换为水平偏移
            if angle > 0:
                angles.append(angle - 90)
            else:
                angles.append(angle + 90)

    if not angles:
        return 0

    # 使用中位数避免异常值影响
    median_angle = np.median(angles)

    # 限制旋转角度在合理范围内
    if abs(median_angle) > 15:
        return 0  # 角度过大可能是误检测

    return median_angle


def detect_text_regions(gray):
    """
    检测图像中的文字区域

    参数:
        gray: 灰度图像
    返回:
        二值化的文字区域mask
    """
    # 使用自适应阈值
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2
    )

    # 形态学操作连接文字
    kernel_h = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 1))
    kernel_v = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 15))

    # 水平连接
    dilated = cv2.dilate(binary, kernel_h, iterations=2)
    # 垂直方向轻微连接
    dilated = cv2.dilate(dilated, kernel_v, iterations=1)

    return dilated


def detect_page_number_position(img, debug=False):
    """
    检测页码数字的位置，用于确定护照方向

    页码特征：
    1. 小的数字字符（1-3位）
    2. 通常在护照边缘位置
    3. 当护照横置时，页码应该是竖直方向

    参数:
        img: 输入图像
        debug: 是否打印调试信息
    返回:
        "bottom", "top", "left", "right", 或 None
    """
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 二值化 - 检测深色文字
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # 查找连通组件（可能的文字区域）
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        binary, connectivity=8
    )

    # 筛选可能的页码数字
    # 页码通常是小的矩形区域
    page_number_candidates = []

    for i in range(1, num_labels):  # 跳过背景（标签0）
        x, y, comp_w, comp_h, area = stats[i]

        # 页码特征过滤
        # 1. 面积适中（不能太大也不能太小）
        min_area = (h * w) / 50000  # 相对于图像大小的最小面积
        max_area = (h * w) / 500  # 相对于图像大小的最大面积

        if area < min_area or area > max_area:
            continue

        # 2. 宽高比合理（数字通常高度大于宽度，但不会过于极端）
        aspect_ratio = comp_h / (comp_w + 1)
        if aspect_ratio < 0.3 or aspect_ratio > 5:
            continue

        # 3. 尺寸合理
        if comp_w < 5 or comp_h < 10:
            continue

        page_number_candidates.append(
            {"x": x, "y": y, "w": comp_w, "h": comp_h, "area": area, "cx": x + comp_w / 2, "cy": y + comp_h / 2}
        )

    if not page_number_candidates:
        return None

    # 分析候选区域的位置分布
    # 计算各个边缘区域的候选数量和密度
    edge_size = min(h, w) // 8

    # 定义四个边缘区域
    regions = {
        "bottom": [c for c in page_number_candidates if c["cy"] > h - edge_size],
        "top": [c for c in page_number_candidates if c["cy"] < edge_size],
        "left": [c for c in page_number_candidates if c["cx"] < edge_size],
        "right": [c for c in page_number_candidates if c["cx"] > w - edge_size],
    }

    # 计算每个区域的得分（候选数量）
    scores = {region: len(candidates) for region, candidates in regions.items()}

    if debug:
        print(f"    页码候选数量: {len(page_number_candidates)}")
        print(f"    区域分布: bottom={scores['bottom']}, top={scores['top']}, "
              f"left={scores['left']}, right={scores['right']}")

    # 找到候选最多的区域
    max_region = max(scores, key=scores.get)
    max_score = scores[max_region]

    # 如果某个区域有明显的候选聚集，返回该区域
    if max_score > 0:
        return max_region

    return None


def detect_mrz_position(img, debug=False):
    """
    检测MRZ（机读区）的位置，用于确定护照方向

    MRZ特征：
    1. 由两行或三行密集的等宽字符组成
    2. 位于护照底部
    3. 水平方向排列

    使用投影分析法：
    - 将图像二值化后，计算水平和垂直投影
    - MRZ区域在水平投影中会形成明显的密集行
    - 通过比较不同方向的投影来确定方向

    参数:
        img: 输入图像
        debug: 是否打印调试信息
    返回:
        "bottom", "top", "left", "right", 或 None
    """
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 二值化
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # 计算水平投影（每行的像素和）
    h_proj = np.sum(binary, axis=1)
    # 计算垂直投影（每列的像素和）
    v_proj = np.sum(binary, axis=0)

    # 分析投影分布
    # MRZ区域应该有连续的高投影值

    # 分析水平投影的底部和顶部
    h_size = h // 5
    bottom_h_proj = np.mean(h_proj[h - h_size :])
    top_h_proj = np.mean(h_proj[:h_size])

    # 分析垂直投影的左侧和右侧
    w_size = w // 5
    left_v_proj = np.mean(v_proj[:w_size])
    right_v_proj = np.mean(v_proj[w - w_size :])

    if debug:
        print(
            f"    投影分析: bottom_h={bottom_h_proj:.1f}, top_h={top_h_proj:.1f}, "
            f"left_v={left_v_proj:.1f}, right_v={right_v_proj:.1f}"
        )

    # 选择投影值最高的区域
    values = {
        "bottom": bottom_h_proj,
        "top": top_h_proj,
        "left": left_v_proj,
        "right": right_v_proj,
    }

    max_region = max(values, key=values.get)
    max_val = values[max_region]

    # 计算平均值
    avg_val = sum(values.values()) / len(values)

    # 如果最高值明显高于平均值，则返回该区域
    if max_val > avg_val * 1.15:
        return max_region

    return None


def correct_orientation(img):
    """
    校正护照方向，确保是横置且内容正向

    策略：
    1. 先进行精细角度校正（微调角度，不只是简单90度旋转）
    2. 确保横置（宽 > 高）
    3. 优先根据页码数字位置判断方向，页码应该是竖直方向且摆正
    4. 页码可以在左侧或右侧（顶部或底部在竖直方向上）
    5. 如果找不到页码，使用MRZ判断方向（MRZ应在底部）

    参数:
        img: 输入图像
    返回:
        校正后的图像
    """
    h, w = img.shape[:2]

    # 首先进行精细角度校正（微调）
    fine_angle = detect_fine_angle(img)

    if abs(fine_angle) > 0.5:
        print(f"    精细角度校正: {fine_angle:.2f}°")
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, fine_angle, 1.0)

        # 计算旋转后的画布大小
        cos = np.abs(M[0, 0])
        sin = np.abs(M[0, 1])
        new_w = int((h * sin) + (w * cos))
        new_h = int((h * cos) + (w * sin))

        # 调整旋转矩阵
        M[0, 2] += (new_w - w) / 2
        M[1, 2] += (new_h - h) / 2

        img = cv2.warpAffine(img, M, (new_w, new_h), borderMode=cv2.BORDER_REPLICATE)
        h, w = img.shape[:2]

    # 步骤1: 如果是竖向（h > w），先检测页码或MRZ位置决定旋转方向
    if h > w:
        # 优先使用页码检测
        page_num_position = detect_page_number_position(img, debug=True)

        if page_num_position:
            print(f"    图像竖向，检测到页码位置: {page_num_position}")

            if page_num_position == "left":
                # 页码在图像左侧，逆时针旋转90度使页码在左侧保持竖直
                print("    逆时针旋转90度（页码在左侧）")
                img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
            elif page_num_position == "right":
                # 页码在图像右侧，顺时针旋转90度使页码在右侧保持竖直
                print("    顺时针旋转90度（页码在右侧）")
                img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
            elif page_num_position == "top":
                # 页码在图像顶部，逆时针旋转90度使页码到左侧竖直
                print("    逆时针旋转90度（页码在顶部→左侧）")
                img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
            elif page_num_position == "bottom":
                # 页码在图像底部，顺时针旋转90度使页码到右侧竖直
                print("    顺时针旋转90度（页码在底部→右侧）")
                img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
        else:
            # 页码检测失败，使用MRZ检测
            mrz_position = detect_mrz_position(img)
            print(f"    未检测到页码，使用MRZ位置: {mrz_position}")

            if mrz_position == "left":
                # MRZ在图像左侧，顺时针旋转90度使MRZ到底部
                print("    顺时针旋转90度（MRZ在左侧→底部）")
                img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
            elif mrz_position == "right":
                # MRZ在图像右侧，逆时针旋转90度使MRZ到底部
                print("    逆时针旋转90度（MRZ在右侧→底部）")
                img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
            elif mrz_position == "top":
                # MRZ在图像顶部，逆时针旋转90度
                print("    逆时针旋转90度（MRZ在顶部）")
                img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
            elif mrz_position == "bottom":
                # MRZ在图像底部，顺时针旋转90度
                print("    顺时针旋转90度（MRZ在底部）")
                img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
            else:
                # 默认顺时针旋转
                print("    默认顺时针旋转90度使内页横置")
                img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)

        h, w = img.shape[:2]

    # 步骤2: 现在图像是横向的，检测是否需要180度翻转
    # 使用MRZ判断（MRZ应该在底部），页码可以在左侧或右侧（顶部或底部均可）
    mrz_position = detect_mrz_position(img, debug=True)

    if mrz_position == "top":
        # MRZ在顶部，说明整页倒置，需要旋转180度
        print("    检测到MRZ在顶部，旋转180度使MRZ到底部")
        img = cv2.rotate(img, cv2.ROTATE_180)
    else:
        # MRZ位置正常或未检测到，检查页码位置
        page_num_position = detect_page_number_position(img, debug=True)

        if page_num_position:
            print(f"    横向图像，页码位置: {page_num_position}")
            # 页码在左侧或右侧是正常的（竖直方向）
            # 页码在顶部或底部也可以接受（根据需求：页码不一定在底部，也有可能在顶部）
            if page_num_position in ["left", "right"]:
                print("    页码在侧边，竖直方向，保持当前方向")
            elif page_num_position in ["top", "bottom"]:
                print(f"    页码在{page_num_position}，保持当前方向（页码可以在顶部或底部）")
        else:
            print("    未检测到明确的页码位置，保持当前方向")

    return img


def safe_crop(img, margin_percent=2):
    """
    安全裁剪，去除白色背景但保留护照完整内容

    参数:
        img: 输入图像
        margin_percent: 安全边距百分比
    返回:
        裁剪后的图像
    """
    h, w = img.shape[:2]

    # 使用灰度图检测护照区域
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 使用更低的阈值，避免浅色内容被当作背景
    _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)

    # 使用更大的kernel和更少的迭代，避免过度侵蚀
    kernel = np.ones((15, 15), np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=3)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)

    # 找轮廓
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        print("    安全裁剪: 未检测到轮廓，保留原图")
        return img

    # 合并所有较大的轮廓，而不是只取最大的
    min_area = (h * w) * 0.05  # 至少占图像5%的面积
    valid_contours = [c for c in contours if cv2.contourArea(c) > min_area]

    if not valid_contours:
        print("    安全裁剪: 没有足够大的轮廓，保留原图")
        return img

    # 合并所有有效轮廓的边界框
    all_points = []
    for contour in valid_contours:
        all_points.extend(contour.reshape(-1, 2))

    all_points = np.array(all_points)
    x, y, bw, bh = cv2.boundingRect(all_points)

    # 使用更大的安全边距
    margin_x = max(20, int(bw * margin_percent / 100))
    margin_y = max(20, int(bh * margin_percent / 100))

    # 扩展边界框
    x = max(0, x - margin_x)
    y = max(0, y - margin_y)
    x2 = min(w, x + bw + 2 * margin_x)
    y2 = min(h, y + bh + 2 * margin_y)

    # 验证裁剪是否合理（不能切掉太多）
    crop_ratio = (bw * bh) / (h * w)
    if crop_ratio < 0.1:
        print(f"    安全裁剪: 裁剪区域过小 ({crop_ratio:.1%})，保留原图")
        return img

    # 裁剪
    cropped = img[y:y2, x:x2]

    print(f"    安全裁剪: ({x}, {y}) -> ({x2}, {y2}), 边距: {margin_x}x{margin_y}px, 保留: {crop_ratio:.1%}")

    return cropped


def process_passport_page(input_path, output_path):
    """
    处理护照内页

    处理流程:
    1. 检测护照轮廓
    2. 透视变换拉正
    3. 精细角度校正
    4. 确保横置方向
    5. 安全裁剪背景

    参数:
        input_path: 输入图片路径
        output_path: 输出图片路径
    返回:
        处理是否成功
    """
    print(f"\n处理护照内页: {os.path.basename(input_path)}")

    img = cv2.imread(input_path)
    if img is None:
        print("  错误：无法读取图片")
        return False

    h, w = img.shape[:2]
    print(f"  原始尺寸: {w}x{h}")

    result = None

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
        print(f"  透视变换尺寸: {rw}x{rh}")
    else:
        print("  未检测到轮廓，使用原图")
        result = img.copy()

    # 校正方向
    result = correct_orientation(result)

    # 安全裁剪
    result = safe_crop(result)

    rh, rw = result.shape[:2]
    print(f"  输出尺寸: {rw}x{rh}")

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
  python p.py --input ./img --output ./img-out
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
    print("\n功能: 封皮删除 + 精细角度校正 + 透视变换 + 安全裁剪")

    # 从命令行参数获取路径
    input_dir = args.input
    output_dir = args.output

    print(f"\n输入目录: {input_dir}")
    print(f"输出目录: {output_dir}")

    os.makedirs(output_dir, exist_ok=True)

    # 支持的图片扩展名
    image_extensions = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"}

    # 扫描输入目录中的所有图片文件
    files_to_process = []
    for filename in sorted(os.listdir(input_dir)):
        name, ext = os.path.splitext(filename)
        if ext.lower() in image_extensions:
            files_to_process.append(filename)

    if not files_to_process:
        print("\n错误：输入目录中没有找到图片文件")
        return

    print(f"\n找到 {len(files_to_process)} 个图片文件")

    # 处理每个文件
    processed_files = []
    skipped_covers = []

    for input_name in files_to_process:
        input_path = os.path.join(input_dir, input_name)

        # 读取图像
        img = cv2.imread(input_path)
        if img is None:
            print(f"\n跳过 {input_name}: 无法读取")
            continue

        print(f"\n检测页面类型: {input_name}")

        # 检测是否为深色封皮
        if is_dark_cover(img):
            print(f"  -> 深色封皮，跳过处理")
            skipped_covers.append(input_name)
            continue

        print(f"  -> 内页，开始处理")

        # 生成输出文件名
        name, _ = os.path.splitext(input_name)
        output_name = f"{name}_final.png"
        output_path = os.path.join(output_dir, output_name)

        # 处理内页
        success = process_passport_page(input_path, output_path)

        if success:
            processed_files.append(output_name)

    print("\n" + "=" * 60)
    print("处理完成!")
    print("=" * 60)

    # 显示统计信息
    print(f"\n跳过的封皮 ({len(skipped_covers)} 个):")
    for name in skipped_covers:
        print(f"  - {name}")

    # 显示输出文件信息
    print(f"\n输出文件 ({len(processed_files)} 个):")
    for output_name in processed_files[:10]:  # 只显示前10个
        output_path = os.path.join(output_dir, output_name)
        if os.path.exists(output_path):
            img = cv2.imread(output_path)
            if img is not None:
                h, w = img.shape[:2]
                size_kb = os.path.getsize(output_path) / 1024
                print(f"  {output_name}: {w}x{h} 像素, {size_kb:.1f} KB")

    if len(processed_files) > 10:
        print(f"  ... 还有 {len(processed_files) - 10} 个文件")


if __name__ == "__main__":
    main()
