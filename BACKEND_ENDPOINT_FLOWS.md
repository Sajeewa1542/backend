# Backend Endpoint Flows - Detailed Mapping

**Project**: Hybrid Variation Evaluation Prototype  
**Backend**: FastAPI (Python) on port 8000  
**Data Store**: JSON files in `backend/data/` (project_<id>.json + projects_index.json)  
**Document Date**: May 2026

---

## Overview: Request → Handler → Services → Storage → Response

Each endpoint follows a consistent pattern:
1. **Request arrives** at FastAPI route
2. **Validation** of input (models, dependencies)
3. **Invoke services** (ML, engines, managers)
4. **Persist/query** data via StorageManager
5. **Return normalized response**

---

## Endpoint Reference (12 Total)

### Group 1: Health & Static Info (2 endpoints)
1. `GET /` - Root/status
2. `GET /health` - Health check

### Group 2: File Upload & Processing (3 endpoints)
3. `POST /upload/files` - Upload BOQ, Rate Breakdown, Schedule
4. `POST /upload/additional-files` - Upload BSR/HSR/Quotations
5. `GET /projects` - List all projects

### Group 3: Session Management (3 endpoints)
6. `POST /session/create` - Create conversation session
7. `GET /session/{project_id}/{session_id}` - Get session context
8. `POST /session/{project_id}/{session_id}/continue` - Resume session
9. `POST /session/{project_id}/{session_id}/close` - End session

### Group 4: Chat & Variation (3 endpoints)
10. `POST /chat` - FIDIC workflow chat with ML extraction
11. `POST /variation/{project_id}/confirm-and-evaluate` - Deterministic evaluation after human confirmation
12. `POST /generate-pdf` - Generate variation proposal PDF

### Supporting Endpoints (Not in main 12 but present)
- `GET /variation-types` - Static FIDIC type definitions
- `GET /variation/{project_id}/{variation_id}` - Get variation details
- `GET /download/{filename}` - Download generated PDF/DOCX
- Debug endpoints: `/debug/project/{id}`, etc.

---

## Detailed Endpoint Flows

### ✅ 1. GET /
**Purpose**: Root endpoint, returns API info  
**Input**: None  
**Output**: 
```json
{
  "message": "Hybrid Rule-Based and ML-Assisted Variation Evaluation Prototype",
  "version": "2.0.0",
  "status": "running"
}
```
**Services Invoked**: None (static)  
**Storage Access**: None

---

### ✅ 2. GET /health
**Purpose**: Health check, used for probing  
**Input**: None  
**Output**:
```json
{
  "status": "healthy",
  "timestamp": "2026-05-15T00:24:36Z"
}
```
**Services Invoked**: None  
**Storage Access**: None

---

### ✅ 3. POST /upload/files
**Purpose**: Upload core project files (BOQ, Rate Breakdown, Schedule)  
**Input**:
```
Files: 
- boq: Excel/CSV with columns [description, qty, unit, rate]
- breakdown: Excel/CSV/PDF with rate items
- schedule: Excel/CSV with activities
```

**Request Flow**:
```
1. Validate file formats (CSV/Excel)
2. Create project in storage via StorageManager.create_project()
3. Create default session
4. For each file:
   a. Save to uploaded_files/
   b. Invoke CostEngine.load_boq() → parses Excel/CSV
   c. Invoke TimeEngine.parse_schedule() → extracts activities with CPM data
   d. Store parsed items via StorageManager.add_boq_items(), add_rate_breakdowns(), add_activities()
5. If Rate Breakdown is PDF → OCRProcessor.process_pdf() first
6. Return counts and metadata
```

**Output**:
```json
{
  "status": "success",
  "data": {
    "project_id": 1,
    "session_id": 1,
    "session_key": "unique_key",
    "boq_items": 42,
    "rate_breakdowns": 15,
    "schedule_tasks": 28,
    "processing_notes": ["✓ BOQ processed: 42 items...", ...]
  }
}
```

**Services Invoked**:
- `StorageManager.create_project()` → Creates JSON file + updates index
- `CostEngine.validate_boq_file()` → Checks structure
- `CostEngine.load_boq()` → Parses Excel/CSV → List[Dict]
- `TimeEngine.parse_schedule()` → Extracts activities, calculates CPM
- `OCRProcessor.process_pdf()` → If rate breakdown is PDF
- `SessionManager.create_session()` → Initializes conversation session

**Storage Mutations**:
- Creates: `backend/data/project_<id>.json` with populated boq_items, rate_breakdowns, activities
- Updates: `backend/data/projects_index.json` with new project entry

**Key Logic**:
- BOQ validation looks for headers containing ['desc', 'qty', 'unit', 'rate']
- Schedule parsing calls `TimeEngine.calculate_cpm()` for critical path
- Rate breakdown stored twice: once as rate_breakdowns, once as rate_sources (for resolver)

---

### ✅ 4. POST /upload/additional-files
**Purpose**: Upload supporting docs (BSR, HSR, Quotations, Drawings) for variation evaluation  
**Input**:
```
Form Data:
- project_id: int (required)
- variation_id: str (optional)
- file_type: str ('bsr', 'hsr', 'quotation', 'specification', 'drawing', 'rate_breakdown')
- files: List[UploadFile] (required)
```

**Request Flow**:
```
1. For each file:
   a. Save to uploaded_files/additional/
   b. Create file record in storage
   c. If file_type in {bsr, hsr, quotation, rate_breakdown}:
      - Invoke rate_source_extractor.extract_from_file()
      - Parse extracted items via StorageManager.add_rate_sources()
   d. Return file metadata + extracted preview
```

**Output**:
```json
{
  "status": "success",
  "files_uploaded": 2,
  "rate_sources_extracted": 8,
  "preview": [
    {"source_type": "BSR", "rate": 150.0, "description": "..."}
  ],
  "files": [
    {
      "filename": "bsr_rates.pdf",
      "type": "bsr",
      "size": 52340,
      "rate_sources_extracted": 5,
      "preview": [...]
    }
  ]
}
```

**Services Invoked**:
- `RateSourceExtractor.extract_from_file()` → OCR or structured parsing
- `StorageManager.add_rate_sources()` → Stores parsed rates for resolver

**Storage Mutations**:
- Adds records to project["rate_sources"] and project["additional_files"]

---

### ✅ 5. GET /projects
**Purpose**: List all projects with metadata  
**Input**: None  
**Output**:
```json
{
  "projects": [
    {
      "id": 1,
      "name": "Parking Expansion",
      "created_at": "2026-05-15T...",
      "boq_items": 42,
      "rate_breakdowns": 15,
      "activities": 28
    }
  ]
}
```

**Services Invoked**:
- `StorageManager.get_projects()` → Reads projects_index.json + aggregates counts from each project file

---

### ✅ 6. GET /variation-types
**Purpose**: Return FIDIC variation types (static, for frontend dropdown)  
**Input**: None  
**Output**:
```json
{
  "variation_types": [
    {
      "id": 1,
      "code": "TYPE1",
      "name": "Quantity Changes",
      "evaluation_mode": "quantity_change",
      "description": "Changes in quantity..."
    },
    // TYPE2-TYPE6...
  ]
}
```

**Services Invoked**: None (hardcoded)

---

### ✅ 7. POST /session/create
**Purpose**: Create a new conversation session for a project  
**Input**:
```json
{
  "project_id": 1,
  "metadata": {
    "custom_key": "value"
  }
}
```

**Request Flow**:
```
1. StorageManager.create_session(project_id, metadata)
   a. Load project from storage
   b. Create session object with unique session_key (uuid)
   c. Add to project["sessions"] array
   d. Save project back
2. Return session object
```

**Output**:
```json
{
  "id": 1,
  "session_key": "uuid-string",
  "project_id": 1,
  "status": "active",
  "created_at": "2026-05-15T...",
  "session_metadata": {},
  "chat_history": []
}
```

**Storage Mutations**:
- Appends session to project["sessions"]

---

### ✅ 8. GET /session/{project_id}/{session_id}
**Purpose**: Retrieve session context (history, variation state)  
**Input**: project_id, session_id in path  
**Output**:
```json
{
  "session_id": 1,
  "session_key": "uuid",
  "project_id": 1,
  "status": "active",
  "created_at": "...",
  "metadata": {},
  "conversation_history": [
    {"role": "user", "content": "..."},
    {"role": "ai", "content": "..."}
  ],
  "variations_count": 1,
  "variations": [...]
}
```

**Services Invoked**:
- `SessionManager.get_session_context()` → Assembles full context from storage

---

### ✅ 9. POST /session/{project_id}/{session_id}/continue
**Purpose**: Resume an inactive/closed session  
**Input**: project_id, session_id in path  
**Output**:
```json
{
  "status": "success",
  "context": {
    "session_id": 1,
    ...
  }
}
```

**Request Flow**:
```
1. Get session
2. If status != "active", set status = "active"
3. Return full session context
```

---

### ✅ 10. POST /session/{project_id}/{session_id}/close
**Purpose**: Mark session as completed  
**Input**: project_id, session_id  
**Output**:
```json
{
  "status": "success",
  "message": "Session closed"
}
```

**Storage Mutations**:
- Sets session["status"] = "completed"

---

### ⭐ 11. POST /chat - **Core FIDIC Workflow**
**Purpose**: ML-assisted extraction + candidate ranking (NO evaluation here)  
**Input**:
```json
{
  "message": "The excavation work increases from 1000 m3 to 1500 m3. Use rate RB/19.",
  "project_id": 1,
  "session_id": 1
}
```

**Request Flow** (Complex - 15+ steps):

```
PHASE 1: Initialize
─────────────────
1. Get or create session
2. Save user message to chat history
3. Retrieve project from storage

PHASE 2: ML Model Training
──────────────────────────
4. CostEngine.train_model(project_id)
   → Fits TF-IDF vectorizer on BOQ descriptions
   → Stores in MLModel.tfidf_matrix

PHASE 3: Context Building
──────────────────────────
5. Build search query from user message + session history
6. CostEngine.ml_model.find_similar_items(query, top_n=20)
   → Use TF-IDF to rank BOQ items by relevance
   → Returns: [{"description": "...", "similarity_score": 0.85}, ...]

7. TimeEngine.identify_relevant_activities(query, project_activities, normalization_map)
   → Tokenize query using keyword_normalization_map
   → Match activity names using token overlap + deterministic trade rules
   → Returns top 5 activity candidates

PHASE 4: Groq LLM Extraction
────────────────────────────
8. MLModel.parse_instruction(message, project_context, chat_history, session_metadata)
   → Sends to Groq/Qwen via API call
   → Workflow state determines prompt:
      - If no variation_type → ask user to select TYPE1-6
      - If collecting_details → extract quantities, BOQ refs, rate refs, activity names, supporting docs
   → Returns JSON:
      {
        "reply": "Based on your input...",
        "workflow_state": "collecting_details",
        "affected_boq_candidates": [{"description": "...", "similarity_score": 0.75}],
        "affected_activity_candidates": [],
        "original_quantity": 1000,
        "new_quantity": 1500,
        "unit": "m3",
        "rate_evidence_candidates": [{"source_type": "rate_breakdown", "rate": 150}],
        "requires_human_confirmation": true
      }

PHASE 5: Fallback Matching
──────────────────────────
9. If AI candidates incomplete → use deterministic TF-IDF matches as fallback

10. Extract rate reference from message (e.g., "RB/19")

11. RateResolver.resolve_rate(project_id, query, unit, preferred_work_type)
    → Priority order:
       a. Exact BOQ match by reference
       b. Similar BOQ items (TF-IDF)
       c. Exact rate source match (BSR/HSR/Quotation reference)
       d. Similar rate sources (TF-IDF)
    → Returns:
       {
         "status": "candidates_found",
         "selected_candidate": {...},
         "candidates": [
           {"source_type": "BOQ", "rate": 150, "similarity_score": 1.0},
           {"source_type": "BSR", "rate": 148, "similarity_score": 0.92}
         ],
         "missing_information": []
       }

12. If explicit rate reference found (e.g., RB/19) → bypass resolver, use exact match

13. Infer variation type/mode from message if not explicit
    → Checks for keywords: "change", "omit", "substitute", etc.
    → Maps TYPE1-6 to evaluation modes

14. Extract quantities from message using regex patterns
    → "revised total quantity is 1500 m3" → {"value": 1500, "unit": "m3"}

PHASE 6: Normalize for Frontend
───────────────────────────────
15. Normalize BOQ candidates to standard field names
16. Normalize activity candidates 
17. Normalize rate candidates

PHASE 7: Persist Session State
──────────────────────────────
18. Update session["session_metadata"]["variation_state"] with:
    - original_description, new_quantity, unit, etc.
    - confirmed_rate_source, confirmed_rate_source_id
    - affected_boq_candidates, affected_activity_candidates
    
    IMPORTANT: Do NOT save conclusions (no cost/time predictions here)

19. Save AI response to chat_history

PHASE 8: Return to Frontend
───────────────────────────
20. Return full extraction result (NO EVALUATION)
```

**Output**:
```json
{
  "reply": "I understand you want to increase excavation from 1000 m3 to 1500 m3 using rate RB/19. Please confirm this is correct...",
  "proposal": null,
  "session_id": 1,
  "workflow_state": "collecting_details",
  "requires_human_confirmation": true,
  
  "variation_type": "TYPE1",
  "evaluation_mode": "quantity_change",
  "unit": "m3",
  "extracted_quantities": [
    {"value": 1000, "unit": "m3", "description": "original quantity"},
    {"value": 1500, "unit": "m3", "description": "revised total quantity"}
  ],
  
  "affected_boq_candidates": [
    {
      "item_reference": "5.1",
      "description": "Excavation of soil",
      "unit": "m3",
      "rate": 145.0,
      "quantity": 1000,
      "similarity_score": 0.92,
      "confidence_score": 0.92
    }
  ],
  
  "affected_activity_candidates": [
    {
      "activity_id": "A3",
      "activity_name": "Excavation & Foundation",
      "duration": 30,
      "is_critical": true,
      "similarity_score": 0.88
    }
  ],
  
  "selected_rate_candidate": {
    "source_type": "rate_breakdown",
    "source_id": "RB/19",
    "item_reference": "RB/19",
    "description": "Excavation rate",
    "unit": "m3",
    "rate": 150.0,
    "similarity_score": 1.0,
    "confidence_score": 0.99
  },
  
  "rate_candidates": [
    {...},
    {...}
  ]
}
```

**Services Invoked**:
- `SessionManager` - Get/update session
- `CostEngine.train_model()` - TF-IDF vectorization
- `CostEngine.ml_model.find_similar_items()` - BOQ ranking
- `MLModel.parse_instruction()` - **Groq LLM call** (async)
- `TimeEngine.identify_relevant_activities()` - Activity matching
- `RateResolver.resolve_rate()` - Rate ranking
- `rate_source_extractor` - If new file processing needed

**Storage Access**:
- Read: project, boq_items, activities, rate_sources, session history
- Write: chat_history, session_metadata (variation_state)

**CRITICAL POINTS**:
- ⚠️ **NO cost/time evaluation happens here** - only extraction & matching
- ⚠️ **Human confirmation required** before evaluation (enforced in next endpoint)
- ⚠️ **MLModel.parse_instruction()** makes external API call to Groq - can be slow

---

### ⭐ 12. POST /variation/{project_id}/confirm-and-evaluate - **Deterministic Evaluation**
**Purpose**: Human-confirmed, rule-based cost & time impact calculation  
**Input**:
```json
{
  "project_id": 1,
  "session_id": 1,
  "variation_type": "TYPE1",
  "evaluation_mode": "quantity_change",
  
  "original_boq_item_ref": "5.1",
  "original_description": "Excavation of soil",
  "original_quantity": 1000,
  "new_quantity": 1500,
  "unit": "m3",
  
  "confirmed_rate": 150.0,
  "confirmed_rate_source": "rate_breakdown",
  "confirmed_rate_source_id": "RB/19",
  
  "confirmed_activity_ref": "A3",
  "confirmed_productivity": 10.0,
  "productivity_source": "project_schedule",
  
  "supporting_documents": [],
  "engineer_instruction_ref": "EI/001",
  "human_confirmed": true
}
```

**Request Flow**:

```
PHASE 1: Validation
───────────────────
1. Check human_confirmed == true (enforce explicit confirmation)
2. Validate all required fields based on variation_type:
   - TYPE1: need original_boq_item_ref, original_qty, new_qty, confirmed_rate
   - TYPE2: need both original + replacement BOQ refs & quantities
   - TYPE4: need original BOQ ref & quantity
   - TYPE5: need replacement description & quantity
   If missing → return 400 with missing_fields list

PHASE 2: Create Variation Record
─────────────────────────────────
3. Create variation_data object with all confirmed inputs
4. StorageManager.add_variation(project_id, session_id, variation_data)
   → Appends to project["variations"] array
   → Returns variation_id

PHASE 3: Deterministic Cost Evaluation
──────────────────────────────────────
5. VariationEvaluator.evaluate_confirmed_variation(project_id, request_data)
   
   Switch on evaluation_mode:
   
   a) "quantity_change" (TYPE1):
      qty_delta = new_quantity - original_quantity
      amount = qty_delta × confirmed_rate
      formula = f"({new_qty} - {old_qty}) × {rate}"
      → Creates cost_line with type="quantity_change"
   
   b) "omission" (TYPE4):
      qty_delta = 0 - original_quantity
      amount = qty_delta × confirmed_rate
      → Creates cost_line with type="omission"
   
   c) "substitution" (TYPE2):
      omission_amount = (0 - original_qty) × original_rate
      addition_amount = replacement_qty × replacement_rate
      → Creates TWO cost_lines: [omission, addition]
      total = omission + addition
   
   d) "additional_work" (TYPE5):
      amount = replacement_quantity × confirmed_rate
      → Creates cost_line with type="addition"
   
   e) "time_sequence_change" (TYPE6):
      Uses TimeEngine.calculate_eot() for CPM-based delay analysis
   
   All modes return:
   {
     "cost_lines": [
       {
         "line_type": "quantity_change",
         "description": "...",
         "quantity": 500,
         "unit": "m3",
         "rate": 150.0,
         "amount": 75000,
         "formula": "...",
         "used_rate_source": {...}
       }
     ],
     "total_cost_impact": 75000.0,
     "formula_summary": ["Quantity change: (1500-1000)×150 = 75000"],
     "manual_confirmation_required": false
   }

PHASE 4: Time Impact Calculation
─────────────────────────────────
6. If confirmed_activity_ref provided:
   TimeEngine.calculate_eot(project_id, activity_id, duration_change, activity_type)
   → Performs CPM analysis on schedule network
   → Returns: {"eot_days": 5, "critical_path": [...], "cpm_proof": {...}}
   
   If not on critical path → eot_days = 0 (no time claim)
   If on critical path → eot_days = duration_change

PHASE 5: QS Validation
──────────────────────
7. ValidationEngine.validate_confirmed_variation(project, request_data, evaluation_result)
   Runs 11 checks:
   - Human confirmation provided?
   - BOQ reference present (if not additional_work)?
   - External source (BSR/HSR) has supporting document?
   - TYPE2 has both original & replacement?
   - TYPE4 omission has negative amount?
   - TYPE5 additional_work has positive amount?
   - Rate sources documented?
   - Activity mapping for time claims?
   - CPM proof for EOT?
   - Drawings for TYPE3?
   - Reasonable rate increase?
   Returns: {"valid": bool, "warnings": [...], "errors": [...]}

PHASE 6: Store Evaluation Result
─────────────────────────────────
8. Update variation record:
   StorageManager.update_variation(project_id, variation_id, {
     "cost_lines": cost_lines,
     "total_cost_impact": 75000.0,
     "time_impact": {...},
     "validation": {...},
     "formula_summary": [...],
     "status": "Calculated",
     "updated_at": datetime.utcnow()
   })

PHASE 7: Generate PDF/DOCX
──────────────────────────
9. Build proposal_data from project + variation + evaluation result:
   {
     "project_name": "Parking Expansion",
     "variation_id": 1,
     "variation_type": "TYPE1",
     "description": "Excavation increase",
     "cost_lines": [...],
     "total_cost_impact": 75000,
     "time_impact": {...},
     "validation": {...},
     "rate_sources": [...],
     "assumptions": [...]
   }

10. PDFGenerator.generate_variation_proposal(proposal_data, output_path)
    → Multi-page proposal with:
       - Executive summary
       - Cost breakdown table
       - Time impact analysis
       - QS validation results
       - Formulas with evidence
    → Saves to backend/generated_reports/variation_proposal_<id>.pdf

11. DOCXGenerator.generate_variation_proposal(proposal_data, output_path)
    → Editable Word document with same content
    → Saves to backend/generated_reports/variation_proposal_<id>.docx

PHASE 8: Store Generated File URLs
──────────────────────────────────
12. Update variation with PDF/DOCX URLs:
    {
      "pdf_url": "/download/variation_proposal_1.pdf",
      "docx_url": "/download/variation_proposal_1.docx",
      "pdf_path": "...",
      "docx_path": "..."
    }

PHASE 9: Return Complete Result
───────────────────────────────
13. Return success response with all data
```

**Output**:
```json
{
  "status": "success",
  "variation_id": 1,
  "cost_lines": [
    {
      "line_type": "quantity_change",
      "description": "Excavation of soil",
      "quantity": 500,
      "unit": "m3",
      "rate": 150.0,
      "amount": 75000.0,
      "formula": "(1500 - 1000) × 150",
      "used_rate_source": {
        "source_type": "rate_breakdown",
        "item_reference": "RB/19",
        "description": "Excavation rate",
        "rate": 150.0,
        "confidence": "Human confirmed"
      }
    }
  ],
  "total_cost_impact": 75000.0,
  "time_impact": {
    "eot_days": 5,
    "critical_path": ["A1", "A3", "A5"],
    "on_critical_path": true,
    "cpm_proof": {...}
  },
  "validation": {
    "valid": true,
    "warnings": [],
    "errors": []
  },
  "pdf_url": "/download/variation_proposal_1.pdf",
  "docx_url": "/download/variation_proposal_1.docx",
  "proposal": {
    "project_name": "Parking Expansion",
    "variation_id": 1,
    "variation_type": "TYPE1",
    "cost_lines": [...],
    "total_cost_impact": 75000.0,
    ...
  }
}
```

**Services Invoked**:
- `VariationEvaluator.evaluate_confirmed_variation()` - **Deterministic engine**
- `TimeEngine.calculate_eot()` - CPM analysis
- `ValidationEngine.validate_confirmed_variation()` - QS checks
- `PDFGenerator.generate_variation_proposal()` - PDF creation
- `DOCXGenerator.generate_variation_proposal()` - DOCX creation
- `StorageManager` - Persistence

**Storage Mutations**:
- Creates: new variation record in project["variations"]
- Creates: PDF file at backend/generated_reports/variation_proposal_<id>.pdf
- Creates: DOCX file at backend/generated_reports/variation_proposal_<id>.docx
- Updates: project variation with cost_lines, time_impact, validation, URLs

**CRITICAL POINTS**:
- ✅ **ALL calculations are deterministic** (no ML predictions)
- ✅ **Formula-based** - every cost line shows its math
- ✅ **Traceable** - rate source and BOQ item referenced
- ✅ **CPM-aware** - time impact only if on critical path
- ✅ **QS validation** - professional standards enforced

---

### 13. POST /generate-pdf
**Purpose**: Quick PDF generation (ad-hoc, not tied to stored variation)  
**Input**:
```json
{
  "project_name": "Parking Expansion",
  "variation_type": "TYPE1",
  "cost_lines": [...],
  "total_cost_impact": 75000,
  ...
}
```

**Output**: Binary PDF file (application/pdf)

**Services Invoked**:
- `PDFGenerator.generate_variation_proposal()`

---

### 14. GET /download/{filename}
**Purpose**: Download generated PDF/DOCX  
**Input**: filename in path (e.g., "variation_proposal_1.pdf")  
**Output**: Binary file with correct MIME type  
**Security**: Only allows .pdf and .docx extensions

---

## Data Flow Diagram

```
┌─────────────────┐
│   Frontend UI   │
│   (React)       │
└────────┬────────┘
         │
         │ POST /chat
         │ + user message
         │
         ▼
┌─────────────────────────────────────────┐
│        FastAPI Application              │
│  POST /chat endpoint                    │
└────────┬────────────────────────────────┘
         │
         ├─→ SessionManager
         │   └─→ Get/create session
         │
         ├─→ CostEngine.ml_model.find_similar_items()
         │   └─→ TF-IDF ranking on BOQ
         │
         ├─→ MLModel.parse_instruction()
         │   └─→ 🌐 Groq API call (extraction)
         │
         ├─→ TimeEngine.identify_relevant_activities()
         │   └─→ Keyword matching on activities
         │
         ├─→ RateResolver.resolve_rate()
         │   └─→ TF-IDF ranking on rates
         │
         └─→ StorageManager
             └─→ Save session state
                 └─→ backend/data/project_<id>.json

         ▼
    Return extraction result
    (candidates, not evaluation)

         │
         │ POST /variation/confirm-and-evaluate
         │ + human confirmation + selections
         │
         ▼
┌─────────────────────────────────────────┐
│  VariationEvaluator                     │
│  (Deterministic Rule-Based)             │
└────────┬────────────────────────────────┘
         │
         ├─→ TYPE1 → qty_delta × rate
         ├─→ TYPE2 → (omission) + (addition)
         ├─→ TYPE4 → 0 - qty × rate
         ├─→ TYPE5 → qty × rate
         └─→ TYPE6 → CPM analysis
                
         ▼
    Evaluation Result
    (cost_lines, time_impact, validation)
         │
         ├─→ PDFGenerator
         │   └─→ backend/generated_reports/variation_proposal_<id>.pdf
         │
         ├─→ DOCXGenerator
         │   └─→ backend/generated_reports/variation_proposal_<id>.docx
         │
         └─→ StorageManager
             └─→ Update project["variations"][id]
                 └─→ backend/data/project_<id>.json

         ▼
    Return PDF + DOCX URLs + full proposal
```

---

## Session State Architecture

Each session maintains a **variation_state** object in `session["session_metadata"]["variation_state"]`:

```json
{
  "variation_type": "TYPE1",
  "evaluation_mode": "quantity_change",
  
  "original_boq_item_ref": "5.1",
  "original_description": "Excavation",
  "original_quantity": 1000,
  "new_quantity": 1500,
  "unit": "m3",
  
  "confirmed_rate": 150.0,
  "confirmed_rate_source": "rate_breakdown",
  "confirmed_rate_source_id": "RB/19",
  
  "replacement_item_ref": null,
  "replacement_description": null,
  
  "confirmed_activity_ref": "A3",
  "activity_name": "Excavation & Foundation",
  "confirmed_productivity": 10.0,
  "productivity_source": "project_schedule",
  "is_critical": true,
  
  "supporting_documents": [],
  "human_confirmed": false,
  
  "cost_result": null,
  "time_result": null,
  "pdf_url": null,
  "docx_url": null
}
```

**SessionManager** ensures:
- Existing confirmed values are **never deleted** by None/empty updates
- Missing keys receive defaults from `get_default_variation_state()`
- Updates are **merge-safe** (deep update, not shallow replace)

---

## Error Handling

All endpoints follow these patterns:

| Status | Use Case |
|--------|----------|
| 400 | Validation failed (missing fields, invalid format) |
| 404 | Resource not found (project, session, variation) |
| 500 | Server error (exception during processing) |

Error responses include:
```json
{
  "detail": "User-friendly error message or dict with more info"
}
```

For evaluation errors:
```json
{
  "error": "Missing required fields for evaluation",
  "missing_fields": ["original_quantity", "confirmed_rate"],
  "message": "Please complete..."
}
```

---

## Summary Table

| # | Endpoint | Method | Input | Output | Services | Storage |
|---|----------|--------|-------|--------|----------|---------|
| 1 | `/` | GET | - | API info | - | - |
| 2 | `/health` | GET | - | {"status": "healthy"} | - | - |
| 3 | `/upload/files` | POST | BOQ, Rate, Schedule | {project_id, counts} | CostEngine, TimeEngine | Create project |
| 4 | `/upload/additional-files` | POST | Files (BSR/HSR/etc) | {files_uploaded, extracted} | RateSourceExtractor | Add rate_sources |
| 5 | `/projects` | GET | - | List of projects | StorageManager | Read |
| 6 | `/variation-types` | GET | - | FIDIC types 1-6 | - | - |
| 7 | `/session/create` | POST | project_id | {session} | SessionManager | Create session |
| 8 | `/session/{pid}/{sid}` | GET | - | {session_context} | SessionManager | Read |
| 9 | `/session/{pid}/{sid}/continue` | POST | - | {success, context} | SessionManager | Update status |
| 10 | `/session/{pid}/{sid}/close` | POST | - | {success} | SessionManager | Update status |
| 11 | `/chat` | POST | message | Extraction result (no eval) | MLModel, RateResolver, TimeEngine | Update session |
| 12 | `/variation/{pid}/confirm-and-evaluate` | POST | Confirmed data + human_confirmed=true | Cost lines, PDF, DOCX | VariationEvaluator, PDFGen | Create variation |
| 13 | `/generate-pdf` | POST | Proposal data | PDF binary | PDFGenerator | - |
| 14 | `/download/{filename}` | GET | filename | PDF/DOCX binary | - | Read file |

---

## Key Design Patterns

### 1. **Extraction vs. Evaluation Split**
- **`/chat`** = ML extraction + ranking (idempotent, repeatable)
- **`/confirm-and-evaluate`** = Deterministic calculation (once per human confirmation)

### 2. **Session State Persistence**
- Variation data accumulates in `session_metadata.variation_state`
- User can refine selections across multiple chat turns
- No evaluation until human_confirmed=true

### 3. **Candidate Ranking**
```
Priority order for rates:
1. Exact reference match (RB/19)
2. BOQ items (similar description)
3. BSR/HSR (preferred rate sources)
4. Quotations
5. Manual entry required
```

### 4. **Deterministic Formula Preservation**
Every cost line includes:
- Formula text (e.g., "(1500-1000)×150")
- Component values (qty, rate, unit)
- Used rate source with confidence
- Enables audit trail & QS review

### 5. **CPM-Aware Time Impact**
- Only activities on critical path → EOT claim
- Off-critical-path delays → float absorption (no EOT)
- CPM proof included in proposal

---

## Testing Endpoints

**Health Check**:
```bash
curl http://localhost:8000/health
```

**Upload Files**:
```bash
curl -X POST http://localhost:8000/upload/files \
  -F "boq=@sample_boq.csv" \
  -F "breakdown=@sample_rate_breakdown.csv" \
  -F "schedule=@sample_schedule.csv"
```

**Chat**:
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": 1,
    "session_id": 1,
    "message": "Excavation increases from 1000 m3 to 1500 m3 using rate RB/19"
  }'
```

**Confirm & Evaluate**:
```bash
curl -X POST http://localhost:8000/variation/1/confirm-and-evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": 1,
    "session_id": 1,
    "variation_type": "TYPE1",
    "evaluation_mode": "quantity_change",
    "original_boq_item_ref": "5.1",
    "original_quantity": 1000,
    "new_quantity": 1500,
    "unit": "m3",
    "confirmed_rate": 150.0,
    "confirmed_rate_source": "rate_breakdown",
    "confirmed_rate_source_id": "RB/19",
    "human_confirmed": true
  }'
```

---

**End of Backend Endpoint Flows Document**
