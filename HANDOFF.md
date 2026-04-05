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
  `gaia-magnetics-00106-jmm`
- Service account:
  `vet-dev-backend@app-01-488817.iam.gserviceaccount.com`

## Deploy Command

```powershell
powershell -Command "& 'C:\Users\Tolu\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd' run deploy gaia-magnetics --source 'c:\Users\Tolu\Documents\Terra Analytics\Magnetics Main\2\magnetics (main)\gaia-magnetics' --region us-central1 --project app-01-488817 --quiet"
```

> On Windows, `gcloud` resolves to a Python Store alias and fails. Use the explicit `gcloud.cmd` path via `powershell -Command`.

## What Changed Most Recently

### This session (2026-04-05)

**Live deploys completed:**
- `gaia-magnetics-00098-bt7` - structured export-path observability added for provider failures and fallback outcomes.
- `gaia-magnetics-00099-r6r` - export model corrected to `claude-sonnet-4-6` with startup/preflight availability logging.
- `gaia-magnetics-00100-z9k` - fenced JSON parsing and safer object extraction deployed.
- `gaia-magnetics-00101-lz8` - wrapper-aware parsing improvements deployed.
- `gaia-magnetics-00102-nx9` - parse-forensics logging deployed for exact JSON decode diagnostics.
- `gaia-magnetics-00103-zvw` - export page reworked so users choose from actual processed outputs before report generation.
- `gaia-magnetics-00104-8bb` - truncation-aware retry and smaller split report/pptx package generation deployed.
- `gaia-magnetics-00105-qbj` - first block-based export generation rollout deployed.
- `gaia-magnetics-00106-jmm` - smaller block prompts, wrapper unwrapping, and tighter block validation updates deployed.

**Export state now live:**
- Export generation for `DOCX`, `PDF`, and `PPTX` uses direct Anthropic whenever `ANTHROPIC_API_KEY` is present.
- Cloud Run has `ANTHROPIC_API_KEY` attached from Secret Manager.
- The configured export model is `claude-sonnet-4-6`.
- The export system reads `export_agent.md`.
- Export-path logging now includes provider failures, parse-forensics, retry modes, block outcomes, validation rejection reasons, and final path outcomes.
- The export page now exposes actual processed outputs and lets users choose which outputs should be allowed into report exports before any `DOCX`, `PDF`, or `PPTX` is generated.
- Export generation is no longer one large all-in-one package attempt. It is now a block-based server-side merge flow with per-block fallback.

**Current live export reality:**
- The export path is still not fixed.
- The latest checked export on `00106-jmm` for task `5f3ed2605e3144a19edc43f5c9af1ffa` ended with:
  `export.path.outcome = anthropic_response_invalid_fallback_used`
- Successful blocks in that live run:
  - `executive_summary`
  - `pptx_group_3`
  - `pptx_group_4`
- Failed blocks in that live run:
  - `project_setup` -> parse failure, `failure_class = truncated_json`
  - `pptx_group_1` -> parse failure, `failure_class = truncated_json`
  - `pptx_group_2` -> block validation failure, `missing_expected_section`
- Final package validation also failed with:
  - `pptx:Data and Survey Summary:slide_density`
- Files still generate, but they are still fallback-backed. Do not treat that as success.

**Success condition:**
- The export path is only considered fixed when Cloud Logging shows:
  `export.path.outcome = anthropic_success`

**Previously deployed scientific and UX fixes still live:**
- Interval-based diurnal correction remains the preferred path.
- Corrected, regional, and residual outputs remain first-class products.
- Line profiles and point-based scales use the displayed survey values instead of unrelated grid-wide stats.
- Preview and Visualisation Aurora context upgrades remain live.
- Home page still shows a single `Projects` button.

## Most Important Files Right Now

- `backend/services/ai_service.py` - block-based export generation, parse forensics, retry logic, merge logic
- `backend/services/export_service.py` - DOCX/PDF/PPTX builders and final package validation
- `backend/gcp/vertex_ai.py` - `AnthropicClaudeClient`, provider error classification, preflight
- `backend/config.py` - export model configuration
- `backend/models/ai.py` - Aurora response shape
- `backend/services/processing_service.py` - `_clean_dataframe`, `_infer_base_station_mask`, `_apply_diurnal_correction`
- `backend/services/task_service.py` - `_xlsx_to_csv_bytes`
- `frontend/js/sections/export.js` - export request payload assembly and user output selection
- `frontend/index.html` - export UI shell

## Remaining Gaps

1. **`_xlsx_to_csv_bytes` text fallback** - bold-only BS detection still misses partially-bold rows. Add text-based row detection at upload time.
2. **Split the still-failing export blocks further** - `project_setup` and `pptx_group_1` are still truncating live.
3. **Fix PPTX validation tension** - `pptx_group_2` can fail `missing_expected_section`, and merged PPTX validation can fail `slide_density`.
4. **Reach a true live Anthropic success** - no more fallback-backed “success” claims. The only acceptable success marker is:
   `export.path.outcome = anthropic_success`
5. **Fresh live export QA after success** - once the live path reaches `anthropic_success`, inspect a real frontend-generated `DOCX/PDF/PPTX` set.
6. **Browser QA on current revision** - confirm Aurora answers correctly from both Preview and Visualisation with a real processed task.
7. **Re-process the known dataset** after the export path stabilizes.
8. Update docs again after the next live export change or success/failure shift.

## Working Style

- Keep updates short and concrete.
- Prefer fixing and verifying over only describing.
- If you deploy, report the exact revision and URL.
- If you make assumptions, state them after the work.
- Keep user-visible AI wording as `Aurora AI` unless the user asks to change it.
- Always run relevant syntax checks before deploying.
- Update `STATUS.md`, `CONTEXT.md`, and `HANDOFF.md` after significant changes or deploys.
