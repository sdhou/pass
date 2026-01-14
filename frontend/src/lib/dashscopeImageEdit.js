function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('Failed to read image blob'))
    reader.onload = () => {
      if (typeof reader.result !== 'string') {
        reject(new Error('Unexpected FileReader result'))
        return
      }
      resolve(reader.result)
    }
    reader.readAsDataURL(blob)
  })
}

async function loadImage(src) {
  const img = new Image()
  img.decoding = 'async'
  img.src = src
  await img.decode()
  return img
}

export async function imageUrlToPngDataUrl(imageUrl) {
  const res = await fetch(imageUrl)
  if (!res.ok) {
    throw new Error(`Failed to fetch image: ${res.status}`)
  }
  const blob = await res.blob()
  return blobToDataUrl(blob)
}

export async function rotatedImageUrlToPngDataUrl(imageUrl, rotationDeg) {
  const img = await loadImage(imageUrl)

  const rad = (rotationDeg * Math.PI) / 180
  const absCos = Math.abs(Math.cos(rad))
  const absSin = Math.abs(Math.sin(rad))

  const w = img.naturalWidth
  const h = img.naturalHeight

  const canvasW = Math.max(1, Math.round(w * absCos + h * absSin))
  const canvasH = Math.max(1, Math.round(w * absSin + h * absCos))

  const canvas = document.createElement('canvas')
  canvas.width = canvasW
  canvas.height = canvasH

  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('Canvas 2D context not available')

  ctx.translate(canvasW / 2, canvasH / 2)
  ctx.rotate(rad)
  ctx.drawImage(img, -w / 2, -h / 2)

  const dataUrl = canvas.toDataURL('image/png')
  canvas.width = 0
  canvas.height = 0

  return dataUrl
}

export async function callDashscopeQwenImageEdit({
  apiKey,
  imageDataUrl,
  prompt,
  model = 'qwen-image-edit-plus',
  region = 'cn',
}) {
  if (!imageDataUrl) throw new Error('Missing image')
  if (!prompt) throw new Error('Missing prompt')

  const res = await fetch('/api/qwen-image-edit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      apiKey: apiKey || undefined,
      imageDataUrl,
      prompt,
      model,
      region,
    }),
  })

  const data = await res.json().catch(() => null)
  if (!res.ok) {
    const errMsg = data?.error || `HTTP ${res.status}`
    throw new Error(errMsg)
  }

  const imageUrl = data?.imageUrl
  if (!imageUrl) throw new Error('No image returned')

  return imageUrl
}
