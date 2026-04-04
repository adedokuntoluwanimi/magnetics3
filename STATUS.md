# GAIA Magnetics Status

Last updated: `2026-04-04`

## Live Snapshot

- App URL:
  `https://gaia-magnetics-348555315681.us-central1.run.app`
- Cloud Run service:
  `gaia-magnetics`
- Latest live revision:
  `gaia-magnetics-00088-w6w`
- Region:
  `us-central1`
- Infra project:
  `app-01-488817`
- AI project:
  `app-01-488817-ai`
- Service account:
  `vet-dev-backend@app-01-488817.iam.gserviceaccount.com`

> Revision `gaia-magnetics-00088-w6w` is serving 100% traffic.

## Revision History (This Session)

| Revision | What changed |
|---|---|
| `00082-mgx` | Diurnal: reference value moved to `nanmedian`; `_use_fft_fallback` added for single-base case |
| `00083-lg2` | Diurnal: single-base case now falls through to FFT estimation |
| `00084-l4k` | Base-station coordinate detection tolerance tightened in `_infer_base_station_mask` |
| `00087-sgq` | Preview Aurora base-station count fix, point-view scale/stat alignment, single `Projects` button on home |
| `00088-w6w` | Aurora UI-context upgrade: active layer, view type, traverse endpoints, displayed-value source, and run metadata now passed from UI to chat |

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

### Scientific and UX fixes now live

- Line profiles show `point.magnetic` instead of `raw_magnetic`.
- Base station points are excluded from line profiles and map overlay.
- Survey-only traverse distance is now preserved in both backend processing and frontend line-profile display, so off-line base-station revisits no longer create fake gaps.
- Point-based views (`Map`, `Line Profiles`) use displayed point values for sidebar stats/scale.
- Grid-based views (`Contour`, `Heatmap`, `3D`) use grid-surface stats.
- Home page now shows a single `Projects` button.

### Aurora improvements now live

- Preview Aurora rebuilds preview-side context from uploaded survey data.
- Aurora now receives explicit UI context from the frontend.
- Visualisation Aurora can answer from the active layer, view mode, traverse selection, approximate line endpoints, displayed stats, displayed-value provenance, and key processing metadata.

## Active Investigation (Current)

- Upload-time XLSX base-station detection is still weaker than processing-time detection because `_xlsx_to_csv_bytes` relies on bold formatting and can miss partially bold BS rows.
- The previously misleading line-profile gap was traced to base-station detours inflating `along_line_m`; that fix is now live.
- Aurora preview and visualisation context upgrades are now live, but should be browser-QA’d against a real task on revision `00088-w6w`.
- Action needed: re-process the known dataset in the UI on revision `00088-w6w`, then verify saved outputs, Aurora preview responses, and Aurora visualisation responses.

## Verification Status

- Python syntax checks passed for updated backend Aurora files.
- `node --check` passed for updated frontend chat and visualisation files.
- Revisions `00082-mgx`, `00083-lg2`, `00084-l4k`, `00087-sgq`, and `00088-w6w` all deployed successfully to Cloud Run.
- `/api/health` returned healthy after deploying `00088-w6w`.

## Important Open Items

1. **Fix `_xlsx_to_csv_bytes`** — bold-only detection misses partially-bold BS rows. It should also check for "BS"/"base" text in row content.
2. **Re-process the test dataset** — rerun on revision `00088-w6w` so saved results pick up the corrected along-line distance handling.
3. **Browser-QA Aurora** — verify Preview and Visualisation chat answers against the exact screen state.
4. Claude-backed export drafting still needs a quality pass.
5. Manual browser QA on the latest visualisation and home-page fixes.

## Main Files Most Relevant Right Now

### Backend

- `backend/services/processing_service.py`
- `backend/services/task_service.py`
- `backend/services/ai_service.py`
- `backend/routes/ai.py`
- `backend/models/ai.py`

### Frontend

- `frontend/index.html`
- `frontend/js/shared/ai_chat.js`
- `frontend/js/sections/preview.js`
- `frontend/js/sections/visualisation.js`
