import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    // PDF 相关库本身就很大，无法进一步拆分，提高警告阈值
    chunkSizeWarningLimit: 800,
    rollupOptions: {
      output: {
        manualChunks: {
          // React 相关
          "vendor-react": ["react", "react-dom"],
          // PDF 读取库（较大）
          "vendor-pdfjs": ["pdfjs-dist"],
          // PDF 生成库
          "vendor-jspdf": ["jspdf"],
        },
      },
    },
  },
});
