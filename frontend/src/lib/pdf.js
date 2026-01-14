import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist'
import workerSrc from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

GlobalWorkerOptions.workerSrc = workerSrc

function toBlob(canvas, type = 'image/png', quality) {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (!blob) {
          reject(new Error('Failed to convert canvas to Blob'))
          return
        }
        resolve(blob)
      },
      type,
      quality,
    )
  })
}

export async function renderPdfFileToPageImages(file, options = {}) {
  const { scale = 1.8, signal, onProgress } = options

  const arrayBuffer = await file.arrayBuffer()
  const loadingTask = getDocument({ data: new Uint8Array(arrayBuffer) })

  if (signal) {
    if (signal.aborted) {
      loadingTask.destroy()
      throw new DOMException('Aborted', 'AbortError')
    }

    signal.addEventListener(
      'abort',
      () => {
        loadingTask.destroy()
      },
      { once: true },
    )
  }

  const pdf = await loadingTask.promise
  const results = []

  try {
    for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
      if (signal?.aborted) {
        throw new DOMException('Aborted', 'AbortError')
      }

      const page = await pdf.getPage(pageNumber)
      const viewport = page.getViewport({ scale })

      const canvas = document.createElement('canvas')
      canvas.width = Math.ceil(viewport.width)
      canvas.height = Math.ceil(viewport.height)

      const ctx = canvas.getContext('2d', { alpha: false })
      if (!ctx) throw new Error('Canvas 2D context not available')

      await page.render({ canvasContext: ctx, viewport }).promise

      const blob = await toBlob(canvas)
      const url = URL.createObjectURL(blob)

      results.push({
        pageNumber,
        url,
        width: canvas.width,
        height: canvas.height,
      })

      page.cleanup?.()

      canvas.width = 0
      canvas.height = 0

      onProgress?.({ pageNumber, numPages: pdf.numPages })
    }

    return results
  } finally {
    pdf.destroy?.()
  }
}

export function revokePdfPageImageUrls(pages) {
  for (const page of pages) {
    if (page?.url) URL.revokeObjectURL(page.url)
  }
}
