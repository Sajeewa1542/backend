# Hybrid Variation Evaluation API

Clean FastAPI backend prepared for Vercel serverless deployment.

## Files

- `index.py` - Vercel entrypoint; exports the FastAPI `app`.
- `vercel_app.py` - API routes and deterministic variation evaluation logic.
- `storage_manager.py` - lightweight JSON storage helper.
- `requirements.txt` - minimal Python dependencies.
- `vercel.json` - Vercel build and route configuration.

## Run Locally

```bash
pip install -r requirements.txt
uvicorn index:app --reload
```

Open:

- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8000/health`

## Deploy To Vercel

Vercel uses `index.py` as the Python function entrypoint.

```json
{
  "src": "index.py",
  "use": "@vercel/python"
}
```

The app supports temporary file uploads. On Vercel, files are written under `/tmp`; locally, files are written under `uploaded_files/`. CSV uploads for BOQ, rate breakdown, and schedule are parsed with Python's standard library. Excel, PDF, OCR, ML extraction, and report generation are intentionally not included in this clean Vercel backend.

## AI Chat

The `/chat` endpoint uses Groq for QS-style structured extraction when `GROQ_API_KEY` is configured. Set these locally in `.env` and in Vercel Environment Variables:

```env
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile
```

If Groq is not configured, `/chat` still returns deterministic candidate matches from uploaded CSV project data.

## Important Limitation

Project data is stored as JSON files locally. On Vercel, runtime storage is written to `/tmp`, which is temporary and not persistent between deployments or cold starts. This is acceptable only for short-lived request/session workflows.
