# GAIA Magnetics Status

Last updated: `2026-03-28`

## Live Snapshot

- App URL:
  `https://gaia-magnetics-348555315681.us-central1.run.app`
- Cloud Run service:
  `gaia-magnetics`
- Latest ready revision:
  `gaia-magnetics-00060-rtr`
- Region:
  `us-central1`
- Infra project:
  `app-01-488817`
- AI project:
  `app-01-488817-ai`
- Service account:
  `vet-dev-backend@app-01-488817.iam.gserviceaccount.com`

> Deployed to revision `gaia-magnetics-00060-rtr`. Health endpoint verified ok.

## Current Product State

- FastAPI backend is live with modular `routes`, `services`, `models`, `gcp`, and `jobs`.
- Frontend is still anchored on `frontend/index.html` with ES-module sections under `frontend/js/sections`.
- Core workflow is live:
  `Home -> Projects -> Analysis -> Preview -> Processing -> Visualisation -> Export`
- Results storage is split correctly:
  Firestore keeps lightweight task metadata, full processing grids live in GCS `results.json`.
- Google Maps is live and the app can serve preview/visualisation maps from the deployed service.

## Most Recent Completed Work

### AI assistant fully wired (this session)

- Removed all "Aurora" branding from user-visible surfaces.
  All screens now show `GAIA AI` instead.
- Added `default="claude-sonnet-4-6"` to `config.py`.
  Previously the model env var had no default so every AI call silently fell back.
- `VertexAuroraClient` renamed to `VertexAIClient` (alias kept for safety).
  `container.py` updated to use the new name.
- `AIService` system prompt no longer says "You are Aurora".
  It now instructs Claude as a senior geophysical magnetics analyst.
- Export AI call now uses 3000 tokens and requests a structured response
  (`EXECUTIVE SUMMARY`, `KEY FINDINGS`, `MODELLING NOTES`, `RECOMMENDATIONS`).
- New `_parse_response` method in `ai_service.py` maps the structured sections
  correctly to `summary` and `highlights` instead of throwing away most of the output.
- `AIService` now accepts `storage_backend` and implements `_extract_reference_text`.
  The reference file uploaded in project setup (PDF, DOCX, TXT, KML, KMZ, GeoJSON)
  is downloaded from GCS, text-extracted, and injected into every AI prompt.
- Export AI call now passes the full GCS results (stats + 50-point sample)
  instead of only the lightweight Firestore copy.

### Export document quality improved

- PDF rebuilt with `SimpleDocTemplate` — proper styles, stats table with green header,
  full AI sections rendered as formatted paragraphs and bullets.
- DOCX rebuilt with config summary table, stats table, and full AI analysis.
- PPTX rebuilt as a 6-slide deck:
  Title, Survey Summary (AI), Key Findings (AI bullets), Processing Config,
  Magnetic Statistics, Notes and Limitations.

### Interactive AI chatbox added to all three screens

- New shared module `frontend/js/shared/ai_chat.js`:
  manages chat state, bubble rendering, API calls, keyboard shortcuts.
- **Preview**: right-side `a-panel` added. Auto-loads on every `loadPreview()`.
  Initial question asks for expected outputs, risks, and one recommendation.
- **Visualisation**: chat input row added below the right stats panel.
  `renderInterpretation` fires a layer-specific AI question on every layer change.
  Chat body (`visAIBody`) persists across layer changes; only the layer card refreshes.
- **Export**: existing `a-panel` upgraded from one-shot static content to live chat.
  Auto-loads on `loadExportView()`. Previous static placeholder text replaced.
- All three support follow-up questions (type + Enter or ↑ button).
  User bubbles right-aligned, AI bubbles left-aligned with highlights below.

### Aurora text removed from export page

- Export format cards: descriptions no longer mention Aurora.
- Section heading changed from "Aurora AI report options" to "AI report options".
- Export AI panel header changed from "Aurora" to "GAIA AI".
- Processing step 6 detail text updated.
- Home page capability card updated from "Aurora AI" to "GAIA AI".

## Important Open Items

1. **Deploy required** — all AI and chat changes are local only.
   Run:
   ```powershell
   gcloud run deploy gaia-magnetics --source gaia-magnetics --region=us-central1 --project=app-01-488817 --quiet
   ```
2. Full browser click-through on latest UI still needs a manual pass.
3. Long-running processing still timed out in live smoke polling.
   Project create/upload/preview work; full processing completion needs investigation.
4. `predicted_points` still use sampled surface values for hover/readout
   instead of a separately persisted predicted-value field.
5. Export Cloud Run Job is NOT yet implemented — exports still run inside the API service.
6. Service account (`vet-dev-backend@app-01-488817.iam.gserviceaccount.com`)
   must have `roles/aiplatform.user` on `app-01-488817-ai` for the AI calls to work on live.
7. More visualisation types can still be added:
   anomaly threshold masks, histograms, uncertainty overlays, crossover/profile QC.

## Main Files Most Relevant Right Now

### Backend
- `backend/config.py`
- `backend/gcp/vertex_ai.py`
- `backend/services/ai_service.py`
- `backend/services/export_service.py`
- `backend/services/container.py`
- `backend/services/processing_service.py`
- `backend/services/task_service.py`
- `backend/routes/tasks.py`

### Frontend
- `frontend/index.html`
- `frontend/js/shared/ai_chat.js`
- `frontend/js/sections/preview.js`
- `frontend/js/sections/visualisation.js`
- `frontend/js/sections/export.js`
- `frontend/js/state.js`
- `frontend/js/api.js`

## Verification Status

- Python syntax checks passed:
  `ai_service.py`, `export_service.py`, `container.py`
- JS brace balance checks passed:
  `ai_chat.js`, `preview.js`, `visualisation.js`, `export.js`
- Deployed to Cloud Run revision `gaia-magnetics-00060-rtr`.
- Live health endpoint: `{"status":"ok"}`
