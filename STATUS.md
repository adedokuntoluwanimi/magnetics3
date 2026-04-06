# GAIA Magnetics Status

Last updated: `2026-04-07`

## Live Snapshot

- App URL:
  `https://magnetics.terracode-analytics.live`
  (also `https://gaia-magnetics-348555315681.us-central1.run.app`)
- Cloud Run service:
  `gaia-magnetics`
- Latest live revision:
  `gaia-magnetics-00120-jpb` (Analysis page A+C reconstruction + geometry-aware add-ons, deployed 2026-04-07)
- Region:
  `us-central1`
- Infra project:
  `app-01-488817`
- AI project:
  `app-01-488817-ai`
- Service account:
  `vet-dev-backend@app-01-488817.iam.gserviceaccount.com`

## Revision History (Recent)

| Revision | What changed |
|---|---|
| `00106-jmm` | Smaller block prompts, wrapper unwrapping, tighter block validation |
| `00107+` | Export block token budgets raised, `pptx_group_2` split into `2a`/`2b`, PPTX validation relaxed, Aurora chat `max_tokens` 1200→2400 |
| `00110+` | Export UI reworked: removed static availability card and selection summary; dynamic processed outputs; camelCase→kebab-case data attribute fix for downloads |
| `00111+` | Page transitions (fadeUp animation), screen persistence on refresh (localStorage + URL hash), re-entrancy guard on navigation |
| `00112+` | Custom domain `magnetics.terracode-analytics.live` live; browser tab title V2 removed |
| `00113+` | Firebase Authentication added (Google OAuth + email/password); `backend/auth.py`, `frontend/js/auth.js`, all API routes protected |
| `00114-rdc` | Login page redesigned: blurred app UI ghost background, floating login card, proper Google logo, live password requirements indicator |
| `00117-blh` | `waitForAuth` switched to `auth.authStateReady()`; dark mode set as default theme |
| `00118-mkt` | Google sign-in switched from redirect to popup (fixes post-auth loop); password reveal eye toggle on both password fields |
| `00120-jpb` | Analysis page A+C reconstruction; profile-based add-on helpers (FVD/SVD/HD/THG/tilt/analytic signal); geometry-aware `_apply_add_ons`; filter cutoff control; IGRF date input; SVD/THG/Tilt checkboxes; `PROCESSING_METHODS.txt` |

## Current Product State

- FastAPI backend is live with modular `routes`, `services`, `models`, `gcp`, and `jobs`.
- Frontend is a full SPA: `frontend/index.html` with ES-module sections under `frontend/js/sections`.
- Core workflow is live: `Home → Projects → Setup → Analysis → Preview → Processing → Visualisation → Export`
- Firebase Authentication is live: Google OAuth + email/password sign-in, all API routes protected by `verify_token`.
- Custom domain `magnetics.terracode-analytics.live` is live and SSL-provisioned.
- Screen state persists across refresh (localStorage + URL hash).
- Page transitions use a subtle fadeUp animation.
- Firestore stores project/task metadata and lightweight result references.
- Full processing outputs persisted to GCS `results.json`.
- Google Maps-backed preview and visualisation views are live.
- Aurora AI branding retained throughout.

## Most Recent Completed Work

### Analysis Page Reconstruction + Multi-line Processing Parity (2026-04-07)

**Analysis page — A. Corrections**
- IGRF: added survey date picker to the UI; `collectAnalysisConfig` now sends `survey_date` as ISO datetime; `saveAndPreview` blocks if IGRF is enabled without a date.
- Filtering: added cutoff half-wavelength control (stations); backend converts to spatial frequency `cutoff_freq = 1 / n_stations`; per-line for multi-line; high-pass warning shown in UI.

**Analysis page — C. Add-ons**
- Added: Second Vertical Derivative (SVD) with pre-smooth toggle; Total Horizontal Gradient (THG); Tilt Derivative — all selectable from the analysis page.
- Renamed analytic signal description to be explicit about profile vs surface basis.
- Updated all add-on descriptions to be geometry-aware and scientifically explicit.
- Regional residual method descriptions updated.

**Backend — profile-based add-on helpers (new functions)**
- `_second_vertical_derivative_grid`: FFT wavenumber-domain −K² operator for multi-line grids.
- `_spacing_from_along_line`: derives per-station spacing from `along_line_m`.
- `_fvd_profile`, `_svd_profile`, `_hd_profile`, `_thg_profile`, `_tilt_profile`, `_analytic_signal_profile`: spacing-aware finite-difference profile implementations.
- `_compute_profile_add_ons`: orchestrates all profile add-ons for a single line segment.

**Backend — `_apply_add_ons` rebuilt**
- Detects single-line vs multi-line from `results["points"]` line_id count.
- Single-line: profile-based computation on points data; values back-projected to grid for display.
- Multi-line: FFT wavenumber-domain methods on the 2D surface.
- SVD, THG, tilt derivative, analytic signal all now selectively computed when requested.
- `addon_provenance` metadata block stored per add-on: source_field, method, profile_based, smoothing_applied, description, warning.
- `profile_add_ons` flat array added to results for profile chart consumers.

**Backend — `_apply_corrections` filter cutoff**
- `filter_cutoff_stations` config key accepted; converted to `cutoff_freq = 1 / n_stations`.
- Applied with `sample_spacing=1.0` (station-count domain) when spatial cutoff is used.
- Per-line filter for multi-line; single-line treated as one segment.

**Documentation**
- `PROCESSING_METHODS.txt` created: exact algorithm description for every correction and add-on, tied to the source code.

### Auth Fix + Login UX (2026-04-06)
- `frontend/js/auth.js` — `waitForAuth` now uses `auth.authStateReady()` instead of `onAuthStateChanged`. Eliminates the race where the first callback fired with `null` before Firebase finished reading IndexedDB, causing `app.js` to redirect to `/login` immediately after a successful sign-in.
- `frontend/js/auth.js` — Google sign-in switched from `signInWithRedirect` to `signInWithPopup`. The redirect flow had a cross-page IndexedDB race (write on `/login` could complete after the read on `/`); popup completes in the same page context before navigation so auth state is guaranteed to be persisted.
- `frontend/login.html` — Removed the `getGoogleRedirectResult()` IIFE; on-load check is now just `waitForAuth()` → redirect if already signed in.
- `frontend/login.html` — Password reveal (eye) toggle added to both Sign in and Create account password fields. Crossed-out eye shown by default; swaps to open eye when password is visible.
- `frontend/index.html` — Default theme changed from `light` to `dark`.

### Firebase Authentication (2026-04-05)
- `frontend/js/auth.js` — Firebase JS SDK v11.6.0 from CDN; exports `waitForAuth`, `getIdToken`, `signInWithGoogle`, `signInWithEmail`, `signUpWithEmail`, `signOutUser`.
- `backend/auth.py` — `verify_token` FastAPI dependency using `firebase-admin` with ADC (no service account key; org policy blocks key creation).
- `backend/main.py` — All routes except `/health` and `/login` now require a valid Firebase ID token.
- `backend/requirements.txt` — `firebase-admin==6.6.0` added.
- `frontend/js/api.js` — Every request attaches `Authorization: Bearer <token>`; 401 triggers sign-out + redirect.
- `frontend/js/app.js` — Auth gate on load; user display name in top nav; sign-out button.

### Login Page Redesign (2026-04-05)
- `frontend/login.html` — Full rewrite.
  - Background: CSS-rendered ghost of the GAIA app (dark sidebar with nav, top bar, magnetic anomaly map with coloured contour rings, data cards) — blurred with `filter:blur(7px)`.
  - Foreground: white floating card with brand strip, segmented tab control, email/password fields, live password requirements panel (uppercase, lowercase, number, special char, 8+ chars), proper 4-colour Google SVG logo on the Google button.
  - No icons next to brand name. No "Jane Smith" placeholder.
  - Full validation before submit; friendly error messages; Enter key support; loading states.

### Export fixes (this session)
- Removed static "Processed outputs available for export" card and "Selection summary" from export UI.
- Removed "Drilling recommendations" from export narrative.
- Dynamic processed output chips: only outputs matching the user's applied corrections appear.
- Fixed camelCase→kebab-case data attribute bug (`data-exportOutput` → `data-export-output`) that was blocking downloads.
- Export block token budgets raised significantly; `pptx_group_2` split into `2a`/`2b`.
- PPTX slide density validation relaxed (bullets >4→>5, body >280→>400 chars).
- Aurora chat `max_tokens` raised 1200→2400 to fix incomplete responses.

### Navigation / UX (this session)
- Page transitions: `fadeUp 0.25s cubic-bezier(0.22,1,0.36,1)` animation on `.screen`.
- Screen persistence on refresh: `localStorage` + URL hash. After sidebar hydration, `window.go(target)` restores the last screen.
- Re-entrancy guard in `window.go` to prevent infinite navigation recursion.
- Custom domain `magnetics.terracode-analytics.live` CNAME → Cloud Run, SSL auto-provisioned.
- Browser tab title: "V2" removed.

## Active Investigation (Current)

- Analysis page reconstruction deployed as `00120-jpb` — needs QA.
- Export `anthropic_success` has not yet been confirmed in Cloud Logging — the camelCase download fix and token budget increases were deployed but a fresh export run hasn't been verified against logs yet.
- Firebase authorized domain: `magnetics.terracode-analytics.live` should still be added to Firebase Console → Authentication → Settings → Authorized domains as a best practice, even though popup sign-in is now working without it.

## Verification Status

- Google sign-in confirmed working end-to-end (popup flow, no redirect loop).
- Dark mode confirmed as default on app load.
- Password eye toggle confirmed on both sign-in and create account forms.
- Login page confirmed live at `https://magnetics.terracode-analytics.live/login`.
- Export download fix (kebab-case chip attributes) deployed but not yet end-to-end verified.

## Important Open Items

1. **QA the new analysis page** — now live at `00120-jpb`; verify IGRF date, SVD/THG/Tilt toggles, filter cutoff, and run a processing job to confirm add-on outputs.
2. **QA new analysis page** — confirm IGRF date input saves and is used correctly; confirm SVD/THG/Tilt checkboxes save and trigger correct backend add-ons.
3. **Add SVD and THG to export layer list** — `export_service.py` does not yet render `second_vertical_derivative` or `thg` in DOCX/PDF/PPTX; they are stored in `results.json` but not exported.
4. **Verify export download end-to-end** — test that a real export job produces a downloadable file without "Choose at least one processed output" error.
5. **Confirm `anthropic_success` in Cloud Logging** — run a fresh export and check logs for `export.path.outcome = anthropic_success`.
6. **Fix `_xlsx_to_csv_bytes` bold detection** — add text-based fallback for partially-bold BS rows.
7. **Browser QA on Aurora** — verify Preview and Visualisation chat answers against active screen state.
8. **Re-process known dataset** — rerun after export and analysis page stabilise.
9. **Add custom domain to Firebase authorized domains** — `magnetics.terracode-analytics.live` in Firebase Console (good hygiene; popup works without it).
10. Native FileGDB output not yet implemented; `gdb_bundle` uses feature-class-style GeoJSON.

## Main Files Most Relevant Right Now

### Backend
- `backend/services/processing_service.py` — Profile add-on helpers, geometry-aware `_apply_add_ons`, filter cutoff
- `backend/services/export_service.py` — DOCX/PDF/PPTX builders (SVD/THG not yet added here)
- `backend/auth.py` — Firebase token verification
- `backend/main.py` — Route registration + auth dependencies

### Frontend
- `frontend/index.html` — Analysis section A+C rebuilt
- `frontend/js/sections/analysis.js` — ADD_ON_MAP, collectAnalysisConfig, loadAnalysis, initAnalysis
- `frontend/js/sections/export.js` — Export selection and download
- `frontend/js/sections/navigation.js` — Screen routing + persistence

### Documentation
- `PROCESSING_METHODS.txt` — Exact algorithm reference for all corrections and add-ons
