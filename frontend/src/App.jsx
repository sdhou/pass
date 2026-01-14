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
    // Setting pages to empty will trigger useEffect cleanup for old pages
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
      message.success(`Successfully rendered ${newPages.length} pages`)
    } catch (error) {
      console.error(error)
      message.error('Failed to parse PDF')
    } finally {
      setLoading(false)
      setProgress(null)
    }

    return false // Prevent auto upload
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
        <Title level={3} style={{ color: 'white', margin: 0 }}>PDF Rotator</Title>
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
            <p className="ant-upload-text">Click or drag PDF file to this area to upload</p>
            <p className="ant-upload-hint">
              Support for a single PDF file.
            </p>
          </Dragger>

          {loading && (
            <div style={{ textAlign: 'center', margin: '50px 0' }}>
              <Spin
                size="large"
                tip={
                  progress
                    ? `Rendering ${progress.pageNumber}/${progress.numPages}...`
                    : 'Rendering PDF pages...'
                }
              />
            </div>
          )}

          {!loading && pages.length === 0 && <Empty description="No PDF loaded" />}

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
        PDF Rotator ©{new Date().getFullYear()}
      </Footer>
    </Layout>
  )
}

export default App
