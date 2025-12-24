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
 * 根据四角坐标裁剪图片
 * 支持比例坐标 (0-1) 和像素坐标，自动判断并增加安全边距
 */
const cropByCorners = async (imageBase64: string, corners: PassportCorners): Promise<string> => {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement("canvas");
      const ctx = canvas.getContext("2d");
      if (!ctx) {
        reject(new Error("无法创建 canvas context"));
        return;
      }

      // 收集所有坐标值
      let allX = [corners.topLeft[0], corners.topRight[0], corners.bottomLeft[0], corners.bottomRight[0]];
      let allY = [corners.topLeft[1], corners.topRight[1], corners.bottomLeft[1], corners.bottomRight[1]];

      // 判断是比例坐标还是像素坐标
      const maxX = Math.max(...allX);
      const maxY = Math.max(...allY);
      const isRatioCoords = maxX <= 1 && maxY <= 1;

      // 如果是比例坐标，转换为像素坐标
      if (isRatioCoords) {
        console.log("检测到比例坐标，转换为像素坐标");
        allX = allX.map((x) => x * img.width);
        allY = allY.map((y) => y * img.height);
      }

      // 增加较大的安全边距（图片尺寸的 2%，确保不会截掉任何内容）
      const paddingX = img.width * 0.02;
      const paddingY = img.height * 0.02;

      const minX = Math.max(0, Math.min(...allX) - paddingX);
      const cropMaxX = Math.min(img.width, Math.max(...allX) + paddingX);
      const minY = Math.max(0, Math.min(...allY) - paddingY);
      const cropMaxY = Math.min(img.height, Math.max(...allY) + paddingY);

      const width = cropMaxX - minX;
      const height = cropMaxY - minY;

      if (width <= 0 || height <= 0) {
        reject(new Error("裁剪区域无效"));
        return;
      }

      canvas.width = width;
      canvas.height = height;

      // 裁剪图片
      ctx.drawImage(img, minX, minY, width, height, 0, 0, width, height);

      console.log("裁剪完成:", {
        isRatioCoords,
        minX: Math.round(minX),
        minY: Math.round(minY),
        width: Math.round(width),
        height: Math.round(height),
        imgWidth: img.width,
        imgHeight: img.height,
      });
      resolve(canvas.toDataURL("image/png"));
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
