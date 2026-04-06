# GAIA Magnetics Handoff

You are taking over work on `gaia-magnetics`.

Read these first:

1. `c:\Users\Tolu\Documents\Terra Analytics\Magnetics Main\2\magnetics (main)\Instructions.txt`
2. `c:\Users\Tolu\Documents\Terra Analytics\Magnetics Main\2\magnetics (main)\gaia-magnetics\STATUS.md`
3. `c:\Users\Tolu\Documents\Terra Analytics\Magnetics Main\2\magnetics (main)\gaia-magnetics\CONTEXT.md`

## Current Live State

- Public URL (custom domain):
  `https://magnetics.terracode-analytics.live`
- Fallback Cloud Run URL:
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
  `gaia-magnetics-00120-jpb`
- Service account:
  `vet-dev-backend@app-01-488817.iam.gserviceaccount.com`

## Deploy Command

```powershell
powershell -Command "& 'C:\Users\Tolu\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd' run deploy gaia-magnetics --source 'c:\Users\Tolu\Documents\Terra Analytics\Magnetics Main\2\magnetics (main)\gaia-magnetics' --region us-central1 --project app-01-488817 --quiet"
```

> On Windows, `gcloud` resolves to a Python Store alias and fails. Use the explicit `gcloud.cmd` path via `powershell -Command`.

## What Changed Most Recently

### Session 2026-04-07 — Analysis page reconstruction (A+C) + processing methods document

**Analysis page — A. Corrections**
- IGRF: survey date picker added to UI. `collectAnalysisConfig` sends `survey_date`. `saveAndPreview` blocks if IGRF is enabled without a date. Backend already read `survey_date` from `analysis_config` — it just needed the UI to supply it.
- Filtering: cutoff half-wavelength (stations) input added. Config key `filter_cutoff_stations`. Backend converts: `cutoff_freq = 1 / n_stations`, applied in station-count domain (`sample_spacing=1.0`). Per-line for multi-line.

**Analysis page — C. Add-ons**
- Added: Second Vertical Derivative (SVD) checkbox with pre-smooth toggle; Total Horizontal Gradient (THG) checkbox; Tilt Derivative checkbox.
- All add-on descriptions updated to be scientifically explicit and geometry-aware.
- `ADD_ON_MAP` updated: `second_vertical_derivative`, `thg`, `tilt_derivative` now map to backend keys.
- `collectAnalysisConfig` collects: `survey_date`, `filter_cutoff_stations`, `svd_pre_smooth`.
- `loadAnalysis` restores all new fields.
- `window.toggleIGRF`, `window.toggleSVD` added as toggle helpers.

**Backend — new profile helper functions**
Added to `processing_service.py` after line ~451 (before `_RTP_LOW_INC_THRESHOLD`):
- `_second_vertical_derivative_grid`: FFT −K² operator for 2D grids.
- `_spacing_from_along_line`: derives per-station spacing from `along_line_m`.
- `_fvd_profile`, `_svd_profile`, `_hd_profile`, `_thg_profile`, `_tilt_profile`, `_analytic_signal_profile`: spacing-aware finite-difference profile implementations (1D, along-traverse).
- `_compute_profile_add_ons`: orchestrates all profile add-ons for one line, returns dict of arrays.

**Backend — `_apply_add_ons` rebuilt**
- Detects geometry from `results["points"]` line_id count.
- Single-line: profile methods → back-project to grid via `griddata(nearest)` for display.
- Multi-line: existing FFT/gradient surface methods.
- SVD, THG, tilt now selectively computed and returned.
- `profile_add_ons` flat dict added to results (one value per point, for profile chart consumers).
- `addon_provenance` metadata block: source_field, method, profile_based, smoothing_applied, description, warning.
- `total_gradient` backward-compat alias kept for export service.

**Backend — `_apply_corrections` filter**
- `filter_cutoff_stations` from config → `cutoff_freq = 1 / n_stations`, `sample_spacing=1.0`.
- Per-line energy ratios and warnings reported per line.
- High-pass always raises a noise-amplification warning.

**Documentation**
- `PROCESSING_METHODS.txt` created at repo root — exact algorithm reference for all corrections and add-ons, tied to source code.

### Session 2026-04-06 — Auth loop fix, dark mode default, password eye toggle

**Auth loop fix**
- `frontend/js/auth.js`: `waitForAuth` now uses `auth.authStateReady()` → `auth.currentUser` instead of `onAuthStateChanged`. The old implementation unsubscribed after the first callback, which could fire with `null` before Firebase finished loading its persisted session from IndexedDB — causing `app.js` to redirect to `/login` right after sign-in.
- `frontend/js/auth.js`: `signInWithGoogle` switched from `signInWithRedirect` to `signInWithPopup`. The redirect flow had a cross-page IndexedDB race (write on `/login` → navigate → read on `/` before write completes). Popup completes in the same page context so auth state is persisted before we navigate. Removed `signInWithRedirect`, `getRedirectResult`, and `getGoogleRedirectResult` exports.
- `frontend/login.html`: Removed the `getGoogleRedirectResult()` IIFE. On-load check is now just `waitForAuth()` → redirect if already signed in. `doGoogle` now awaits `signInWithGoogle()` and then does `window.location.replace("/")`.

**Dark mode default**
- `frontend/index.html`: `data-theme` attribute changed from `"light"` to `"dark"`. The theme toggle in `navigation.js` still works — it reads and flips the attribute.

**Password eye toggle**
- `frontend/login.html`: Eye button added to both Sign in and Create account password fields. Uses inline SVG (crossed-out eye / open eye). `togglePw(id, btn)` swaps `input.type` between `"password"` and `"text"` and swaps the icon. `tabindex="-1"` keeps it out of the tab order.

### Session 2026-04-05 — Auth, Login, Export UX, Navigation

**Firebase Authentication — new**
- `frontend/js/auth.js` (new): Firebase JS SDK v11.6.0 from CDN. Exports `waitForAuth`, `getIdToken`, `signInWithGoogle`, `signInWithEmail`, `signUpWithEmail`, `signOutUser`. Auto-refreshes token within 5 min of expiry.
- `backend/auth.py` (new): `verify_token` FastAPI dependency. Extracts Bearer token, calls `firebase_auth.verify_id_token()`. Uses ADC (no service account key — org policy blocks creation). Raises HTTP 401 on failure.
- `backend/main.py`: `/health` and `/login` routes are public. All other routes require `Depends(verify_token)`. Added `/login` route returning `login.html`. Startup pre-initialises Firebase.
- `backend/requirements.txt`: Added `firebase-admin==6.6.0`.
- `frontend/js/api.js`: Every `request()` attaches `Authorization: Bearer <token>`. 401 → `signOutUser()` + redirect to `/login`.
- `frontend/js/app.js`: `waitForAuth()` gate on boot. Wires `window.signOut`. Shows `user.displayName` in top nav.

**Login page — full redesign**
- `frontend/login.html` (new): Served at `/login`.
  - Background: blurred CSS ghost of the GAIA app — dark sidebar with nav items + active project, top bar with tool buttons, a full magnetic anomaly map (radial gradients + SVG contour rings in orange/blue/yellow/green/purple), compass, scale bar, 4 data cards.
  - Foreground: white floating login card — `GAIA Magnetics · Geophysical Platform` text (no icons), segmented Sign in / Create account tab control, email/password fields, live password requirements panel (5 checkmarks: uppercase, lowercase, number, special char, 8+ chars), 4-colour Google SVG logo on the Google button.
  - Placeholder text is neutral (`Your full name`, `you@example.com`). No "Jane Smith".
  - Full client-side validation before submit; friendly error messages mapped from Firebase error codes; Enter key support; loading states on buttons.

**Export UI fixes**
- Removed static "Processed outputs available for export" card from `index.html`.
- Removed selection summary card and drilling recommendations from `export.js`.
- Dynamic output chips: only outputs matching the user's applied corrections appear (filtered by `appState.task.analysis_config.corrections`).
- Fixed camelCase→kebab-case bug in chip data attributes: `data-exportOutput` → `data-export-output`. This was silently blocking all downloads.
- Export block token budgets raised (all blocks); `pptx_group_2` split into `pptx_group_2a` and `pptx_group_2b`.
- PPTX slide density validation relaxed: bullets >5 (was >4), body >400 chars (was >280).
- Aurora chat `max_tokens` raised from 1200 → 2400 (fixes incomplete responses).
- Export `_build_artifact()` wrapped in try/except so one format failure doesn't abort the entire export job.

**Navigation and UX**
- Page transitions: `.screen` elements animate in with `fadeUp 0.25s cubic-bezier(0.22,1,0.36,1)` and 14px translateY.
- Screen persistence on refresh: `localStorage.setItem("gaiaCurrentScreen", target)` + `history.pushState`. After sidebar hydration, `window.go(target)` restores the last screen.
- `popstate` listener for browser back/forward.
- Re-entrancy guard `_goInProgress` in `window.go` — prevents infinite recursion when screen-load callbacks call `window.go` back to the same screen.
- Custom domain `magnetics.terracode-analytics.live` — CNAME in Spaceship → Cloud Run domain mapping → Google-managed SSL cert.
- Browser tab title: "V2" removed from `<title>`.

## Immediate Next Steps

### 1. QA the analysis page
After deploy:
- Enable IGRF and try saving without a date — should block with a notice.
- Enable IGRF with a date, save, re-open the task — date should be restored.
- Enable SVD — pre-smooth toggle should appear; save and reopen — state restored.
- Enable THG and Tilt Derivative — both should save and restore correctly.
- Run processing on a single-line task — check that `addon_provenance` in results metadata shows `profile_based: true` for derivative add-ons.
- Run processing on a multi-line task — check `profile_based: false`.

### 3. Add SVD and THG to export service
`export_service.py` does not yet list `second_vertical_derivative` or `thg` in its layer registry. Add them alongside the existing FVD and horizontal derivative entries if export of these outputs is needed.

### 4. Verify export download end-to-end
Run a fresh export on any processed task. Confirm:
- No "Choose at least one processed output" error in console.
- Download button produces a file.
- Check Cloud Logging for `export.path.outcome = anthropic_success`.

## Most Important Files Right Now

| File | Why |
|---|---|
| `backend/services/processing_service.py` | Profile add-on helpers, geometry-aware `_apply_add_ons`, filter cutoff |
| `frontend/index.html` | Analysis section A+C rebuilt — IGRF date, filter cutoff, SVD/THG/Tilt |
| `frontend/js/sections/analysis.js` | ADD_ON_MAP, collectAnalysisConfig, loadAnalysis, toggleIGRF/toggleSVD |
| `PROCESSING_METHODS.txt` | Exact algorithm reference for all corrections and add-ons |
| `backend/services/export_service.py` | SVD and THG not yet in layer registry — next addition needed here |
| `backend/auth.py` | Firebase token verification |
| `frontend/js/sections/export.js` | Export selection and download |
| `frontend/js/sections/navigation.js` | Screen routing, persistence, transitions |

## Remaining Gaps

1. **QA the analysis page** — live at `00120-jpb`; verify IGRF date, SVD/THG/Tilt, filter cutoff, run a processing job.
2. **SVD and THG not in export layer list** — `export_service.py` needs updating before these appear in DOCX/PDF/PPTX.
3. **Export download unverified** — kebab-case chip fix deployed but not end-to-end confirmed.
4. **`anthropic_success` not yet confirmed** — raised token budgets deployed; needs a fresh export run + log check.
5. **`_xlsx_to_csv_bytes` text fallback** — bold-only BS detection still misses partially-bold rows.
6. **Browser QA on Aurora** — Preview and Visualisation chat not yet verified against real processed task.
7. **Re-process known dataset** — after export stabilises.
8. **Firebase authorized domain** — `magnetics.terracode-analytics.live` not yet added to Firebase Console (good hygiene; popup sign-in works without it).
9. **Native FileGDB** — still not implemented; `gdb_bundle` uses feature-class-style GeoJSON.

## Working Style

- Keep updates short and concrete.
- Prefer fixing and verifying over only describing.
- If you deploy, report the exact revision and URL.
- If you make assumptions, state them after the work.
- Keep user-visible AI wording as `Aurora AI` unless the user asks to change it.
- Always run relevant syntax checks before deploying.
- Update `STATUS.md`, `CONTEXT.md`, and `HANDOFF.md` after significant changes or deploys.
