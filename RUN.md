# Running the Passport Processor

This project consists of a **FastAPI backend** for image processing and a **React frontend** for the user interface.

## Prerequisites

- **Python 3.11+**
- **Node.js 18+**
- **PyMuPDF** is used to split PDFs (no poppler needed)

## Installation

1. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt -r backend/requirements.txt
   ```

2. **Install Frontend dependencies:**
   ```bash
   cd frontend
   npm install
   ```

## Running the Application

### 1. Start the Backend (FastAPI)

The backend handles PDF splitting, image processing, and task management.

```bash
# From the project root
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

- **Entry Point:** `backend/main.py`
- **Port:** `8000` (The frontend is configured to proxy `/api` requests to this port)
- **Environment Variables:** Ensure `DASHSCOPE_API_KEY` is set in your environment or `.env` file.

### 2. Start the Frontend (Vite + React)

The frontend provides the UI for uploading PDFs and reviewing results.

```bash
cd frontend
npm run dev
```

- **URL:** `http://localhost:5173`
- **Features:** PDF upload, candidate boundary overlays, and manual 4-corner labeling.


## API Endpoints Overview

The frontend communicates with the backend via these primary endpoints:

- `POST /api/runs`: Upload a PDF file and start a new processing run.
- `GET /api/runs/{run_id}/pages`: Get a list of extracted pages for a run.
- `GET /api/runs/{run_id}/pages/{page_num}/image`: Get the image for a specific page.
- `GET /api/runs/{run_id}/pages/{page_num}/viz`: Get AI/CV boundary candidates.
- `POST /api/runs/{run_id}/pages/{page_num}/label`: Save a manual boundary label.

## Typical User Flow

1. **Upload PDF:** Drag and drop a passport PDF into the upload area.
2. **Review Pages:** The PDF is split into individual pages, which are displayed as cards.
3. **Review Candidates:** Open a page to see AI/CV candidate quads (the backend calls Qwen on-demand when you open a page).
4. **Manual Labeling:** Click 4 corner points and submit. The system is conservative: it prefers manual labels over risky auto-crops.

## Output Storage

Processing results and intermediate files are stored in:
- `backend/data/runs/<run_id>/pages/`: Extracted page images (`.png`) and page metadata (`.json`).
- `backend/data/runs/<run_id>/masks/`: Saved masks with final red quad overlay.
