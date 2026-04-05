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
  `gaia-magnetics-00097-thc`
- Service account:
  `vet-dev-backend@app-01-488817.iam.gserviceaccount.com`

## Deploy Command

```powershell
powershell -Command "& 'C:\Users\Tolu\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd' run deploy gaia-magnetics --source 'c:\Users\Tolu\Documents\Terra Analytics\Magnetics Main\2\magnetics (main)\gaia-magnetics' --region us-central1 --project app-01-488817 --quiet"
```

> On Windows, `gcloud` resolves to a Python Store alias and fails. Use the explicit `gcloud.cmd` path via `powershell -Command`.

## What Changed Most Recently

### This session (2026-04-05)

**Live deploys completed:**
- `gaia-magnetics-00092-nlz` - export layout and narrative quality refactor deployed.
- `gaia-magnetics-00093-cvs` - direct Anthropic export client path deployed from local `.env`.
- `gaia-magnetics-00095-pdg` - Cloud Run now reads `ANTHROPIC_API_KEY` from Secret Manager secret `gaia-anthropic-api-key`.
- `gaia-magnetics-00096-sfz` - export routing locked so live DOCX/PDF/PPTX generation uses the Anthropic key whenever it exists, regardless of older provider env labels.
- `gaia-magnetics-00097-thc` - export pipeline hardened for truthful report generation, stricter scientific labeling, clearer Anthropic failure handling, and lower-token prompt payloads.

**Export state now live:**
- Export generation for `DOCX`, `PDF`, and `PPTX` now uses direct Anthropic whenever `ANTHROPIC_API_KEY` is present.
- Cloud Run has `ANTHROPIC_API_KEY` attached from Secret Manager.
- The export system reads `export_agent.md`, builds structured `{docx,pdf,pptx}` packages, and renders them through the backend builders.
- The export path now rejects raw JSON/CSV-like narrative output, placeholder strings, repeated paragraphs, unsupported sections, and misleading labels before rendering.
- Anthropic export failures are now classified more clearly, and fallback output is held to stricter truthfulness and formatting rules.
- Export prompts now send a smaller filtered payload plus a smaller relevant slice of `export_agent.md` to reduce token use.
- Live export failures seen on 2026-04-04 were not provider-routing mistakes; Cloud Run logs showed `anthropic.RateLimitError` with `429 RESOURCE_EXHAUSTED`, after which the system fell back to `_build_fallback_export_package(...)`. That provider-side risk still exists.

**Previously deployed scientific and UX fixes still live:**
- Interval-based diurnal correction remains the preferred path.
- Corrected, regional, and residual outputs remain first-class products.
- Line profiles and point-based scales use the displayed survey values instead of unrelated grid-wide stats.
- Preview and Visualisation Aurora context upgrades remain live.
- Home page still shows a single `Projects` button.

## Most Important Files Right Now

- `backend/services/processing_service.py` - `_clean_dataframe`, `_infer_base_station_mask`, `_apply_diurnal_correction`
- `backend/services/ai_service.py` - preview rebuild path, export prompt assembly, fallback export package
- `backend/services/export_service.py` - DOCX/PDF/PPTX builders and export quality gate
- `backend/services/container.py` - live export-client selection
- `backend/gcp/vertex_ai.py` - `AnthropicClaudeClient` and Vertex clients
- `backend/config.py` - `.env` loading, export settings, Anthropic key detection
- `backend/models/ai.py` - Aurora request schema
- `frontend/js/shared/ai_chat.js` - shared chat payload assembly
- `frontend/js/sections/visualisation.js` - line profiles, map overlay, stats source, Aurora context builder
- `frontend/js/sections/preview.js` - preview chat context builder
- `frontend/js/sections/export.js` - export request payload assembly
- `frontend/index.html` - shared UI shell and home-page hero

## Remaining Gaps

1. **`_xlsx_to_csv_bytes` text fallback** - bold-only detection still misses partially-bold BS rows. Add text-based row detection at upload time.
2. **Fresh live export QA after hardening deploy** - generate a new `DOCX/PDF/PPTX` set after revision `00097-thc` and verify the output quality on the live service.
3. **Anthropic 429 handling** - keep improving export resilience because Cloud Run logs already showed `anthropic.RateLimitError` `429 RESOURCE_EXHAUSTED` during previous live exports.
4. **Browser QA on current revision** - confirm Aurora answers correctly from both Preview and Visualisation with a real processed task.
5. **Re-process the known dataset** and verify saved outputs reflect the corrected along-line distance path.
6. Update docs again after the next live export verification run if the export behavior changes.

## Working Style

- Keep updates short and concrete.
- Prefer fixing and verifying over only describing.
- If you deploy, report the exact revision and URL.
- If you make assumptions, state them after the work.
- Keep user-visible AI wording as `Aurora AI` unless the user asks to change it.
- Always run relevant syntax checks before deploying.
- Update `STATUS.md`, `CONTEXT.md`, and `HANDOFF.md` after significant changes or deploys.
