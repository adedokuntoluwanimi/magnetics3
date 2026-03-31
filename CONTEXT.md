# GAIA Magnetics Context

Last updated: `2026-03-31`

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
  `gaia-magnetics-00067-b5x`
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

### Setup

- Two-step setup flow:
  `Project details -> Task setup`
- Scenario selection is optional and now includes an explicit `Off` option.
- Prediction mode now expects one selected predicted-traverse type:
  `infill` or `offset`.
- Old generic station-spacing handling was reduced so generated traverses depend on the chosen prediction mode.
- Survey upload supports CSV/XLSX with coordinate mapping, raw-data mapping, and base-station handling.

### Preview

- Preview renders Google Maps-backed station maps.
- Summary cards show survey traverses and predicted traverses separately.
- Predicted traverse counts now reflect configured traverses more accurately.
- Single uploaded traverses are meant to remain a single traverse through preview and processing.
- Assistant surface uses `Aurora AI`.

### Processing

- Processing pipeline persists richer metadata and predicted-station magnetic values.
- User-facing step descriptions were simplified where needed, especially around fallback wording.
- Result loading in the frontend is cached more aggressively to reduce repeat fetch delays.
- Blank scenario now resolves to an automatic analysis-only path instead of defaulting to `explicit`.
- Derived layers/add-ons can still be generated when predictive modelling is disabled.

### Visualisation

- Combined surface presentation remains heatmap plus contour.
- Users can now choose to view all traverses together or focus on a selected traverse.
- Layer-driven views and maps remain powered by the processed task results.
- Dark-mode contrast for plots and assistant surfaces was improved.
- Assistant surface uses `Aurora AI`.

### Export

- Export view retains the assistant panel and plain-language export guidance.
- Assistant surface uses `Aurora AI`.

## Important Files

### Backend

- `backend/routes/tasks.py`
- `backend/models/__init__.py`
- `backend/models/processing.py`
- `backend/models/project.py`
- `backend/services/ai_service.py`
- `backend/services/preview_service.py`
- `backend/services/processing_service.py`

### Frontend

- `frontend/index.html`
- `frontend/js/state.js`
- `frontend/js/sections/analysis.js`
- `frontend/js/sections/setup.js`
- `frontend/js/sections/preview.js`
- `frontend/js/sections/processing.js`
- `frontend/js/sections/visualisation.js`
- `frontend/js/sections/maps.js`
- `frontend/js/sections/export.js`

## Known Follow-Up Areas

1. Manual browser QA on the newest deploy.
2. Confirm predicted overlay behavior on a real dataset end to end.
3. Revisit per-traverse surface rendering if the current traverse filter is not sufficient.
4. Keep an eye on live processing latency and export response time.
5. Continue reducing stale wording in docs and UI where older assumptions remain.
6. Older tasks may need a fresh processing run to regenerate results with the current single-traverse fix.

## Deployment Note

```powershell
gcloud run deploy gaia-magnetics --source . --region=us-central1 --project=app-01-488817 --quiet
```
