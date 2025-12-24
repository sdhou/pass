import io
import base64
import tempfile
import os
from typing import List

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pdf2image import convert_from_bytes
from PIL import Image

app = FastAPI(title="PDF to Images API")

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def image_to_base64(image: Image.Image, format: str = "PNG") -> str:
    """将PIL Image转换为base64字符串"""
    buffer = io.BytesIO()
    image.save(buffer, format=format)
    buffer.seek(0)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


@app.post("/api/upload")
async def upload_pdf(file: UploadFile = File(...)):
    """
    上传PDF文件并将每页转换为图片
    返回所有页面的base64编码图片
    """
    # 验证文件类型
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="只支持PDF文件")

    try:
        # 读取上传的PDF文件内容
        pdf_content = await file.read()

        # 将PDF转换为图片列表
        images = convert_from_bytes(pdf_content, dpi=150)

        # 将每张图片转换为base64
        result = []
        for i, image in enumerate(images):
            base64_image = image_to_base64(image)
            result.append({
                "page": i + 1,
                "image": f"data:image/png;base64,{base64_image}",
                "width": image.width,
                "height": image.height
            })

        return JSONResponse(content={
            "success": True,
            "total_pages": len(result),
            "images": result
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF处理失败: {str(e)}")


@app.get("/api/health")
async def health_check():
    """健康检查接口"""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
