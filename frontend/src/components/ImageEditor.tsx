import type { ChangeEvent } from "react";
import { useCallback, useRef, useState } from "react";
import type { Crop, PixelCrop } from "react-image-crop";
import ReactCrop from "react-image-crop";
import "react-image-crop/dist/ReactCrop.css";
import "./ImageEditor.css";

interface ImageEditorProps {
  imageSrc: string;
  pageNumber: number;
  onSave: (newImageSrc: string) => void;
  onClose: () => void;
}

function ImageEditor({ imageSrc, pageNumber, onSave, onClose }: ImageEditorProps) {
  const [rotation, setRotation] = useState(0);
  const [crop, setCrop] = useState<Crop>();
  const [completedCrop, setCompletedCrop] = useState<PixelCrop>();
  const imgRef = useRef<HTMLImageElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  // 旋转处理
  const handleRotate = (degrees: number) => {
    setRotation((prev) => (prev + degrees) % 360);
  };

  const handleRotationChange = (e: ChangeEvent<HTMLInputElement>) => {
    setRotation(Number(e.target.value));
  };

  // 生成最终图片
  const generateImage = useCallback(() => {
    if (!imgRef.current || !canvasRef.current) return null;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;

    const image = imgRef.current;
    const radians = (rotation * Math.PI) / 180;

    // 计算旋转后的尺寸
    const sin = Math.abs(Math.sin(radians));
    const cos = Math.abs(Math.cos(radians));

    let srcWidth = image.naturalWidth;
    let srcHeight = image.naturalHeight;
    let srcX = 0;
    let srcY = 0;

    // 如果有裁剪区域
    if (completedCrop && completedCrop.width > 0 && completedCrop.height > 0) {
      const scaleX = image.naturalWidth / image.width;
      const scaleY = image.naturalHeight / image.height;
      srcX = completedCrop.x * scaleX;
      srcY = completedCrop.y * scaleY;
      srcWidth = completedCrop.width * scaleX;
      srcHeight = completedCrop.height * scaleY;
    }

    const rotatedWidth = srcWidth * cos + srcHeight * sin;
    const rotatedHeight = srcWidth * sin + srcHeight * cos;

    canvas.width = rotatedWidth;
    canvas.height = rotatedHeight;

    ctx.translate(rotatedWidth / 2, rotatedHeight / 2);
    ctx.rotate(radians);
    ctx.drawImage(image, srcX, srcY, srcWidth, srcHeight, -srcWidth / 2, -srcHeight / 2, srcWidth, srcHeight);

    return canvas.toDataURL("image/png");
  }, [rotation, completedCrop]);

  const handleSave = () => {
    const newImage = generateImage();
    if (newImage) {
      onSave(newImage);
    }
    onClose();
  };

  return (
    <div className="editor-overlay">
      <div className="editor-modal">
        <div className="editor-header">
          <h3>编辑第 {pageNumber} 页</h3>
          <button className="close-btn" onClick={onClose}>
            ✕
          </button>
        </div>

        <div className="editor-content">
          <div className="editor-canvas-area">
            <ReactCrop crop={crop} onChange={(c) => setCrop(c)} onComplete={(c) => setCompletedCrop(c)}>
              <img ref={imgRef} src={imageSrc} alt="编辑预览" style={{ transform: `rotate(${rotation}deg)` }} className="editor-image" />
            </ReactCrop>
          </div>

          <div className="editor-controls">
            <div className="control-group">
              <label>旋转角度</label>
              <div className="rotation-buttons">
                <button onClick={() => handleRotate(-90)} className="control-btn">
                  ↺ 左转90°
                </button>
                <button onClick={() => handleRotate(90)} className="control-btn">
                  ↻ 右转90°
                </button>
              </div>
              <div className="rotation-slider">
                <input type="range" min="-180" max="180" value={rotation} onChange={handleRotationChange} />
                <span>{rotation}°</span>
              </div>
            </div>

            <div className="control-group">
              <label>裁剪区域</label>
              <p className="control-hint">在图片上拖拽选择裁剪区域</p>
              {completedCrop && completedCrop.width > 0 && (
                <button onClick={() => setCrop(undefined)} className="control-btn secondary">
                  清除选区
                </button>
              )}
            </div>
          </div>
        </div>

        <div className="editor-footer">
          <button className="cancel-btn" onClick={onClose}>
            取消
          </button>
          <button className="save-btn" onClick={handleSave}>
            保存修改
          </button>
        </div>

        <canvas ref={canvasRef} style={{ display: "none" }} />
      </div>
    </div>
  );
}

export default ImageEditor;
