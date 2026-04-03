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
  `gaia-magnetics-00077-hxg`
- Service account:
  `vet-dev-backend@app-01-488817.iam.gserviceaccount.com`

> Revision `gaia-magnetics-00077-hxg` is live and `/api/health` returned `{"status":"ok"}` after deploy.

## What Changed Most Recently

### Diurnal correction

- Reworked diurnal correction to use consecutive base-station pairs as separate time windows.
- Drift is now treated as signed and time-varying inside each interval instead of one global base mean adjustment.
- Survey points outside valid base-station windows remain explicitly flagged instead of being silently forced through the same correction path.
- Diurnal metadata now stores interval details and per-point offset support more cleanly.

### Regional and residual separation

- Single-traverse workflows now generate spreadsheet-style `regional_field` and `regional_residual` from the corrected profile using a linear fit against traverse distance.
- Multi-point grid workflows still keep the broader smoothed surface fallback where a line-fit method is not appropriate.
- Regional and residual remain separate user-visible outputs rather than one blended product.

### Visualisation and AI behavior

- Visualisation line profiles now use preserved raw magnetic values for the magnetic layer instead of collapsing everything to anomaly-scale processed values.
- Manual horizontal and vertical axis controls were added to line profiles.
- Aurora AI now resolves base-station count from actual processed points where available and its prompt/context was cleaned to avoid leaking internal field names like `is_base_station`.
- Uploaded CSVs now remain one traverse per file through preview/processing logic.

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
2. Manual browser QA is still needed on the latest live build, especially for spreadsheet-style diurnal/regional/residual comparison.
3. A fresh live `Book1`/`Site C` processing rerun should be used to confirm the visual outputs now match the intended field workflow closely enough.
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
