import { Button, Card, Slider, Space } from 'antd'
import { MinusOutlined, PlusOutlined, RotateLeftOutlined, RotateRightOutlined } from '@ant-design/icons'

export default function PageCard({
  pageNumber,
  imageUrl,
  rotationDeg,
  onRotationChange,
  disabled = false,
}) {
  const normalized = ((rotationDeg % 360) + 360) % 360

  const anchor = Math.round(rotationDeg / 90) * 90
  const fineAdjustment = rotationDeg - anchor

  const rotate90 = (direction) => {
    const delta = direction === 'right' ? 90 : -90
    onRotationChange(rotationDeg + delta)
  }

  const handleFineNudge = (delta) => {
    const newFine = Math.min(Math.max(fineAdjustment + delta, -45), 45)
    onRotationChange(anchor + newFine)
  }

  return (
    <Card
      title={`第 ${pageNumber} 页`}
      size="small"
      styles={{ body: { display: 'flex', flexDirection: 'column', gap: 12 } }}
    >
      <div style={{ width: '100%', overflow: 'hidden', display: 'flex', justifyContent: 'center', backgroundColor: '#f0f0f0', borderRadius: 4 }}>
        <img
          src={imageUrl}
          alt={`第 ${pageNumber} 页`}
          style={{
            maxWidth: '100%',
            maxHeight: 300,
            transform: `rotate(${normalized}deg)`,
            transformOrigin: 'center center',
            transition: 'transform 0.3s ease',
          }}
        />
      </div>

      <Space direction="vertical" size="small" style={{ width: '100%' }}>
        <Space align="center" wrap style={{ justifyContent: 'center', width: '100%' }}>
          <Button
            icon={<RotateLeftOutlined />}
            onClick={() => rotate90('left')}
            disabled={disabled}
          >
            -90°
          </Button>
          <Button
            icon={<RotateRightOutlined />}
            onClick={() => rotate90('right')}
            disabled={disabled}
          >
            +90°
          </Button>

          <span>角度：{rotationDeg.toFixed(1)}°</span>
        </Space>

        <div style={{ display: 'flex', alignItems: 'center', width: '100%' }}>
          <Button icon={<MinusOutlined />} onClick={() => handleFineNudge(-1)} disabled={disabled} />
          <div style={{ flex: 1, margin: '0 12px' }}>
            <Slider
              min={-45}
              max={45}
              step={0.5}
              marks={{ 0: '0°' }}
              value={fineAdjustment}
              tooltip={{ formatter: (val) => `${val > 0 ? '+' : ''}${val}°` }}
              onChange={(value) => {
                if (typeof value === 'number') onRotationChange(anchor + value)
              }}
              disabled={disabled}
            />
          </div>
          <Button icon={<PlusOutlined />} onClick={() => handleFineNudge(1)} disabled={disabled} />
        </div>
      </Space>
    </Card>
  )
}
