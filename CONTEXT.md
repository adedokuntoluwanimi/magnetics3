# GAIA Magnetics Context

## Purpose

This file captures the working context for the `gaia-magnetics` project.
`Instructions.txt` in the parent workspace remains the single source of truth for required product behavior, architecture, workflow, and GCP design.

Last updated: `2026-03-24` after revision `gaia-magnetics-00043-fkg`.

## Workspace And Paths

- Workspace root:
  `c:\Users\Tolu\Documents\Terra Analytics\Magnetics Main\2\magnetics (main)`
- App folder:
  `c:\Users\Tolu\Documents\Terra Analytics\Magnetics Main\2\magnetics (main)\gaia-magnetics`
- Instructions file:
  `c:\Users\Tolu\Documents\Terra Analytics\Magnetics Main\2\magnetics (main)\Instructions.txt`

## Current Live Deployment

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
- Latest deployed revision:
  `gaia-magnetics-00043-fkg`
- Service account:
  `vet-dev-backend@app-01-488817.iam.gserviceaccount.com`

## Standing User Requirements

These are active constraints that must not be violated:

- `Instructions.txt` is the single source of truth.
- Preserve the folder structure.
- Use `frontend/index.html` as the UI reference — do not arbitrarily redesign it.
- Use `frontend/favicon.png` as the favicon.
- Use `frontend/logo-dark.png` as the app logo.
- Backend must be FastAPI with clean modular separation: `routes`, `services`, `models`, `gcp`.
- Real integrations only: Firestore, Cloud Storage, Pub/Sub, Cloud Run Jobs, Vertex AI, Google Maps.
- No dummy data anywhere.
- All AI features use Claude Sonnet 4.6 through Vertex AI Marketplace in project `app-01-488817-ai`.
- No emojis or decorative icons unless explicitly asked.
- Dark/light mode toggle uses ☀ (sun) and ☾ (crescent) symbols — never spells out "Dark" or "Light".

## Backend Structure

```
backend/
  main.py
  config.py
  logging_utils.py
  requirements.txt   — includes scikit-learn (required by xgboost)
  jobs/
    __init__.py
    processing_job.py  — Cloud Run Job entrypoint; reads GAIA_RUN_ID, runs pipeline
  routes/
    health.py
    projects.py        — PATCH now accepts name and/or context
    tasks.py
    processing.py      — dispatches Cloud Run Job; falls back to background thread
    ai.py
    exports.py
    maps.py
  services/
    container.py       — includes get_jobs_backend()
    project_service.py
    task_service.py    — xlsx→csv conversion + auto base station detection
    analysis_service.py
    preview_service.py — UTM→WGS84; traverse count in build_preview response
    processing_service.py
    export_service.py
    ai_service.py
    maps_service.py
  models/
    common.py
    project.py         — ColumnMapping extended with time cols + coord system fields
    processing.py
    ai.py
  gcp/
    clients.py
    firestore_store.py
    storage_backend.py
    pubsub_backend.py
    cloud_run_jobs.py  — fire-and-forget (no longer blocks on operation.result)
    vertex_ai.py
    maps.py
```

### Key model: ColumnMapping (backend/models/project.py)

```python
class ColumnMapping(GaiaModel):
    latitude: str
    longitude: str
    magnetic_field: str
    hour: str | None = None
    minute: str | None = None
    second: str | None = None
    coordinate_system: str = "wgs84"   # "wgs84" or "utm"
    utm_zone: int | None = None
    utm_hemisphere: str | None = None  # "N" or "S"
    # base_station_column and base_station_value removed — base stations are
    # auto-detected by duplicate (lat, lon) coordinate pairs
```

## Frontend Structure

```
frontend/
  index.html          — single HTML entry point, all CSS inline
  favicon.png
  logo-dark.png
  js/
    app.js
    api.js
    state.js
    shared/
      dom.js
      loaders.js
      format.js
      notice.js
      modal.js        — showConfirm() / showAlert() — branded modal, replaces browser confirm/alert
    sections/
      navigation.js
      home.js         — loadHomeStatus() exists but is NOT called anywhere
      setup.js
      analysis.js
      preview.js
      processing.js
      visualisation.js
      export.js
      maps.js
      progress.js
      sidebar.js
```

### Key frontend behaviours

- `home.js` `loadHomeStatus()` is defined but intentionally not called — live service status was removed from the home screen.
- Survey file upload accepts `.csv`, `.xlsx`, `.xls`. SheetJS (`xlsx.full.min.js` from CDN) parses xlsx headers client-side.
- Column mapping card contains a coordinate system selector (WGS84 / UTM). UTM selection shows zone + hemisphere inputs.
- When Raw data is selected in Project Setup, a "Time columns" section appears under column mapping with Hour / Minutes / Seconds selectors.
- Coordinate system is always sent with task creation (not only raw data) so preview can convert UTM points reliably.
- Base station detection: **auto-detected by duplicate (lat, lon) coordinates** — any coordinate pair appearing more than once is flagged as a base station. `__is_base_station__` column added automatically. No user input required. xlsx bold-row detection is still present for xlsx uploads.
- Diurnal correction uses base station rows + time columns (hour/minute/second) to interpolate a magnetic time series at each survey measurement time via `numpy.interp`.
- Explicit scenario: rows with no magnetic reading = prediction targets. Rows with a reading = training data.
- Sparse scenario: all rows are training data; backend generates a regular prediction grid. User sets spacing (metres); must be ≥ 1 and ≤ traverse length or upload is rejected.
- Prediction toggle: `#predModelToggle` in analysis screen. When off, `run_prediction: false` is sent and modelling steps are skipped.
- Sidebar actions are in a `⋮` dropdown (`.sb-dots-wrap` → `.sb-dropdown`) — not inline buttons.
- Sidebar is resizable by dragging the right edge (6 px zone) — no visible handle element.
- Project overview screen (`#screen-project`) is separate from workflow tabs. Accessed only by clicking a project in the sidebar.
- Project header button order: New task → Delete project → Open analysis.
- Task 3-dot menu includes "Edit task setup" — calls `window.loadTaskForEdit(task, project)` to pre-fill step 2 form.
- Preview map: fullscreen button (`.map-fs-btn`), color picker (`.map-color-picker`, 6 swatches). `recolorSurveyMarkers(color)` exported from `maps.js`.
- Preview map predicted points (sparse): hollow blue circles rendered separately from measured green filled circles.
- Preview uses backend predicted points only (no synthetic fallback).
- Preview basemap selector is custom; Google map type control is disabled.
- Processing page no longer renders a map panel.

## Recent Fixes (2026-03-24)

- Processing results payload is sanitized (NaN/inf -> null) before saving to Firestore to avoid InvalidArgument errors.
- Multi-line surveys are merged during processing (all survey files are loaded).
- Predicted points are clamped to measured bounds both in preview and processing outputs.
- Processing with prediction modelling disabled now uses nearest-neighbor interpolation on real data (no dummy grid/surface).
- Basemap choices limited to Terrain, Satellite, Hybrid, Dark.

## Infrastructure And Runtime Configuration

### Cloud Run Environment Variables

- `AI_PROVIDER=vertex_claude`
- `GOOGLE_CLOUD_PROJECT=app-01-488817-ai`
- `GOOGLE_CLOUD_REGION=us-central1`
- `CLAUDE_MODEL=claude-sonnet-4-6`
- `GCS_BUCKET_RAW=gs://gaia-magnetics-uploads-app-01-488817`
- `GCS_BUCKET_PROCESSED=gs://gaia-magnetics-results-app-01-488817`
- `GCS_BUCKET_EXPORTS=gs://gaia-magnetics-results-app-01-488817/exports`
- `GAIA_INFRA_PROJECT_ID=app-01-488817`
- `GAIA_AI_PROJECT_ID=app-01-488817-ai`
- `GAIA_REGION=us-central1`
- `GAIA_SERVICE_NAME=gaia-magnetics`
- `GAIA_UPLOADS_BUCKET=gaia-magnetics-uploads-app-01-488817`
- `GAIA_RESULTS_BUCKET=gaia-magnetics-results-app-01-488817`
- `GAIA_PUBLIC_BUCKET=gaia-magnetics-results-app-01-488817`
- `GAIA_PROCESSING_TOPIC=gaia-magnetics-processing`
- `GAIA_EXPORT_TOPIC=gaia-magnetics-export`
- `GAIA_MAPS_API_KEY_SECRET=gaia-google-maps-api-key`
- `GAIA_AURORA_MODEL=claude-sonnet-4-6`

### GCP Resources

- Firestore database: `(default)` in project `app-01-488817`
- Upload bucket: `gs://gaia-magnetics-uploads-app-01-488817`
- Results bucket: `gs://gaia-magnetics-results-app-01-488817`
- Pub/Sub topic: `gaia-magnetics-processing`
- Pub/Sub topic: `gaia-magnetics-export`
- Secret Manager secret: `gaia-google-maps-api-key` — exposed via `/api/maps/key`
- Artifact Registry: `us-central1-docker.pkg.dev/app-01-488817/gaia/`

### Maps Notes

- Google Maps key is in Secret Manager **version 3** (`gaia-google-maps-api-key`).
- Active key is the **"GAIA Magnetics Maps"** key — restricted to `maps-backend.googleapis.com`, with `browserKeyRestrictions` allowing both Cloud Run URL patterns.
- The key is NOT stored in this file for security reasons.
- The key at Secret Manager version 1–2 was a different, unconfigured key. Version 3 is the correct one.
- Map type is `roadmap`. Maps JS URL does NOT include `loading=async` — that parameter defers `window.google.maps` population past the `<script onload>` event, causing `maps.Map is not a constructor`. Use the synchronous load path.
- `fitBounds` fires after the map `idle` event with a `resize` trigger, plus a secondary `setTimeout` resize at 600ms to catch white-tile edge cases.
- If tiles still appear white: open browser Network tab and look for `maps.googleapis.com/maps/vt` requests — check their HTTP status to distinguish key/billing issues from rendering issues.

## Deployment History

| Revision | Change |
|----------|--------|
| `00003–00007` | Initial build and workspace restore |
| `00012-8wv` | Two-pane setup, sidebar projects-only, column mapping, api.js 422 fix |
| `00015-hkl` | Sidebar actions, inline rename, collapsible, project overview screen, reference files, backend rename/delete |
| `00016` | Analysis screen wired, preview screen fixed, processing_service ID fix |
| `00017` | Preview map points from GCS CSV, container.py updated |
| `00018` | (intermediate) |
| `00019-hs9` | Live status removed, capabilities rewritten, 3-dot sidebar menus, project edit/delete, time columns, scroll-to-top, maps roadmap fix |
| `00020-stg` | Live status removed from app.js, emojis removed, base station UI changed, Maps resize fix |
| `00021-6ks` | xlsx upload, bold base station detection (openpyxl), UTM conversion (pyproj), ColumnMapping extended, coord system selector, ☀/☾ mode toggle |
| `00022-vbk` | Secret Manager updated to correct Maps key (version 3); Maps URL adds `loading=async`; secondary resize at 600ms for white-tile fix |
| `00024-b4b` | Preview map fix: always send coordinate system in task payload so UTM points render; Maps JS load uses `loading=async` |
| `00025` | Maps white-tile fix: removed loading=async; UTM hemisphere detection corrected; container height fix; preview loading overlay |
| `00026-kk7` | Base station auto-detect (duplicate coords); diurnal via time interpolation; explicit/sparse scenario rewrites; sparse spacing validation; prediction toggle; map color picker; sidebar edge resize; branded modals; project header reorder; edit task from sidebar |
| `00027-7lb` | Maps fix: removed `loading=async` from Maps JS URL — `window.google.maps` was undefined after script load causing `maps.Map is not a constructor` |
| `00028-mqk` | scikit-learn added (XGBoost crash fix); Cloud Run Job architecture: `backend/jobs/processing_job.py` entrypoint, `cloud_run_jobs.py` fire-and-forget, processing route dispatches job with thread fallback; `gaia-magnetics-processing` Cloud Run Job created; processing page map replaced with real Google Maps; preview traverse/predicted-traverse stats |

## Deploy Command

```
gcloud builds submit --tag us-central1-docker.pkg.dev/app-01-488817/gaia/gaia-magnetics:latest .
gcloud run deploy gaia-magnetics --image us-central1-docker.pkg.dev/app-01-488817/gaia/gaia-magnetics:latest --region us-central1 --project app-01-488817
```

## Architectural Gaps Still Open

- Export generation still runs inside the API service — needs Cloud Run Jobs (`gaia-magnetics-export` job not yet created)
- Full live end-to-end browser path not yet conclusively verified:
  `project → upload → analysis → preview → processing → visualisation → export`
- True Esri File GDB export not implemented — current output is a pseudo-zip bundle
- Processing Cloud Run Job dispatch requires `vet-dev-backend` service account to have `roles/run.developer` — verify on first live processing run

## Cloud Run Jobs

### Processing job — `gaia-magnetics-processing`
- Region: `us-central1`, project `app-01-488817`
- Image: same as the API service (`gaia-magnetics:latest`)
- Command: `python -m backend.jobs.processing_job`
- Memory: 2 GiB, CPU: 2, max-retries: 0, timeout: 30 min
- Env vars: same project/bucket/model vars as the API service
- Triggered by `POST /api/processing/tasks/{id}/runs` — API dispatches fire-and-forget, falls back to background thread if dispatch fails

### Export job — not yet created
- Will use `gaia-magnetics-export` job name (already in `config.py`)
- Create command when ready:
  ```
  gcloud run jobs create gaia-magnetics-export \
    --image us-central1-docker.pkg.dev/app-01-488817/gaia/gaia-magnetics:latest \
    --region us-central1 --project app-01-488817 \
    --service-account vet-dev-backend@app-01-488817.iam.gserviceaccount.com \
    --command python --args="-m" --args="backend.jobs.export_job" \
    --memory 2Gi --cpu 2 --max-retries 0 --task-timeout 1800
  ```

## Important Notes For The Next Person

- The user cares about no dummy data and wants the app to work from the frontend, not only API tests.
- The user is sensitive to long waits without visible status — always preserve flash messages and progress indicators.
- Do not rename or restructure existing files without explicit instruction.
- If another workspace restore is ever needed, backup is in `.codex-restore\backup-current`.
- The user's survey data uses UTM coordinates (e.g. Long=541780, Lat=745700 in Zone 32N, Northern hemisphere) — not decimal degrees. The coordinate system selector must be set to UTM for correct map rendering.
