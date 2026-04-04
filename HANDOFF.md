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
  `gaia-magnetics-00088-w6w`
- Service account:
  `vet-dev-backend@app-01-488817.iam.gserviceaccount.com`

## Deploy Command

```powershell
powershell -Command "& 'C:\Users\Tolu\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd' run deploy gaia-magnetics --source 'c:\Users\Tolu\Documents\Terra Analytics\Magnetics Main\2\magnetics (main)\gaia-magnetics' --region us-central1 --project app-01-488817 --quiet"
```

> On Windows, `gcloud` resolves to a Python Store alias and fails. Use the explicit `gcloud.cmd` path via `powershell -Command`.

## What Changed Most Recently

### This session (2026-04-04)

**Live deploys completed:**
- `gaia-magnetics-00087-sgq` — visualisation scale/stat alignment, preview Aurora count fix, single `Projects` button on home.
- `gaia-magnetics-00088-w6w` — Aurora now receives rich screen-aware UI context from Preview and Visualisation.

**Visualisation and processing fixes now live:**
- Line profiles show `point.magnetic` instead of `raw_magnetic`.
- Base station points are excluded from line profiles and map overlay.
- Traverse distance no longer stretches through off-line base-station revisits; backend `along_line_m` and frontend profile distance both follow survey points only.
- Point-based views (`Map`, `Line Profiles`) now compute scale/stat ranges from the displayed point values instead of unrelated grid-wide values.
- Grid-based views (`Contour`, `Heatmap`, `3D`) still use grid-surface stats.
- Home page hero now has one `Projects` button, not two.

**Aurora AI fixes now live:**
- Preview Aurora rebuilds preview-side context from uploaded survey data instead of depending only on saved processed outputs.
- Aurora request payloads now include `ui_context`.
- On Visualisation, Aurora now knows the active layer, visual mode, selected traverse, approximate line start/end coordinates, whether the user is on a map or profile plot, displayed value source, displayed stats, and key processing metadata like diurnal method and regional method.
- On Preview, Aurora now knows preview bounds, preview point count, base-station count, and traverse count from the current screen state.

### Previous session

- Diurnal correction: interval-based consecutive base-station interpolation is the preferred path.
- Regional and residual are first-class outputs with configurable methods.
- Corrected, regional, and residual surfaces are persisted separately.
- Export and Aurora reporting receive distinct corrected/regional/residual context.

## Most Important Files Right Now

- `backend/services/processing_service.py` — `_clean_dataframe`, `_infer_base_station_mask`, `_apply_diurnal_correction`
- `backend/services/ai_service.py` — preview rebuild path, UI-context prompt assembly
- `backend/models/ai.py` — Aurora request schema
- `frontend/js/shared/ai_chat.js` — shared chat payload assembly
- `frontend/js/sections/visualisation.js` — line profiles, map overlay, stats source, Aurora context builder
- `frontend/js/sections/preview.js` — preview chat context builder
- `frontend/index.html` — shared UI shell and home-page hero

## Remaining Gaps

1. **`_xlsx_to_csv_bytes` text fallback** — bold-only detection still misses partially-bold BS rows. Add text-based row detection at upload time.
2. **Browser QA on revision `00088-w6w`** — confirm Aurora answers correctly from both Preview and Visualisation with a real processed task.
3. **Re-process the known dataset** on revision `00088-w6w` and verify saved outputs reflect the corrected along-line distance path.
4. Claude-backed export drafting quality pass.
5. Update docs again after the next processing rerun if new scientific findings emerge.

## Working Style

- Keep updates short and concrete.
- Prefer fixing and verifying over only describing.
- If you deploy, report the exact revision and URL.
- If you make assumptions, state them after the work.
- Keep user-visible AI wording as `Aurora AI` unless the user asks to change it.
- Always run relevant syntax checks before deploying.
- Update `STATUS.md`, `CONTEXT.md`, and `HANDOFF.md` after significant changes or deploys.
