import http from 'node:http'

const PORT = Number(process.env.PORT || 8787)

function readJson(req, maxBytes = 25 * 1024 * 1024) {
  return new Promise((resolve, reject) => {
    let size = 0
    let body = ''

    req.setEncoding('utf8')
    req.on('data', (chunk) => {
      size += chunk.length
      if (size > maxBytes) {
        reject(new Error('Payload too large'))
        req.destroy()
        return
      }
      body += chunk
    })

    req.on('end', () => {
      try {
        resolve(body ? JSON.parse(body) : {})
      } catch {
        reject(new Error('Invalid JSON'))
      }
    })

    req.on('error', reject)
  })
}

function sendJson(res, statusCode, data) {
  const text = JSON.stringify(data)
  res.writeHead(statusCode, {
    'Content-Type': 'application/json; charset=utf-8',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  })
  res.end(text)
}

async function dashscopeImageEdit({ apiKey, region, model, imageDataUrl, prompt }) {
  const origin = region === 'intl' ? 'https://dashscope-intl.aliyuncs.com' : 'https://dashscope.aliyuncs.com'
  const url = `${origin}/api/v1/services/aigc/multimodal-generation/generation`

  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model,
      input: {
        messages: [
          {
            role: 'user',
            content: [{ image: imageDataUrl }, { text: prompt }],
          },
        ],
      },
      parameters: {
        n: 1,
        watermark: false,
        prompt_extend: false,
      },
    }),
  })

  const data = await res.json().catch(() => null)
  if (!res.ok) {
    const errMsg = data?.message || `HTTP ${res.status}`
    const errCode = data?.code
    const message = errCode ? `${errCode}: ${errMsg}` : errMsg
    const error = new Error(message)
    error.statusCode = res.status
    error.dashscope = data
    throw error
  }

  const content = data?.output?.choices?.[0]?.message?.content
  const imageUrl = Array.isArray(content) ? content.find((c) => c?.image)?.image : null
  if (!imageUrl) {
    const error = new Error('No image returned')
    error.statusCode = 502
    error.dashscope = data
    throw error
  }

  return { imageUrl, raw: data }
}

const server = http.createServer(async (req, res) => {
  if (req.method === 'OPTIONS') {
    res.writeHead(204, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    })
    res.end()
    return
  }

  if (req.method !== 'POST' || req.url !== '/api/qwen-image-edit') {
    sendJson(res, 404, { error: 'Not found' })
    return
  }

  try {
    const body = await readJson(req)

    const region = body?.region === 'intl' ? 'intl' : 'cn'
    const model = typeof body?.model === 'string' && body.model ? body.model : 'qwen-image-edit-plus'
    const imageDataUrl = body?.imageDataUrl
    const prompt = body?.prompt

    const envKey = region === 'intl' ? process.env.DASHSCOPE_API_KEY_INTL : process.env.DASHSCOPE_API_KEY
    const apiKey = typeof body?.apiKey === 'string' && body.apiKey ? body.apiKey : envKey

    if (!apiKey) {
      sendJson(res, 400, { error: 'Missing API Key' })
      return
    }
    if (!imageDataUrl || typeof imageDataUrl !== 'string') {
      sendJson(res, 400, { error: 'Missing imageDataUrl' })
      return
    }
    if (!prompt || typeof prompt !== 'string') {
      sendJson(res, 400, { error: 'Missing prompt' })
      return
    }

    const result = await dashscopeImageEdit({ apiKey, region, model, imageDataUrl, prompt })
    sendJson(res, 200, { imageUrl: result.imageUrl })
  } catch (err) {
    const statusCode = Number(err?.statusCode) || 500
    sendJson(res, statusCode, { error: err?.message || 'Request failed' })
  }
})

server.listen(PORT)
