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
- Latest live revision:
  `gaia-magnetics-00078-hr7`
- Service account:
  `vet-dev-backend@app-01-488817.iam.gserviceaccount.com`

> Revision `gaia-magnetics-00078-hr7` is live and `/api/health` returned `{"status":"ok"}` after deploy.

## What Changed Most Recently

### Diurnal correction and correction reporting

- Diurnal correction now prefers true interval-based consecutive base-station interpolation using the first valid base reading as the reference.
- Leading and trailing samples outside the base-station range now use explicit constant-hold handling instead of being folded silently into the same interval logic.
- Single-base and FFT fallback modes are still supported, but they are now labelled explicitly in correction metadata and QA outputs.
- Diurnal metadata now records the method used, interval coverage, base-reading counts, max absolute correction, and interpolated-base statistics.

### Regional and residual separation

- Regional and residual are now first-class processing products rather than a narrow add-on alias.
- The backend now supports configurable regional methods:
  `polynomial`, `trend`, `lowpass`, and `igrf_context`.
- Corrected, regional, and residual surfaces are now persisted separately, with residual defined explicitly as `Corrected - Regional`.
- Separate regional/residual stats, report metadata, and export-ready image assets are now stored alongside the main corrected field outputs.

### Visualisation, export, and AI behavior

- Visualisation now labels the main layer as `Corrected Magnetic Field` and separates `Regional Magnetic Field` and `Residual Magnetic Field` into their own result groups.
- Layer descriptions, method-aware metadata, captions, and empty-state behaviour now explain what each product means scientifically.
- Export now previews which products are available for a run and treats corrected/regional/residual maps as separate interpretive products when present.
- Aurora/export reporting now receives distinct corrected/regional/residual context instead of one blended regional-residual story.

## Most Important Files To Check First

- `backend/services/processing_service.py`
- `backend/services/preview_service.py`
- `backend/services/ai_service.py`
- `backend/services/export_service.py`
- `backend/services/task_service.py`
- `frontend/index.html`
- `frontend/js/sections/setup.js`
- `frontend/js/sections/processing.js`
- `frontend/js/sections/visualisation.js`
- `frontend/js/sections/export.js`
- `frontend/js/sections/sidebar.js`
- `tests/test_processing_service.py`
- `tests/test_ai_service.py`
- `tests/test_export_service.py`

## Remaining Gaps

1. Claude-backed export drafting still needs another quality pass so PDF/DOCX/PPTX narratives stop falling back and become more project-specific.
2. Manual browser QA is still needed on revision `gaia-magnetics-00078-hr7`, especially for the new regional-method controls and export-content preview.
3. A fresh live rerun should be used to confirm interval-based diurnal reporting and corrected/regional/residual visual grouping on real datasets.
4. Keep watching latency on longer processing and export jobs.

## Deploy Command

```powershell
gcloud run deploy gaia-magnetics --source . --region=us-central1 --project=app-01-488817 --quiet
```

## Working Style

- Keep updates short and concrete.
- Prefer fixing and verifying over only describing.
- If you deploy, report the exact revision and URL.
- If you make assumptions, state them after the work.
- Keep user-visible AI wording as `Aurora AI` unless the user asks to change it.
