# GAIA Magnetics Handoff

You are taking over work on `gaia-magnetics`.

Read these first:

1. `c:\Users\Tolu\Documents\Terra Analytics\Magnetics Main\2\magnetics (main)\Instructions.txt`
2. `c:\Users\Tolu\Documents\Terra Analytics\Magnetics Main\2\magnetics (main)\gaia-magnetics\STATUS.md`
3. `c:\Users\Tolu\Documents\Terra Analytics\Magnetics Main\2\magnetics (main)\gaia-magnetics\CONTEXT.md`

## Current Live State

- Public URL:
  `https://gaia-magnetics-348555315681.us-central1.run.app`
- Cloud Run service:
  `gaia-magnetics`
- Region:
  `us-central1`
- Infra project:
  `app-01-488817`
- AI project:
  `app-01-488817-ai`
- Latest ready revision:
  `gaia-magnetics-00056-xbp`
- Service account:
  `vet-dev-backend@app-01-488817.iam.gserviceaccount.com`

## What Changed Most Recently

### Navigation and projects

- `Projects` is now the top-level nav item.
- Home-page project buttons point into the projects hub.
- New project and new task actions route through the existing setup screen, but conceptually the setup screen is now under Projects.
- The previous broken setup navigation was fixed by routing directly to the `setup` screen instead of querying a missing `data-s="setup"` nav tab.
- Projects directory now also exposes an `Edit project` action.

### Preview and maps

- Preview no longer draws station-connecting lines.
- Basemap options were reduced to `Terrain`, `Satellite`, and `Map`.
- Predicted markers are filtered/layered so they do not overlap measured/base stations as badly as before.
- Measured and predicted marker colours persist from Preview into Visualisation.

### Visualisation

- Visualisation was refactored to support selectable result layers.
- Selected layer now controls:
  stats, value scale, map hover values, heatmap/contour/3D source data, and line profiles.
- Line profiles support stacking.
- Hover behaviour changes when stacking is enabled.

### Processing

- Added processing add-ons:
  `First Vertical Derivative`
  `Horizontal Derivative`
- Backend derived-layer generation was improved for single-traverse data.
- Prediction behaviour is scenario-driven:
  `explicit` predicts at explicit unknown rows.
  `sparse` predicts at generated line/grid nodes from spacing settings.

### Encoding and setup editing

- Remaining mojibake in the active frontend/backend paths was cleaned up.
- Existing tasks can now be edited via setup and saved back through the backend task-update route.
- Browser title now serves as:
  `GAIA Magnetics - V2`

### Deployment

- Latest successful deployment used source deploy to Cloud Run.
- Health endpoint was verified after deploy.
- Latest deploy verified:
  live health `ok`
  homepage `200`
  homepage free of mojibake markers in fetched HTML
  live smoke succeeded through project create, task upload, analysis save, and preview
- Live smoke still timed out waiting for processing completion.

## Most Important Files To Check First

- `frontend/index.html`
- `frontend/js/state.js`
- `frontend/js/sections/navigation.js`
- `frontend/js/sections/sidebar.js`
- `frontend/js/sections/setup.js`
- `frontend/js/sections/analysis.js`
- `frontend/js/sections/preview.js`
- `frontend/js/sections/maps.js`
- `frontend/js/sections/visualisation.js`
- `frontend/js/api.js`
- `backend/routes/tasks.py`
- `backend/services/task_service.py`
- `backend/services/processing_service.py`

## Remaining Gaps

1. Full live click-through verification still needs a deliberate browser pass, especially the latest `Projects -> setup` fixes.
2. Long-running processing still needs investigation because live smoke timed out waiting for completion.
3. `predicted_points` still rely on sampled surface values for hover/readout rather than a separately persisted predicted-value field.
4. Export Cloud Run Job is still not implemented.
5. More visualisation types can be added next if requested.

## Deploy Command

```powershell
gcloud run deploy gaia-magnetics --source gaia-magnetics --region=us-central1 --project=app-01-488817 --quiet
```

## Working Style

- Keep updates short and direct.
- Prefer fixing and verifying over only describing.
- If you deploy, report the exact revision and URL.
- If you make assumptions, state them after the work.
