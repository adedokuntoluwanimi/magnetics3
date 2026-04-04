# GAIA Magnetics Status

Last updated: `2026-04-04`

## Live Snapshot

- App URL:
  `https://gaia-magnetics-348555315681.us-central1.run.app`
- Cloud Run service:
  `gaia-magnetics`
- Latest live revision:
  `gaia-magnetics-00078-hr7`
- Region:
  `us-central1`
- Infra project:
  `app-01-488817`
- AI project:
  `app-01-488817-ai`
- Service account:
  `vet-dev-backend@app-01-488817.iam.gserviceaccount.com`

> Revision `gaia-magnetics-00078-hr7` is serving 100% traffic and `/api/health` returned `{"status":"ok"}` after deploy.

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

### Processing and scientific output upgrades

- Diurnal correction now prefers true interval-based consecutive base-station interpolation using the first valid base reading as the reference.
- Leading and trailing survey samples outside the valid base-station range now use explicit constant-hold handling instead of being silently folded into the same interval logic.
- Diurnal reporting now stores method, base-reading counts, interval counts, coverage, max correction, and interpolated-base statistics.
- Regional and residual are now first-class outputs with configurable regional methods:
  `polynomial`, `trend`, `lowpass`, and `igrf_context`.
- Corrected, regional, and residual surfaces now persist separately, with `Residual = Corrected - Regional` enforced explicitly.

### Visualisation and UI clarity upgrades

- Analysis now explains interval-based diurnal correction and fallback logic directly in the UI.
- Regional/residual settings now expose explicit regional-method controls and method-aware helper text.
- Visualisation now groups `Corrected Magnetic Field`, `Regional Magnetic Field`, `Residual Magnetic Field`, and derived products separately.
- Layer descriptions, captions, run-summary badges, and method-aware interpretation metadata now reflect actual backend metadata.

### Export and reporting upgrades

- Export previews now show which products are actually available for the current run.
- Corrected/regional/residual content can now be selected independently in the export UI.
- Export bundles and report generators now recognise separate corrected/regional/residual map assets.
- Aurora/export reporting now receives separate corrected/regional/residual metadata instead of one blended residual-only context.

## Verification Status

- `py -3 -m unittest tests.test_processing_service tests.test_ai_service tests.test_export_service` passed.
- `py -3 -m py_compile backend/services/processing_service.py backend/services/ai_service.py backend/services/preview_service.py backend/services/export_service.py backend/models/processing.py` passed.
- `node --check frontend/js/sections/analysis.js` passed.
- `node --check frontend/js/sections/setup.js` passed.
- `node --check frontend/js/sections/processing.js` passed.
- `node --check frontend/js/sections/visualisation.js` passed.
- `node --check frontend/js/sections/export.js` passed.
- Live Cloud Run deploy completed successfully to revision `gaia-magnetics-00078-hr7`.

## Important Open Items

1. Claude-backed export drafting still needs another quality pass so report narratives become reliably task-specific.
2. Manual browser QA is still needed on the latest deploy, especially for the new regional-method controls and export-content preview.
3. Fresh live reruns should be used to confirm the interval-based diurnal reporting and corrected/regional/residual outputs match user expectations on real datasets.
4. Continue watching Vertex/Claude quota and long-run processing latency.

## Main Files Most Relevant Right Now

### Backend

- `backend/services/processing_service.py`
- `backend/services/preview_service.py`
- `backend/services/ai_service.py`
- `backend/services/export_service.py`
- `backend/models/processing.py`
- `backend/routes/tasks.py`

### Frontend

- `frontend/index.html`
- `frontend/js/sections/analysis.js`
- `frontend/js/sections/processing.js`
- `frontend/js/sections/visualisation.js`
- `frontend/js/sections/export.js`
- `frontend/js/sections/preview.js`
