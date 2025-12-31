import * as pdfjsLib from "pdfjs-dist";

// 设置 workerSrc
// 注意：在 Vite 中我们通常需要这样引入 worker，或者使用 CDN
// 为了兼容性更好，这里使用 unpkg CDN 对应的版本
import pdfWorker from "pdfjs-dist/build/pdf.worker.mjs?url";

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorker;

export interface PageImage {
  page: number;
  image: string; // base64 string
  width: number;
  height: number;
}

export const convertPdfToImages = async (file: File, onProgress?: (current: number, total: number) => void): Promise<PageImage[]> => {
  const arrayBuffer = await file.arrayBuffer();

  // 加载 PDF 文档
  const loadingTask = pdfjsLib.getDocument(arrayBuffer);
  const pdf = await loadingTask.promise;
  const numPages = pdf.numPages;
  const images: PageImage[] = [];

  for (let i = 1; i <= numPages; i++) {
    const page = await pdf.getPage(i);

    // 设置缩放比例，1.5 约等于 150 DPI (默认是 72 DPI, 1.5 * 72 = 108，我们可以调大一点保证清晰度)
    // 后端之前是用 dpi=150，这里我们使用更高的 scale = 3 (≈216 DPI) 以保证清晰度
    const viewport = page.getViewport({ scale: 3 });

    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d");

    if (!context) {
      throw new Error("Canvas context not available");
    }

    canvas.height = viewport.height;
    canvas.width = viewport.width;

    const renderContext = {
      canvas: null,
      canvasContext: context,
      viewport: viewport,
    };

    await page.render(renderContext).promise;

    const base64 = canvas.toDataURL("image/png");

    images.push({
      page: i,
      image: base64,
      width: viewport.width,
      height: viewport.height,
    });

    if (onProgress) {
      onProgress(i, numPages);
    }
  }

  return images;
};
