/**
 * 护照智能裁剪工具
 * 使用通义千问VL API识别护照边界并裁剪
 */

const API_KEY_STORAGE_KEY = "dashscope_api_key";

/**
 * 获取API Key，如果没有则提示用户输入
 */
export const getApiKey = (): string | null => {
  let apiKey = localStorage.getItem(API_KEY_STORAGE_KEY);

  if (!apiKey) {
    apiKey = prompt("请输入 DashScope API Key:\n(可在 https://dashscope.console.aliyun.com/ 获取)");
    if (apiKey) {
      localStorage.setItem(API_KEY_STORAGE_KEY, apiKey);
    }
  }

  return apiKey;
};

/**
 * 清除存储的API Key
 */
export const clearApiKey = (): void => {
  localStorage.removeItem(API_KEY_STORAGE_KEY);
};

/**
 * 护照四角坐标
 */
interface PassportCorners {
  topLeft: [number, number];
  topRight: [number, number];
  bottomLeft: [number, number];
  bottomRight: [number, number];
}

/**
 * 调用通义千问VL API检测护照边界
 * 返回的是比例坐标 (0-1)，后续需要乘以图片尺寸得到像素坐标
 */
const detectPassportBoundary = async (imageBase64: string, apiKey: string): Promise<PassportCorners> => {
  // 移除 data:image/xxx;base64, 前缀
  const base64Data = imageBase64.replace(/^data:image\/\w+;base64,/, "");

  const prompt = `分析这张扫描图片，识别护照/证件文档的边界。

这是一本打开的护照扫描件，包含左右两页。请找到整个护照文档（包括所有签证页、印章）的最外层边界。

返回护照四个角在图片中的位置比例（0到1之间的小数）：
- 0 表示图片最左边/最上边
- 1 表示图片最右边/最下边

返回严格的JSON格式:
{"topLeft":[x比例,y比例],"topRight":[x比例,y比例],"bottomLeft":[x比例,y比例],"bottomRight":[x比例,y比例]}

例如：护照左上角在图片宽度30%、高度10%的位置，则 topLeft 为 [0.30, 0.10]

注意：请确保边界覆盖护照的全部内容，宁可稍微大一点也不要截掉任何护照内容。`;

  const response = await fetch("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model: "qwen-vl-max",
      messages: [
        {
          role: "user",
          content: [
            {
              type: "image_url",
              image_url: {
                url: `data:image/png;base64,${base64Data}`,
              },
            },
            {
              type: "text",
              text: prompt,
            },
          ],
        },
      ],
    }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    console.error("API 错误:", errorText);
    if (response.status === 401) {
      clearApiKey();
      throw new Error("API Key 无效，请重新输入");
    }
    throw new Error(`API 调用失败: ${response.status}`);
  }

  const data = await response.json();
  const content = data.choices?.[0]?.message?.content;

  if (!content) {
    throw new Error("API 返回内容为空");
  }

  console.log("VL API 返回:", content);

  // 尝试从返回内容中提取JSON
  const jsonMatch = content.match(/\{[\s\S]*\}/);
  if (!jsonMatch) {
    throw new Error("无法从返回内容中提取坐标JSON");
  }

  try {
    const corners = JSON.parse(jsonMatch[0]) as PassportCorners;
    // 验证坐标格式
    if (
      !corners.topLeft ||
      !corners.topRight ||
      !corners.bottomLeft ||
      !corners.bottomRight ||
      corners.topLeft.length !== 2 ||
      corners.topRight.length !== 2 ||
      corners.bottomLeft.length !== 2 ||
      corners.bottomRight.length !== 2
    ) {
      throw new Error("坐标格式不正确");
    }

    // 验证是否是比例值 (0-1)，如果值大于1则说明AI返回的是像素坐标，需要标记
    const allValues = [...corners.topLeft, ...corners.topRight, ...corners.bottomLeft, ...corners.bottomRight];
    const isRatioCoords = allValues.every((v) => v >= 0 && v <= 1);

    if (!isRatioCoords) {
      console.warn("API 返回的可能是像素坐标而非比例坐标，将尝试使用");
    }

    return corners;
  } catch {
    throw new Error("解析坐标JSON失败: " + jsonMatch[0]);
  }
};

/**
 * 计算护照底边的倾斜角度（弧度）
 * 使用底边两点计算角度，使MRZ码水平对齐
 */
const calculateRotationAngle = (bottomLeft: [number, number], bottomRight: [number, number]): number => {
  const deltaX = bottomRight[0] - bottomLeft[0];
  const deltaY = bottomRight[1] - bottomLeft[1];
  // 计算底边相对于水平线的角度
  const angle = Math.atan2(deltaY, deltaX);
  console.log("计算的旋转角度:", (angle * 180) / Math.PI, "度");
  return angle;
};

/**
 * 根据四角坐标裁剪图片并校正角度
 * 策略：先旋转整张图片使护照水平，然后裁剪护照区域
 */
const cropByCorners = async (imageBase64: string, corners: PassportCorners): Promise<string> => {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      // 第一步：将坐标转换为像素坐标
      let topLeft = [...corners.topLeft] as [number, number];
      let topRight = [...corners.topRight] as [number, number];
      let bottomLeft = [...corners.bottomLeft] as [number, number];
      let bottomRight = [...corners.bottomRight] as [number, number];

      const maxCoord = Math.max(...topLeft, ...topRight, ...bottomLeft, ...bottomRight);
      const isRatioCoords = maxCoord <= 1;

      if (isRatioCoords) {
        console.log("检测到比例坐标，转换为像素坐标");
        topLeft = [topLeft[0] * img.width, topLeft[1] * img.height];
        topRight = [topRight[0] * img.width, topRight[1] * img.height];
        bottomLeft = [bottomLeft[0] * img.width, bottomLeft[1] * img.height];
        bottomRight = [bottomRight[0] * img.width, bottomRight[1] * img.height];
      }

      // 第二步：计算旋转角度（基于底边，校正护照倾斜）
      // 只进行倾斜校正，保持护照原有方向（竖直的护照保持竖直）
      const rotationAngle = calculateRotationAngle(bottomLeft, bottomRight);
      console.log("校正旋转角度:", (rotationAngle * 180) / Math.PI, "度");

      // 第三步：创建一个足够大的临时canvas，用于旋转整张原图
      // 旋转后图片可能会变大，需要计算对角线长度作为新尺寸
      const diagonal = Math.hypot(img.width, img.height);
      const tempCanvas = document.createElement("canvas");
      tempCanvas.width = Math.ceil(diagonal);
      tempCanvas.height = Math.ceil(diagonal);
      const tempCtx = tempCanvas.getContext("2d");
      if (!tempCtx) {
        reject(new Error("无法创建临时 canvas context"));
        return;
      }

      // 填充白色背景
      tempCtx.fillStyle = "#FFFFFF";
      tempCtx.fillRect(0, 0, tempCanvas.width, tempCanvas.height);

      // 将原点移动到临时canvas中心
      const tempCenterX = tempCanvas.width / 2;
      const tempCenterY = tempCanvas.height / 2;
      tempCtx.translate(tempCenterX, tempCenterY);
      // 旋转（逆向旋转来校正倾斜）
      tempCtx.rotate(-rotationAngle);
      // 绘制原图（原图中心对齐到临时canvas中心）
      tempCtx.drawImage(img, -img.width / 2, -img.height / 2);

      // 第四步：计算旋转后的护照四角坐标
      // 需要将原始坐标先相对于原图中心，然后旋转，再加上临时canvas中心偏移
      const rotatePointAroundOrigin = (point: [number, number], imgCenter: [number, number], angle: number, newCenter: [number, number]): [number, number] => {
        // 将坐标转换为相对于原图中心
        const relX = point[0] - imgCenter[0];
        const relY = point[1] - imgCenter[1];
        // 旋转
        const cos = Math.cos(-angle);
        const sin = Math.sin(-angle);
        const rotatedX = relX * cos - relY * sin;
        const rotatedY = relX * sin + relY * cos;
        // 转换为相对于新canvas中心的坐标
        return [newCenter[0] + rotatedX, newCenter[1] + rotatedY];
      };

      const imgCenterX = img.width / 2;
      const imgCenterY = img.height / 2;

      const rotatedTopLeft = rotatePointAroundOrigin(topLeft, [imgCenterX, imgCenterY], rotationAngle, [tempCenterX, tempCenterY]);
      const rotatedTopRight = rotatePointAroundOrigin(topRight, [imgCenterX, imgCenterY], rotationAngle, [tempCenterX, tempCenterY]);
      const rotatedBottomLeft = rotatePointAroundOrigin(bottomLeft, [imgCenterX, imgCenterY], rotationAngle, [tempCenterX, tempCenterY]);
      const rotatedBottomRight = rotatePointAroundOrigin(bottomRight, [imgCenterX, imgCenterY], rotationAngle, [tempCenterX, tempCenterY]);

      console.log("旋转后的四角坐标:", { rotatedTopLeft, rotatedTopRight, rotatedBottomLeft, rotatedBottomRight });

      // 第五步：计算旋转后护照的边界框（用于裁剪）
      const allRotatedX = [rotatedTopLeft[0], rotatedTopRight[0], rotatedBottomLeft[0], rotatedBottomRight[0]];
      const allRotatedY = [rotatedTopLeft[1], rotatedTopRight[1], rotatedBottomLeft[1], rotatedBottomRight[1]];

      const paddingX = img.width * 0.02;
      const paddingY = img.height * 0.02;

      const cropMinX = Math.max(0, Math.min(...allRotatedX) - paddingX);
      const cropMaxX = Math.min(tempCanvas.width, Math.max(...allRotatedX) + paddingX);
      const cropMinY = Math.max(0, Math.min(...allRotatedY) - paddingY);
      const cropMaxY = Math.min(tempCanvas.height, Math.max(...allRotatedY) + paddingY);

      const cropWidth = cropMaxX - cropMinX;
      const cropHeight = cropMaxY - cropMinY;

      if (cropWidth <= 0 || cropHeight <= 0) {
        reject(new Error("裁剪区域无效"));
        return;
      }

      // 第六步：从旋转后的临时canvas中裁剪护照区域
      const finalCanvas = document.createElement("canvas");
      finalCanvas.width = Math.round(cropWidth);
      finalCanvas.height = Math.round(cropHeight);
      const finalCtx = finalCanvas.getContext("2d");
      if (!finalCtx) {
        reject(new Error("无法创建最终 canvas context"));
        return;
      }

      finalCtx.drawImage(
        tempCanvas,
        cropMinX,
        cropMinY,
        cropWidth,
        cropHeight, // 源区域
        0,
        0,
        cropWidth,
        cropHeight // 目标区域
      );

      console.log("裁剪并旋转完成:", {
        isRatioCoords,
        rotationAngleDeg: (rotationAngle * 180) / Math.PI,
        cropArea: { x: Math.round(cropMinX), y: Math.round(cropMinY), w: Math.round(cropWidth), h: Math.round(cropHeight) },
        tempCanvasSize: { w: tempCanvas.width, h: tempCanvas.height },
        imgSize: { w: img.width, h: img.height },
      });

      resolve(finalCanvas.toDataURL("image/png"));
    };
    img.onerror = () => reject(new Error("无法加载图片"));
    img.src = imageBase64;
  });
};

/**
 * 智能裁剪护照主函数
 */
export const smartCropPassport = async (imageBase64: string): Promise<string> => {
  const apiKey = getApiKey();
  if (!apiKey) {
    throw new Error("需要 API Key 才能使用智能裁剪功能");
  }

  console.log("开始检测护照边界...");
  const corners = await detectPassportBoundary(imageBase64, apiKey);
  console.log("检测到护照边界:", corners);

  console.log("开始裁剪护照...");
  const croppedImage = await cropByCorners(imageBase64, corners);
  console.log("护照裁剪完成");

  return croppedImage;
};
