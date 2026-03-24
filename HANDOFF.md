# GAIA Magnetics Handoff Directive

You are the next chat taking over work on `gaia-magnetics`.

Read these first, in order:

1. `c:\Users\Tolu\Documents\Terra Analytics\Magnetics Main\2\magnetics (main)\Instructions.txt`
2. `c:\Users\Tolu\Documents\Terra Analytics\Magnetics Main\2\magnetics (main)\gaia-magnetics\CONTEXT.md`

## Non-Negotiable Rules

- Treat `Instructions.txt` as the single source of truth.
- Do not delete or rename the existing folder structure.
- Use `frontend/index.html` as the UI reference.
- Do not reintroduce dummy data, emojis, or icons unless explicitly requested.
- All AI paths must use Claude Sonnet 4.6 through Vertex AI Marketplace in project `app-01-488817-ai`.
- Preserve the live service unless the user explicitly asks for a different deployment target.
- No spelling out "Dark" or "Light" — use ☀ / ☾ symbols for the theme toggle.

## Current State At Handoff

- Public app URL:
  `https://gaia-magnetics-348555315681.us-central1.run.app`
- Cloud Run service:
  `gaia-magnetics`
- Region:
  `us-central1`
- Infra project:
  `app-01-488817`
- AI project:
  `app-01-488817-ai`
- Current revision:
  `gaia-magnetics-00046-xlp` (deployed 2026-03-24)
- Git commit:
  `7305d04` on `github.com:adedokuntoluwanimi/magnetics3` branch `main`
- Service account:
  `vet-dev-backend@app-01-488817.iam.gserviceaccount.com`

---

## What Was Done — Session ending 2026-03-20 (revisions 00016 → 00021)

### Analysis screen fully wired (rev 00016)

**Files changed:** `frontend/js/sections/analysis.js`, `frontend/js/app.js`, `frontend/js/sections/navigation.js`

- `analysis.js` complete rewrite: `collectAnalysisConfig()` normalises to short backend IDs, `persistAnalysis()` saves to Firestore, `loadAnalysis(task)` restores UI from saved config, `initAnalysis()` exposes `window.saveAndPreview`.
- Correction/add-on IDs are now short strings everywhere: `diurnal`, `igrf`, `filtering`, `lag`, `heading`, `rtp`, `analytic_signal`, `emag2`, `uncertainty`.
- `processing_service.py` updated to match same IDs in `_apply_corrections` and `_apply_add_ons`.

### Preview screen fixed (rev 00016–00017)

**Files changed:** `frontend/js/sections/preview.js`, `frontend/index.html`, `backend/services/preview_service.py`, `backend/services/container.py`

- Replaced `setCardValues(cardIndex, values)` (`:nth-of-type` mismatch bug) with `setVal(id, text)` using stable element IDs.
- Dataset row removed; display-name maps added for correction/add-on/model IDs.
- `preview_service.py` now accepts `storage_backend` and loads up to 500 survey points from GCS CSV using `column_mapping`.
- `container.py`: `get_preview_service()` passes `get_storage_backend()`.

### Home page and sidebar polish (rev 00019)

**Files changed:** `frontend/index.html`, `frontend/js/sections/navigation.js`, `frontend/js/sections/sidebar.js`, `frontend/js/sections/setup.js`, `backend/routes/projects.py`, `frontend/js/api.js`

- Live service status removed from home page (both `navigation.js` and `app.js` call sites).
- Capability cards rewritten — no architecture details, no emojis.
- Sidebar action buttons replaced with `⋮` dropdown menu (`.sb-dots-wrap`, `.sb-dropdown`, `.sb-dd-item`). Dropdown is `position:fixed`, positioned from `getBoundingClientRect`. Auto-closes on outside click.
- Book emoji removed from "No tasks yet" project screen placeholder.
- Project screen: "✎ Edit" button on context card enables inline textarea editing. "⊗ Delete project" button in header.
- Backend `PATCH /api/projects/{id}`: `ProjectPatch` model accepts optional `name` and/or `context`. Updates only the provided fields.
- `renameProject(projectId, name, context)` in `api.js` — both `name` and `context` are optional keyword args.
- Raw data section: Time column mapping (Hour/Min/Sec selectors) appears when Raw data is selected; toggles with `setState`.
- `setup.js` scrolls to top with smooth behaviour at start of `submitTaskFlow`.
- Google Maps: `mapTypeId` set to `roadmap`; `fitBounds` deferred to `idle` event.

### Further Google Maps and base station changes (rev 00020)

**Files changed:** `frontend/js/app.js`, `frontend/index.html`, `frontend/js/sections/maps.js`, `frontend/js/sections/setup.js`

- `loadHomeStatus` import and call removed from `app.js` entirely.
- All emojis stripped from capability cards.
- Separate base station CSV upload removed from setup. Replaced with descriptive text explaining the xlsx bold-row approach.
- `maps.js`: container gets explicit pixel height before map init; `resize` event triggered inside `idle` listener before `fitBounds`.

### xlsx upload, bold base station detection, UTM conversion, symbols (rev 00021)

**Files changed:** `frontend/index.html`, `frontend/js/sections/setup.js`, `frontend/js/sections/navigation.js`, `backend/requirements.txt`, `backend/models/project.py`, `backend/services/task_service.py`, `backend/services/preview_service.py`

#### Dark/light mode
`navigation.js` `toggleDark`: `button.textContent = dark ? "\u2600" : "\u263D"` (☀ / ☾).

#### xlsx support + bold base station detection
- `surveyInput.accept` extended to include `.xlsx,.xls`.
- SheetJS `xlsx.full.min.js` loaded from CDN (`xlsx-0.20.3`) in `<head>`.
- `readFileHeaders(file)`: if filename ends `.xlsx?`, uses `window.XLSX.read()` + `sheet_to_json` to extract header row; otherwise reads as text.
- `handleFiles()` calls `readFileHeaders()` instead of direct `.text()`.
- Backend: `openpyxl==3.1.5` added to `requirements.txt`.
- `task_service.py`: `_xlsx_to_csv_bytes(raw_bytes)` — loads workbook with openpyxl, iterates rows, detects bold rows (all non-empty cells have `font.bold=True`), appends `__is_base_station__` column (1/0), returns UTF-8 CSV bytes.
- In `create_task`: xlsx/xls files are normalised through `_xlsx_to_csv_bytes` before profiling and GCS upload. Stored object name gets `.csv` extension.

#### UTM coordinate conversion
- `pyproj==3.7.1` added to `requirements.txt`.
- `ColumnMapping` model extended: `hour`, `minute`, `second`, `coordinate_system` (default `"wgs84"`), `utm_zone`, `utm_hemisphere`.
- `index.html`: coordinate system radio (WGS84 / UTM) inside column mapping card, shown after file is uploaded. UTM selection reveals zone number input + hemisphere dropdown.
- `setup.js`: `window.setCoordSystem(cs)` toggles radio state, shows/hides UTM zone row, stores on `window.state.coordSystem`. `submitTaskFlow` reads zone/hemisphere and adds to `mapping` before serialising to FormData.
- `preview_service.py`: `_utm_to_wgs84(easting, northing, zone, hemisphere)` via pyproj. `_auto_utm_zone(easting, northing)` heuristic (northing >= 5M → N, else S; zone defaults to 32). `_extract_preview_points` branches on `coordinate_system == "utm"` — converts each row before returning lat/lon.

### Google Maps key fix + loading=async (rev 00022)

**Files changed:** `frontend/js/sections/maps.js` (code); Secret Manager updated outside codebase

#### Root cause investigation
- Two API keys exist on `app-01-488817`:
  - "API key 3" (`AIzaSyAQ35P2u6NIYG9PS2vukDEg7vFqckc9hgs`) — no restrictions at all; was stored in Secret Manager versions 1–2
  - "GAIA Magnetics Maps" (`AIzaSyCZnI90Ur9iDCvQAppQ_nlui7dO4S0TEPE`) — restricted to `maps-backend.googleapis.com`, `browserKeyRestrictions` allows both Cloud Run URL patterns
- Secret Manager `gaia-google-maps-api-key` **version 3** now holds the correct "GAIA Magnetics Maps" key.
- The Maps JS library was loading (`loading=async` warning in console confirmed library reached the browser), but tiles were white.

#### Code changes
- `maps.js` `ensureGoogleMaps()`: Maps URL now includes `&loading=async` — required by Google's newer Maps JS API; without it the library uses legacy synchronous init that can leave tiles unrendered.
- `maps.js` `renderStationMap()`: added secondary `setTimeout(() => { trigger resize + fitBounds }, 600)` after the `idle` listener — catches cases where the container is still being laid out when the first resize fires.

#### Still to verify
- User should hard-refresh and navigate to Preview to confirm tiles now render.
- If still white: open browser Network tab, check `maps.googleapis.com/maps/vt` requests for HTTP errors.

## What Was Done — Session ending 2026-03-22 (revisions 00026 → 00028)

### Major feature batch (rev 00026-kk7)

**Files changed:** `frontend/index.html`, `frontend/js/sections/maps.js`, `frontend/js/sections/preview.js`, `frontend/js/sections/sidebar.js`, `frontend/js/sections/setup.js`, `frontend/js/sections/analysis.js`, `frontend/js/sections/processing.js`, `frontend/js/sections/progress.js`, `frontend/js/shared/modal.js` (new), `backend/services/task_service.py`, `backend/services/preview_service.py`, `backend/services/processing_service.py`, `backend/models/project.py`

- **Base station auto-detection**: duplicate (lat, lon) coordinates in a CSV = base station readings. `_auto_detect_base_stations()` in `task_service.py` adds `__is_base_station__` column. No user-selectable column needed.
- **Diurnal correction**: `processing_service.py` uses `__is_base_station__` rows + hour/minute/second columns to interpolate a base station time series via `numpy.interp`. Falls back to median if no base station rows found.
- **Explicit scenario rewrite**: `_prepare_prediction_inputs` — train on rows where `magnetic` is not null; predict on rows where `magnetic` IS null (they are the target coordinates with no reading).
- **Sparse scenario rewrite**: train on all measured rows; predict on regular grid. Spacing validated: must be ≥ 1 m and ≤ traverse length (diagonal of bounding box). `ValueError` raised before processing if invalid.
- **Sparse map**: preview and result maps show hollow blue circles for predicted grid nodes and green filled circles for measured stations. `renderStationMap` accepts `{predictedPoints}` option.
- **Prediction modelling toggle**: `#predModelToggle` checkbox in analysis screen; `run_prediction: false` skips modelling steps in `execute_run`.
- **Map color picker**: 6 preset swatches in preview/visualisation; `recolorSurveyMarkers(color)` updates all survey markers in place.
- **Sidebar edge resize**: removed `#sbResizeHandle` element; `initSidebarResize()` detects mousedown within 6 px of sidebar right edge instead.
- **Branded modals**: `frontend/js/shared/modal.js` — `showConfirm()` and `showAlert()` replace all browser `confirm()`/`alert()` calls.
- **Project header button order**: New task → Delete project → Open analysis.
- **Edit task from sidebar**: 3-dot dropdown includes "Edit task setup" — calls `window.loadTaskForEdit(task, project)` which pre-fills step 2 form.
- **Setup errors scroll to top**: `submitTaskFlow` scrolls `#setupScroll` to top before showing flash message.
- **Preview fullscreen button**: `.map-fs-btn` in top-right of preview map container.
- **Preview loading overlay**: three-stage label progression while map data loads.
- **Processing step names**: user-friendly — "Data loading", "Data cleaning", "Corrections", "Station grid", "Modelling", "Derived layers", "Save results".
- **`ColumnMapping` model**: removed `base_station_column` and `base_station_value` (replaced by auto-detection).

### Maps `maps.Map is not a constructor` fix (rev 00027-7lb)

**Files changed:** `frontend/js/sections/maps.js`

- Root cause: `loading=async` was back in the Maps JS URL. With that parameter, `window.google.maps` is not populated when `<script onload>` fires, causing `maps.Map is not a constructor`.
- Fix: removed `&loading=async` from the Maps API URL.

### Processing crash fix + Cloud Run Jobs + processing map + traverse stats (rev 00028-mqk)

**Files changed:** `backend/requirements.txt`, `backend/jobs/__init__.py` (new), `backend/jobs/processing_job.py` (new), `backend/gcp/cloud_run_jobs.py`, `backend/routes/processing.py`, `backend/services/container.py`, `backend/services/preview_service.py`, `frontend/index.html`, `frontend/js/sections/processing.js`

#### Processing crash fix
- `scikit-learn==1.6.1` added to `requirements.txt` — `XGBRegressor` requires it; its absence caused `ImportError` on every processing attempt.

#### Cloud Run Jobs architecture
- `backend/jobs/processing_job.py`: standalone entrypoint — reads `GAIA_RUN_ID` from env, instantiates `ProcessingService`, calls `execute_run()`. The job writes all step updates to Firestore as it runs.
- `cloud_run_jobs.py`: `_run_job` now fire-and-forget — submits the execution and returns immediately instead of blocking on `operation.result(timeout=60)`.
- `routes/processing.py`: tries `jobs.run_processing_job({"GAIA_RUN_ID": run_id})` first; if that raises (job not reachable, permission issue, etc.), logs a warning and falls back to `background_tasks.add_task(service.execute_run, run_id)`. Either way the run proceeds.
- `container.py`: `get_jobs_backend()` factory added.
- `gaia-magnetics-processing` Cloud Run Job created: same image, `python -m backend.jobs.processing_job`, 2 vCPU / 2 GiB RAM, 30-min timeout, max-retries 0.

#### Processing page map
- SVG dot map (`#procMapSvg`) replaced with a real Google Maps container (`#procMapHost`).
- `processing.js` imports `renderStationMap` and renders the live Google Maps view using `dataset_profile.preview_points`. Map only initialises once per task to avoid re-creating on each poll tick.

#### Preview traverse stats
- `preview_service.py`: `_count_traverses(points, predicted_points, task)` groups points by the perpendicular axis (latitude for E-W surveys, longitude for N-S surveys) at 3× station-spacing tolerance. Returns `(survey_count, predicted_count)`. Both values included in `build_preview` response.
- `index.html`: two new rows in preview "Project & task" card — `#pv-traverses` and `#pv-pred-traverses`.
- `preview.js`: populates both rows from `payload.traverse_count` and `payload.predicted_traverse_count`.

## What Was Done — Session ending 2026-03-24 (revisions 00040 → 00043)

- Preview uses backend predicted points only; synthetic fallback removed.
- Processing loads all survey files, clamps predicted points to measured bounds.
- Processing with prediction modelling disabled uses nearest-neighbor interpolation on real data (no dummy grid/surface).
- Results payload sanitized (NaN/inf -> null) before Firestore save to prevent InvalidArgument errors.
- Processing page map panel removed.
- Basemap selector uses custom dropdown only; Google map type control disabled.
- Basemap choices reduced to Terrain, Satellite, Hybrid, Dark.
- Visualisation shows fallback messaging when required data is missing.

---

## Previous Session Work (2026-03-21, revision 00024)

### Preview map conversion + loader update

**Files changed:** `frontend/js/sections/setup.js`, `frontend/js/sections/maps.js`

- `setup.js`: always sends `coordinate_system` (plus UTM zone/hemisphere when set) during task creation so preview conversion works even with Corrected data.

---

## Previous Session Work (2026-03-20, revisions 00012–00015)

See `CONTEXT.md` → "Major Functional Work Added After Initial Build" for full detail.

Key items:
- Two-pane project setup flow
- Sidebar collapsible projects, hover action buttons, inline rename, resizable
- Project overview screen (`#screen-project`)
- Reference files upload (replaced basemap)
- Backend `PATCH`/`DELETE` endpoints for projects and tasks

---

## What Was Done — Session ending 2026-03-24 (revisions 00045 → 00046)

### Firestore crash fix + GCS results architecture (rev 00045-z85)

**Root cause**: `_persist_outputs` stored 2D numpy arrays as list-of-lists in Firestore. Firestore rejects nested arrays (`InvalidArgument: 400 Property results contains invalid nested entity`).

**Fix**:
- Strip `_2d_keys = {"grid_x", "grid_y", "surface", "uncertainty", "analytic_signal", "filtered_surface", "emag2_residual", "rtp_surface"}` from Firestore payload.
- Full results stored only in GCS `results.json`.
- New endpoint `GET /api/projects/{id}/tasks/{id}/results` in `backend/routes/tasks.py` — downloads and returns full `results.json` from GCS.
- `frontend/js/api.js` — added `fetchTaskResults(projectId, taskId)`.
- `visualisation.js` — `loadVisualisation` now calls `fetchTaskResults()` instead of reading Firestore data. Fixes blank visualisation screen after processing completes.
- `export_service.py` — `_load_full_results(task)` reads from GCS artifacts; `create_export` no longer reads from `task["results"]["data"]`.
- `backend/routes/storage.py` (new) — `GET /api/storage/download` proxy for GCS objects when signed URL signing fails.

### UI/UX + base stations + layer toggles (rev 00046-xlp)

**Files changed:** `frontend/index.html`, `frontend/js/sections/navigation.js`, `frontend/js/sections/analysis.js`, `frontend/js/sections/setup.js`, `frontend/js/sections/processing.js`, `frontend/js/sections/visualisation.js`, `frontend/js/sections/maps.js`, `frontend/js/api.js`, `backend/services/preview_service.py`, `backend/services/processing_service.py`

- Home page: GAIA full name added; footer text (GAIA v2.0 / Terracode Cloud) removed.
- Nav guard: workflow screens block without active project (shows notice, stays on home).
- Sidebar: complete collapse, no residual button. Hidden on preview and home screens.
- Analysis: diurnal checkbox disabled (opacity 0.4, pointer-events none, auto-unchecked) when `data_state === "corrected"`.
- Setup: spacing suggestion entirely removed.
- Processing: Modelling step filtered out of pipeline cards when `run_prediction === false`. Per-step ETA labels. Config summary card renders actual user choices.
- Maps: survey traverse polylines via `maps.Polyline` per `line_id`. Base stations = orange triangles (`"M 0,-6 6,6 -6,6 Z"`), popup shows "Used for diurnal correction". `MAP_STYLES` extended with Light, Muted green, Greyscale, Dark.
- Preview service: `is_base_station` flag added to preview points — explicit column match or duplicate (lat,lon) detection.
- Processing service: `is_base_station` + `line_id` in `points` output for both prediction and non-prediction branches.
- Visualisation: Aurora panel → Results layers toggle panel (`#visLayerToggles` + `#visInterpretation`). `renderAurora` and `askAurora` import removed. Layer toggles call `window.switchVisLayer(layerId)`. Stats use real min/max. Map overlay passes `predictedPoints` to `renderStationMap`.

## If The User Asks To Continue Building

### Must fix next deploy (in priority order)

1. **Heatmap/Contour/3D without prediction** (`processing_service.py`): when `run_prediction=false`, generate a scipy griddata surface from corrected points so all vis modes work.
2. **Predicted point magnetic values** (`processing_service.py`): `predicted_points` only has lat/lon; add the predicted magnetic value so map click shows a reading.
3. **Predicted marker fill color** (`maps.js`): hollow blue ring is invisible on light basemaps; add semi-transparent fill.
4. **Value scale gradient** (`index.html`): green CSS vars don't match Viridis; change to `#440154 → #31688e → #35b779 → #fde725`.
5. **"Open Projects" home button** (`navigation.js`): wire to open sidebar projects dropdown.
6. **Nav guard → redirect to setup** (`navigation.js`): instead of notice, call `window.beginNewProjectFlow?.(); window.startProject?.()` to land on project creation page.
7. **Map ↔ Line Profiles switching bug** (`visualisation.js`): call `Plotly.purge(host)` before switching to Map; track and destroy Google Maps instance before switching to Plotly.
8. **Basemap toggle on visualisation** (`index.html`, `visualisation.js`): add `mapTypeSelect` dropdown to visualisation map overlay toolbar; wire to active map instance.
9. **Remove Light/Muted green/Greyscale from mapTypeSelect** (`index.html`): keep Satellite, Hybrid, Terrain, Roadmap, Dark only.
10. **Verify processing auto-start**: confirm processing only triggers on Execute click, not on screen navigation.

### Lower priority
- Export generation still runs inside the API service — `gaia-magnetics-export` Cloud Run Job not yet created (see `CONTEXT.md`)
- True Esri File GDB export not implemented
- Verify diurnal, explicit scenario, sparse spacing with real survey data
- Confirm `vet-dev-backend` SA has `roles/run.developer` for job dispatch

## If The User Asks About Credentials Or GCP Setup

- Maps key: Secret Manager secret `gaia-google-maps-api-key`, exposed via `/api/maps/key`
- Aurora: Vertex AI in project `app-01-488817-ai`
- Cloud Run service account: `vet-dev-backend@app-01-488817.iam.gserviceaccount.com`

## Deploy Commands

```
gcloud builds submit --tag us-central1-docker.pkg.dev/app-01-488817/gaia/gaia-magnetics:latest .
gcloud run deploy gaia-magnetics --image us-central1-docker.pkg.dev/app-01-488817/gaia/gaia-magnetics:latest --region us-central1 --project app-01-488817
```

## Working Style Expected

- Be direct and specific.
- Give short progress updates while working.
- Avoid asking unnecessary questions.
- If you make assumptions, state them after doing the work.
- If you deploy, report the exact revision and URL.
- No emojis or icons unless explicitly requested.
