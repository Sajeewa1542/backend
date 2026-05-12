# Hybrid Variation Evaluation Prototype

This project is a beginner-friendly research prototype for evaluating construction variation proposals. It uses ML-assisted extraction to help identify likely BOQ items, rate sources, and schedule activities, then uses deterministic rules to calculate the final cost and time impact after the user confirms the evidence.

## Start Here

If you are new to the system, read the beginner guide first:

- [User Manual](USER_MANUAL.md)

If you want a short example of how the workflow behaves in practice, see [user_flow.md](user_flow.md).

## What The System Does

The application helps a QS or project user:

- upload BOQ, rate breakdown, schedule, and supporting documents
- extract possible matches from the uploaded files
- review the extracted candidates and confirm the correct source data
- calculate the variation cost and time impact
- generate a proposal PDF with formulas, evidence, and validation notes

The system keeps the final evaluation deterministic. The AI only assists with extraction and matching; it does not make the final calculation.

## Main Folders

- [backend](backend) contains the FastAPI service, storage layer, and evaluation engine.
- [frontend](frontend) contains the React application used by the user.
- [tests](tests) contains backend tests for the variation workflow.
- [uploaded_files](uploaded_files) stores uploaded project documents during development.

## Quick Setup

You can run the project with Docker or with local development tools. **Local development is the current working setup.**

### ✅ Local Development (Currently Working)

#### Prerequisites
- Python 3.10+ (tested with Python 3.13.7)
- Node.js 18+ (for frontend)
- Git

#### Step 1: Clone and Install Backend Dependencies
```bash
cd path/to/Hybrid-Chatbot-for-Evaluation-of-Variation-Proposals
pip install -r backend/requirements.txt
```

#### Step 2: Configure Backend Environment
Create or verify `backend/.env` with your Groq API key:
```env
GROQ_API_KEY=your_groq_api_key_here
```

#### Step 3: Start Backend Server (Terminal 1)
```bash
python -m backend.main
```
The backend will start on `http://localhost:8000`

You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Application startup complete.
```

#### Step 4: Configure Frontend Environment (if needed)
Verify `frontend/.env` contains:
```env
VITE_API_BASE_URL=http://localhost:8000
GROQ_API_KEY=your_groq_api_key_here
```

#### Step 5: Start Frontend Server (Terminal 2)
```bash
cd frontend
npm install  # Only needed first time
npm run dev
```
The frontend will start on `http://localhost:5174`

You should see:
```
VITE v7.3.1  ready in 515 ms
➜  Local:   http://localhost:5174/
```

#### Access the Application
Open your browser and navigate to: **`http://localhost:5174`**

---

### Docker Setup

1. Install Docker Desktop.
2. Create a `.env` file in the [backend](backend) folder with your Groq API key.
3. Run `docker-compose up --build` from the project root.
4. For subsequent runs: `docker-compose up` from the project root.

---

## Default URLs (Local Development)

- **Frontend Application**: `http://localhost:5174/`
- **Backend API**: `http://localhost:8000`
- **API Documentation**: `http://localhost:8000/docs` (Swagger UI)
- **API ReDoc**: `http://localhost:8000/redoc`

## Typical Workflow

1. Create or open a project.
2. Upload the BOQ, schedule, rate breakdown, and any supporting evidence.
3. Review the extracted candidates shown by the system.
4. Confirm the correct BOQ item, rate source, productivity source, and variation mode.
5. Generate the evaluation result.
6. Download the proposal PDF if needed.

## Project Status

The current codebase includes:

- string-safe project and session handling
- rate extraction from PDF, CSV, and spreadsheet files
- candidate ranking for BOQ, rate, and quotation sources
- deterministic cost and time evaluation
- PDF proposal generation
- a React workflow for upload, confirmation, sessions, and results

## Notes

This repository is intended for research and demonstration use. It is not a substitute for professional QS review, contract administration, or legal advice.
