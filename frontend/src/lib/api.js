export const api = {
  async uploadPdf(file) {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch('/api/runs', {
      method: 'POST',
      body: formData,
    });
    if (!res.ok) throw new Error('Upload failed');
    return res.json(); // returns { run_id: ... }
  },

  async getRun(runId) {
    const res = await fetch(`/api/runs/${runId}`);
    if (!res.ok) throw new Error('Get run failed');
    return res.json();
  },

  async getPages(runId) {
    const res = await fetch(`/api/runs/${runId}/pages`);
    if (!res.ok) throw new Error('Get pages failed');
    return res.json(); // returns { pages: [ { page_number: 1, status: '...' }, ... ] }
  },

  async getPageViz(runId, pageNumber) {
    const res = await fetch(`/api/runs/${runId}/pages/${pageNumber}/viz`);
    if (!res.ok) throw new Error('Get viz failed');
    return res.json(); // returns { candidates: [...] }
  },

  async submitLabel(runId, pageNumber, points) {
    const res = await fetch(`/api/runs/${runId}/pages/${pageNumber}/label`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ points }),
    });
    if (!res.ok) throw new Error('Submit label failed');
    return res.json();
  },

  getPageImageUrl(runId, pageNumber) {
    return `/api/runs/${runId}/pages/${pageNumber}/image`;
  }
};
