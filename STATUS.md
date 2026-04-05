# GAIA Magnetics Status

Last updated: `2026-04-05`

## Live Snapshot

- App URL:
  `https://gaia-magnetics-348555315681.us-central1.run.app`
- Cloud Run service:
  `gaia-magnetics`
- Latest live revision:
  `gaia-magnetics-00097-thc`
- Region:
  `us-central1`
- Infra project:
  `app-01-488817`
- AI project:
  `app-01-488817-ai`
- Service account:
  `vet-dev-backend@app-01-488817.iam.gserviceaccount.com`

> Revision `gaia-magnetics-00097-thc` is serving 100% traffic.

## Revision History (Recent)

| Revision | What changed |
|---|---|
| `00090-ntd` | Structured export package rollout with dynamic bundles and spec-driven export metadata |
| `00092-nlz` | Export layout and narrative quality refactor deployed |
| `00093-cvs` | Direct Anthropic export client path deployed from local `.env` |
| `00095-pdg` | Cloud Run bound `ANTHROPIC_API_KEY` from Secret Manager secret `gaia-anthropic-api-key` |
| `00096-sfz` | Export routing locked so live DOCX/PDF/PPTX generation uses direct Anthropic whenever the key exists |
| `00097-thc` | Export pipeline hardened for truthful AI output, stronger provider failure handling, tighter scientific labels, cleaner DOCX/PDF/PPTX structure, and lower-token prompt payloads |

## Current Product State

- FastAPI backend is live with modular `routes`, `services`, `models`, `gcp`, and `jobs`.
- Frontend remains anchored on `frontend/index.html` with ES-module sections under `frontend/js/sections`.
- Core workflow is live:
  `Home -> Projects -> Setup -> Analysis -> Preview -> Processing -> Visualisation -> Export`
- Firestore stores project/task metadata and lightweight result references.
- Full processing outputs are persisted to GCS `results.json`.
- Google Maps-backed preview and visualisation views are live.
- User-visible AI branding remains `Aurora AI`.

## Most Recent Completed Work

### Scientific and UX fixes still live

- Line profiles show `point.magnetic` instead of `raw_magnetic`.
- Base station points are excluded from line profiles and map overlay.
- Survey-only traverse distance is preserved in both backend processing and frontend line-profile display, so off-line base-station revisits no longer create fake gaps.
- Point-based views (`Map`, `Line Profiles`) use displayed point values for sidebar stats/scale.
- Grid-based views (`Contour`, `Heatmap`, `3D`) use grid-surface stats.
- Home page shows a single `Projects` button.

### Aurora improvements still live

- Preview Aurora rebuilds preview-side context from uploaded survey data.
- Aurora receives explicit UI context from the frontend.
- Visualisation Aurora can answer from the active layer, view mode, traverse selection, approximate line endpoints, displayed stats, displayed-value provenance, and key processing metadata.

### Export improvements now live

- Export generation for `DOCX`, `PDF`, and `PPTX` now uses direct Anthropic whenever `ANTHROPIC_API_KEY` is present.
- Cloud Run now reads `ANTHROPIC_API_KEY` from Secret Manager secret `gaia-anthropic-api-key`.
- Export prompt/build logic reads `export_agent.md`.
- DOCX, PDF, and PPTX exports consume structured `{docx, pdf, pptx}` AI output packages.
- CSV, GeoJSON, KMZ/KML, GDB-style, and map-image bundles include `metadata.json` and only generated, selected outputs.
- Corrected, regional, and residual layers are treated as separate export products.
- Export AI generation now rejects raw JSON/CSV-like report text, placeholder strings, repeated boilerplate, unsupported sections, and misleading scientific labels before render time.
- Anthropic export failures are now classified more clearly so rate-limit, permission, model, and provider failures degrade honestly instead of silently surfacing as generic export output.
- Export prompts now use a compressed, filtered payload and a smaller relevant excerpt from `export_agent.md` to reduce token usage while preserving grounding and quality gates.

## Active Investigation (Current)

- Upload-time XLSX base-station detection is still weaker than processing-time detection because `_xlsx_to_csv_bytes` relies on bold formatting and can miss partially bold BS rows.
- The previously misleading line-profile gap was traced to base-station detours inflating `along_line_m`; that fix is live.
- Export provider/key routing is now correct in Cloud Run, and revision `00097-thc` includes stronger output validation and fallback honesty.
- Cloud Run logs previously showed `anthropic.RateLimitError` with HTTP `429 RESOURCE_EXHAUSTED` during export attempts. That risk still exists at the provider layer even though the local export path is now more resilient and truthful.
- Fresh post-hardening live export verification is still pending.

## Verification Status

- Python syntax checks passed for updated export-config/container/client files.
- Export/AI unit tests passed after the export hardening and token optimization pass.
- Revisions `00092-nlz`, `00093-cvs`, `00095-pdg`, `00096-sfz`, and `00097-thc` all deployed successfully to Cloud Run.
- `/api/health` returned healthy after deploying `00097-thc`.
- Cloud Run service now references secret-backed env:
  `ANTHROPIC_API_KEY -> gaia-anthropic-api-key:latest`

## Important Open Items

1. **Fix `_xlsx_to_csv_bytes`** - bold-only detection misses partially-bold BS rows. It should also check for `BS`/`base` text in row content.
2. **Fresh live export QA** - generate a new `DOCX/PDF/PPTX` set after revision `00097-thc` and inspect the real artifacts.
3. **Anthropic 429 mitigation** - continue improving export resilience because provider-side `RESOURCE_EXHAUSTED` can still occur even though fallback handling and validation are now stronger.
4. **Browser-QA Aurora** - verify Preview and Visualisation chat answers against the exact screen state.
5. **Re-process the test dataset** - rerun on current live revision so saved results pick up the corrected along-line distance handling.
6. Native FileGDB output is still not implemented; the current `gdb_bundle` is a geospatial delivery bundle with feature-class-style GeoJSON members.

## Main Files Most Relevant Right Now

### Backend

- `backend/config.py`
- `backend/gcp/vertex_ai.py`
- `backend/services/container.py`
- `backend/services/ai_service.py`
- `backend/services/export_service.py`
- `backend/services/processing_service.py`
- `backend/services/task_service.py`

### Frontend

- `frontend/index.html`
- `frontend/js/shared/ai_chat.js`
- `frontend/js/sections/preview.js`
- `frontend/js/sections/visualisation.js`
- `frontend/js/sections/export.js`
