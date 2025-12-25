import { useCallback, useRef, useState } from "react";
import type { Crop, PixelCrop } from "react-image-crop";
import ReactCrop from "react-image-crop";
import "react-image-crop/dist/ReactCrop.css";
import { smartCropPassport } from "../utils/passport-crop";
import "./ImageCard.css";

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

  const isBusy = isSmartCropping || externalSmartCropping;

  return (
    <div className={`image-card ${isBusy ? "processing" : ""}`}>
      <div className="image-wrapper">
        <ReactCrop crop={crop} onChange={handleCropChange} onComplete={handleComplete}>
          <img ref={imgRef} src={imageSrc} alt={`第 ${page} 页`} style={{ transform: `rotate(${rotation}deg)` }} />
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
