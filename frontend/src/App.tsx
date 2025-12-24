import jsPDF from "jspdf";
import type { ChangeEvent, DragEvent } from "react";
import { useRef, useState } from "react";
import "./App.css";
import ImageCard from "./components/ImageCard";

const getRotatedImage = (src: string, rotation: number): Promise<string> => {
  return new Promise((resolve) => {
    if (rotation === 0) {
      resolve(src);
      return;
    }
    const image = new Image();
    image.src = src;
    image.onload = () => {
      const canvas = document.createElement("canvas");
      const ctx = canvas.getContext("2d");
      if (!ctx) {
        resolve(src);
        return;
      }

      const rad = (rotation * Math.PI) / 180;
      const sin = Math.abs(Math.sin(rad));
      const cos = Math.abs(Math.cos(rad));
      const w = image.width;
      const h = image.height;
      const newWidth = w * cos + h * sin;
      const newHeight = w * sin + h * cos;

      canvas.width = newWidth;
      canvas.height = newHeight;

      ctx.translate(newWidth / 2, newHeight / 2);
      ctx.rotate(rad);
      ctx.drawImage(image, -w / 2, -h / 2);
      resolve(canvas.toDataURL("image/png"));
    };
  });
};

interface PageImage {
  page: number;
  image: string;
  width: number;
  height: number;
  rotation: number;
  history: string[]; // 历史记录
}

interface UploadResponse {
  success: boolean;
  total_pages: number;
  images: Omit<PageImage, "rotation" | "history">[];
}

function App() {
  const [images, setImages] = useState<PageImage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isDragActive, setIsDragActive] = useState(false);
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
        setImages(data.images.map((img) => ({ ...img, rotation: 0, history: [] })));
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

  const handleRotate = (page: number, degrees: number) => {
    setImages((prev) => prev.map((img) => (img.page === page ? { ...img, rotation: (img.rotation + degrees) % 360 } : img)));
  };

  const handleSetRotation = (page: number, rotation: number) => {
    setImages((prev) => prev.map((img) => (img.page === page ? { ...img, rotation } : img)));
  };

  // 裁剪时保存历史
  const handleCrop = (page: number, newImageSrc: string) => {
    setImages((prev) => prev.map((img) => (img.page === page ? { ...img, image: newImageSrc, rotation: 0, history: [...img.history, img.image] } : img)));
  };

  // 撤销
  const handleUndo = (page: number) => {
    setImages((prev) =>
      prev.map((img) => {
        if (img.page === page && img.history.length > 0) {
          const newHistory = [...img.history];
          const previousImage = newHistory.pop()!;
          return { ...img, image: previousImage, rotation: 0, history: newHistory };
        }
        return img;
      })
    );
  };

  const handleDownloadPDF = async () => {
    if (images.length === 0) return;

    setLoading(true);
    try {
      const pdf = new jsPDF("p", "mm", "a4");
      const pageWidth = pdf.internal.pageSize.getWidth();
      const pageHeight = pdf.internal.pageSize.getHeight();

      for (let i = 0; i < images.length; i++) {
        const img = images[i];
        if (i > 0) {
          pdf.addPage();
        }

        const imageData = await getRotatedImage(img.image, img.rotation);
        const imgProps = pdf.getImageProperties(imageData);
        const ratio = imgProps.width / imgProps.height;

        let w = pageWidth;
        let h = w / ratio;

        if (h > pageHeight) {
          h = pageHeight;
          w = h * ratio;
        }

        const x = (pageWidth - w) / 2;
        const y = (pageHeight - h) / 2;

        pdf.addImage(imageData, "PNG", x, y, w, h, undefined, "FAST");
      }

      pdf.save("converted.pdf");
    } catch (err) {
      console.error(err);
      setError("生成PDF失败");
    } finally {
      setLoading(false);
    }
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
            <button className="download-btn" onClick={handleDownloadPDF} disabled={loading}>
              {loading ? "处理中..." : "📥 下载 PDF"}
            </button>
            <button className="clear-btn" onClick={handleClear}>
              清除结果
            </button>
          </div>

          <div className="image-grid">
            {images.map((img) => (
              <ImageCard
                key={img.page}
                page={img.page}
                imageSrc={img.image}
                width={img.width}
                height={img.height}
                rotation={img.rotation}
                canUndo={img.history.length > 0}
                onRotate={(degrees) => handleRotate(img.page, degrees)}
                onSetRotation={(rotation) => handleSetRotation(img.page, rotation)}
                onCrop={(newSrc) => handleCrop(img.page, newSrc)}
                onUndo={() => handleUndo(img.page)}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
