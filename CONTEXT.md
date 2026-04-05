# GAIA Magnetics Context

Last updated: `2026-04-05`

## Purpose

This file captures the current working context for `gaia-magnetics`.
`Instructions.txt` in the parent workspace remains the higher-level project instruction set.

## Workspace

- Workspace root:
  `c:\Users\Tolu\Documents\Terra Analytics\Magnetics Main\2\magnetics (main)`
- App root:
  `c:\Users\Tolu\Documents\Terra Analytics\Magnetics Main\2\magnetics (main)\gaia-magnetics`
- Instructions file:
  `c:\Users\Tolu\Documents\Terra Analytics\Magnetics Main\2\magnetics (main)\Instructions.txt`

## Live Deployment

- Public URL:
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

## Deploy Command

```powershell
powershell -Command "& 'C:\Users\Tolu\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd' run deploy gaia-magnetics --source 'c:\Users\Tolu\Documents\Terra Analytics\Magnetics Main\2\magnetics (main)\gaia-magnetics' --region us-central1 --project app-01-488817 --quiet"
```

> Note: use `powershell -Command` with the explicit `gcloud.cmd` path because of spaces in the path on Windows.

## Standing Constraints

- Preserve the existing folder structure.
- Use `frontend/index.html` as the shared UI shell.
- Keep integrations real: Firestore, Cloud Storage, Cloud Run, Google Maps, Gemini chat, and Anthropic export generation.
- Do not reintroduce dummy data or misleading labels.
- User-visible assistant branding should remain `Aurora AI`.
- The frontend still mixes static shell markup and modular JS; meaningful changes often need both.

## Scientific Conventions

- `raw_magnetic`: snapshot of the original uploaded field value before any corrections. Stored at ingest, never overwritten.
- `point.magnetic`: the fully corrected value after all active pipeline stages.
- Diurnal correction formula: `corrected = raw - (interpolated_base - reference_value)`.
  - `reference_value` = `nanmedian` of all base readings.
  - `interpolated_base` = linearly interpolated between consecutive base station readings.
- Single-base case falls through to FFT estimation because one time-point cannot define a temporal drift trend.
- `along_line_m`: backend-computed cumulative traverse distance in metres using survey points only; off-line base-station revisits should not inflate the traverse path.

## Base Station Detection (Multi-layer)

Detection happens in two places:

### 1. At upload time - `task_service.py:_xlsx_to_csv_bytes`

- Converts `.xlsx` to CSV and adds `__is_base_station__`.
- Detects BS rows by bold formatting.
- Known gap: partially bold BS rows can still be missed.
- Text-based BS detection still needs to be added here.

### 2. At processing time - `processing_service.py:_infer_base_station_mask`

- Reads the existing `__is_base_station__` column.
- Scans text/object columns for `bs`, `base`, `base station`, and `base_station`.
- Uses coordinate repeat detection with a tight tolerance.

## Current Functional Shape

### Navigation and project flow

- Core route sequence is:
  `Home -> Projects -> Setup -> Analysis -> Preview -> Processing -> Visualisation -> Export`
- Selected project and task IDs persist across refreshes.
- Home hero uses a single `Projects` button.

### Setup and analysis

- Survey upload supports CSV/XLSX with coordinate mapping, raw-data mapping, and base-station handling.
- Analysis surfaces interval-based diurnal behaviour, fallback expectations, and regional/residual method controls.

### Preview

- Preview renders Google Maps-backed station maps.
- Summary cards show survey traverses and predicted traverses separately.
- Aurora chat is enabled on Preview.
- Preview Aurora rebuilds station/base-station context from uploaded survey data instead of relying only on saved processed outputs.

### Processing

- Diurnal correction: interval-based consecutive base-station interpolation is preferred; FFT fallback is used only when true base-station interval correction is unavailable.
- Corrected, regional, and residual outputs are persisted separately.
- Regional methods: `polynomial`, `trend`, `lowpass`, `igrf_context`.
- QA and correction reporting expose diurnal method, interval coverage, regional method, and quality state.

### Visualisation

- Line profiles show `point.magnetic`, not `raw_magnetic`.
- Base station points are excluded from line profiles and map overlay.
- Traverse x-axis uses first non-base-station point as origin, with survey-only distance accumulation so base-station revisits do not create fake gaps.
- Point-based views (`Map`, `Line Profiles`) use displayed point values for stats/scale.
- Grid-based views use grid-surface values for stats/scale.
- Layers are grouped as `Main processed field`, `Regional field`, `Residual field`, and `Derived products`.
- Aurora chat on Visualisation receives active layer, visual mode, traverse selection, approximate line endpoints, displayed stats, displayed-value provenance, and key processing metadata.

### Export

- Export jobs complete and bundle outputs are being generated.
- Corrected/regional/residual report content can be selected independently.
- Export AI generation now uses direct Anthropic for `DOCX`, `PDF`, and `PPTX` whenever `ANTHROPIC_API_KEY` is present.
- Cloud Run now gets `ANTHROPIC_API_KEY` from Secret Manager secret `gaia-anthropic-api-key`.
- Chat remains on the existing chat path; the Anthropic switch was made for exports.
- DOCX, PDF, and PPTX exports consume structured `{docx, pdf, pptx}` AI output packages.
- Export prompts now send a compressed, filtered run context instead of a large verbose payload.
- Export AI output is now validated more aggressively for placeholder text, raw dumps, unsupported sections, repeated passages, and misleading scientific labels before rendering.
- DOCX/PDF/PPTX builders now enforce cleaner ordering, tighter PPTX density, and more explicit QA/fallback callouts.
- CSV, GeoJSON, KMZ/KML, GDB-style, and map-image bundles include `metadata.json`.
- Native FileGDB output is still not implemented; the current `gdb_bundle` is a geospatial delivery bundle with feature-class-style GeoJSON members.

## Live Export Failure Context

- The export provider/key routing is now correct in Cloud Run.
- Revision `00097-thc` hardened the Anthropic export path with clearer provider-error classification and stronger output validation.
- Cloud Run logs on 2026-04-04 showed `anthropic.RateLimitError` with HTTP `429 RESOURCE_EXHAUSTED`.
- When that happens, `backend/services/ai_service.py` still falls back, but the fallback package is now held to stricter truthfulness and formatting rules than before.
- Fresh live export artifacts still need to be inspected to confirm the improved report quality on the deployed service.

## Known Follow-Up Areas

1. **Fix bold detection in `_xlsx_to_csv_bytes`** - add text-based fallback so `BS`/`base` in any cell also flags the row.
2. **Fresh live export verification** - generate a new `DOCX/PDF/PPTX` set after revision `00097-thc` and inspect the real artifacts.
3. **Anthropic 429 mitigation** - keep improving provider resilience because recent exports hit `RESOURCE_EXHAUSTED` even though fallback honesty and output quality gates are now stronger.
4. **Browser-QA Aurora** - confirm Preview and Visualisation answers match the exact active screen context.
5. **Re-process the known dataset** - rerun on the current revision to verify saved outputs and Aurora responses against current code.
