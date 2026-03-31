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
  `gaia-magnetics-00065-zkf`
- Service account:
  `vet-dev-backend@app-01-488817.iam.gserviceaccount.com`

> Revision `gaia-magnetics-00065-zkf` is live and `/api/health` returned `{"status":"ok"}` after deploy.

## What Changed Most Recently

### Product and UI updates

- User-visible assistant branding is `Aurora AI`.
- Setup now treats scenario selection as optional.
- Predicted traverse mode is simplified to a single active choice:
  `infill` or `offset`.
- Sidebar project arrow was enlarged.
- Preview and downstream state now preserve predicted traverse metadata more accurately.
- Visualisation now supports viewing all traverses together or focusing on a selected traverse.
- Combined heatmap/contour presentation remains the main surface view.

### Processing and wording updates

- Predicted stations now carry values intended for overlay/readout use.
- Some fallback and processing descriptions were simplified to remove unnecessary jargon.
- Frontend result loading was tightened to reduce repeated fetches and improve perceived load time.

### Mojibake cleanup

- `frontend/index.html` received a full mojibake cleanup sweep.
- Corrupted arrows, placeholders, checkmarks, separators, map attribution text, upload controls, and default placeholders were fixed across all frontend pages.
- Frontend scan for common mojibake sequences is clean.

## Most Important Files To Check First

- `frontend/index.html`
- `frontend/js/state.js`
- `frontend/js/sections/setup.js`
- `frontend/js/sections/preview.js`
- `frontend/js/sections/processing.js`
- `frontend/js/sections/visualisation.js`
- `frontend/js/sections/maps.js`
- `frontend/js/sections/export.js`
- `frontend/js/sections/analysis.js`
- `backend/services/preview_service.py`
- `backend/services/processing_service.py`
- `backend/services/ai_service.py`
- `backend/routes/tasks.py`

## Remaining Gaps

1. Manual browser click-through on the latest live build.
2. End-to-end confirmation on a real dataset that predicted overlay values render exactly as expected.
3. Per-traverse grid rendering is still a potential follow-up if current filtering is not enough.
4. Exports still execute in the API path rather than a dedicated job flow.
5. Watch live processing and export latency after the recent UI and metadata changes.

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
