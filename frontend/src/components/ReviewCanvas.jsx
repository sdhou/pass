import React, { useRef, useEffect, useState } from 'react';
import { Button, Space, message } from 'antd';

const ReviewCanvas = ({ imageUrl, candidates = [], onSave, onCancel }) => {
  const canvasRef = useRef(null);
  const [points, setPoints] = useState([]);
  const [image, setImage] = useState(null);
  const [scale, setScale] = useState(1);

  useEffect(() => {
    const img = new Image();
    img.crossOrigin = 'Anonymous';
    img.src = imageUrl;
    img.onload = () => {
      setImage(img);
    };
  }, [imageUrl]);

  useEffect(() => {
    if (image && canvasRef.current) {
      const canvas = canvasRef.current;
      const ctx = canvas.getContext('2d');
      
      const padding = 48;
      const availableWidth = window.innerWidth - padding;
      const availableHeight = window.innerHeight - 200;
      
      const scaleX = availableWidth / image.width;
      const scaleY = availableHeight / image.height;
      const s = Math.min(1, scaleX, scaleY);
      
      setScale(s);

      canvas.width = image.width * s;
      canvas.height = image.height * s;

      draw(ctx, image, s);
    }
  }, [image, points, candidates]);

  const draw = (ctx, img, s) => {
    ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
    
    // Draw Image
    ctx.drawImage(img, 0, 0, img.width * s, img.height * s);

    // Draw Candidates (Blue/Green)
    candidates.forEach((quad, idx) => {
      ctx.strokeStyle = idx === 0 ? '#00ff00' : '#0000ff';
      ctx.lineWidth = 2;
      drawQuad(ctx, quad, s);
    });

    if (points.length > 0) {
      ctx.fillStyle = 'red';
      points.forEach(p => {
        ctx.beginPath();
        ctx.arc(p[0] * s, p[1] * s, 4, 0, Math.PI * 2);
        ctx.fill();
      });

      if (points.length === 4) {
        ctx.strokeStyle = 'red';
        ctx.lineWidth = 3;
        const sorted = orderQuad(points);
        drawQuad(ctx, sorted, s);
      }
    }
  };

  const drawQuad = (ctx, quad, s) => {
    if (!quad || quad.length < 3) return;
    ctx.beginPath();
    ctx.moveTo(quad[0][0] * s, quad[0][1] * s);
    for (let i = 1; i < quad.length; i++) {
      ctx.lineTo(quad[i][0] * s, quad[i][1] * s);
    }
    ctx.closePath();
    ctx.stroke();
  };

  const handleCanvasClick = (e) => {
    if (points.length >= 4) return;

    const rect = canvasRef.current.getBoundingClientRect();
    const x = (e.clientX - rect.left) / scale;
    const y = (e.clientY - rect.top) / scale;

    setPoints([...points, [x, y]]);
  };

  const orderQuad = (pts) => {
    const p = pts.map((v) => [Number(v[0]), Number(v[1])]);
    const sums = p.map(([x, y]) => x + y);
    const diffs = p.map(([x, y]) => x - y);

    const tl = p[sums.indexOf(Math.min(...sums))];
    const br = p[sums.indexOf(Math.max(...sums))];
    const tr = p[diffs.indexOf(Math.max(...diffs))];
    const bl = p[diffs.indexOf(Math.min(...diffs))];

    return [tl, tr, br, bl];
  };

  const handleReset = () => {
    setPoints([]);
  };

  const handleConfirm = () => {
    if (points.length !== 4) {
      message.warning('请选择4个点');
      return;
    }
    const sorted = orderQuad(points);
    onSave(sorted);
  };

  const handleUseCandidate = (idx) => {
    if (candidates && candidates[idx]) {
      onSave(orderQuad(candidates[idx]));
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16 }}>
      <Space wrap style={{ marginBottom: 8 }}>
        {candidates.map((cand, idx) => (
          <Button 
            key={idx} 
            onClick={() => handleUseCandidate(idx)}
            style={{ 
              borderColor: idx === 0 ? '#00ff00' : '#0000ff', 
              color: idx === 0 ? 'green' : 'blue' 
            }}
          >
            采用候选{idx + 1} ({idx === 0 ? '绿色' : '蓝色'})
          </Button>
        ))}
      </Space>

      <canvas 
        ref={canvasRef} 
        onClick={handleCanvasClick}
        style={{ cursor: 'crosshair', border: '1px solid #ccc', boxShadow: '0 2px 8px rgba(0,0,0,0.1)' }}
      />
      
      <Space>
        <Button onClick={onCancel}>返回</Button>
        <Button onClick={handleReset} disabled={points.length === 0}>重置</Button>
        <Button type="primary" onClick={handleConfirm} disabled={points.length !== 4}>提交手动标注 (红色)</Button>
      </Space>
      
      <div style={{ color: '#666' }}>
        {points.length === 0 ? '点击图片上的4个角进行手动标注' : `已选择 ${points.length}/4 个点`}
      </div>
    </div>
  );
};

export default ReviewCanvas;
