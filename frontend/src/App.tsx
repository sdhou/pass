import type { ChangeEvent, DragEvent } from "react";
import { useRef, useState } from "react";
import "./App.css";
import ImageEditor from "./components/ImageEditor";

interface PageImage {
  page: number;
  image: string;
  width: number;
  height: number;
  rotation?: number;
}

interface UploadResponse {
  success: boolean;
  total_pages: number;
  images: PageImage[];
}

function App() {
  const [images, setImages] = useState<PageImage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isDragActive, setIsDragActive] = useState(false);
  const [editingImage, setEditingImage] = useState<PageImage | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleUpload = async (file: File) => {
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setError("请上传PDF文件");
      return;
    }

    setLoading(true);
    setError(null);
    setImages([]);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await fetch("/api/upload", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "上传失败");
      }

      const data: UploadResponse = await response.json();

      if (data.success) {
        setImages(data.images.map((img) => ({ ...img, rotation: 0 })));
      } else {
        throw new Error("处理失败");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传过程中发生错误");
    } finally {
      setLoading(false);
    }
  };

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      handleUpload(file);
    }
  };

  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragActive(true);
  };

  const handleDragLeave = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragActive(false);
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragActive(false);

    const file = e.dataTransfer.files?.[0];
    if (file) {
      handleUpload(file);
    }
  };

  const handleClick = () => {
    fileInputRef.current?.click();
  };

  const handleClear = () => {
    setImages([]);
    setError(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  // 快速旋转
  const handleQuickRotate = (page: number, degrees: number) => {
    setImages((prev) => prev.map((img) => (img.page === page ? { ...img, rotation: ((img.rotation || 0) + degrees) % 360 } : img)));
  };

  // 打开编辑器
  const handleEdit = (img: PageImage) => {
    setEditingImage(img);
  };

  // 保存编辑后的图片
  const handleSaveEdit = (newImageSrc: string) => {
    if (!editingImage) return;

    setImages((prev) => prev.map((img) => (img.page === editingImage.page ? { ...img, image: newImageSrc, rotation: 0 } : img)));
    setEditingImage(null);
  };

  return (
    <div className="app">
      <header className="header">
        <h1>📄 PDF 转图片</h1>
        <p>上传PDF文件，将每一页转换为高清图片</p>
      </header>

      <div className="upload-area">
        <div
          className={`upload-zone ${isDragActive ? "drag-active" : ""} ${loading ? "uploading" : ""}`}
          onClick={handleClick}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          <input ref={fileInputRef} type="file" accept=".pdf" onChange={handleFileChange} className="upload-input" />
          {loading ? (
            <div className="loading-container">
              <div className="spinner"></div>
              <span className="loading-text">正在处理PDF文件...</span>
            </div>
          ) : (
            <>
              <div className="upload-icon">📁</div>
              <h3>点击或拖拽上传PDF文件</h3>
              <p>支持 .pdf 格式</p>
            </>
          )}
        </div>
      </div>

      {error && <div className="error-message">⚠️ {error}</div>}

      {images.length > 0 && (
        <div className="results-container">
          <div className="results-header">
            <h2>转换结果</h2>
            <span className="page-count">共 {images.length} 页</span>
            <button className="clear-btn" onClick={handleClear}>
              清除结果
            </button>
          </div>

          <div className="image-grid">
            {images.map((img) => (
              <div key={img.page} className="image-card">
                <div className="image-wrapper">
                  <img src={img.image} alt={`第 ${img.page} 页`} style={{ transform: `rotate(${img.rotation || 0}deg)` }} />
                </div>
                <div className="image-actions">
                  <button className="action-btn rotate-btn" onClick={() => handleQuickRotate(img.page, -90)} title="左转90°">
                    ↺
                  </button>
                  <button className="action-btn rotate-btn" onClick={() => handleQuickRotate(img.page, 90)} title="右转90°">
                    ↻
                  </button>
                  <button className="action-btn edit-btn" onClick={() => handleEdit(img)} title="编辑">
                    ✂️ 编辑
                  </button>
                </div>
                <div className="image-info">
                  <span className="page-number">第 {img.page} 页</span>
                  <span className="image-size">
                    {img.width} × {img.height}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {editingImage && <ImageEditor imageSrc={editingImage.image} pageNumber={editingImage.page} onSave={handleSaveEdit} onClose={() => setEditingImage(null)} />}
    </div>
  );
}

export default App;
