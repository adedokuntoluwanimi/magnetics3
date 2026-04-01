# GAIA Magnetics Context

Last updated: `2026-04-01`

## Purpose

This file captures the current working context for `gaia-magnetics`.
`Instructions.txt` in the parent workspace remains the higher-level project instruction set.

## Workspace

- Workspace root:
  `c:\Users\Tolu\Documents\Terra Analytics\Magnetics Main\2\magnetics (main)`
- App root:
  `c:\Users\Tolu\Documents\Terra Analytics\Magnetics Main\2\magnetics (main)\gaia-magnetics`
- Instructions file:
  `c:\Users\Tolu\Documents\Terra Analytics\Magnetics Main\2\magnetics (main)\Instructions.txt`

## Live Deployment

- Public URL:
  `https://gaia-magnetics-348555315681.us-central1.run.app`
- Cloud Run service:
  `gaia-magnetics`
- Latest live revision:
  `gaia-magnetics-00073-87x`
- Region:
  `us-central1`
- Infra project:
  `app-01-488817`
- AI project:
  `app-01-488817-ai`
- Service account:
  `vet-dev-backend@app-01-488817.iam.gserviceaccount.com`

## Standing Constraints

- Preserve the existing folder structure.
- Use `frontend/index.html` as the shared UI shell.
- Keep integrations real:
  Firestore, Cloud Storage, Cloud Run, Google Maps, Vertex AI.
- Do not reintroduce dummy data or misleading labels.
- User-visible assistant branding should remain `Aurora AI`.
- The frontend currently mixes static shell markup and modular JS; changes often need both.

## Current Functional Shape

### Navigation and project flow

- Top navigation is project-centric.
- Core route sequence is:
  `Home -> Projects -> Setup -> Analysis -> Preview -> Processing -> Visualisation -> Export`
- Sidebar project controls and project/task launch actions are active.
- Selected project and task IDs now persist across refreshes.

### Setup

- Two-step setup flow:
  `Project details -> Task setup`
- Scenario selection is optional and includes an explicit `Off` option.
- Setup restores from the saved task/project state after refresh.
- Prediction mode expects one selected predicted-traverse type:
  `infill` or `offset`.
- Survey upload supports CSV/XLSX with coordinate mapping, raw-data mapping, and base-station handling.

### Preview

- Preview renders Google Maps-backed station maps.
- Summary cards show survey traverses and predicted traverses separately.
- Single uploaded traverses are meant to remain a single traverse through preview and processing.
- Aurora chat is enabled on Preview and is now using the Vertex/Gemini chat path.
- Live smoke test confirmed Preview Aurora returns a real model response.

### Processing

- Processing pipeline persists richer metadata and keeps the full heavy result payload in GCS.
- Firestore task documents now only keep Firestore-safe result metadata and artifact references.
- `support_mask` stays in `results.json` but is excluded from the Firestore task payload.
- Blank scenario now resolves to an automatic analysis-only path instead of defaulting to `explicit`.
- Derived layers/add-ons can still be generated when predictive modelling is disabled.
- IGRF is currently working in live runs via `ppigrf`.

### Visualisation

- Contour map is the current default surface-style view.
- Users can now choose to view all traverses together or focus on a selected traverse.
- Dark-mode contrast for plots and assistant surfaces was improved.
- Aurora chat is enabled on Visualisation and is using the Vertex/Gemini chat path.
- Live smoke test confirmed Visualisation Aurora returns a real model response.

### Export

- Export jobs complete and bundle outputs are being generated.
- Export screen chat is intentionally disabled for now.
- AI export drafting still has a remaining reliability gap: export jobs can complete while the Aurora export-authoring step falls back to saved-data-only content instead of a live Claude-authored narrative.

## Important Files

### Backend

- `backend/config.py`
- `backend/gcp/firestore_store.py`
- `backend/gcp/vertex_ai.py`
- `backend/services/ai_service.py`
- `backend/services/container.py`
- `backend/services/export_service.py`
- `backend/services/processing_service.py`
- `backend/routes/ai.py`
- `backend/routes/tasks.py`

### Frontend

- `frontend/index.html`
- `frontend/js/state.js`
- `frontend/js/shared/ai_chat.js`
- `frontend/js/sections/analysis.js`
- `frontend/js/sections/setup.js`
- `frontend/js/sections/navigation.js`
- `frontend/js/sections/preview.js`
- `frontend/js/sections/processing.js`
- `frontend/js/sections/visualisation.js`
- `frontend/js/sections/export.js`

## Known Follow-Up Areas

1. Fix Claude-backed export drafting so PDF/DOCX/PPTX narrative generation stops falling back.
2. Manual browser QA on the newest deploy.
3. Confirm uploaded-data analysis and visualisation behavior again on a larger real dataset.
4. Keep an eye on live processing latency and export response time.
5. Re-run older tasks if they still show pre-fix line splitting or stale task-result payloads.

## Deployment Note

```powershell
gcloud run deploy gaia-magnetics --source . --region=us-central1 --project=app-01-488817 --quiet
```
