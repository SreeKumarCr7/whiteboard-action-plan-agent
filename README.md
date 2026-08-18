# Whiteboard to Action Plan Agent

Photograph a meeting whiteboard or sticky-note wall and turn it into a structured, editable action plan (owners, due dates, priorities) — always with a mandatory human review step before anything is final. Every task is fully editable before it's exported, and the agent refuses to fabricate owners, due dates, or content that isn't actually written on the board.

Two independently deployable apps live in this repo:

- `backend/` — FastAPI (Python 3.11+), async endpoints. OCR via AWS Textract, LLM via Groq, research via Tavily.
- `frontend/` — React + Vite SPA.

## Architecture

The frontend drives a five-step backend pipeline, calling each endpoint in sequence and showing live progress:

| Step | Endpoint | What it does |
| --- | --- | --- |
| 1. OCR | `POST /api/ocr` | Accepts a base64 image, runs AWS Textract `DetectDocumentText`, returns raw text + per-line list. |
| 2. Clean notes | `POST /api/clean-notes` | Groq de-duplicates and splits OCR text into distinct notes, fixing only confident single-character OCR errors. |
| 3. Extract items | `POST /api/extract-items` | Groq extracts candidate action items (text, owner, due, priority) and flags unclear terms. Never invents owners/dates. |
| 4. Research terms | `POST /api/research-terms` | Conditionally called when unclear terms exist; looks each up via Tavily and returns a summary + source URL. |
| 5. Synthesize plan | `POST /api/synthesize-plan` | Groq produces the final structured plan (tasks, open questions, summary), using research only as clarifying context. |

Reliability guardrail: every LLM prompt instructs the model to never fabricate owners, due dates, or action items not clearly present in the notes — anything unclear goes into `open_questions` for the human to resolve.

## Live demo

_Pending deployment._ Link will go here.

## Deployed backend

_Pending deployment._ Base URL will go here.

## Local dev setup

### Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows
# .venv/bin/python -m pip install -r requirements.txt      # macOS/Linux
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

Health check: http://localhost:8000/health → `{"status":"ok"}`

Copy `backend/.env.example` to `backend/.env` and fill in the required credentials:

| Env var | Purpose |
| --- | --- |
| `AWS_ACCESS_KEY_ID` | AWS key for Textract (needs only `textract:DetectDocumentText`) |
| `AWS_SECRET_ACCESS_KEY` | AWS secret |
| `AWS_REGION` | e.g. `us-east-1` or `ap-south-1` |
| `GROQ_API_KEY` | Groq for note cleanup / extraction / synthesis |
| `TAVILY_API_KEY` | Tavily for unclear-term research |
| `ALLOWED_ORIGINS` | Comma-separated frontend origins allowed by CORS (default `http://localhost:5173`) |

**Required IAM permission:** the AWS key only needs `textract:DetectDocumentText` on the `DetectDocumentText` API. Attach this scoped-down policy instead of a broad one:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["textract:DetectDocumentText"],
      "Resource": "*"
    }
  ]
}
```

Textract does not support resource-level restrictions, so the only way to scope it down is to limit the actions to just `textract:DetectDocumentText` (no S3, no broader `textract:*`).

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 (Vite proxies `/api` → `http://localhost:8000` during dev).

In production, set `VITE_API_BASE_URL` to the deployed backend origin (see `frontend/.env.example`).

## Deployment

- **Frontend → Vercel.** Root directory: `frontend`. Build command `npm run build`, output `dist` (see `frontend/vercel.json`). Set env var `VITE_API_BASE_URL` to the deployed backend URL.
- **Backend → Render.** Blueprint is in `backend/render.yaml`. Set the secret env vars (`AWS_*`, `GROQ_API_KEY`, `TAVILY_API_KEY`, `ALLOWED_ORIGINS`) in the Render dashboard.


