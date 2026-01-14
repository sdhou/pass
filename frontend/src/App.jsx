import { useState, useEffect } from 'react'
import { Upload, message, Layout, Row, Col, Typography, Empty, Spin, Input, Select, Button, Space } from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import PageCard from './components/PageCard'
import { renderPdfFileToPageImages, revokePdfPageImageUrls } from './lib/pdf'
import { rotatedImageUrlToPngDataUrl, callDashscopeQwenImageEdit } from './lib/dashscopeImageEdit'
import './App.css'

const { Header, Content, Footer } = Layout
const { Dragger } = Upload
const { Title } = Typography

function App() {
  const [pages, setPages] = useState([])
  const [loading, setLoading] = useState(false)
  const [progress, setProgress] = useState(null)
  const [rotations, setRotations] = useState({})
  const [apiKey, setApiKey] = useState(() => localStorage.getItem('dashscope_api_key') || '')
  const [region, setRegion] = useState('cn')
  const [processing, setProcessing] = useState(false)
  const [processingStatus, setProcessingStatus] = useState('')
  const [processedUrls, setProcessedUrls] = useState({})

  useEffect(() => {
    return () => {
      revokePdfPageImageUrls(pages)
    }
  }, [pages])

  useEffect(() => {
    localStorage.setItem('dashscope_api_key', apiKey)
  }, [apiKey])

  const handleUpload = async (file) => {
    setPages([])
    setRotations({})
    setProcessedUrls({})
    setProgress(null)
    setLoading(true)

    try {
      const newPages = await renderPdfFileToPageImages(file, {
        onProgress: ({ pageNumber, numPages }) => {
          setProgress({ pageNumber, numPages })
        },
      })
      setPages(newPages)
      setProgress(null)
      message.success(`已渲染 ${newPages.length} 页`)
    } catch (error) {
      console.error(error)
      message.error('解析 PDF 失败')
    } finally {
      setLoading(false)
      setProgress(null)
    }

    return false
  }

  const handleRotationChange = (pageNumber, newRotation) => {
    setRotations(prev => ({
      ...prev,
      [pageNumber]: newRotation
    }))
  }

  const handleProcess = async () => {
    if (!apiKey) {
      message.error('请输入 DashScope API Key')
      return
    }

    setProcessing(true)
    setProcessedUrls({})
    
    try {
      for (let i = 0; i < pages.length; i++) {
        const page = pages[i]
        const num = page.pageNumber
        setProcessingStatus(`正在处理第 ${num}/${pages.length} 页...`)
        
        try {
          const rotation = rotations[num] || 0
          
          const imageDataUrl = await rotatedImageUrlToPngDataUrl(page.url, rotation)
          
          const newImageUrl = await callDashscopeQwenImageEdit({
            apiKey,
            imageDataUrl,
            prompt: '用红线框出整本护照 护照可能是歪斜的',
            region,
          })
          
          setProcessedUrls(prev => ({
            ...prev,
            [num]: newImageUrl
          }))
          
          setRotations(prev => ({
            ...prev,
            [num]: 0
          }))
          
        } catch (err) {
          console.error(`Page ${num} error:`, err)
          const msg = err?.message || '未知错误'
          if (msg === 'Failed to fetch') {
            message.error('无法连接本地代理服务，请先启动代理')
          } else {
            message.error(`第 ${num} 页处理失败: ${msg}`)
          }
        }
      }
      message.success('处理完成')
    } catch (error) {
      console.error(error)
      message.error('处理过程中断')
    } finally {
      setProcessing(false)
      setProcessingStatus('')
    }
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header style={{ display: 'flex', alignItems: 'center', color: 'white' }}>
        <Title level={3} style={{ color: 'white', margin: 0 }}>PDF 旋转工具</Title>
      </Header>
      <Content style={{ padding: '24px 50px' }}>
        <div style={{ background: '#fff', padding: 24, minHeight: 280, borderRadius: 8 }}>
          
          <Dragger
            accept=".pdf"
            beforeUpload={handleUpload}
            showUploadList={false}
            disabled={loading || processing}
            style={{ marginBottom: 24 }}
          >
            <p className="ant-upload-drag-icon">
              <InboxOutlined />
            </p>
            <p className="ant-upload-text">点击或拖拽 PDF 文件到此处</p>
            <p className="ant-upload-hint">仅支持单个 PDF 文件</p>
          </Dragger>

          {pages.length > 0 && (
            <div style={{ marginBottom: 24, padding: '16px', border: '1px solid #f0f0f0', borderRadius: '8px' }}>
              <Space wrap>
                <Input.Password
                  placeholder="请输入 DashScope API Key"
                  value={apiKey}
                  onChange={e => setApiKey(e.target.value)}
                  style={{ width: 200 }}
                  disabled={processing}
                />
                <Select
                  value={region}
                  onChange={setRegion}
                  options={[
                    { value: 'cn', label: '国内 (CN)' },
                    { value: 'intl', label: '国际 (Intl)' },
                  ]}
                  disabled={processing}
                  style={{ width: 120 }}
                />
                <Button 
                  type="primary" 
                  onClick={handleProcess} 
                  loading={processing}
                  disabled={!apiKey}
                >
                  {processing ? '处理中...' : '处理 (红线框选护照)'}
                </Button>
                {processingStatus && <span>{processingStatus}</span>}
              </Space>
            </div>
          )}

          {loading && (
            <div style={{ textAlign: 'center', margin: '50px 0' }}>
              <Spin
                size="large"
                tip={
                  progress
                    ? `正在渲染 ${progress.pageNumber}/${progress.numPages}...`
                    : '正在渲染 PDF 页面...'
                }
              />
            </div>
          )}

          {!loading && pages.length === 0 && <Empty description="暂无 PDF" />}

          {!loading && pages.length > 0 && (
            <Row gutter={[16, 16]}>
              {pages.map((page) => (
                <Col xs={24} md={12} key={page.pageNumber}>
                    <PageCard
                      pageNumber={page.pageNumber}
                      imageUrl={processedUrls[page.pageNumber] || page.url}
                      rotationDeg={rotations[page.pageNumber] || 0}
                      onRotationChange={(deg) => handleRotationChange(page.pageNumber, deg)}
                      disabled={processing}
                    />
                </Col>
              ))}
            </Row>
          )}
        </div>
      </Content>
      <Footer style={{ textAlign: 'center' }}>
        PDF 旋转工具 ©{new Date().getFullYear()}
      </Footer>
    </Layout>
  )
}

export default App
