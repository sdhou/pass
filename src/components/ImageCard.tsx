import { useCallback, useEffect, useRef, useState } from "react";
import type { Crop, PixelCrop } from "react-image-crop";
import ReactCrop from "react-image-crop";
import "react-image-crop/dist/ReactCrop.css";
import { smartCropPassport } from "../utils/passport-crop";
import "./ImageCard.css";

/**
 * 根据旋转角度生成预旋转的图片
 */
const generateRotatedImage = (imageSrc: string, rotationDeg: number): Promise<string> => {
  return new Promise((resolve) => {
    if (rotationDeg === 0) {
      resolve(imageSrc);
      return;
    }

    const img = new Image();
    img.onload = () => {
      const rotRad = (rotationDeg * Math.PI) / 180;
      const cos = Math.abs(Math.cos(rotRad));
      const sin = Math.abs(Math.sin(rotRad));

      // 计算旋转后的画布尺寸
      const newWidth = img.naturalWidth * cos + img.naturalHeight * sin;
      const newHeight = img.naturalWidth * sin + img.naturalHeight * cos;

      const canvas = document.createElement("canvas");
      canvas.width = newWidth;
      canvas.height = newHeight;

      const ctx = canvas.getContext("2d");
      if (!ctx) {
        resolve(imageSrc);
        return;
      }

      // 启用高质量图像渲染
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = "high";

      // 移动原点到中心，旋转，然后绘制
      ctx.translate(newWidth / 2, newHeight / 2);
      ctx.rotate(rotRad);
      ctx.drawImage(img, -img.naturalWidth / 2, -img.naturalHeight / 2);

      resolve(canvas.toDataURL("image/png"));
    };
    img.onerror = () => resolve(imageSrc);
    img.src = imageSrc;
  });
};

interface ImageCardProps {
  page: number;
  imageSrc: string;
  width: number;
  height: number;
  rotation: number;
  canUndo: boolean;
  isSmartCropping?: boolean;
  onRotate: (degrees: number) => void;
  onSetRotation: (rotation: number) => void;
  onCrop: (newImageSrc: string) => void;
  onUndo: () => void;
}

function ImageCard({ page, imageSrc, width, height, rotation, canUndo, isSmartCropping: externalSmartCropping, onRotate, onSetRotation, onCrop, onUndo }: Readonly<ImageCardProps>) {
  const [crop, setCrop] = useState<Crop>();
  const imgRef = useRef<HTMLImageElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [isSmartCropping, setIsSmartCropping] = useState(false);
  const [smartCropError, setSmartCropError] = useState<string | null>(null);

  // 预旋转后的图片 - react-image-crop 会使用这个图片
  const [displaySrc, setDisplaySrc] = useState(imageSrc);

  // 当原始图片或旋转角度变化时，生成预旋转的图片
  useEffect(() => {
    generateRotatedImage(imageSrc, rotation).then(setDisplaySrc);
  }, [imageSrc, rotation]);

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
  // 因为显示的图片已经是预旋转的，所以直接从 displaySrc 图片上裁剪即可
  const handleCropComplete = useCallback(
    (pixelCrop: PixelCrop) => {
      if (!imgRef.current || !canvasRef.current) return;
      if (!pixelCrop || pixelCrop.width < 10 || pixelCrop.height < 10) return;

      const canvas = canvasRef.current;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;

      const image = imgRef.current;
      // 显示的图片已经是预旋转的，直接计算缩放比例
      const scaleX = image.naturalWidth / image.width;
      const scaleY = image.naturalHeight / image.height;

      // 直接从预旋转的图片上裁剪
      const srcX = pixelCrop.x * scaleX;
      const srcY = pixelCrop.y * scaleY;
      const srcWidth = pixelCrop.width * scaleX;
      const srcHeight = pixelCrop.height * scaleY;

      canvas.width = srcWidth;
      canvas.height = srcHeight;

      // 启用高质量图像渲染（必须在设置 canvas 尺寸之后，因为设置尺寸会重置 context 状态）
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = "high";

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

  const isBusy = isSmartCropping || externalSmartCropping;

  return (
    <div className={`image-card ${isBusy ? "processing" : ""}`}>
      <div className="image-wrapper">
        <ReactCrop crop={crop} onChange={handleCropChange} onComplete={handleComplete}>
          <img ref={imgRef} src={displaySrc} alt={`第 ${page} 页`} />
        </ReactCrop>
        {externalSmartCropping && (
          <div className="processing-overlay">
            <div className="processing-spinner" />
          </div>
        )}
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
              let val = Number.parseInt(e.target.value) || 0;
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
          <button className={`action-btn smart-crop-btn ${isBusy ? "loading" : ""}`} onClick={handleSmartCrop} disabled={isBusy} title="智能裁剪护照">
            {isSmartCropping ? "⏳ 识别中..." : "✂️ 智能裁剪"}
          </button>
          <button className={`action-btn undo-btn ${canUndo ? "" : "disabled"}`} onClick={onUndo} disabled={!canUndo} title="撤销">
            ⟲ 撤销
          </button>
        </div>
        {smartCropError && <div className="smart-crop-error">⚠️ {smartCropError}</div>}
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
