# GAIA Magnetics Status

Last updated: `2026-03-31`

## Live Snapshot

- App URL:
  `https://gaia-magnetics-348555315681.us-central1.run.app`
- Cloud Run service:
  `gaia-magnetics`
- Latest live revision:
  `gaia-magnetics-00065-zkf`
- Region:
  `us-central1`
- Infra project:
  `app-01-488817`
- AI project:
  `app-01-488817-ai`
- Service account:
  `vet-dev-backend@app-01-488817.iam.gserviceaccount.com`

> Revision `gaia-magnetics-00065-zkf` is serving 100% traffic. `/api/health` returned `{"status":"ok"}` after deploy.

## Current Product State

- FastAPI backend is live with modular `routes`, `services`, `models`, `gcp`, and `jobs`.
- Frontend remains anchored on `frontend/index.html` with ES-module sections under `frontend/js/sections`.
- Core workflow is live:
  `Home -> Projects -> Analysis -> Preview -> Processing -> Visualisation -> Export`
- Firestore stores lightweight project/task metadata.
- Full processing outputs are persisted to GCS `results.json`.
- Google Maps-backed preview and visualisation views are live.
- User-visible AI branding is `Aurora AI`.

## Most Recent Completed Work

### Setup, prediction, preview, and visualisation updates

- Restored `Aurora AI` branding in user-visible frontend surfaces.
- Expanded the GAAS explanation while keeping the full phrase
  `Geospatial Automation and Inference Analysis`.
- Made scenario selection optional in setup again.
- Increased the sidebar project-arrow size for better visibility.
- Simplified predicted-traverse setup so the user picks one mode:
  `infill` or `offset`.
- Removed the old top-level station-spacing path that conflicted with mode-based traverse generation.
- Carried predicted traverse metadata through preview and processing so generated traverses retain their type and labels.
- Updated preview counts so predicted traverses reflect the configured amount more accurately.
- Added visualisation support for viewing all traverses together or filtering by traverse.
- Kept the main surface view as a combined heatmap/contour presentation.

### Processing and assistant wording cleanup

- Reduced assistant fallback jargon in preview, visualisation, and export surfaces.
- Simplified processing-step wording for cases such as unavailable IGRF dependencies.
- Preserved predicted magnetic values on generated stations so overlay readouts can use them.
- Improved frontend result caching to reduce repeat fetches and soften load-time delays in visualisation flows.

### Mojibake cleanup

- Removed mojibake across the shared frontend shell in `frontend/index.html`.
- Fixed corrupted arrows, placeholders, checkmarks, separators, attribution text, upload controls, and default placeholders across setup, analysis, preview, processing, visualisation, and export.
- Repo-wide frontend scan for common mojibake sequences (`Ã`, `Â`, `â€`, etc.) came back clean after the sweep.

### Deployment

- Deployed the latest frontend cleanup and current app state to Cloud Run.
- Live revision is now `gaia-magnetics-00065-zkf`.

## Important Open Items

1. Full browser click-through on the latest deployed UI still needs a manual pass.
2. Long-running processing should be observed again on live to confirm no timeout regressions remain.
3. Surface rendering is still grid-first; per-traverse filtering is clearer in the UI, but per-traverse regridding is still a possible follow-up if needed.
4. Exports still run in the API service; Export Cloud Run Job remains a future hardening step.
5. Verify Vertex AI permissions remain correct for
   `vet-dev-backend@app-01-488817.iam.gserviceaccount.com`
   on `app-01-488817-ai`.

## Main Files Most Relevant Right Now

### Backend

- `backend/routes/tasks.py`
- `backend/services/ai_service.py`
- `backend/services/preview_service.py`
- `backend/services/processing_service.py`
- `backend/models/processing.py`
- `backend/models/project.py`

### Frontend

- `frontend/index.html`
- `frontend/js/state.js`
- `frontend/js/sections/setup.js`
- `frontend/js/sections/preview.js`
- `frontend/js/sections/processing.js`
- `frontend/js/sections/visualisation.js`
- `frontend/js/sections/maps.js`
- `frontend/js/sections/export.js`
- `frontend/js/sections/analysis.js`

## Verification Status

- `python -m unittest tests.test_processing_service` passed during the recent processing changes.
- `node --check` passed on the updated frontend modules touched in the previous feature pass.
- Frontend mojibake scan across `frontend/index.html`, `frontend/js`, and `frontend/css` is clean.
- Cloud Run deploy completed successfully to revision `gaia-magnetics-00065-zkf`.
- Live health endpoint returned `{"status":"ok"}`.
