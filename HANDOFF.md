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
  `gaia-magnetics-00073-87x`
- Service account:
  `vet-dev-backend@app-01-488817.iam.gserviceaccount.com`

> Revision `gaia-magnetics-00073-87x` is live, `/api/health` returned `{"status":"ok"}`, and a full live smoke test completed after deploy.

## What Changed Most Recently

### Processing and persistence fixes

- Fixed the Firestore task-result persistence failure that was causing completed processing runs to end as failed.
- `support_mask` now stays in `results.json` only and is excluded from the Firestore task payload.
- Added Firestore update sanitization for task, run, project, and export-job updates.
- Added regression coverage for the `support_mask` persistence case.

### Aurora routing and live AI behavior

- Aurora chat is now split by function:
  `Gemini on Vertex AI` for Preview and Visualisation chat,
  `Claude` remains intended for export drafting.
- The live Cloud Run service account now has `Vertex AI User` access on the infra project.
- Live smoke test confirmed Preview and Visualisation Aurora now return real model responses instead of the old fallback text.
- Export screen chat remains intentionally disabled.

### Current export AI state

- Export jobs themselves complete successfully.
- Bundled export outputs are still being generated correctly.
- The remaining AI gap is export drafting:
  Aurora export-authoring can still fall back to saved-data-only content instead of a live Claude-authored draft.

## Most Important Files To Check First

- `backend/config.py`
- `backend/gcp/firestore_store.py`
- `backend/gcp/vertex_ai.py`
- `backend/services/ai_service.py`
- `backend/services/container.py`
- `backend/services/export_service.py`
- `backend/services/processing_service.py`
- `backend/routes/ai.py`
- `backend/routes/tasks.py`
- `frontend/index.html`
- `frontend/js/state.js`
- `frontend/js/shared/ai_chat.js`
- `frontend/js/sections/setup.js`
- `frontend/js/sections/navigation.js`
- `frontend/js/sections/preview.js`
- `frontend/js/sections/processing.js`
- `frontend/js/sections/visualisation.js`
- `frontend/js/sections/export.js`

## Remaining Gaps

1. Fix Claude-backed export drafting so PDF/DOCX/PPTX AI narratives stop falling back.
2. Manual browser click-through on the latest live build.
3. End-to-end confirmation on a larger real dataset that uploaded-data analysis and visualisations still behave well.
4. Watch live processing and export latency now that chat and export use different AI paths.
5. Re-run older tasks if they still show pre-fix line splitting or stale task-result payloads.

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
