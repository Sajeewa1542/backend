# Backend Service

This folder contains the FastAPI backend for the hybrid variation evaluation prototype. The backend accepts uploads, extracts rate and activity candidates, stores project data in JSON files, and runs the deterministic evaluation after the user confirms the evidence.

## Run Locally

1. Install the Python dependencies.
2. Add a `.env` file with your `GROQ_API_KEY` if you want AI-assisted extraction.
3. Start the app with `python -m backend.main`.

The API is served from `http://127.0.0.1:8000` by default.

## Main Responsibilities

- accept BOQ, schedule, rate breakdown, quotation, and supporting document uploads
- extract structured rate sources from PDFs, CSV files, and spreadsheets
- rank candidate BOQ items, rates, and schedule activities
- store project sessions and variation results in JSON files
- generate proposal PDFs for download
- generate proposal DOCX reports for download (PDF optional)

## Key Modules

- [main.py](main.py): API routes and orchestration
- [storage_manager.py](storage_manager.py): JSON persistence and lookup helpers
- [rate_source_extractor.py](rate_source_extractor.py): structured rate extraction from uploaded files
- [rate_resolver.py](rate_resolver.py): candidate ranking and source selection
- [variation_evaluator.py](variation_evaluator.py): final deterministic cost and time evaluation
- [engine.py](engine.py): cost formulas and CPM-based time impact logic
- [validation_engine.py](validation_engine.py): validation and warning checks
- [pdf_utils.py](pdf_utils.py): proposal PDF generation
- [ml_model.py](ml_model.py): extraction prompt and structured matching guidance

## Important Endpoints

- `GET /health`: service health check
- `POST /upload/files`: upload project files
- `POST /upload/additional-files`: upload supporting documents later
- `POST /chat`: request extraction and candidate matching
- `POST /variation/{project_id}/confirm-and-evaluate`: run the confirmed evaluation
- `GET /download/{filename}`: download generated PDF reports

## Data Storage

The backend stores project data under `backend/data/`:

- `projects_index.json`: list of known projects
- `project_{id}.json`: stored BOQ, schedule, variations, and related metadata

Uploaded source files are kept in the local upload folders during development, and generated PDF reports are written to the backend report output directory.

## Notes For Developers

- The final cost and time calculation is deterministic.
- The backend uses AI only for extraction and candidate matching.
- String-safe project, BOQ, and activity references are important for this workflow.
- Activity matching can use a keyword normalization map stored either in the project JSON as `keyword_normalization_map` or in `backend/keyword_normalization_map.json`.
