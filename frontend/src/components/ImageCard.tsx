import { useCallback, useRef, useState } from "react";
import type { Crop, PixelCrop } from "react-image-crop";
import ReactCrop from "react-image-crop";
import "react-image-crop/dist/ReactCrop.css";
import "./ImageCard.css";

interface ImageCardProps {
  page: number;
  imageSrc: string;
  width: number;
  height: number;
  rotation: number;
  canUndo: boolean;
  onRotate: (degrees: number) => void;
  onCrop: (newImageSrc: string) => void;
  onUndo: () => void;
}

function ImageCard({ page, imageSrc, width, height, rotation, canUndo, onRotate, onCrop, onUndo }: ImageCardProps) {
  const [crop, setCrop] = useState<Crop>();
  const imgRef = useRef<HTMLImageElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

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
