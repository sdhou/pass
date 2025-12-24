import jsPDF from "jspdf";
import type { ChangeEvent, DragEvent } from "react";
import { useEffect, useRef, useState } from "react";
import "./App.css";
import ImageCard from "./components/ImageCard";
import { getApiKey, smartCropPassport } from "./utils/passport-crop";
import { convertPdfToImages } from "./utils/pdf-converter";

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
  history: string[];
}

function App() {
  const [images, setImages] = useState<PageImage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [progressText, setProgressText] = useState<string>("");
  const [isDragActive, setIsDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // 智能裁剪状态
  const [isAutoSmartCropping, setIsAutoSmartCropping] = useState(false);
  const [smartCropProgress, setSmartCropProgress] = useState({ current: 0, total: 0 });
  const [currentCroppingPage, setCurrentCroppingPage] = useState<number | null>(null);

  // 返回顶部按钮状态
  const [showBackToTop, setShowBackToTop] = useState(false);

  // 监听滚动事件
  useEffect(() => {
    const handleScroll = () => {
      setShowBackToTop(window.scrollY > 300);
    };
    window.addEventListener("scroll", handleScroll);
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  // 自动智能裁剪所有图片
  const autoSmartCropAll = async (imageList: PageImage[]) => {
    const apiKey = getApiKey();
    if (!apiKey) {
      return; // 用户取消了输入 API Key
    }

    setIsAutoSmartCropping(true);
    setSmartCropProgress({ current: 0, total: imageList.length });

    const updatedImages = [...imageList];

    for (let i = 0; i < imageList.length; i++) {
      setSmartCropProgress({ current: i + 1, total: imageList.length });
      setCurrentCroppingPage(imageList[i].page);

      try {
        const newImage = await smartCropPassport(imageList[i].image);

        // 获取新图片尺寸
        const imgSize = await new Promise<{ width: number; height: number }>((resolve) => {
          const img = new Image();
          img.onload = () => resolve({ width: img.width, height: img.height });
          img.src = newImage;
        });

        updatedImages[i] = {
          ...updatedImages[i],
          image: newImage,
          width: imgSize.width,
          height: imgSize.height,
          history: [...updatedImages[i].history, imageList[i].image],
        };

        // 实时更新状态
        setImages([...updatedImages]);
      } catch (err) {
        console.error(`智能裁剪第 ${i + 1} 页失败:`, err);
        // 继续处理下一张
      }
    }

    setIsAutoSmartCropping(false);
    setCurrentCroppingPage(null);
    setSmartCropProgress({ current: 0, total: 0 });
  };

  const handleUpload = async (file: File) => {
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setError("请上传PDF文件");
      return;
    }

    setLoading(true);
    setProgressText("正在读取PDF...");
    setError(null);
    setImages([]);

    try {
      const result = await convertPdfToImages(file, (current, total) => {
        setProgressText(`正在解析第 ${current} / ${total} 页...`);
      });

      const initialImages = result.map((img) => ({ ...img, rotation: 0, history: [] }));
      setImages(initialImages);
      setLoading(false);
      setProgressText("");

      // PDF 解析完成后自动开始智能裁剪
      autoSmartCropAll(initialImages);
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "PDF处理失败，请检查文件是否损坏");
      setLoading(false);
      setProgressText("");
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

  const handleCrop = (page: number, newImageSrc: string) => {
    const img = new Image();
    img.onload = () => {
      setImages((prev) =>
        prev.map((imgData) =>
          imgData.page === page
            ? {
                ...imgData,
                image: newImageSrc,
                width: img.width,
                height: img.height,
                rotation: 0,
                history: [...imgData.history, imgData.image],
              }
            : imgData
        )
      );
    };
    img.src = newImageSrc;
  };

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
    setProgressText("准备生成PDF...");

    await new Promise((resolve) => setTimeout(resolve, 100));

    try {
      const pdf = new jsPDF("p", "mm", "a4");
      const pageWidth = pdf.internal.pageSize.getWidth();
      const pageHeight = pdf.internal.pageSize.getHeight();

      for (let i = 0; i < images.length; i++) {
        setProgressText(`正在处理第 ${i + 1} / ${images.length} 页...`);
        await new Promise((resolve) => setTimeout(resolve, 0));

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

      setProgressText("正在保存文件...");
      await new Promise((resolve) => setTimeout(resolve, 50));
      pdf.save("converted.pdf");
    } catch (err) {
      console.error(err);
      setError("生成PDF失败");
    } finally {
      setLoading(false);
      setProgressText("");
    }
  };

  const isBusy = loading || isAutoSmartCropping;

  return (
    <div className="app">
      <header className="header">
        <h1>📄 PDF 转图片</h1>
        <p>上传PDF文件，将每一页转换为高清图片</p>
      </header>

      <div className="upload-area">
        <div
          className={`upload-zone ${isDragActive ? "drag-active" : ""} ${isBusy ? "uploading" : ""}`}
          onClick={handleClick}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          <input ref={fileInputRef} type="file" accept=".pdf" onChange={handleFileChange} className="upload-input" />
          {loading ? (
            <div className="loading-container">
              <div className="spinner"></div>
              <span className="loading-text">{progressText || "正在处理..."}</span>
            </div>
          ) : isAutoSmartCropping ? (
            <div className="loading-container">
              <div className="spinner"></div>
              <span className="loading-text">
                ✂️ 智能裁剪中... {smartCropProgress.current} / {smartCropProgress.total}
              </span>
              <div className="smart-crop-global-progress">
                <div className="smart-crop-global-progress-fill" style={{ width: `${(smartCropProgress.current / smartCropProgress.total) * 100}%` }} />
              </div>
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
            <button className="download-btn" onClick={handleDownloadPDF} disabled={isBusy}>
              {isBusy ? (isAutoSmartCropping ? "裁剪中..." : progressText || "处理中...") : "📥 下载 PDF"}
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
                isSmartCropping={currentCroppingPage === img.page}
                onRotate={(degrees) => handleRotate(img.page, degrees)}
                onSetRotation={(rotation) => handleSetRotation(img.page, rotation)}
                onCrop={(newSrc) => handleCrop(img.page, newSrc)}
                onUndo={() => handleUndo(img.page)}
              />
            ))}
          </div>
        </div>
      )}

      {/* 返回顶部按钮 */}
      <button className={`back-to-top ${showBackToTop ? "visible" : ""}`} onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })} title="返回顶部">
        ↑
      </button>
    </div>
  );
}

export default App;
