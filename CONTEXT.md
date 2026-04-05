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

- Public URL (custom domain):
  `https://magnetics.terracode-analytics.live`
- Fallback Cloud Run URL:
  `https://gaia-magnetics-348555315681.us-central1.run.app`
- Cloud Run service:
  `gaia-magnetics`
- Latest live revision:
  `gaia-magnetics-00114-rdc`
- Region:
  `us-central1`
- Infra project:
  `app-01-488817`
- AI project:
  `app-01-488817-ai`
- Service account:
  `vet-dev-backend@app-01-488817.iam.gserviceaccount.com`
- Firebase project:
  `app-01-488817` (same project; Firebase enabled)

## Deploy Command

```powershell
powershell -Command "& 'C:\Users\Tolu\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd' run deploy gaia-magnetics --source 'c:\Users\Tolu\Documents\Terra Analytics\Magnetics Main\2\magnetics (main)\gaia-magnetics' --region us-central1 --project app-01-488817 --quiet"
```

> Note: use `powershell -Command` with the explicit `gcloud.cmd` path because of spaces in the path on Windows. The bare `gcloud` alias resolves to a Windows Store stub and fails.

## Standing Constraints

- Preserve the existing folder structure.
- Use `frontend/index.html` as the shared UI shell.
- Keep integrations real: Firestore, Cloud Storage, Cloud Run, Google Maps, Gemini chat, Anthropic export generation, Firebase Auth.
- Do not reintroduce dummy data or misleading labels.
- User-visible assistant branding must remain `Aurora AI`.
- The frontend mixes static shell markup and modular JS; meaningful changes often need both.
- No service account key creation — org policy blocks it. Use ADC everywhere.

## Authentication Architecture

### Frontend
- Firebase JS SDK v11.6.0 loaded from `https://www.gstatic.com/firebasejs/11.6.0/`.
- `frontend/js/auth.js` exports: `waitForAuth`, `getIdToken`, `signInWithGoogle`, `signInWithEmail`, `signUpWithEmail`, `signOutUser`.
- `frontend/js/api.js` — every `request()` call attaches `Authorization: Bearer <token>`. 401 → sign-out + redirect to `/login`.
- `frontend/js/app.js` — on boot, `waitForAuth()` gate. Unauthenticated users redirect to `/login`.
- `frontend/login.html` — standalone login page served at `/login`. No shell dependencies.

### Backend
- `backend/auth.py` — `verify_token` FastAPI dependency. Extracts Bearer token, calls `firebase_auth.verify_id_token()`. Returns decoded claims on success, raises HTTP 401 on failure.
- `firebase_admin.initialize_app()` with no credentials — uses ADC. Works on Cloud Run because the attached SA has `roles/firebase.sdkAdminServiceAgent`.
- All routes except `/health/*` and `/login` are protected with `dependencies=[Depends(verify_token)]`.

### Pending
- `magnetics.terracode-analytics.live` must be added to Firebase Console → Authentication → Settings → Authorized domains for Google OAuth popup to work on the custom domain.

## Scientific Conventions

- `raw_magnetic`: snapshot of the original uploaded field value before any corrections. Stored at ingest, never overwritten.
- `point.magnetic`: the fully corrected value after all active pipeline stages.
- Diurnal correction formula: `corrected = raw - (interpolated_base - reference_value)`.
  - `reference_value` = `nanmedian` of all base readings.
  - `interpolated_base` = linearly interpolated between consecutive base station readings.
- Single-base case falls through to FFT estimation because one time-point cannot define a temporal drift trend.
- `along_line_m`: backend-computed cumulative traverse distance in metres using survey points only; off-line base-station revisits should not inflate the traverse path.

## Base Station Detection (Multi-layer)

### 1. At upload time — `task_service.py:_xlsx_to_csv_bytes`
- Converts `.xlsx` to CSV and adds `__is_base_station__`.
- Detects BS rows by bold formatting.
- Known gap: partially bold BS rows can still be missed. Text-based BS detection (`BS`/`base` text) still needs adding.

### 2. At processing time — `processing_service.py:_infer_base_station_mask`
- Reads the existing `__is_base_station__` column.
- Scans text/object columns for `bs`, `base`, `base station`, and `base_station`.
- Uses coordinate repeat detection with a tight tolerance.

## Current Functional Shape

### Navigation and project flow
- Core route sequence: `Home → Projects → Setup → Analysis → Preview → Processing → Visualisation → Export`
- Screen state persists across refresh: `localStorage` + URL hash. After sidebar hydration `window.go(target)` restores the last screen.
- Page transitions: `fadeUp 0.25s cubic-bezier(0.22,1,0.36,1)` animation on `.screen` elements.
- Re-entrancy guard (`_goInProgress`) in `window.go` prevents infinite recursion.

### Setup and analysis
- Survey upload supports CSV/XLSX with coordinate mapping, raw-data mapping, and base-station handling.
- Analysis surfaces interval-based diurnal behaviour, fallback expectations, and regional/residual method controls.

### Preview
- Preview renders Google Maps-backed station maps.
- Summary cards show survey traverses and predicted traverses separately.
- Aurora chat enabled on Preview; rebuilds context from uploaded survey data.

### Processing
- Diurnal correction: interval-based consecutive base-station interpolation preferred; FFT fallback only when unavailable.
- Corrected, regional, and residual outputs persisted separately.
- Regional methods: `polynomial`, `trend`, `lowpass`, `igrf_context`.

### Visualisation
- Line profiles show `point.magnetic`, not `raw_magnetic`.
- Base station points excluded from line profiles and map overlay.
- Traverse x-axis uses survey-only distance accumulation.
- Point-based views use displayed point values for stats/scale; grid-based views use grid-surface values.
- Aurora chat receives active layer, view mode, traverse selection, approximate line endpoints, displayed stats, provenance, and processing metadata.

### Export
- Export page lists actual processed output layers; user chooses which outputs appear in reports before generation.
- Dynamic chip generation: only outputs matching the user's applied corrections are shown (not all possible outputs).
- Download fix: chip data attributes written in kebab-case (`data-export-output`) to match CSS query selectors.
- Removed: static availability card, selection summary, drilling recommendations section.
- Export generation uses direct Anthropic for `DOCX`, `PDF`, `PPTX` with `ANTHROPIC_API_KEY` from Secret Manager.
- Configured model: `claude-sonnet-4-6`.
- Block-based generation with per-block fallback and server-side merge.
- Token budgets raised significantly from previous session; `pptx_group_2` split into `2a`/`2b`.
- PPTX validation relaxed (bullets ≤5, body ≤400 chars).
- Aurora chat `max_tokens` raised to 2400 to fix incomplete responses.

### Login
- `frontend/login.html` — served at `/login` by FastAPI, independent of the main shell.
- Design: full-viewport blurred app UI ghost (CSS-rendered sidebar, top bar, magnetic anomaly map, data cards) as background; white floating login card in foreground.
- No icons. No decorative logos.
- Supports: email/password sign-in, email/password account creation, Google OAuth.
- Password requirements: uppercase, lowercase, number, special character, 8+ chars — validated live with a checklist panel.

## Known Follow-Up Areas

1. **Firebase authorized domain** — add `magnetics.terracode-analytics.live` to Firebase Console → Authentication → Settings → Authorized domains.
2. **Verify export download** — end-to-end test: run export, download file, confirm no "Choose at least one processed output" error.
3. **Confirm `anthropic_success`** — check Cloud Logging after a fresh export run for `export.path.outcome = anthropic_success`.
4. **Fix `_xlsx_to_csv_bytes` bold detection** — add text-based BS row fallback.
5. **Browser QA on Aurora** — Preview and Visualisation chat against real processed task.
6. **Re-process known dataset** — after export stabilises.
