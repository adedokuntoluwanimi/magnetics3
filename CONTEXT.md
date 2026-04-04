# GAIA Magnetics Context

Last updated: `2026-04-04`

## Purpose

This file captures the current working context for `gaia-magnetics`.
`Instructions.txt` in the parent workspace remains the higher-level project instruction set.

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

## Standing Constraints

- Preserve the existing folder structure.
- Use `frontend/index.html` as the shared UI shell.
- Keep integrations real:
  Firestore, Cloud Storage, Cloud Run, Google Maps, Vertex AI.
- Do not reintroduce dummy data or misleading labels.
- User-visible assistant branding should remain `Aurora AI`.
- The frontend still mixes static shell markup and modular JS; meaningful changes often need both.

## Current Functional Shape

### Navigation and project flow

- Top navigation is project-centric.
- Core route sequence is:
  `Home -> Projects -> Setup -> Analysis -> Preview -> Processing -> Visualisation -> Export`
- Sidebar project controls and project/task launch actions are active.
- Selected project and task IDs persist across refreshes.
- Project deletion now returns the user to the projects/workspace view instead of Home.

### Setup and analysis

- Two-step setup flow:
  `Project details -> Task setup`
- Scenario selection is optional and includes an explicit `Off` option.
- Setup restores from the saved task/project state after refresh.
- Saved uploads are shown when reopening an existing task.
- Survey upload supports CSV/XLSX with coordinate mapping, raw-data mapping, and base-station handling.
- Analysis now surfaces interval-based diurnal behaviour, fallback expectations, and dedicated regional/residual method controls.

### Preview

- Preview renders Google Maps-backed station maps.
- Summary cards show survey traverses and predicted traverses separately.
- Uploaded CSVs are treated as one traverse per file.
- Preview now carries enough metadata to expose detected base-station revisits and preserve file-level traverse identity.
- Aurora chat is enabled on Preview.

### Processing

- Processing pipeline persists richer metadata and keeps the full heavy result payload in GCS.
- Firestore task documents keep only Firestore-safe result metadata and artifact references.
- Diurnal correction now prefers interval-based consecutive base-station interpolation and records explicit fallback metadata when that path cannot run.
- Corrected, regional, and residual outputs are now persisted separately.
- Regional methods now support:
  `polynomial`, `trend`, `lowpass`, and `igrf_context`.
- QA and correction reporting now expose diurnal method, interval coverage, regional method, quality state, and related badges/metadata.

### Visualisation

- Visualisation now groups outputs into:
  `Main processed field`, `Regional field`, `Residual field`, and `Derived products`.
- The main layer is labelled `Corrected Magnetic Field`.
- Regional and residual layers are labelled explicitly as `Regional Magnetic Field` and `Residual Magnetic Field`.
- Layer descriptions, captions, and interpretation panels now explain the difference between corrected/regional/residual products.
- Visualisation line profiles still use preserved raw magnetic values for the magnetic layer.
- Aurora chat is enabled on Visualisation and is shown in its own dedicated panel.

### Export

- Export jobs complete and bundle outputs are being generated.
- Export filenames still use `task_project` naming.
- Export UI now previews which products are available for the current run.
- Corrected/regional/residual report content can now be selected independently in the export UI.
- Export bundles and report-generation context now distinguish corrected, regional, and residual maps as separate interpretive products.
- Claude-backed narrative generation still needs another quality pass to become consistently specific and reliable.

## Important Files

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
- `frontend/js/sections/preview.js`
- `frontend/js/sections/visualisation.js`
- `frontend/js/sections/export.js`

## Known Follow-Up Areas

1. Improve Claude-backed export drafting quality and reliability.
2. Manual browser QA on revision `gaia-magnetics-00078-hr7`.
3. Verify the interval-based diurnal reporting and corrected/regional/residual outputs against more real datasets.
4. Keep an eye on live processing latency and export response time.

## Deployment Note

```powershell
gcloud run deploy gaia-magnetics --source . --region=us-central1 --project=app-01-488817 --quiet
```
