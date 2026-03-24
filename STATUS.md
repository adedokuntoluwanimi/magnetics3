# GAIA Magnetics Status

## Snapshot

- App URL:
  `https://gaia-magnetics-348555315681.us-central1.run.app`
- Cloud Run service:
  `gaia-magnetics`
- Current revision:
  `gaia-magnetics-00043-fkg`
- Infra project:
  `app-01-488817`
- AI project:
  `app-01-488817-ai`

## What Exists

- FastAPI backend with modular routes, services, models, and GCP integration modules
- Frontend expanded from `frontend/index.html` into modular ES-module JS sections
- Firestore, Cloud Storage, Pub/Sub, Google Maps, and Vertex AI wiring in place
- Full workflow scaffolded and partially live: Setup → Analysis → Preview → Processing → Visualisation → Export
- Context and handoff docs:
  `CONTEXT.md`
  `HANDOFF.md`

## Completed Work — Chronological

### Initial build
- FastAPI backend scaffolded, deployed to Cloud Run
- Project/task flows wired (Firestore + GCS)
- Google Maps key via Secret Manager
- Aurora wired to Claude Sonnet 4.6 on Vertex AI
- Frontend modularised into ES sections

### Project Setup UI overhaul (2026-03-20)
- Two-pane flow (step 1: project details, step 2: task setup)
- CSV upload fully wired, column mapping auto-populated from headers
- Frontend validation before API calls

### Sidebar overhaul (2026-03-20)
- Projects-only list, inline collapsible task sub-lists
- Hover-revealed action buttons (View, New task, Rename, Delete / Open, Rename, Delete)
- Inline rename, delete with confirmation, resizable sidebar

### Project overview screen (2026-03-20)
- `#screen-project` shows project context, task cards with lifecycle badges and per-task actions

### Backend rename/delete endpoints (2026-03-20)
- `PATCH` / `DELETE` for projects and tasks, cascading project delete

### Analysis screen wiring (2026-03-20)
- `analysis.js` fully wired: `collectAnalysisConfig`, `persistAnalysis`, `loadAnalysis`, `initAnalysis`
- Correction and add-on IDs normalised to short backend IDs (`diurnal`, `igrf`, `analytic_signal`, etc.)
- `saveAndPreview` flow: persists analysis config to Firestore then navigates to Preview

### Preview screen fixes (2026-03-20)
- Replaced fragile `:nth-of-type` card selector with stable element IDs on every `.cv` span
- Dataset row removed; all config values render correctly
- `preview_service.py` loads up to 500 survey points from GCS CSV for the map
- `container.py` updated to pass `storage_backend` to `PreviewService`
- Correction / add-on display-name mapping added in `preview.js`

### Preview + home page improvements (2026-03-20, rev 00019)
- Live service status section removed from home page entirely (was leaking backend architecture)
- Core capability cards rewritten with user-facing language, no emojis
- Sidebar action buttons moved to a `⋮` (three-dot) dropdown menu per row
- Book emoji removed from "No tasks yet" placeholder
- Project screen: "Edit context" inline button + "Delete project" button added
- Backend `PATCH /api/projects/{id}` extended to accept optional `context` field (in addition to `name`)
- `renameProject(id, name, context)` API function updated — both fields optional
- Data upload: when Raw data is selected, Time columns section appears (Hour/Min/Sec column selectors)
- `setup.js` scrolls to top and shows flash message during project/task creation
- Google Maps: changed `mapTypeId` from `terrain` to `roadmap`; `fitBounds` now fires after map `idle` event with a `resize` trigger

### Further preview + upload fixes (2026-03-20, rev 00020)
- Live status call removed from `app.js` (was still firing on boot despite nav.js fix)
- All emojis removed from capability cards
- Base station approach changed: separate CSV upload removed; base station info section replaced with instruction text explaining the xlsx bold-row detection approach
- Google Maps: container given explicit pixel height before map init; `resize` + `fitBounds` both triggered after `idle`

### xlsx + UTM + dark/light symbols (2026-03-20, rev 00021)
- Dark/light toggle now uses ☀ / ☾ symbols instead of spelling out "Dark" / "Light"
- Survey file upload now accepts `.xlsx` and `.xls` in addition to `.csv`
- SheetJS (`xlsx` library) loaded from CDN for client-side xlsx header parsing
- Backend: `openpyxl` added to requirements; `_xlsx_to_csv_bytes()` in `task_service.py` converts xlsx to CSV and detects bold rows → `__is_base_station__ = 1` column
- Backend: `pyproj` added to requirements
- `ColumnMapping` model extended: `hour`, `minute`, `second`, `coordinate_system`, `utm_zone`, `utm_hemisphere` fields
- Coordinate system selector added inside column mapping card (WGS84 / UTM); UTM shows zone + hemisphere inputs
- `preview_service.py` converts UTM easting/northing → WGS84 lat/lon via pyproj before returning preview points
- Auto-zone detection falls back to zone 32 N/S based on northing magnitude

### Google Maps key + loading=async fix (2026-03-20, rev 00022)
- Diagnosed two-key mismatch: Secret Manager held an unconfigured key; app now uses the "GAIA Magnetics Maps" key (Secret Manager version 3) which has correct referrer and API restrictions
- `maps.js`: added `loading=async` to Maps JS URL (fixes legacy init warning, may resolve white-tile issue)
- `maps.js`: added secondary `resize` + `fitBounds` trigger at 600ms to recover from layout-timing white-tile cases

### Preview map conversion fix (2026-03-21, rev 00024)
- `setup.js`: always includes `coordinate_system` (and UTM zone/hemisphere when applicable) in task creation so preview converts UTM points even when data state is Corrected

### Major feature batch (2026-03-22, rev 00026-kk7)
- Base station auto-detection by duplicate (lat, lon) coordinates — `__is_base_station__` column added in `task_service.py`
- Diurnal correction via base station time series interpolation (`numpy.interp`) in `processing_service.py`
- Explicit scenario: train on rows with magnetic values, predict on rows with null magnetic
- Sparse scenario: train on all measured rows, generate regular prediction grid; spacing validated against traverse length
- Sparse preview map: hollow blue circles = predicted nodes, green filled = measured stations
- Prediction modelling toggle (`#predModelToggle`) — skips modelling when off
- Map color picker (6 swatches) and `recolorSurveyMarkers(color)` in `maps.js`
- Sidebar edge resize (no visible handle — 6 px right-edge detection)
- Branded confirm/alert modals (`frontend/js/shared/modal.js`)
- Project header: New task → Delete project → Open analysis
- Edit task from sidebar 3-dot menu (`window.loadTaskForEdit`)
- Setup errors scroll to top before flash
- Preview fullscreen button
- Preview loading overlay with three-stage labels
- Processing step names: user-friendly strings

### Maps `maps.Map is not a constructor` fix (2026-03-22, rev 00027-7lb)
- Removed `loading=async` from Maps JS URL. Synchronous load path used instead.

### Processing crash fix + Cloud Run Jobs + map + traverse stats (2026-03-22, rev 00028-mqk)
- `scikit-learn==1.6.1` added — was missing, causing `ImportError` in `XGBRegressor` on every processing run
- `backend/jobs/processing_job.py` created — Cloud Run Job entrypoint reads `GAIA_RUN_ID`, runs full pipeline, writes Firestore step updates
- `cloud_run_jobs.py` changed to fire-and-forget (no blocking on `operation.result`)
- `routes/processing.py` dispatches `gaia-magnetics-processing` Cloud Run Job; falls back to background thread on failure
- `gaia-magnetics-processing` Cloud Run Job created (us-central1, 2 vCPU / 2 GiB, 30 min timeout)
- Processing page SVG map replaced with real Google Maps (`#procMapHost`)
- Preview page: Survey traverses + Predicted traverses rows added; `preview_service.py` computes them from point groupings

### E2E fixes (2026-03-24, rev 00044-55t)

- **pyproj `transform` removed fix**: Both `preview_service.py` and `processing_service.py` used `from pyproj import transform` which was deleted in pyproj 3.0 (installed: 3.7.1). Replaced with `Transformer.from_proj(..., always_xy=True)` in both files. This was crashing all UTM data (preview map empty, processing failed).
- **Signed URL → download proxy**: `_safe_signed_url` in `storage_backend.py` now tries metadata-server signing (SA email + access token) first. Falls back to `/api/storage/download?bucket=...&object=...` proxy endpoint instead of direct public GCS URL (bucket is private). New `backend/routes/storage.py` added with `GET /api/storage/download` endpoint that streams GCS objects through the API.
- **PDF export None crash**: `task["description"]` in `_build_pdf` replaced with `task.get("description") or ""` to guard against None.
- Cloud Run Job `gaia-magnetics-processing` updated to same image so UTM fix applies to job execution too.

### Processing + preview + basemap cleanup (2026-03-23 to 2026-03-24, rev 00040 to 00043)

- Preview uses backend predicted points only (no synthetic fallback).
- Processing loads all survey files (multi-line mode) and clamps predicted points to measured bounds.
- Processing with prediction modelling disabled uses nearest-neighbor interpolation instead of dummy grids/surfaces.
- Results payload sanitized before Firestore save (NaN/inf -> null) to prevent InvalidArgument errors.
- Processing page map panel removed.
- Basemap selector is custom-only; Google map type control disabled.
- Basemap choices reduced to Terrain, Satellite, Hybrid, Dark.
- Visualisation modes show clear fallback messages when required data is missing.

## Main Remaining Gaps

- Export generation still runs inside the API service — `gaia-magnetics-export` Cloud Run Job not yet created
- Full end-to-end live browser path not yet conclusively verified
- True Esri File GDB export not implemented (current output is a zip bundle)
- Verify diurnal correction, explicit scenario, and sparse spacing with real survey data
- Confirm `vet-dev-backend` service account has `roles/run.developer` for job dispatch

## Read Next

1. `..\Instructions.txt`
2. `CONTEXT.md`
3. `HANDOFF.md`
