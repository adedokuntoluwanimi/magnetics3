# GAIA Magnetics Context

Last updated: `2026-03-28`

## Purpose

This file captures the current working context for `gaia-magnetics`.
`Instructions.txt` in the parent workspace remains the single source of truth.

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

## Standing Constraints

- Preserve folder structure.
- Use `frontend/index.html` as the UI reference.
- Do not reintroduce dummy data.
- Keep integrations real:
  Firestore, Cloud Storage, Cloud Run, Cloud Run Jobs, Google Maps, Vertex AI.
- All AI paths must use Claude Sonnet 4.6 via Vertex AI Marketplace in project `app-01-488817-ai`.
- Theme toggle should remain symbol-based, not text-based.

## Current Functional Shape

### Navigation and project flow

- Top nav now shows `Projects` instead of `Project Setup`.
- `Projects` is the directory/list view for projects.
- New project and new task actions still use `screen-setup`, but that setup screen is now part of the Projects flow.
- Home-page project actions route into the projects hub rather than treating setup as a top-level workflow tab.
- Setup routing now uses direct `setup` screen navigation instead of relying on a missing top-bar `data-s="setup"` tab target.
- Directory/project actions now include:
  `Open project`
  `Edit project`
  `+ New task`

### Setup

- Setup remains a two-step flow:
  `Project details -> Task setup`
- Survey upload supports CSV/XLSX.
- Coordinate system supports WGS84 and UTM.
- Coordinate outliers are detected before upload and the user can discard or keep them.
- Base stations are auto-detected from repeated coordinates and xlsx bold-row support still exists.
- Existing tasks can be loaded back into setup for editing.
- Backend supports full task updates through:
  `PUT /api/projects/{project_id}/tasks/{task_id}`

### Analysis

- Analysis persists normalized backend IDs.
- Processing add-ons now include:
  `rtp`
  `analytic_signal`
  `first_vertical_derivative`
  `horizontal_derivative`
  `emag2`
  `uncertainty`

### Preview

- Preview renders Google Maps-backed station maps.
- Preview does not draw connecting station lines anymore.
- Preview stores and reuses the chosen measured/predicted marker colours.
- Basemaps are limited to:
  `Terrain`, `Satellite`, `Map`

### Visualisation

- Visualisation is now driven by the selected result layer, not just the base magnetic surface.
- Available layers are derived from processing outputs and chosen analysis options.
- Selected layer controls:
  stats
  scale bar
  map hover values
  heatmap/contour/3D inputs
  line profiles
- Line profiles support stack-on/off behaviour.
- Visualisation map overlay uses the same measured/predicted colours chosen in Preview.

### Processing backend

- Full results still live in GCS `results.json`, with lightweight metadata in Firestore.
- Backend now computes additional derivative layers:
  `first_vertical_derivative`
  `horizontal_derivative`
- Derived-layer handling is improved for single-traverse outputs.
- Prediction modelling depends directly on the task `scenario`:
  `explicit` trains on rows with magnetic values and predicts rows without them.
  `sparse` trains on all measured rows and predicts generated line/grid nodes from spacing settings.

## Important Files

### Frontend

- `frontend/index.html`
- `frontend/js/state.js`
- `frontend/js/sections/navigation.js`
- `frontend/js/sections/sidebar.js`
- `frontend/js/sections/setup.js`
- `frontend/js/sections/analysis.js`
- `frontend/js/sections/preview.js`
- `frontend/js/sections/maps.js`
- `frontend/js/sections/processing.js`
- `frontend/js/sections/visualisation.js`
- `frontend/js/api.js`

### Backend

- `backend/services/processing_service.py`
- `backend/services/preview_service.py`
- `backend/services/task_service.py`
- `backend/routes/tasks.py`
- `backend/routes/processing.py`
- `backend/gcp/storage_backend.py`

## Known Follow-Up Areas

1. Do a full browser-driven verification pass on the newest UI flows, especially `Projects -> New project`, `Projects -> + New task`, and task edit flows on live revision `00056-xbp`.
2. Investigate why live processing still remains in `running` during smoke polling even though upstream create/preview flows work.
3. Consider persisting explicit predicted values per predicted station instead of sampling from the grid for hover display.
4. Export Cloud Run Job still needs to be implemented if exports are to leave the request path.
5. Additional visualisations worth adding next:
   anomaly threshold masks, histograms, uncertainty overlays, directional derivatives, crossover/profile QC.

## Deployment Note

Latest successful deploy command used:

```powershell
gcloud run deploy gaia-magnetics --source gaia-magnetics --region=us-central1 --project=app-01-488817 --quiet
```
