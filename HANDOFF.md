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

> The most recent code changes (AI wiring, chat panels, export improvements) are **not yet deployed**.
> The live revision is still `00056-xbp`. Deploy before verifying any AI features on live.

## What Changed Most Recently

### AI assistant fully wired to Claude Sonnet 4.6

- `backend/config.py`: model default now `claude-sonnet-4-6`.
- `backend/gcp/vertex_ai.py`: `VertexAIClient` (was `VertexAuroraClient`);
  `max_tokens` param added; alias kept.
- `backend/services/container.py`: wired `VertexAIClient` and `storage_backend` into `AIService`.
- `backend/services/ai_service.py`:
  - System prompt removes "Aurora" branding.
  - Prompt now passes a focused context block (project, task, config, stats, station sample).
  - Reference file (`task.basemap_file`) downloaded from GCS and text-extracted per format
    (PDF via pdfminer, DOCX via python-docx, TXT, KML, KMZ, GeoJSON/JSON); capped at 6000 chars.
  - Export path: 3000 tokens, structured prompt with labelled sections.
  - `_parse_response` correctly maps `EXECUTIVE SUMMARY` → `summary`,
    `KEY FINDINGS` / `MODELLING NOTES` / `RECOMMENDATIONS` → `highlights`.
- `backend/services/export_service.py`:
  - Export AI call now passes full GCS results (stats + 50-point sample) as `extra_results`.
  - PDF rebuilt with `SimpleDocTemplate` (proper styles, stats table).
  - DOCX rebuilt with config table, stats table, full AI analysis.
  - PPTX rebuilt as 6-slide deck using AI-generated content.

### Interactive AI chatbox on all three screens

- New: `frontend/js/shared/ai_chat.js` — shared chat module.
  `initAIChat(bodyEl, inputEl, sendEl, {location})` → `{autoLoad, clear}`.
- **Preview**: new `a-panel` added to the right of the map in `screen-preview`.
  Wired in `preview.js`; auto-loads on every `loadPreview()`.
- **Visualisation**: chat input row added below the right stats panel in `screen-visualisation`.
  `renderInterpretation` fires a layer-specific auto-load on every layer change.
  Chat body (`visAIBody`) persists; layer card (`visLayerCard`) refreshes separately.
  Chat initialised via `MutationObserver` in `initVisualisation` since `visAIBody`
  is created lazily by the first `renderInterpretation` call.
- **Export**: existing `a-panel` upgraded from static one-shot content to live chat.
  Input row added. `_ensureExportChat()` called from `initExport` and `loadExportView`.

### Aurora text removed

- All user-visible "Aurora" text replaced with "GAIA AI" or neutral "AI".
- Affected: export format card descriptions, section headings, panel headers,
  processing step detail, home page capability card.
- Internal Python class/variable names (`AuroraResponse`, `aurora_sections` API field)
  left unchanged to avoid breaking the API contract.

## Most Important Files To Check First

- `backend/config.py`
- `backend/gcp/vertex_ai.py`
- `backend/services/ai_service.py`
- `backend/services/export_service.py`
- `backend/services/container.py`
- `frontend/js/shared/ai_chat.js`
- `frontend/js/sections/preview.js`
- `frontend/js/sections/visualisation.js`
- `frontend/js/sections/export.js`
- `frontend/index.html`

## Remaining Gaps

1. **Deploy required** — run deploy command below, then verify `/api/health` and homepage.
2. **SA permissions** — verify `vet-dev-backend@app-01-488817.iam.gserviceaccount.com`
   has `roles/aiplatform.user` on project `app-01-488817-ai`. Without this the AI calls
   will fail silently (falling back to deterministic text).
3. Long-running processing still times out on live smoke; needs investigation.
4. `predicted_points` still use sampled surface values for hover/readout.
5. Export Cloud Run Job not yet implemented.
6. Full browser click-through after deploy.

## Deploy Command

```powershell
gcloud run deploy gaia-magnetics --source gaia-magnetics --region=us-central1 --project=app-01-488817 --quiet
```

## Working Style

- Keep updates short and direct.
- Prefer fixing and verifying over only describing.
- If you deploy, report the exact revision and URL.
- If you make assumptions, state them after the work.
- No "Aurora" branding in user-visible text. Internal Python names are fine to keep.
