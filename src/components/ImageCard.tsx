import { removeBackground as imglyRemoveBackground } from "@imgly/background-removal";
import { useCallback, useRef, useState } from "react";
import type { Crop, PixelCrop } from "react-image-crop";
import ReactCrop from "react-image-crop";
import "react-image-crop/dist/ReactCrop.css";
import { smartCropPassport } from "../utils/passport-crop";
import "./ImageCard.css";

// 裁剪透明区域，只保留有内容的部分
const trimTransparentPixels = (imageSrc: string): Promise<string> => {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement("canvas");
      const ctx = canvas.getContext("2d");
      if (!ctx) {
        reject(new Error("无法创建 canvas context"));
        return;
      }

      canvas.width = img.width;
      canvas.height = img.height;
      ctx.drawImage(img, 0, 0);

      const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
      const data = imageData.data;

      let minX = canvas.width;
      let minY = canvas.height;
      let maxX = 0;
      let maxY = 0;

      // 使用透明度阈值，忽略几乎透明的像素
      const alphaThreshold = 10;

      // 扫描所有像素，找到非透明区域的边界
      for (let y = 0; y < canvas.height; y++) {
        for (let x = 0; x < canvas.width; x++) {
          const alpha = data[(y * canvas.width + x) * 4 + 3];
          if (alpha > alphaThreshold) {
            minX = Math.min(minX, x);
            minY = Math.min(minY, y);
            maxX = Math.max(maxX, x);
            maxY = Math.max(maxY, y);
          }
        }
      }

      console.log("裁剪边界:", { minX, minY, maxX, maxY, originalWidth: canvas.width, originalHeight: canvas.height });

      // 如果没有找到非透明像素，返回原图
      if (minX > maxX || minY > maxY) {
        console.log("未找到需要裁剪的区域，返回原图");
        resolve(imageSrc);
        return;
      }

      // 裁剪到非透明区域
      const trimmedWidth = maxX - minX + 1;
      const trimmedHeight = maxY - minY + 1;

      const trimmedCanvas = document.createElement("canvas");
      trimmedCanvas.width = trimmedWidth;
      trimmedCanvas.height = trimmedHeight;
      const trimmedCtx = trimmedCanvas.getContext("2d");
      if (!trimmedCtx) {
        reject(new Error("无法创建裁剪 canvas context"));
        return;
      }

      trimmedCtx.drawImage(canvas, minX, minY, trimmedWidth, trimmedHeight, 0, 0, trimmedWidth, trimmedHeight);
      console.log("裁剪完成，新尺寸:", { width: trimmedWidth, height: trimmedHeight });
      resolve(trimmedCanvas.toDataURL("image/png"));
    };
    img.onerror = () => reject(new Error("无法加载图片"));
    img.src = imageSrc;
  });
};

// 使用 @imgly/background-removal 在浏览器本地删除背景
const removeBackground = async (imageSrc: string): Promise<string> => {
  // 将 base64 或 URL 转换为 Blob
  const response = await fetch(imageSrc);
  const imageBlob = await response.blob();

  // 调用本地背景删除
  const resultBlob = await imglyRemoveBackground(imageBlob);
  console.log("背景删除结果 Blob 类型:", resultBlob.type, "大小:", resultBlob.size);

  // 将结果 Blob 转换为 base64
  const base64Result = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      if (typeof reader.result === "string") {
        resolve(reader.result);
      } else {
        reject(new Error("无法读取处理后的图片"));
      }
    };
    reader.onerror = reject;
    reader.readAsDataURL(resultBlob);
  });

  // 裁剪透明区域
  return trimTransparentPixels(base64Result);
};

interface ImageCardProps {
  page: number;
  imageSrc: string;
  width: number;
  height: number;
  rotation: number;
  canUndo: boolean;
  onRotate: (degrees: number) => void;
  onSetRotation: (rotation: number) => void;
  onCrop: (newImageSrc: string) => void;
  onUndo: () => void;
}

function ImageCard({ page, imageSrc, width, height, rotation, canUndo, onRotate, onSetRotation, onCrop, onUndo }: ImageCardProps) {
  const [crop, setCrop] = useState<Crop>();
  const imgRef = useRef<HTMLImageElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [isRemovingBg, setIsRemovingBg] = useState(false);
  const [bgRemoveError, setBgRemoveError] = useState<string | null>(null);
  const [isSmartCropping, setIsSmartCropping] = useState(false);
  const [smartCropError, setSmartCropError] = useState<string | null>(null);

  const handleRemoveBackground = async () => {
    setIsRemovingBg(true);
    setBgRemoveError(null);

    try {
      const newImage = await removeBackground(imageSrc);
      onCrop(newImage);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "背景删除失败";
      setBgRemoveError(errorMessage);
    } finally {
      setIsRemovingBg(false);
    }
  };

  const handleSmartCrop = async () => {
    setIsSmartCropping(true);
    setSmartCropError(null);

    try {
      const newImage = await smartCropPassport(imageSrc);
      onCrop(newImage);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "智能裁剪失败";
      setSmartCropError(errorMessage);
    } finally {
      setIsSmartCropping(false);
    }
  };

  // 裁剪完成后立即应用
  const handleCropComplete = useCallback(
    (pixelCrop: PixelCrop) => {
      if (!imgRef.current || !canvasRef.current) return;
      if (!pixelCrop || pixelCrop.width < 10 || pixelCrop.height < 10) return;

      const canvas = canvasRef.current;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;

      const image = imgRef.current;
      const scaleX = image.naturalWidth / image.width;
      const scaleY = image.naturalHeight / image.height;

      const srcX = pixelCrop.x * scaleX;
      const srcY = pixelCrop.y * scaleY;
      const srcWidth = pixelCrop.width * scaleX;
      const srcHeight = pixelCrop.height * scaleY;

      canvas.width = srcWidth;
      canvas.height = srcHeight;

      ctx.drawImage(image, srcX, srcY, srcWidth, srcHeight, 0, 0, srcWidth, srcHeight);

      const newImage = canvas.toDataURL("image/png");
      onCrop(newImage);
      setCrop(undefined);
    },
    [onCrop]
  );

  const handleCropChange = (c: Crop) => {
    setCrop(c);
  };

  const handleComplete = (pixelCrop: PixelCrop) => {
    if (pixelCrop.width > 10 && pixelCrop.height > 10) {
      setTimeout(() => {
        handleCropComplete(pixelCrop);
      }, 150);
    }
  };

  return (
    <div className="image-card">
      <div className="image-wrapper">
        <ReactCrop crop={crop} onChange={handleCropChange} onComplete={handleComplete}>
          <img ref={imgRef} src={imageSrc} alt={`第 ${page} 页`} style={{ transform: `rotate(${rotation}deg)` }} />
        </ReactCrop>
      </div>

      <div className="image-actions">
        <div className="rotation-control">
          <button className="slider-btn" onClick={() => onSetRotation((rotation - 1 + 360) % 360)} title="-1°">
            -
          </button>
          <input
            type="range"
            min="-180"
            max="180"
            value={rotation > 180 ? rotation - 360 : rotation}
            onChange={(e) => {
              const val = Number(e.target.value);
              onSetRotation(val >= 0 ? val : 360 + val);
            }}
            className="rotation-slider"
          />
          <button className="slider-btn" onClick={() => onSetRotation((rotation + 1) % 360)} title="+1°">
            +
          </button>
          <input
            type="number"
            value={Math.round(rotation > 180 ? rotation - 360 : rotation)}
            onChange={(e) => {
              let val = parseInt(e.target.value) || 0;
              // Limit input range if needed, though visual feedback is enough
              if (val > 180) val = 180;
              if (val < -180) val = -180;
              onSetRotation(val >= 0 ? val : 360 + val);
            }}
            className="rotation-input"
          />
          <span className="unit">°</span>
        </div>
        <div className="btn-group">
          <button className="action-btn rotate-btn" onClick={() => onRotate(-90)} title="左转90°">
            ↺
          </button>
          <button className="action-btn rotate-btn" onClick={() => onRotate(90)} title="右转90°">
            ↻
          </button>
          <button className={`action-btn undo-btn ${!canUndo ? "disabled" : ""}`} onClick={onUndo} disabled={!canUndo} title="撤销">
            ⟲ 撤销
          </button>
        </div>
        <div className="btn-group">
          <button className={`action-btn remove-bg-btn ${isRemovingBg ? "loading" : ""}`} onClick={handleRemoveBackground} disabled={isRemovingBg} title="删除背景">
            {isRemovingBg ? "⏳ 处理中..." : "🎨 删除背景"}
          </button>
          <button className={`action-btn smart-crop-btn ${isSmartCropping ? "loading" : ""}`} onClick={handleSmartCrop} disabled={isSmartCropping} title="智能裁剪护照">
            {isSmartCropping ? "⏳ 识别中..." : "✂️ 智能裁剪"}
          </button>
        </div>
        {bgRemoveError && <div className="bg-remove-error">⚠️ {bgRemoveError}</div>}
        {smartCropError && <div className="bg-remove-error">⚠️ {smartCropError}</div>}
      </div>

      <div className="image-info">
        <span className="page-number">第 {page} 页</span>
        <span className="image-size">
          {width} × {height}
        </span>
      </div>

      <canvas ref={canvasRef} style={{ display: "none" }} />
    </div>
  );
}

export default ImageCard;
