import { useState, useEffect } from 'react'
import { Upload, message, Layout, Row, Col, Typography, Empty, Spin } from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import PageCard from './components/PageCard'
import { renderPdfFileToPageImages, revokePdfPageImageUrls } from './lib/pdf'
import './App.css'

const { Header, Content, Footer } = Layout
const { Dragger } = Upload
const { Title } = Typography

function App() {
  const [pages, setPages] = useState([])
  const [loading, setLoading] = useState(false)
  const [progress, setProgress] = useState(null)
  const [rotations, setRotations] = useState({})

  useEffect(() => {
    return () => {
      revokePdfPageImageUrls(pages)
    }
  }, [pages])

  const handleUpload = async (file) => {
    setPages([])
    setRotations({})
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
            disabled={loading}
            style={{ marginBottom: 24 }}
          >
            <p className="ant-upload-drag-icon">
              <InboxOutlined />
            </p>
            <p className="ant-upload-text">点击或拖拽 PDF 文件到此处</p>
            <p className="ant-upload-hint">仅支持单个 PDF 文件</p>
          </Dragger>

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
                    imageUrl={page.url}
                    rotationDeg={rotations[page.pageNumber] || 0}
                    onRotationChange={(deg) => handleRotationChange(page.pageNumber, deg)}
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
