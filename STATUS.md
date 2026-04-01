# GAIA Magnetics Status

Last updated: `2026-04-01`

## Live Snapshot

- App URL:
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

> Revision `gaia-magnetics-00073-87x` is serving 100% traffic. `/api/health` returned `{"status":"ok"}` and a full live smoke test completed after deploy.

## Current Product State

- FastAPI backend is live with modular `routes`, `services`, `models`, `gcp`, and `jobs`.
- Frontend remains anchored on `frontend/index.html` with ES-module sections under `frontend/js/sections`.
- Core workflow is live:
  `Home -> Projects -> Setup -> Analysis -> Preview -> Processing -> Visualisation -> Export`
- Firestore stores project/task metadata and lightweight result references.
- Full processing outputs are persisted to GCS `results.json`.
- Google Maps-backed preview and visualisation views are live.
- User-visible AI branding is `Aurora AI`.

## Most Recent Completed Work

### Live processing and persistence fixes

- Fixed the task-result persistence failure that was causing completed runs to end as failed.
- The Firestore write path now sanitizes update payloads before persistence.
- `support_mask` is no longer written into the task-document `results` payload, which resolved the invalid nested entity error.
- Added a regression test covering the `support_mask` persistence case.

### Aurora chat and AI routing

- Aurora chat now uses the split AI path:
  `Gemini on Vertex AI` for Preview and Visualisation chat,
  `Claude` remains reserved for export drafting.
- Granted the live Cloud Run service account Vertex AI access on the infra project.
- Live smoke test confirmed Aurora now returns real model responses on Preview and Visualisation instead of the old fallback text.
- Export screen chat remains disabled by design for now.

### Setup, processing, and visualisation state

- Project and task selection now persist across hard refreshes.
- Setup state restores from the selected project/task instead of dropping the user back to a blank flow.
- Processing summary now reflects the exact chosen corrections, add-ons, filter mode, and prediction status more directly.
- Blank scenario remains truly optional and the explicit `Off` option is still in place.
- Single uploaded traverses remain single instead of being split into many inferred traverses.
- IGRF is working again in live processing via `ppigrf`.

## Smoke Test Result

The most recent full live smoke pass completed successfully against revision `gaia-magnetics-00073-87x`.

- Health check: passed
- Project creation: passed
- Task upload: passed
- Analysis save: passed
- Preview Aurora chat: passed with a real model response
- Processing run: passed and completed
- Visualisation Aurora chat: passed with a real model response
- Export job: completed

## Important Open Items

1. Claude-backed export drafting is still not reliably generating the AI-authored export narrative. Export jobs complete, but Aurora export authoring can still fall back to saved-data-only copy.
2. Manual browser click-through on the latest deployed UI still needs a human pass.
3. Long-running processing should be observed again on live to confirm no timeout regressions remain on larger datasets.
4. Surface rendering is now contour-first, but per-traverse regridding is still a possible follow-up if needed.
5. Keep an eye on Vertex/Claude quota behavior separately now that chat and export use different AI paths.
6. Re-run older tasks created before the single-traverse and persistence fixes if they still show bad inferred traverses or stale results.

## Main Files Most Relevant Right Now

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
- `frontend/js/sections/setup.js`
- `frontend/js/sections/navigation.js`
- `frontend/js/sections/preview.js`
- `frontend/js/sections/processing.js`
- `frontend/js/sections/visualisation.js`
- `frontend/js/sections/export.js`

## Verification Status

- `py -3 -m unittest tests.test_processing_service tests.test_ai_service tests.test_export_service` passed.
- `py -3 -m py_compile backend/gcp/firestore_store.py backend/services/processing_service.py` passed.
- Live Cloud Run deploy completed successfully to revision `gaia-magnetics-00073-87x`.
- Full live smoke test completed successfully after deploy.
