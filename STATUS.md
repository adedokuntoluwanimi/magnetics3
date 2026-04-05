# GAIA Magnetics Status

Last updated: `2026-04-05`

## Live Snapshot

- App URL:
  `https://gaia-magnetics-348555315681.us-central1.run.app`
- Cloud Run service:
  `gaia-magnetics`
- Latest live revision:
  `gaia-magnetics-00106-jmm`
- Region:
  `us-central1`
- Infra project:
  `app-01-488817`
- AI project:
  `app-01-488817-ai`
- Service account:
  `vet-dev-backend@app-01-488817.iam.gserviceaccount.com`

> Revision `gaia-magnetics-00106-jmm` is serving 100% traffic.

## Revision History (Recent)

| Revision | What changed |
|---|---|
| `00096-sfz` | Export routing locked so live DOCX/PDF/PPTX generation uses direct Anthropic whenever the key exists |
| `00097-thc` | Export pipeline hardened for truthful AI output, stronger provider failure handling, tighter scientific labels, cleaner DOCX/PDF/PPTX structure, and lower-token prompt payloads |
| `00098-bt7` | Structured export-path observability added for provider failures and fallback outcomes |
| `00099-r6r` | Anthropic export model corrected to `claude-sonnet-4-6` with startup preflight logging |
| `00100-z9k` | Export JSON parser hardened for fenced JSON and safe object extraction |
| `00101-lz8` | Wrapper-aware parsing improvements deployed, but live parse failures remained |
| `00102-nx9` | Parse-forensics logging deployed for exact JSON decode diagnostics |
| `00103-zvw` | Export page reworked so users choose from actual processed outputs before report generation |
| `00104-8bb` | Truncation-aware retry and smaller split report/pptx package generation deployed |
| `00105-qbj` | First block-based export generation rollout deployed |
| `00106-jmm` | Smaller block prompts, wrapper unwrapping, and tighter block validation updates deployed |

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
- Point-based views (`Map`, `Line Profiles`) use displayed point values for sidebar stats and scale.
- Grid-based views (`Contour`, `Heatmap`, `3D`) use grid-surface stats.
- Home page shows a single `Projects` button.

### Aurora improvements still live

- Preview Aurora rebuilds preview-side context from uploaded survey data.
- Aurora receives explicit UI context from the frontend.
- Visualisation Aurora can answer from the active layer, view mode, traverse selection, approximate line endpoints, displayed stats, displayed-value provenance, and key processing metadata.

### Export improvements now live

- Export generation for `DOCX`, `PDF`, and `PPTX` uses direct Anthropic whenever `ANTHROPIC_API_KEY` is present.
- Cloud Run reads `ANTHROPIC_API_KEY` from Secret Manager secret `gaia-anthropic-api-key`.
- The configured live export model is now `claude-sonnet-4-6`.
- Startup/preflight export logging now reports whether the configured Anthropic model is available.
- Export prompt/build logic reads `export_agent.md`.
- Export-path observability now logs structured provider failures, parse failures, retry modes, validation rejection causes, and final outcomes.
- The export page now surfaces actual generated output layers and lets users choose which processed outputs may appear in report exports before `DOCX`, `PDF`, or `PPTX` generation runs.
- Export generation has been refactored away from one large package attempt into small report and PPTX block calls that are merged server-side.
- Per-block fallback is now possible, so a failed block does not automatically collapse the entire package generation path.
- CSV, GeoJSON, KMZ/KML, GDB-style, and map-image bundles include `metadata.json` and only generated, selected outputs.

## Active Investigation (Current)

- Upload-time XLSX base-station detection is still weaker than processing-time detection because `_xlsx_to_csv_bytes` relies on bold formatting and can miss partially bold BS rows.
- The live export failure is now clearly diagnosed as an export architecture/validation problem, not a provider-routing problem.
- The latest checked live export on `00106-jmm` still ended with:
  `export.path.outcome = anthropic_response_invalid_fallback_used`
- Block-level live failures on 2026-04-05 showed:
  - `project_setup` still truncating with `failure_class = truncated_json`
  - `pptx_group_1` still truncating with `failure_class = truncated_json`
  - `pptx_group_2` failing block validation with `missing_expected_section`
  - final package validation failing with `pptx:Data and Survey Summary:slide_density`
- Some blocks now succeed live:
  - `executive_summary`
  - `pptx_group_3`
  - `pptx_group_4`
- Files still generate, but they are still fallback-backed and should not be treated as trustworthy high-quality exports until the live outcome becomes:
  `anthropic_success`

## Verification Status

- Python syntax checks passed for the export-model, parser, block-generation, and export-selection updates.
- Focused export/AI unit tests passed after the block-generation rollout.
- Revisions `00098-bt7` through `00106-jmm` all deployed successfully to Cloud Run.
- `/api/health` returned healthy after the recent deploys.
- Cloud Run service now references secret-backed env:
  `ANTHROPIC_API_KEY -> gaia-anthropic-api-key:latest`
- Live Cloud Run logs now expose the exact current export blockers instead of generic fallback messages.

## Important Open Items

1. **Fix `_xlsx_to_csv_bytes`** - bold-only detection misses partially-bold BS rows. It should also check for `BS`/`base` text in row content.
2. **Finish the block export architecture** - split the still-failing `project_setup` and `pptx_group_1` blocks into even smaller generation units.
3. **Resolve PPTX validation friction** - current live package validation still rejects `Data and Survey Summary` with `slide_density`, and `pptx_group_2` can fail `missing_expected_section`.
4. **Reach a real live Anthropic success** - do not treat file generation as success. The export path is only considered fixed when Cloud Logging shows:
   `export.path.outcome = anthropic_success`
5. **Fresh live artifact QA after success** - once `anthropic_success` is reached, inspect a real `DOCX/PDF/PPTX` set from the frontend.
6. **Browser-QA Aurora** - verify Preview and Visualisation chat answers against the exact screen state.
7. **Re-process the test dataset** - rerun on the current live revision after the export work stabilizes so saved outputs and exports reflect the latest code.
8. Native FileGDB output is still not implemented; the current `gdb_bundle` is a geospatial delivery bundle with feature-class-style GeoJSON members.

## Main Files Most Relevant Right Now

### Backend

- `backend/config.py`
- `backend/gcp/vertex_ai.py`
- `backend/services/container.py`
- `backend/services/ai_service.py`
- `backend/services/export_service.py`
- `backend/services/processing_service.py`
- `backend/services/task_service.py`
- `backend/models/ai.py`

### Frontend

- `frontend/index.html`
- `frontend/js/shared/ai_chat.js`
- `frontend/js/sections/preview.js`
- `frontend/js/sections/visualisation.js`
- `frontend/js/sections/export.js`
