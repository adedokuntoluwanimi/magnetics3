# GAIA Magnetics Status

Last updated: `2026-03-28`

## Live Snapshot

- App URL:
  `https://gaia-magnetics-348555315681.us-central1.run.app`
- Cloud Run service:
  `gaia-magnetics`
- Latest ready revision:
  `gaia-magnetics-00056-xbp`
- Region:
  `us-central1`
- Infra project:
  `app-01-488817`
- AI project:
  `app-01-488817-ai`
- Service account:
  `vet-dev-backend@app-01-488817.iam.gserviceaccount.com`

## Current Product State

- FastAPI backend is live with modular `routes`, `services`, `models`, `gcp`, and `jobs`.
- Frontend is still anchored on `frontend/index.html` with ES-module sections under `frontend/js/sections`.
- Core workflow is live:
  `Home -> Projects -> Analysis -> Preview -> Processing -> Visualisation -> Export`
- Results storage is split correctly:
  Firestore keeps lightweight task metadata, full processing grids live in GCS `results.json`.
- Google Maps is live and the app can serve preview/visualisation maps from the deployed service.

## Most Recent Completed Work

### Preview and live map recovery

- Preview/map failures were fixed and the app was redeployed successfully.
- Live routes and frontend assets were refreshed on Cloud Run.
- Predicted markers now use fill colour and are filtered so they do not sit on top of measured/base stations.

### Projects flow and homepage behaviour

- Added a proper `Projects` directory screen.
- The top nav now uses `Projects` instead of `Project Setup`.
- Home-page project entry points now lead into the projects hub.
- Project creation and task creation still use the existing setup screen, but that screen now presents as part of the Projects flow.
- Home page copy now describes GAIA as `GAaaS`:
  `Geophysical Automation as a Service`.

### Project/task setup and routing fixes

- Added a real backend task-update route:
  `PUT /api/projects/{project_id}/tasks/{task_id}`
- Existing tasks can now be reopened into setup, edited, and saved back through the API.
- Projects directory cards now expose:
  `Open project`
  `Edit project`
  `+ New task`
- Setup routing no longer depends on a missing top-nav `setup` tab.
- Project/task entry points now route directly to the real setup screen, fixing the broken `New project` / `New task` path from the Projects page.

### Encoding and UI cleanup

- Swept the active frontend/backend paths for mojibake and cleaned the remaining user-visible text corruption.
- Browser title is now:
  `GAIA Magnetics - V2`
- Project sidebar and home typography were increased slightly for readability.

### Preview and basemap changes

- Preview no longer connects stations with lines.
- Basemap choices were reduced to:
  `Terrain`, `Satellite`, and `Map`.
- Visualisation map overlay now exposes the same basemap selector.

### Setup and data-quality improvements

- Coordinate outlier detection now flags points that are far from the main survey cluster.
- The user is prompted to either keep all points or discard the distant outliers before upload.

### Visualisation refactor

- Visualisation is now layer-driven instead of TMF-only.
- User can switch between available result layers such as:
  `TMF`, `Filtered surface`, `RTP`, `Analytic signal`, `First Vertical Derivative`, `Horizontal Derivative`, `EMAG2 residual`, `Uncertainty`.
- Selected layer now drives:
  stats, colour scale, map hover values, and line-profile rendering.
- Line profiles now support profile stacking.
- Measured and predicted points use the same colours chosen in Preview.
- When stacking is enabled, hover emphasises station identity instead of value readout.

### Processing updates

- Added backend support for:
  `First Vertical Derivative`
  `Horizontal Derivative`
- Derived layers now behave better for single-traverse outputs instead of collapsing to empty/zero-like results.
- Processing step text and related status strings were cleaned up to remove encoding corruption.

## Important Open Items

1. Full browser click-through on the latest deployed UI still needs a deliberate manual pass after revision `00056-xbp`.
2. The create/setup routing fix is deployed, but it has not yet been browser-driven end to end from the live Projects page in this repo session.
3. Long-running processing still timed out in live smoke polling; project creation, task upload, analysis save, and preview succeeded live, but full processing completion still needs follow-up.
4. `predicted_points` are still displayed using sampled surface values rather than a separately persisted predicted-value field.
5. Export generation still runs inside the API service; export Cloud Run Job is not yet implemented.
6. More visualisation types can still be added:
   anomaly masks, histograms, uncertainty overlays, directional-gradient views, crossover/profile QC views.

## Main Files Most Relevant Right Now

- `frontend/index.html`
- `frontend/js/sections/navigation.js`
- `frontend/js/sections/sidebar.js`
- `frontend/js/sections/setup.js`
- `frontend/js/sections/preview.js`
- `frontend/js/sections/maps.js`
- `frontend/js/sections/visualisation.js`
- `frontend/js/sections/analysis.js`
- `frontend/js/sections/processing.js`
- `frontend/js/state.js`
- `frontend/js/api.js`
- `backend/routes/tasks.py`
- `backend/services/task_service.py`
- `backend/services/processing_service.py`

## Verification Status

- Local syntax checks passed for the modified frontend JS files.
- `python -m py_compile backend/services/processing_service.py` passed.
- Cloud Run deploy succeeded to revision `gaia-magnetics-00056-xbp`.
- Live `/api/health` reports `ok`.
- Live homepage returns `200`.
- Live homepage served:
  `GAIA Magnetics - V2`
  `GAaaS`
  `New project...`
- Live homepage no longer showed mojibake markers in the fetched HTML.
- Live smoke reached:
  project creation
  task upload
  analysis save
  preview
- Live smoke still timed out waiting for processing completion.
