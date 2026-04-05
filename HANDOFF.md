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
  `gaia-magnetics-00114-rdc`
- Service account:
  `vet-dev-backend@app-01-488817.iam.gserviceaccount.com`

## Deploy Command

```powershell
powershell -Command "& 'C:\Users\Tolu\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd' run deploy gaia-magnetics --source 'c:\Users\Tolu\Documents\Terra Analytics\Magnetics Main\2\magnetics (main)\gaia-magnetics' --region us-central1 --project app-01-488817 --quiet"
```

> On Windows, `gcloud` resolves to a Python Store alias and fails. Use the explicit `gcloud.cmd` path via `powershell -Command`.

## What Changed Most Recently

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

### 1. Add Firebase authorized domain (user action required)
Firebase Console → project `app-01-488817` → Authentication → Settings → Authorized domains → Add `magnetics.terracode-analytics.live`.
Without this, Google OAuth popup throws `auth/unauthorized-domain` on the custom domain.

### 2. Verify export download end-to-end
Run a fresh export on any processed task. Confirm:
- No "Choose at least one processed output" error in console.
- Download button produces a file.
- Check Cloud Logging for `export.path.outcome = anthropic_success`.

### 3. If export still failing
Check Cloud Logging for per-block outcomes. The dominant failure modes as of the last check were:
- `project_setup` truncating (token budget too small) → split further or reduce prompt context.
- `pptx_group_1` truncating → same fix.
- `pptx_group_2` missing section → check block prompt covers all required sections.

## Most Important Files Right Now

| File | Why |
|---|---|
| `backend/auth.py` | New Firebase auth dependency |
| `backend/main.py` | Route auth wiring + `/login` route |
| `frontend/login.html` | New standalone login page |
| `frontend/js/auth.js` | New Firebase auth helpers |
| `frontend/js/api.js` | Auth-aware request wrapper |
| `frontend/js/app.js` | App boot + auth gate |
| `frontend/js/sections/export.js` | Export selection, chip fix, download |
| `frontend/js/sections/navigation.js` | Screen routing, persistence, transitions |
| `backend/services/ai_service.py` | Block export + Aurora chat |
| `backend/services/export_service.py` | DOCX/PDF/PPTX builders |

## Remaining Gaps

1. **Firebase authorized domain** — `magnetics.terracode-analytics.live` not yet added to Firebase Console.
2. **Export download unverified** — kebab-case chip fix deployed but not end-to-end confirmed.
3. **`anthropic_success` not yet confirmed** — raised token budgets deployed; needs a fresh export run + log check.
4. **`_xlsx_to_csv_bytes` text fallback** — bold-only BS detection still misses partially-bold rows.
5. **Browser QA on Aurora** — Preview and Visualisation chat not yet verified against real processed task.
6. **Re-process known dataset** — after export stabilises.
7. **Native FileGDB** — still not implemented; `gdb_bundle` uses feature-class-style GeoJSON.

## Working Style

- Keep updates short and concrete.
- Prefer fixing and verifying over only describing.
- If you deploy, report the exact revision and URL.
- If you make assumptions, state them after the work.
- Keep user-visible AI wording as `Aurora AI` unless the user asks to change it.
- Always run relevant syntax checks before deploying.
- Update `STATUS.md`, `CONTEXT.md`, and `HANDOFF.md` after significant changes or deploys.
