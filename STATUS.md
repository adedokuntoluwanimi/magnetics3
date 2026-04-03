# GAIA Magnetics Status

Last updated: `2026-04-03`

## Live Snapshot

- App URL:
  `https://gaia-magnetics-348555315681.us-central1.run.app`
- Cloud Run service:
  `gaia-magnetics`
- Latest live revision:
  `gaia-magnetics-00077-hxg`
- Region:
  `us-central1`
- Infra project:
  `app-01-488817`
- AI project:
  `app-01-488817-ai`
- Service account:
  `vet-dev-backend@app-01-488817.iam.gserviceaccount.com`

> Revision `gaia-magnetics-00077-hxg` is serving 100% traffic and `/api/health` returned `{"status":"ok"}` after deploy.

## Current Product State

- FastAPI backend is live with modular `routes`, `services`, `models`, `gcp`, and `jobs`.
- Frontend remains anchored on `frontend/index.html` with ES-module sections under `frontend/js/sections`.
- Core workflow is live:
  `Home -> Projects -> Setup -> Analysis -> Preview -> Processing -> Visualisation -> Export`
- Firestore stores project/task metadata and lightweight result references.
- Full processing outputs are persisted to GCS `results.json`.
- Google Maps-backed preview and visualisation views are live.
- User-visible AI branding remains `Aurora AI`.

## Most Recent Completed Work

### Setup, project flow, and exports

- Project/task setup persistence now restores user-entered fields more reliably.
- Saved uploads are shown again when reopening task setup.
- Project deletion now stays in the projects/workspace flow instead of kicking the user back to Home.
- Export filenames now use `task_project` naming instead of generic names.
- Export screen chat remains removed; Aurora still works behind the scenes for report generation.

### AI and visualisation fixes

- Aurora chat now avoids exposing internal key names in normal answers.
- Base-station count resolution was tightened so Aurora can answer from processed task data instead of only stale validation metadata.
- Visualisation chat sits in its own dedicated panel again.
- Line profiles now use raw magnetic values for the magnetic-layer view and expose manual axis controls.

### Processing and geophysical workflow

- Base-station detection now respects repeated same-coordinate revisits and CSV `BS`-style markers.
- Diurnal correction now uses consecutive base-station pairs as piecewise correction windows with signed drift.
- Uploaded CSVs are treated as one traverse per file through preview and processing.
- Single-traverse regional/residual separation now supports a line-fit method against traverse distance, matching the spreadsheet-style workflow more closely.
- Regional field and residual field remain separate outputs and visualisation layers.

## Verification Status

- `py -3 -m unittest tests.test_processing_service tests.test_ai_service tests.test_export_service` passed.
- `py -3 -m py_compile backend/services/processing_service.py backend/services/ai_service.py backend/services/preview_service.py` passed.
- `node --check frontend/js/sections/setup.js` passed.
- `node --check frontend/js/sections/processing.js` passed.
- `node --check frontend/js/sections/visualisation.js` passed.
- `node --check frontend/js/sections/export.js` passed.
- Live Cloud Run deploy completed successfully to revision `gaia-magnetics-00077-hxg`.

## Important Open Items

1. Claude-backed export drafting still needs another quality pass so report narratives become reliably task-specific.
2. Manual browser QA is still needed on the latest deploy.
3. Fresh live reruns should be used to confirm the new piecewise diurnal and spreadsheet-style regional/residual outputs match user expectations on real datasets.
4. Continue watching Vertex/Claude quota and long-run processing latency.

## Main Files Most Relevant Right Now

### Backend

- `backend/services/processing_service.py`
- `backend/services/preview_service.py`
- `backend/services/ai_service.py`
- `backend/services/export_service.py`
- `backend/services/task_service.py`
- `backend/routes/tasks.py`

### Frontend

- `frontend/index.html`
- `frontend/js/sections/setup.js`
- `frontend/js/sections/sidebar.js`
- `frontend/js/sections/processing.js`
- `frontend/js/sections/visualisation.js`
- `frontend/js/sections/export.js`
- `frontend/js/sections/preview.js`
