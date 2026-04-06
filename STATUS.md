# GAIA Magnetics Status

Last updated: `2026-04-06`

## Live Snapshot

- App URL:
  `https://magnetics.terracode-analytics.live`
  (also `https://gaia-magnetics-348555315681.us-central1.run.app`)
- Cloud Run service:
  `gaia-magnetics`
- Latest live revision:
  `gaia-magnetics-00118-mkt` (popup auth fix + password eye + dark mode default, deployed 2026-04-06)
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

- Export `anthropic_success` has not yet been confirmed in Cloud Logging — the camelCase download fix and token budget increases were deployed but a fresh export run hasn't been verified against logs yet.
- Firebase authorized domain: `magnetics.terracode-analytics.live` should still be added to Firebase Console → Authentication → Settings → Authorized domains as a best practice, even though popup sign-in is now working without it.

## Verification Status

- Google sign-in confirmed working end-to-end (popup flow, no redirect loop).
- Dark mode confirmed as default on app load.
- Password eye toggle confirmed on both sign-in and create account forms.
- Login page confirmed live at `https://magnetics.terracode-analytics.live/login`.
- Export download fix (kebab-case chip attributes) deployed but not yet end-to-end verified.

## Important Open Items

1. **Verify export download end-to-end** — test that a real export job produces a downloadable file without "Choose at least one processed output" error.
2. **Confirm `anthropic_success` in Cloud Logging** — run a fresh export and check logs for `export.path.outcome = anthropic_success`.
3. **Fix `_xlsx_to_csv_bytes` bold detection** — add text-based fallback for partially-bold BS rows.
4. **Browser QA on Aurora** — verify Preview and Visualisation chat answers against active screen state.
5. **Re-process known dataset** — rerun after export stabilises.
6. **Add custom domain to Firebase authorized domains** — `magnetics.terracode-analytics.live` in Firebase Console → Authentication → Settings → Authorized domains (good hygiene; popup works without it but redirect-based flows would need it).
7. Native FileGDB output not yet implemented; `gdb_bundle` uses feature-class-style GeoJSON.

## Main Files Most Relevant Right Now

### Backend
- `backend/auth.py` — Firebase token verification (new)
- `backend/main.py` — Route registration + auth dependencies
- `backend/services/ai_service.py` — Block-based export generation, Aurora chat
- `backend/services/export_service.py` — DOCX/PDF/PPTX builders

### Frontend
- `frontend/login.html` — Login page (new)
- `frontend/js/auth.js` — Firebase auth helpers (new)
- `frontend/js/api.js` — Auth-aware request wrapper
- `frontend/js/app.js` — App boot + auth gate
- `frontend/js/sections/export.js` — Export selection and download
- `frontend/js/sections/navigation.js` — Screen routing + persistence
