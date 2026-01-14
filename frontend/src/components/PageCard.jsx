import { Button, Card, Slider, Space } from 'antd'
import { RotateLeftOutlined, RotateRightOutlined } from '@ant-design/icons'

export default function PageCard({
  pageNumber,
  imageUrl,
  rotationDeg,
  onRotationChange,
}) {
  const normalized = ((rotationDeg % 360) + 360) % 360

  const anchor = Math.round(rotationDeg / 90) * 90
  const fineAdjustment = rotationDeg - anchor

  const rotate90 = (direction) => {
    const delta = direction === 'right' ? 90 : -90
    onRotationChange(rotationDeg + delta)
  }

  return (
    <Card
      title={`Page ${pageNumber}`}
      size="small"
      styles={{ body: { display: 'flex', flexDirection: 'column', gap: 12 } }}
    >
      <div style={{ width: '100%', overflow: 'hidden', display: 'flex', justifyContent: 'center', backgroundColor: '#f0f0f0', borderRadius: 4 }}>
        <img
          src={imageUrl}
          alt={`Page ${pageNumber}`}
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
          >
            -90°
          </Button>
          <Button
            icon={<RotateRightOutlined />}
            onClick={() => rotate90('right')}
          >
            +90°
          </Button>

          <span>Angle: {rotationDeg.toFixed(1)}°</span>
        </Space>

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
        />
      </Space>
    </Card>
  )
}
