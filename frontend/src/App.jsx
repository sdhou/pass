import { useState } from 'react'
import { Layout, Upload, message, Button, List, Card, Typography, Spin, Breadcrumb, Tag, Space } from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import ReviewCanvas from './components/ReviewCanvas'
import { api } from './lib/api'
import './App.css'

const { Header, Content, Footer } = Layout
const { Dragger } = Upload
const { Title, Text } = Typography

function App() {
  const [runId, setRunId] = useState(null)
  const [pages, setPages] = useState([])
  const [loading, setLoading] = useState(false)
  const [view, setView] = useState('upload')
  const [selectedPage, setSelectedPage] = useState(null)
  const [pageCandidates, setPageCandidates] = useState([])

  const handleUpload = async (file) => {
    setLoading(true)
    try {
      const data = await api.uploadPdf(file)
      setRunId(data.run_id)
      message.success('上传成功')
      await loadPages(data.run_id)
    } catch (error) {
      console.error(error)
      message.error('上传失败')
      setLoading(false)
    }
    return false
  }

  const loadPages = async (id) => {
    setLoading(true)
    try {
      const data = await api.getPages(id)
      const pageList = Array.isArray(data) ? data : (data.pages || [])
      setPages(pageList)
      setView('list')
    } catch (error) {
      console.error(error)
      message.error('加载页面失败')
    } finally {
      setLoading(false)
    }
  }

  const handleReview = async (page) => {
    setLoading(true)
    setSelectedPage(page)
    try {
      const data = await api.getPageViz(runId, page.page_number)
      setPageCandidates(data.candidates || [])
      setView('review')
    } catch (error) {
      console.error(error)
      message.error('加载页面详情失败')
    } finally {
      setLoading(false)
    }
  }

  const handleSaveLabel = async (points) => {
    try {
      await api.submitLabel(runId, selectedPage.page_number, points)
      message.success('标注已保存')
      setView('list')
      loadPages(runId)
    } catch (error) {
      console.error(error)
      message.error('保存标注失败')
    }
  }

  const handleBackToList = () => {
    setView('list')
    setSelectedPage(null)
    setPageCandidates([])
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 24px' }}>
        <Title level={4} style={{ color: 'white', margin: 0 }}>护照边界审核</Title>
        {runId && <span style={{ color: 'rgba(255,255,255,0.65)' }}>任务 ID: {runId}</span>}
      </Header>
      
      <Content style={{ padding: '24px 50px' }}>
        <div style={{ background: '#fff', padding: 24, minHeight: 280, borderRadius: 8 }}>
          
          {view === 'upload' && (
            <div style={{ maxWidth: 600, margin: '50px auto' }}>
              <Title level={3} style={{ textAlign: 'center', marginBottom: 32 }}>上传护照 PDF</Title>
              <Dragger
                accept=".pdf"
                beforeUpload={handleUpload}
                showUploadList={false}
                disabled={loading}
                height={200}
              >
                <p className="ant-upload-drag-icon">
                  <InboxOutlined />
                </p>
                <p className="ant-upload-text">点击或拖拽 PDF 文件到此区域上传</p>
              </Dragger>
              {loading && <div style={{ textAlign: 'center', marginTop: 24 }}><Spin size="large" /></div>}
            </div>
          )}

          {view === 'list' && (
            <div>
              <Breadcrumb style={{ marginBottom: 16 }} items={[{ title: '任务 ' + runId }, { title: '页面列表' }]} />
              
              {loading && pages.length === 0 ? (
                <div style={{ textAlign: 'center', padding: 50 }}><Spin /></div>
              ) : (
                <List
                  grid={{ gutter: 16, xs: 1, sm: 2, md: 2, lg: 2, xl: 2, xxl: 2 }}
                  dataSource={pages}
                  renderItem={(page) => (
                    <List.Item>
                      <Card
                        hoverable
                        style={{ cursor: 'pointer' }}
                        onClick={() => handleReview(page)}
                        cover={
                           <div style={{ height: 400, overflow: 'hidden', background: '#f0f0f0', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                             <img 
                               alt={`第 ${page.page_number} 页`} 
                               src={api.getPageImageUrl(runId, page.page_number)} 
                               style={{ width: '100%', height: '100%', objectFit: 'contain' }}
                               loading="lazy"
                             />
                           </div>
                        }
                      >
                        <Card.Meta 
                          title={`第 ${page.page_number} 页`} 
                          description={
                            <Space>
                              {page.status === 'labelled' ? <Tag color="success">已标注</Tag> : <Tag color="warning">待处理</Tag>}
                            </Space>
                          } 
                        />
                      </Card>
                    </List.Item>
                  )}
                />
              )}
            </div>
          )}

          {view === 'review' && selectedPage && (
            <div>
              <Breadcrumb style={{ marginBottom: 16 }} items={[
                { title: <a onClick={handleBackToList}>{'任务 ' + runId}</a> },
                { title: `第 ${selectedPage.page_number} 页` }
              ]} />
              
              <div style={{ textAlign: 'center', marginBottom: 16 }}>
                 <Title level={4}>审核并标注第 {selectedPage.page_number} 页</Title>
                 <Text type="secondary">审核候选框（绿色/蓝色）或点击 4 个点进行手动标注（红色）。</Text>
              </div>

              <ReviewCanvas 
                imageUrl={api.getPageImageUrl(runId, selectedPage.page_number)}
                candidates={pageCandidates}
                onSave={handleSaveLabel}
                onCancel={handleBackToList}
              />
            </div>
          )}

        </div>
      </Content>
      <Footer style={{ textAlign: 'center' }}>
        护照边界审核 ©{new Date().getFullYear()}
      </Footer>
    </Layout>
  )
}

export default App

