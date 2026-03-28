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
  `gaia-magnetics-00056-xbp` (AI/chat changes not yet deployed)
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
  The `VertexAIClient` in `backend/gcp/vertex_ai.py` uses `ai_project_id` (not `infra_project_id`).
- Theme toggle should remain symbol-based, not text-based.
- No "Aurora" branding anywhere in user-visible surfaces. Use "GAIA AI".

## Current Functional Shape

### Navigation and project flow

- Top nav shows `Projects`.
- Home-page project actions route into the projects hub.
- Setup routing uses direct `setup` screen navigation.
- Directory/project actions include:
  `Open project`, `Edit project`, `+ New task`

### Setup

- Two-step flow: `Project details -> Task setup`
- Survey upload supports CSV/XLSX.
- Coordinate system supports WGS84 and UTM.
- Coordinate outliers detected before upload; user can discard or keep.
- Base stations auto-detected from repeated coordinates; xlsx bold-row support.
- Existing tasks can be loaded back into setup for editing.
- Reference file upload (PDF, DOCX, TXT, KML, KMZ, GeoJSON, ZIP) stored in GCS
  as `task.basemap_file`. Text is extracted and injected into every AI prompt.
- Backend supports full task updates through:
  `PUT /api/projects/{project_id}/tasks/{task_id}`

### Analysis

- Analysis persists normalised backend IDs.
- Processing add-ons:
  `rtp`, `analytic_signal`, `first_vertical_derivative`, `horizontal_derivative`,
  `emag2`, `uncertainty`

### Preview

- Preview renders Google Maps-backed station maps.
- No connecting station lines.
- Stores and reuses chosen measured/predicted marker colours.
- Basemaps: `Terrain`, `Satellite`, `Map`
- **AI chat panel** on the right side auto-loads on every `loadPreview()` call.
  Users can ask follow-up questions.

### Visualisation

- Layer-driven: TMF, Filtered surface, RTP, Analytic signal, FVD, Horizontal derivative,
  EMAG2 residual, Uncertainty.
- Selected layer drives stats, scale bar, hover values, heatmap/contour/3D, line profiles.
- Line profiles support stacking.
- **AI chat input** at the bottom of the right stats panel.
  `renderInterpretation` auto-fires a layer-specific AI question on every layer change.
  Chat body (`visAIBody`) persists; only the layer metadata card refreshes.

### Export

- **AI chat panel** on the right side.
  Auto-loads on `loadExportView()` with export guidance.
  Users can ask follow-up questions about formats and deliverables.
- AI-generated content (Claude Sonnet 4.6) embedded in PDF, DOCX, PPTX.
- PDF uses `SimpleDocTemplate` with stats table and AI sections.
- DOCX has config summary, stats table, and full AI analysis.
- PPTX is a 6-slide deck: Title, Survey Summary, Key Findings, Config, Stats, Limitations.
- Data exports (CSV, GeoJSON, KML/KMZ, GDB, PNG/JPG) are pure data transforms,
  no AI involved.

### AI service

- Model: `claude-sonnet-4-6` (default set in `config.py`; overridable via `GAIA_AURORA_MODEL`
  or `CLAUDE_MODEL` env vars).
- Client: `VertexAIClient` in `backend/gcp/vertex_ai.py` via `AnthropicVertex`.
- Every AI call receives:
  project name + context, task name + description, processing config, magnetic stats,
  30-point station sample, and reference file text (if uploaded).
- Export call uses 3000 tokens and a structured prompt requesting labelled sections.
- `_parse_response` in `ai_service.py` extracts sections into `summary` + `highlights`.
- Falls back to a deterministic text response if the Vertex AI call fails.

### Shared AI chat module

- `frontend/js/shared/ai_chat.js`
- `initAIChat(bodyEl, inputEl, sendEl, {location})` → returns `{autoLoad, clear}`.
- `autoLoad(question?)` clears the body and fires an initial AI call.
- Enter to send, Shift+Enter for newline.
- Disabled during pending calls.

### Processing backend

- Full results in GCS `results.json`; lightweight metadata in Firestore.
- Derived layers: `first_vertical_derivative`, `horizontal_derivative`
- Prediction scenarios:
  `explicit` — rows with values train, rows without are predicted.
  `sparse` — all measured rows train; user-defined predicted traverses or grid nodes.

## Important Files

### Backend

- `backend/config.py` — model default and all env var settings
- `backend/gcp/vertex_ai.py` — `VertexAIClient` (Claude via AnthropicVertex)
- `backend/services/ai_service.py` — prompt construction, reference file extraction, response parsing
- `backend/services/export_service.py` — PDF/DOCX/PPTX builders, export AI call
- `backend/services/container.py` — dependency wiring
- `backend/services/processing_service.py`
- `backend/services/task_service.py`
- `backend/routes/tasks.py`
- `backend/routes/ai.py`
- `backend/routes/exports.py`

### Frontend

- `frontend/index.html`
- `frontend/js/shared/ai_chat.js` — shared chat component
- `frontend/js/sections/preview.js`
- `frontend/js/sections/visualisation.js`
- `frontend/js/sections/export.js`
- `frontend/js/state.js`
- `frontend/js/api.js`

## Known Follow-Up Areas

1. Deploy to Cloud Run to make AI/chat changes live.
2. Verify `vet-dev-backend@app-01-488817.iam.gserviceaccount.com` has
   `roles/aiplatform.user` on `app-01-488817-ai`.
3. Full browser click-through on latest UI flows after deploy.
4. Investigate why live processing times out during smoke polling.
5. Persist explicit predicted values per predicted station (currently sampled from surface grid).
6. Implement export Cloud Run Job to move exports out of the request path.
7. Additional visualisations: anomaly masks, histograms, uncertainty overlays,
   directional derivatives, crossover/profile QC.

## Deployment Note

```powershell
gcloud run deploy gaia-magnetics --source gaia-magnetics --region=us-central1 --project=app-01-488817 --quiet
```
