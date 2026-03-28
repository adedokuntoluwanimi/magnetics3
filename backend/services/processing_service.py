"""GAIA Magnetics – Processing Service
Industry-grade geophysical magnetic data processing pipeline.
Scientific auditability, numerical stability, Oasis Montaj-comparable outputs.
"""
from __future__ import annotations

import io
import json
import math
import logging
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd
from scipy.fft import rfft, irfft, rfftfreq
from scipy.interpolate import CubicSpline, RBFInterpolator, griddata, interp1d
from scipy.optimize import curve_fit
from scipy.signal import correlate
from scipy.spatial import KDTree
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler

from backend.logging_utils import log_event
from backend.models import PipelineRun, PipelineStep

logger = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL SCIENTIFIC HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _proc_log(name: str, arr: np.ndarray, n_affected: int = 0) -> None:
    vals = np.asarray(arr, dtype=np.float64).ravel()
    valid = vals[~np.isnan(vals)]
    if valid.size == 0:
        logger.warning("Stage %-32s | NO VALID DATA", name)
        return
    logger.info(
        "Stage %-32s | n=%d affected=%d | min=%.4f max=%.4f mean=%.4f std=%.4f",
        name, int(valid.size), int(n_affected),
        float(np.min(valid)), float(np.max(valid)),
        float(np.mean(valid)), float(np.std(valid)),
    )


def _spectral_energy(arr: np.ndarray) -> float:
    valid = arr[~np.isnan(arr)]
    return float(np.sum(valid ** 2)) if valid.size > 0 else 0.0


# ── IGRF ────────────────────────────────────────────────────────────────────

def _compute_igrf_total(
    lat: np.ndarray, lon: np.ndarray, decimal_yr: float
) -> Optional[np.ndarray]:
    """
    Compute IGRF-13 total field (nT) per point.
    Returns None if pyIGRF is unavailable (caller handles fallback).
    """
    try:
        import pyIGRF
        results = np.empty(len(lat), dtype=np.float64)
        for i in range(len(lat)):
            igrf = pyIGRF.igrf_value(
                float(lat[i]), float(lon[i]), 0.0, decimal_yr
            )
            # igrf_value returns (D, I, H, X, Y, Z, F); F is index 6
            results[i] = float(igrf[6])
        return results
    except Exception as exc:
        logger.critical(
            "CRITICAL: pyIGRF unavailable or failed (%s). "
            "IGRF correction will be skipped — output is NOT geophysically corrected.",
            exc,
        )
        return None


# ── Diurnal ─────────────────────────────────────────────────────────────────

def _compute_dt_median(t: np.ndarray) -> float:
    """Median sample interval in seconds."""
    if len(t) < 2:
        return 1.0
    diffs = np.diff(np.sort(t))
    pos = diffs[diffs > 0]
    return float(np.median(pos)) if pos.size > 0 else 1.0


def _diurnal_fft_fallback(
    mag: np.ndarray, t: np.ndarray, min_period_s: float = 3600.0
) -> np.ndarray:
    """
    Estimate long-period (diurnal) trend via FFT low-pass.
    Cutoff frequency = 1 / min_period_s, derived from actual sample interval.
    Returns the trend to subtract.
    """
    n = len(mag)
    valid = ~np.isnan(mag)
    if valid.sum() < 4 or n < 4:
        return np.full(n, float(np.nanmean(mag)))

    dt_median = _compute_dt_median(t)
    fc_hz = 1.0 / max(min_period_s, dt_median * 2)

    mag_filled = mag.copy()
    mag_filled[~valid] = float(np.nanmean(mag))

    spectrum = rfft(mag_filled)
    freqs = rfftfreq(n, d=dt_median)

    filt = np.zeros_like(spectrum)
    filt[freqs <= fc_hz] = spectrum[freqs <= fc_hz]

    trend = irfft(filt, n=n)
    return trend.astype(np.float64)


# ── FFT filter ──────────────────────────────────────────────────────────────

def _apply_fft_filter(
    mag: np.ndarray,
    filter_type: Optional[str],
    cutoff_low: Optional[float],
    cutoff_high: Optional[float],
    sample_spacing: float = 1.0,
) -> tuple:
    """Zero-phase FFT filter. Returns (filtered_mag, energy_report)."""
    if not filter_type:
        return mag.copy(), {}

    n = len(mag)
    valid = ~np.isnan(mag)
    mag_filled = mag.copy()
    mag_filled[~valid] = float(np.nanmean(mag[valid])) if valid.any() else 0.0

    energy_before = _spectral_energy(mag_filled)

    spectrum = rfft(mag_filled)
    freqs = rfftfreq(n, d=sample_spacing)
    filt = np.zeros(len(spectrum), dtype=complex)

    if filter_type == "lowpass" and cutoff_low:
        filt[freqs <= cutoff_low] = spectrum[freqs <= cutoff_low]
    elif filter_type == "highpass" and cutoff_high:
        filt[freqs >= cutoff_high] = spectrum[freqs >= cutoff_high]
    elif filter_type == "bandpass" and cutoff_low and cutoff_high:
        mask = (freqs >= cutoff_low) & (freqs <= cutoff_high)
        filt[mask] = spectrum[mask]
    else:
        return mag.copy(), {"warning": "Missing cutoff parameters; filter not applied."}

    filtered = irfft(filt, n=n).astype(np.float64)
    filtered[~valid] = np.nan
    energy_after = _spectral_energy(filtered[valid]) if valid.any() else 0.0

    report = {
        "filter_type": filter_type,
        "energy_before": round(energy_before, 4),
        "energy_after": round(energy_after, 4),
        "energy_ratio": round(energy_after / max(energy_before, 1e-9), 4),
    }
    return filtered, report


# ── Variogram ────────────────────────────────────────────────────────────────

def _experimental_variogram(
    x: np.ndarray, y: np.ndarray, z: np.ndarray, n_lags: int = 20
) -> tuple:
    n = len(x)
    if n > 250:
        rng = np.random.default_rng(42)
        idx = rng.choice(n, 250, replace=False)
        x, y, z = x[idx], y[idx], z[idx]
        n = 250

    dists, sqdiffs = [], []
    for i in range(n):
        for j in range(i + 1, n):
            d = math.hypot(float(x[i] - x[j]), float(y[i] - y[j]))
            sqdiffs.append(0.5 * (float(z[i]) - float(z[j])) ** 2)
            dists.append(d)

    dists = np.array(dists, dtype=np.float64)
    sqdiffs = np.array(sqdiffs, dtype=np.float64)
    max_lag = float(np.percentile(dists, 50))
    lag_edges = np.linspace(0.0, max_lag, n_lags + 1)

    h_vals, g_vals = [], []
    for i in range(n_lags):
        mask = (dists >= lag_edges[i]) & (dists < lag_edges[i + 1])
        if mask.sum() >= 3:
            h_vals.append(float(np.mean(dists[mask])))
            g_vals.append(float(np.mean(sqdiffs[mask])))

    return np.array(h_vals, dtype=np.float64), np.array(g_vals, dtype=np.float64)


def _spherical_variogram(h: np.ndarray, nugget: float, sill: float, vrange: float) -> np.ndarray:
    r = h / max(vrange, 1e-9)
    return np.where(
        h == 0, nugget,
        np.where(h >= vrange, nugget + sill,
                 nugget + sill * (1.5 * r - 0.5 * r ** 3))
    )


def _fit_variogram_model(h: np.ndarray, gamma: np.ndarray) -> dict:
    if len(h) < 3:
        return {"model": "none", "range": float(np.nanmax(h)) if len(h) else 1.0,
                "sill": float(np.nanmax(gamma)) if len(gamma) else 1.0,
                "nugget": 0.0, "fit_rmse": None}
    try:
        popt, _ = curve_fit(
            _spherical_variogram, h, gamma,
            p0=[float(gamma[0]) * 0.1, float(np.max(gamma)), float(h[len(h) // 2])],
            bounds=([0, 0, 1e-9], [np.inf, np.inf, np.inf]),
            maxfev=3000,
        )
        g_fit = _spherical_variogram(h, *popt)
        fit_rmse = float(np.sqrt(np.mean((gamma - g_fit) ** 2)))
        logger.info("Variogram: nugget=%.4f sill=%.4f range=%.4f RMSE=%.4f",
                    popt[0], popt[1], popt[2], fit_rmse)
        return {"model": "spherical", "nugget": round(float(popt[0]), 4),
                "sill": round(float(popt[1]), 4), "range": round(float(popt[2]), 4),
                "fit_rmse": round(fit_rmse, 4)}
    except Exception as exc:
        logger.warning("Variogram fit failed (%s); using defaults.", exc)
        return {"model": "fallback", "nugget": 0.0,
                "sill": float(np.nanmax(gamma)), "range": float(h[-1]), "fit_rmse": None}


# ── Derived layers ───────────────────────────────────────────────────────────

def _first_vertical_derivative_fft(
    surface: np.ndarray, dx: float = 1.0, dy: float = 1.0
) -> np.ndarray:
    s = surface.astype(np.float64)
    ny, nx = s.shape
    kx = np.fft.fftfreq(nx, d=dx) * 2 * np.pi
    ky = np.fft.fftfreq(ny, d=dy) * 2 * np.pi
    KX, KY = np.meshgrid(kx, ky)
    K = np.sqrt(KX ** 2 + KY ** 2)
    return np.real(np.fft.ifft2(np.fft.fft2(s) * K)).astype(np.float64)


def _analytic_signal_3d(
    surface: np.ndarray, dx: float = 1.0, dy: float = 1.0
) -> np.ndarray:
    s = surface.astype(np.float64)
    gx, gy = np.gradient(s, dy, dx)
    gz = _first_vertical_derivative_fft(s, dx, dy)
    return np.sqrt(gx ** 2 + gy ** 2 + gz ** 2)


def _tilt_derivative(
    surface: np.ndarray, dx: float = 1.0, dy: float = 1.0
) -> np.ndarray:
    vdr = _first_vertical_derivative_fft(surface, dx, dy)
    gx, gy = np.gradient(surface.astype(np.float64), dy, dx)
    thd = np.sqrt(gx ** 2 + gy ** 2)
    return np.arctan2(vdr, thd + 1e-10).astype(np.float64)


def _total_gradient(
    surface: np.ndarray, dx: float = 1.0, dy: float = 1.0
) -> np.ndarray:
    return _analytic_signal_3d(surface, dx, dy)


_RTP_LOW_INC_THRESHOLD = 15.0


def _rtp_fourier(
    surface: np.ndarray,
    inclination: Optional[float] = None,
    declination: Optional[float] = None,
    dx: float = 1.0,
    dy: float = 1.0,
) -> np.ndarray:
    """
    Fourier-domain RTP with zero-padding, cosine taper, ε-damping for low inc.
    Falls back to legacy mean-centering if inc/dec not provided.
    """
    s = surface.astype(np.float64)
    orig_ny, orig_nx = s.shape

    if inclination is None or declination is None:
        # Legacy fallback
        return s - float(np.nanmean(s))

    def _next_pow2(n: int) -> int:
        return int(2 ** math.ceil(math.log2(max(n, 1))))

    pad_ny = _next_pow2(orig_ny * 2)
    pad_nx = _next_pow2(orig_nx * 2)

    ty = np.hanning(orig_ny).reshape(-1, 1)
    tx = np.hanning(orig_nx).reshape(1, -1)
    taper = (ty @ tx) ** 0.5

    s_padded = np.zeros((pad_ny, pad_nx), dtype=np.float64)
    s_padded[:orig_ny, :orig_nx] = s * taper

    inc_r = math.radians(inclination)
    dec_r = math.radians(declination)
    l = math.cos(inc_r) * math.cos(dec_r)
    m = math.cos(inc_r) * math.sin(dec_r)
    n_inc = math.sin(inc_r)

    kx = np.fft.fftfreq(pad_nx, d=dx)
    ky = np.fft.fftfreq(pad_ny, d=dy)
    KX, KY = np.meshgrid(kx, ky)
    K = np.sqrt(KX ** 2 + KY ** 2)
    K_safe = np.where(K == 0, 1e-10, K)

    # ε-damping for low inclinations
    if abs(inclination) < _RTP_LOW_INC_THRESHOLD:
        epsilon = math.sin(math.radians(_RTP_LOW_INC_THRESHOLD)) ** 2
        logger.warning(
            "RTP: low inclination (%.1f°) — applying ε-damping (ε=%.4f) for stability.",
            inclination, epsilon,
        )
    else:
        epsilon = 0.0

    L = n_inc + 1j * (l * KX / K_safe + m * KY / K_safe)
    L_abs2 = np.abs(L) ** 2
    L_damp = L / np.where(L_abs2 < epsilon, epsilon, L_abs2)

    S = np.fft.fft2(s_padded)
    rtp_padded = np.real(np.fft.ifft2(S * L_damp))

    taper_safe = np.where(taper < 1e-6, 1.0, taper)
    result = rtp_padded[:orig_ny, :orig_nx] / taper_safe
    return result.astype(np.float64)


def _apply_upward_continuation(
    surface: np.ndarray, height: float, dx: float = 1.0, dy: float = 1.0
) -> np.ndarray:
    s = surface.astype(np.float64)
    ny, nx = s.shape
    kx = np.fft.fftfreq(nx, d=dx) * 2 * np.pi
    ky = np.fft.fftfreq(ny, d=dy) * 2 * np.pi
    KX, KY = np.meshgrid(kx, ky)
    K = np.sqrt(KX ** 2 + KY ** 2)
    operator = np.exp(-K * abs(height))
    return np.real(np.fft.ifft2(np.fft.fft2(s) * operator)).astype(np.float64)


def _apply_downward_continuation(
    surface: np.ndarray, height: float, dx: float = 1.0, dy: float = 1.0,
    max_gain: float = 10.0,
) -> np.ndarray:
    s = surface.astype(np.float64)
    ny, nx = s.shape
    kx = np.fft.fftfreq(nx, d=dx) * 2 * np.pi
    ky = np.fft.fftfreq(ny, d=dy) * 2 * np.pi
    KX, KY = np.meshgrid(kx, ky)
    K = np.sqrt(KX ** 2 + KY ** 2)
    operator = np.exp(K * abs(height))
    operator = np.minimum(operator, max_gain)
    logger.warning("Downward continuation applied (height=%.1f m). This is numerically unstable.", height)
    return np.real(np.fft.ifft2(np.fft.fft2(s) * operator)).astype(np.float64)


# ── Output integrity validation ─────────────────────────────────────────────

def _validate_integrity(
    surface: np.ndarray,
    mag_before: np.ndarray,
    mag_after: np.ndarray,
) -> dict:
    s = surface.ravel()
    nan_count = int(np.sum(np.isnan(s)))
    inf_count = int(np.sum(np.isinf(s)))
    issues = []

    input_std = float(np.nanstd(mag_before)) if len(mag_before) > 0 else 1.0
    output_std = float(np.nanstd(surface))

    flat_field = output_std < 0.01 * input_std
    if flat_field:
        issues.append("flat_field")

    smoothing_ratio = output_std / max(float(np.nanstd(mag_after)), 1e-9)
    over_smoothed = smoothing_ratio < 0.3
    if over_smoothed:
        issues.append("over_smoothed")

    surface_max = float(np.nanmax(np.abs(surface)))
    input_max = float(np.nanmax(np.abs(mag_before))) if len(mag_before) > 0 else 1.0
    artificial_spikes = surface_max > 5.0 * input_max
    if artificial_spikes:
        issues.append("artificial_spikes")

    if nan_count > 0:
        issues.append(f"nan_cells:{nan_count}")
    if inf_count > 0:
        issues.append(f"inf_cells:{inf_count}")

    status = "ok" if not issues else "degraded"
    return {
        "status": status,
        "issues": issues,
        "nan_count": nan_count,
        "inf_count": inf_count,
        "flat_field": flat_field,
        "over_smoothed": over_smoothed,
        "artificial_spikes": artificial_spikes,
        "smoothing_ratio": round(smoothing_ratio, 4),
        "pre_correction_std": round(float(np.nanstd(mag_before)), 4),
        "post_correction_std": round(float(np.nanstd(mag_after)), 4),
    }


def _compute_quality_score(
    integrity: dict, igrf_applied: bool, rmse: Optional[float], input_std: float
) -> float:
    score = 1.0
    for _ in integrity.get("issues", []):
        score -= 0.1
    if not igrf_applied:
        score -= 0.15
    if rmse is not None and input_std > 0:
        ratio = rmse / input_std
        if ratio > 0.5:
            score -= 0.15
        elif ratio > 0.2:
            score -= 0.05
    return round(max(0.0, min(1.0, score)), 3)


# ═══════════════════════════════════════════════════════════════════════════
# PROCESSING SERVICE CLASS
# ═══════════════════════════════════════════════════════════════════════════

class ProcessingService:
    def __init__(self, store, storage_backend) -> None:
        self._store = store
        self._storage = storage_backend

    def start_run(self, task_id: str) -> dict:
        task = self._store.get_task(task_id)
        if not task:
            raise ValueError("Task not found.")

        run = PipelineRun(
            task_id=task_id,
            status="queued",
            steps=[
                PipelineStep(name="Data loading", status="queued", detail="Waiting to start"),
                PipelineStep(name="Data cleaning", status="queued", detail="Queued"),
                PipelineStep(name="Corrections", status="queued", detail="Queued"),
                PipelineStep(name="Station grid", status="queued", detail="Queued"),
                PipelineStep(name="Modelling", status="queued", detail="Queued"),
                PipelineStep(name="Derived layers", status="queued", detail="Queued"),
                PipelineStep(name="Save results", status="queued", detail="Queued"),
            ],
        )
        payload = run.model_dump(mode="json")
        payload["logs"] = []
        persisted = self._store.create_processing_run(payload)
        self._store.update_task(
            task_id,
            {
                "processing_run_id": run.id,
                "lifecycle": "queued",
                "updated_at": utc_now(),
            },
        )
        return persisted

    def execute_run(self, run_id: str) -> dict:
        run = self._store.get_processing_run(run_id)
        if not run:
            raise ValueError("Processing run not found.")

        task = self._store.get_task(run["task_id"])
        if not task:
            raise ValueError("Task not found.")

        try:
            self._update_run(run_id, 0, "running", "Checking your uploaded survey data...")
            frame = self._load_dataframe(task)
            frame, n_removed = self._remove_coordinate_outliers(frame)
            removed_msg = f" ({n_removed} out-of-area points removed)" if n_removed > 0 else ""
            self._update_run(run_id, 0, "completed", f"{len(frame)} survey readings loaded{removed_msg}")

            self._update_run(run_id, 1, "running", "Removing duplicates and sorting data...")
            cleaned = self._clean_dataframe(frame)
            self._update_run(run_id, 1, "completed", f"{len(cleaned)} readings ready after cleaning")

            self._update_run(run_id, 2, "running", "Applying your selected magnetic corrections...")
            corrected, correction_summary = self._apply_corrections(task, cleaned)
            self._update_run(run_id, 2, "completed", correction_summary)

            config = task.get("analysis_config") or {}
            run_prediction = config.get("run_prediction", True)

            if run_prediction:
                self._update_run(run_id, 3, "running", "Preparing station data for modelling...")
                prep = self._prepare_prediction_inputs(task, corrected)
                self._update_run(run_id, 3, "completed", prep["detail"])

                self._update_run(run_id, 4, "running", "Running the magnetic field model...")
                results = self._generate_surfaces(task, prep)
                self._update_run(run_id, 4, "completed", f"Model complete - used {results['model_used']} approach")

                self._update_run(run_id, 5, "running", "Calculating derived layers...")
                add_on_payload = self._apply_add_ons(task, results)
                self._update_run(run_id, 5, "completed", add_on_payload["detail"])
            else:
                self._update_run(run_id, 3, "completed", "Prediction modelling disabled - skipped")
                self._update_run(run_id, 4, "completed", "Prediction modelling disabled - skipped")
                self._update_run(run_id, 5, "completed", "No derived layers - modelling was disabled")
                grid_x, grid_y = self._build_grid(task, corrected)
                surface = self._nearest_surface(
                    corrected["longitude"].to_numpy(),
                    corrected["latitude"].to_numpy(),
                    corrected["magnetic"].to_numpy(),
                    grid_x,
                    grid_y,
                )
                uncertainty = self._uncertainty_surface(
                    corrected["longitude"].to_numpy(),
                    corrected["latitude"].to_numpy(),
                    grid_x,
                    grid_y,
                    np.zeros_like(surface),
                )
                results = {
                    "grid_x": grid_x,
                    "grid_y": grid_y,
                    "surface": surface,
                    "uncertainty": uncertainty,
                    "model_used": "none",
                    "points": corrected[["latitude", "longitude", "magnetic"]
                        + (["__is_base_station__"] if "__is_base_station__" in corrected.columns else [])
                        + (["_line_id"] if "_line_id" in corrected.columns else [])
                    ].rename(columns={"__is_base_station__": "is_base_station", "_line_id": "line_id"}).to_dict(orient="records"),
                    "stats": {
                        "min": float(corrected["magnetic"].min()), "max": float(corrected["magnetic"].max()),
                        "mean": float(corrected["magnetic"].mean()), "std": float(corrected["magnetic"].std()),
                        "point_count": len(corrected), "anomaly_count": 0,
                    },
                    "predicted_points": [],
                }
                add_on_payload = {
                    "analytic_signal": [],
                    "first_vertical_derivative": [],
                    "horizontal_derivative": [],
                    "filtered_surface": [],
                    "emag2_residual": [],
                    "rtp_surface": [],
                    "selected_add_ons": [],
                    "detail": "No add-ons — modelling disabled",
                }
                prep = {
                    "frame": corrected,
                    "train_frame": corrected,
                    "predict_frame": pd.DataFrame({"latitude": [], "longitude": []}),
                    "grid_x": grid_x,
                    "grid_y": grid_y,
                }

            self._update_run(run_id, 6, "running", "Saving results to your project...")
            stored = self._persist_outputs(task, prep, results, add_on_payload)
            self._update_run(run_id, 6, "completed", "Saved outputs, visual assets, and grid artifacts")

            self._store.update_processing_run(
                run_id,
                {
                    "status": "completed",
                    "updated_at": utc_now(),
                },
            )
            self._store.update_task(
                task["id"],
                {
                    "lifecycle": "completed",
                    "updated_at": utc_now(),
                    "results": stored,
                },
            )
            log_event("INFO", "Processing completed", action="processing.complete", task_id=task["id"], run_id=run_id)
            return self._store.get_processing_run(run_id)
        except Exception as exc:
            self._store.update_processing_run(
                run_id,
                {
                    "status": "failed",
                    "updated_at": utc_now(),
                    "error": str(exc),
                },
            )
            self._store.update_task(
                task["id"],
                {
                    "lifecycle": "failed",
                    "updated_at": utc_now(),
                },
            )
            log_event("ERROR", "Processing failed", action="processing.failed", task_id=task["id"], run_id=run_id, error=str(exc))
            raise

    def get_run(self, run_id: str) -> dict | None:
        return self._store.get_processing_run(run_id)

    # ── Data loading (unchanged) ────────────────────────────────────────────

    def _load_dataframe(self, task: dict) -> pd.DataFrame:
        mapping = task["column_mapping"]
        frames: list[pd.DataFrame] = []
        for artifact in task.get("survey_files") or []:
            csv_text = self._storage.download_text(artifact["bucket"], artifact["object_name"])
            frame = pd.read_csv(io.StringIO(csv_text))
            missing_cols = [mapping["latitude"], mapping["longitude"]]
            if any(col not in frame.columns for col in missing_cols):
                log_event(
                    "WARNING",
                    "Survey file missing coordinate columns",
                    task_id=task.get("id"),
                    missing=missing_cols,
                    file=artifact.get("object_name"),
                )
                continue

            frame["_raw_lat"] = pd.to_numeric(frame[mapping["latitude"]], errors="coerce")
            frame["_raw_lon"] = pd.to_numeric(frame[mapping["longitude"]], errors="coerce")
            frame["magnetic"] = pd.to_numeric(frame.get(mapping["magnetic_field"], pd.Series(dtype=float)), errors="coerce")

            for col_key, dest in [("hour", "_hour"), ("minute", "_minute"), ("second", "_second")]:
                col_name = mapping.get(col_key)
                if col_name and col_name in frame.columns:
                    frame[dest] = pd.to_numeric(frame[col_name], errors="coerce")

            frame = frame.dropna(subset=["_raw_lat", "_raw_lon"]).copy()

            coord_sys = (mapping.get("coordinate_system") or "wgs84").lower()
            if coord_sys == "utm":
                from pyproj import Proj, Transformer
                utm_zone = mapping.get("utm_zone")
                utm_hemi = mapping.get("utm_hemisphere") or "N"
                if not utm_zone:
                    first_n = float(frame["_raw_lat"].iloc[0])
                    utm_zone = 32
                    utm_hemi = "N" if first_n < 5_000_000 else "S"
                south = str(utm_hemi).upper() == "S"
                utm_proj = Proj(proj="utm", zone=int(utm_zone), ellps="WGS84", south=south)
                wgs84_proj = Proj(proj="latlong", ellps="WGS84")
                transformer = Transformer.from_proj(utm_proj, wgs84_proj, always_xy=True)
                lats, lons = [], []
                for _, row in frame.iterrows():
                    try:
                        lon, lat = transformer.transform(float(row["_raw_lon"]), float(row["_raw_lat"]))
                        lats.append(lat)
                        lons.append(lon)
                    except Exception:
                        lats.append(None)
                        lons.append(None)
                frame["latitude"] = lats
                frame["longitude"] = lons
            else:
                frame["latitude"] = frame["_raw_lat"]
                frame["longitude"] = frame["_raw_lon"]

            frame = frame.dropna(subset=["latitude", "longitude"])
            if not frame.empty:
                frames.append(frame)

        if not frames:
            raise ValueError("No valid coordinate rows found in the survey file(s).")

        return pd.concat(frames, ignore_index=True)

    @staticmethod
    def _remove_coordinate_outliers(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
        original_len = len(frame)
        for col in ("latitude", "longitude"):
            if col not in frame.columns or frame.empty:
                continue
            q1 = frame[col].quantile(0.25)
            q3 = frame[col].quantile(0.75)
            iqr = q3 - q1
            if iqr == 0:
                continue
            lo = q1 - 3 * iqr
            hi = q3 + 3 * iqr
            frame = frame[(frame[col] >= lo) & (frame[col] <= hi)]
        return frame.reset_index(drop=True), original_len - len(frame)

    @staticmethod
    def _filter_predicted_to_bounds(predicted: list[dict], frame: pd.DataFrame) -> list[dict]:
        if not predicted or frame.empty:
            return predicted
        min_lat, max_lat = float(frame["latitude"].min()), float(frame["latitude"].max())
        min_lon, max_lon = float(frame["longitude"].min()), float(frame["longitude"].max())
        pad_lat = max((max_lat - min_lat) * 0.05, 0.002)
        pad_lon = max((max_lon - min_lon) * 0.05, 0.002)
        return [
            p for p in predicted
            if min_lat - pad_lat <= p.get("latitude", 0) <= max_lat + pad_lat
            and min_lon - pad_lon <= p.get("longitude", 0) <= max_lon + pad_lon
        ]

    # ── Stage 2: Data cleaning (upgraded) ───────────────────────────────────

    def _clean_dataframe(self, frame: pd.DataFrame) -> pd.DataFrame:
        cleaned = frame.copy()

        # Tolerance-based spatial deduplication
        xy = cleaned[["longitude", "latitude"]].to_numpy(dtype=np.float64)
        tol = 1e-6
        scale = 1.0 / max(tol, 1e-12)
        rounded = np.round(xy * scale).astype(np.int64)
        seen: set = set()
        keep = []
        for i, key in enumerate(map(tuple, rounded)):
            if key not in seen:
                seen.add(key)
                keep.append(i)
        n_removed = len(cleaned) - len(keep)
        if n_removed > 0:
            logger.info("Stage 2.clean: removed %d duplicate positions (tol=%.1e)", n_removed, tol)
        cleaned = cleaned.iloc[keep].reset_index(drop=True)

        # Spatial jump flagging (warn only, do not remove)
        xy2 = cleaned[["longitude", "latitude"]].to_numpy(dtype=np.float64)
        if len(xy2) >= 2:
            dists = np.linalg.norm(np.diff(xy2, axis=0), axis=1)
            pos_dists = dists[dists > 0]
            if pos_dists.size > 0:
                median_dist = float(np.median(pos_dists))
                n_jumps = int(np.sum(dists > median_dist * 10.0))
                if n_jumps > 0:
                    logger.warning(
                        "Stage 2.clean: %d unrealistic spatial jumps detected (threshold=%.4f)",
                        n_jumps, median_dist * 10.0,
                    )

        # Build time_s for time-aware corrections
        if "_hour" in cleaned.columns and "_minute" in cleaned.columns:
            _sec = cleaned["_second"].fillna(0) if "_second" in cleaned.columns else 0
            cleaned["time_s"] = (
                cleaned["_hour"].fillna(0) * 3600.0
                + cleaned["_minute"].fillna(0) * 60.0
                + _sec
            ).astype(np.float64)
            cleaned = cleaned.sort_values("time_s", na_position="last").reset_index(drop=True)
        else:
            cleaned["time_s"] = np.arange(len(cleaned), dtype=np.float64)

        _proc_log("2.clean/magnetic", cleaned["magnetic"].to_numpy(dtype=np.float64))
        return cleaned

    # ── Stage 3: Corrections (upgraded) ─────────────────────────────────────

    def _apply_corrections(self, task: dict, frame: pd.DataFrame) -> tuple[pd.DataFrame, str]:
        """
        Apply corrections in physical order:
        spike → IGRF → diurnal → lag → heading → FFT filter
        Returns (corrected_df, summary_string).
        """
        out = frame.copy()
        selected = {item.lower() for item in (task.get("analysis_config", {}).get("corrections") or [])}
        config = task.get("analysis_config", {})
        notes: list[str] = []
        igrf_applied = False

        mag_before = out["magnetic"].to_numpy(dtype=np.float64).copy()

        # Compute decimal year from time columns or current year
        decimal_yr = float(datetime.now(timezone.utc).year)
        if "time_s" in out.columns and "_hour" in out.columns:
            try:
                now = datetime.now(timezone.utc)
                yr = now.year
                start = datetime(yr, 1, 1, tzinfo=timezone.utc)
                end = datetime(yr + 1, 1, 1, tzinfo=timezone.utc)
                decimal_yr = yr + (now - start).total_seconds() / (end - start).total_seconds()
            except Exception:
                pass

        # ── 3.0 Spike removal ───────────────────────────────────────────────
        if "filtering" in selected or True:  # always run spike check
            out, spike_note = self._apply_spike_removal(out)
            if spike_note:
                notes.append(spike_note)

        # ── 3.1 IGRF correction ──────────────────────────────────────────────
        if "igrf" in selected:
            lat = out["latitude"].to_numpy(dtype=np.float64)
            lon = out["longitude"].to_numpy(dtype=np.float64)
            igrf_vals = _compute_igrf_total(lat, lon, decimal_yr)
            if igrf_vals is not None:
                valid_igrf = ~np.isnan(igrf_vals)
                if valid_igrf.sum() > 0:
                    igrf_mean = float(np.nanmean(igrf_vals))
                    out["magnetic"] = out["magnetic"] - igrf_vals
                    igrf_applied = True
                    logger.info(
                        "IGRF applied: mean_field=%.2f nT, min=%.2f, max=%.2f",
                        igrf_mean, float(np.nanmin(igrf_vals)), float(np.nanmax(igrf_vals)),
                    )
                    notes.append(f"IGRF-13 correction (mean ref={igrf_mean:.1f} nT)")
                    _proc_log("3.1.igrf", out["magnetic"].to_numpy(dtype=np.float64))
            else:
                logger.critical(
                    "IGRF correction requested but pyIGRF unavailable. "
                    "Output is NOT geophysically corrected. Run status: incomplete_physical_model."
                )
                notes.append("IGRF FAILED — pyIGRF unavailable (output not geophysically corrected)")

        # ── 3.2 Diurnal correction ───────────────────────────────────────────
        if "diurnal" in selected:
            out, diurnal_note = self._apply_diurnal_correction(out, task)
            notes.append(diurnal_note)

        # ── 3.3 Lag correction ───────────────────────────────────────────────
        if "lag" in selected and len(out) > 3:
            out, lag_note = self._apply_lag_correction(out)
            notes.append(lag_note)

        # ── 3.4 Heading correction ───────────────────────────────────────────
        if "heading" in selected and len(out) > 3:
            out, heading_note = self._apply_heading_correction(out)
            notes.append(heading_note)

        # ── 3.5 FFT filter (last) ────────────────────────────────────────────
        if "filtering" in selected:
            filter_type = config.get("filter_type", "")
            # Map UI filter names to FFT types
            fft_type_map = {"low-pass": "lowpass", "high-pass": "highpass", "band-pass": "bandpass"}
            fft_type = fft_type_map.get(filter_type, filter_type)
            if fft_type in ("lowpass", "highpass", "bandpass"):
                mag_arr = out["magnetic"].to_numpy(dtype=np.float64)
                t_arr = out["time_s"].to_numpy(dtype=np.float64) if "time_s" in out.columns else np.arange(len(out), dtype=np.float64)
                dt = _compute_dt_median(t_arr)
                filtered, energy_rep = _apply_fft_filter(
                    mag_arr, fft_type,
                    config.get("fft_cutoff_low"),
                    config.get("fft_cutoff_high"),
                    sample_spacing=dt,
                )
                out["magnetic"] = filtered
                energy_ratio = energy_rep.get("energy_ratio", 1.0)
                notes.append(f"{filter_type} FFT filter (energy retained: {energy_ratio:.1%})")
                _proc_log(f"3.5.fft_{fft_type}", out["magnetic"].to_numpy(dtype=np.float64))

        mag_after = out["magnetic"].to_numpy(dtype=np.float64)
        _proc_log("3.final", mag_after)
        logger.info("Corrections complete: igrf_applied=%s, steps=%s", igrf_applied, notes)

        detail = ", ".join(notes) if notes else "No additional corrections were requested"
        return out, detail

    def _apply_spike_removal(self, frame: pd.DataFrame) -> tuple[pd.DataFrame, str]:
        """
        Triple-domain spike removal: global z-score AND spatial AND temporal.
        Only removes points flagged by all three checks.
        """
        out = frame.copy()
        mag = out["magnetic"].to_numpy(dtype=np.float64)
        valid = ~np.isnan(mag)
        if valid.sum() < 8:
            return out, ""

        mu = float(np.nanmean(mag))
        sigma = float(np.nanstd(mag)) + 1e-9
        z_scores = np.abs((mag - mu) / sigma)
        stat_extreme = (z_scores > 3.5) & valid
        n_stat = int(stat_extreme.sum())

        if n_stat == 0:
            return out, ""

        candidate_positions = np.where(stat_extreme)[0]
        spikes = stat_extreme.copy()

        try:
            lon = out["longitude"].to_numpy(dtype=np.float64)
            lat = out["latitude"].to_numpy(dtype=np.float64)
            pts = np.column_stack([lon[valid], lat[valid]])
            tree = KDTree(pts)
            all_pts = np.column_stack([lon, lat])
            k = min(8, valid.sum() - 1)
            dist, nn_idx_raw = tree.query(all_pts[candidate_positions], k=k + 1)

            t = out["time_s"].to_numpy(dtype=np.float64) if "time_s" in out.columns else np.arange(len(out), dtype=np.float64)
            t_sort_idx = np.argsort(t)
            t_sorted_pos = {int(orig_i): int(sorted_pos)
                            for sorted_pos, orig_i in enumerate(t_sort_idx)}

            valid_indices = np.where(valid)[0]
            for ci, ni_row in zip(candidate_positions, nn_idx_raw):
                # Spatial check
                neighbours = valid_indices[ni_row[ni_row < len(valid_indices)][:k]]
                nb_mag = mag[neighbours][~np.isnan(mag[neighbours])]
                if len(nb_mag) >= 2:
                    local_std = float(np.std(nb_mag)) + 1e-9
                    spatial_z = abs(float(mag[ci]) - float(np.median(nb_mag))) / local_std
                    spatially_bad = spatial_z >= 2.0
                else:
                    spatially_bad = True

                # Temporal check
                sorted_pos = t_sorted_pos.get(int(ci))
                temporally_bad = True
                if sorted_pos is not None:
                    t_nb = []
                    for offset in [-2, -1, 1, 2]:
                        adj = sorted_pos + offset
                        if 0 <= adj < len(t_sort_idx):
                            orig = int(t_sort_idx[adj])
                            if not np.isnan(mag[orig]):
                                t_nb.append(float(mag[orig]))
                    if len(t_nb) >= 2:
                        t_std = float(np.std(t_nb)) + 1e-9
                        temporal_z = abs(float(mag[ci]) - float(np.median(t_nb))) / t_std
                        temporally_bad = temporal_z >= 2.0

                if not (spatially_bad and temporally_bad):
                    spikes[ci] = False
        except Exception as exc:
            logger.debug("Dual-domain spike check error (%s); using z-score only.", exc)
            spikes = stat_extreme

        n_removed = int(spikes.sum())
        n_preserved = n_stat - n_removed
        if n_removed > 0:
            out.loc[spikes, "magnetic"] = float(np.nanmedian(mag[valid]))

        _proc_log("3.0.spike", out["magnetic"].to_numpy(dtype=np.float64), n_removed)
        logger.info(
            "Spike removal: %d global candidates | %d removed (space+time) | %d preserved as anomalies",
            n_stat, n_removed, n_preserved,
        )
        note = f"spike removal ({n_removed} removed, {n_preserved} real anomalies preserved)" if n_removed > 0 else ""
        return out, note

    def _apply_diurnal_correction(self, frame: pd.DataFrame, task: dict) -> tuple[pd.DataFrame, str]:
        """CubicSpline base-station correction; FFT physical fallback."""
        out = frame.copy()
        bs_col = "__is_base_station__"
        has_bs = bs_col in frame.columns and frame[bs_col].sum() > 0
        has_time = "time_s" in frame.columns

        if has_bs and has_time:
            bs = out[out[bs_col] == 1].dropna(subset=["time_s", "magnetic"])
            survey = out[out[bs_col] != 1].copy()
            if not bs.empty and not survey.empty:
                bs_sorted = bs.sort_values("time_s")
                t_bs = bs_sorted["time_s"].to_numpy(dtype=np.float64)
                m_bs = bs_sorted["magnetic"].to_numpy(dtype=np.float64)
                try:
                    cs = CubicSpline(t_bs, m_bs, extrapolate=True)
                    diurnal_at_survey = cs(survey["time_s"].fillna(t_bs[0]).to_numpy(dtype=np.float64))
                except Exception:
                    diurnal_at_survey = np.interp(
                        survey["time_s"].fillna(t_bs[0]).to_numpy(dtype=np.float64),
                        t_bs, m_bs,
                    )
                bs_mean = float(np.mean(m_bs))
                survey = survey.copy()
                survey["magnetic"] = survey["magnetic"] - diurnal_at_survey + bs_mean
                out = pd.concat([bs, survey]).sort_values("time_s").reset_index(drop=True)
                _proc_log("3.2.diurnal", out["magnetic"].to_numpy(dtype=np.float64))
                return out, "diurnal correction via base station CubicSpline"

        # FFT physical fallback
        if has_time:
            mag = out["magnetic"].to_numpy(dtype=np.float64)
            t = out["time_s"].to_numpy(dtype=np.float64)
            trend = _diurnal_fft_fallback(mag, t, min_period_s=3600.0)
            trend_mean = float(np.nanmean(trend))
            out["magnetic"] = out["magnetic"] - trend + trend_mean
            _proc_log("3.2.diurnal_fft", out["magnetic"].to_numpy(dtype=np.float64))
            return out, "diurnal trend removal via FFT low-pass (physical timescale, no base station)"

        # Last resort: median normalisation
        out["magnetic"] = out["magnetic"] - out["magnetic"].median()
        return out, "diurnal normalisation (median, no time data)"

    def _apply_lag_correction(self, frame: pd.DataFrame) -> tuple[pd.DataFrame, str]:
        """Cross-correlation lag estimation using best-quality flight lines."""
        out = frame.copy()
        if "time_s" not in out.columns or "_line_id" not in out.columns:
            # Fallback: interpolation-based shift of 0
            return out, "lag correction skipped (no time or line data)"

        try:
            lines = out["_line_id"].unique()
            best_line = None
            best_score = -1.0
            for ln in lines:
                mask = out["_line_id"] == ln
                sub = out[mask]["magnetic"].dropna()
                n_valid = len(sub)
                n_total = mask.sum()
                score = n_valid * (n_valid / max(n_total, 1))
                if score > best_score:
                    best_score = score
                    best_line = ln

            if best_line is None or len(lines) < 2:
                return out, "lag correction skipped (insufficient lines)"

            ref_line = out[out["_line_id"] == best_line]["magnetic"].dropna().to_numpy(dtype=np.float64)
            # Pick second best line
            lines_other = [l for l in lines if l != best_line]
            other_line = out[out["_line_id"] == lines_other[0]]["magnetic"].dropna().to_numpy(dtype=np.float64)

            min_len = min(len(ref_line), len(other_line), 500)
            a = ref_line[:min_len]
            b = other_line[:min_len]

            a_n = (a - np.mean(a)) / (np.std(a) + 1e-9)
            b_n = (b - np.mean(b)) / (np.std(b) + 1e-9)
            corr = correlate(a_n, b_n, mode="full")
            lags = np.arange(-(len(b_n) - 1), len(a_n))
            peak_idx = int(np.argmax(np.abs(corr)))
            lag = int(lags[peak_idx])
            peak_val = float(corr[peak_idx])
            confidence = abs(peak_val) / (len(a_n) + 1e-9)

            # Reject unrealistic lag
            if abs(lag) > 15:
                logger.warning("Lag %d samples exceeds threshold (15); skipping lag correction.", lag)
                return out, f"lag correction skipped (estimated lag {lag} samples exceeds threshold)"

            # Apply via interpolation shift
            if lag != 0 and "time_s" in out.columns:
                t = out["time_s"].to_numpy(dtype=np.float64)
                mag = out["magnetic"].to_numpy(dtype=np.float64)
                valid = ~np.isnan(mag)
                if valid.sum() > 3:
                    t_shift = t + lag * _compute_dt_median(t[valid])
                    interp_fn = interp1d(t[valid], mag[valid], bounds_error=False, fill_value="extrapolate")
                    out["magnetic"] = interp_fn(t_shift)
                    _proc_log("3.3.lag", out["magnetic"].to_numpy(dtype=np.float64))

            return out, f"lag correction ({lag} samples, confidence={confidence:.3f})"
        except Exception as exc:
            logger.warning("Lag correction failed (%s); skipping.", exc)
            return out, "lag correction skipped (error)"

    def _apply_heading_correction(self, frame: pd.DataFrame) -> tuple[pd.DataFrame, str]:
        """Adaptive equal-count bin heading bias correction."""
        out = frame.copy()
        lon = out["longitude"].to_numpy(dtype=np.float64)
        lat = out["latitude"].to_numpy(dtype=np.float64)
        mag = out["magnetic"].to_numpy(dtype=np.float64)

        if len(lon) < 4:
            return out, "heading correction skipped (insufficient points)"

        dx = np.diff(lon, prepend=lon[0])
        dy = np.diff(lat, prepend=lat[0])
        heading = np.arctan2(dy, dx + 1e-12)

        n_bins = max(4, min(16, int(math.sqrt(len(heading)))))
        percentiles = np.linspace(0, 100, n_bins + 1)
        bin_edges = np.percentile(heading, percentiles)
        bin_edges[-1] += 1e-9

        corrected_mag = mag.copy()
        for i in range(n_bins):
            mask = (heading >= bin_edges[i]) & (heading < bin_edges[i + 1])
            if mask.sum() >= 3:
                bin_bias = float(np.nanmean(mag[mask]))
                overall_mean = float(np.nanmean(mag))
                corrected_mag[mask] = mag[mask] - (bin_bias - overall_mean)

        out["magnetic"] = corrected_mag
        _proc_log("3.4.heading", out["magnetic"].to_numpy(dtype=np.float64))
        return out, f"heading correction ({n_bins} adaptive bins)"

    # ── Stage 4: Grid prep (unchanged) ──────────────────────────────────────

    def _prepare_prediction_inputs(self, task: dict, frame: pd.DataFrame) -> dict:
        grid_x, grid_y = self._build_grid(task, frame)
        scenario = (task.get("scenario") or "explicit").lower()

        if scenario == "explicit":
            has_mag = frame["magnetic"].notna()
            train = frame[has_mag].dropna(subset=["magnetic"]).reset_index(drop=True)
            predict = frame[~has_mag][["latitude", "longitude"]].reset_index(drop=True)
            if train.empty:
                raise ValueError("No rows with magnetic field values found for training.")
            if predict.empty:
                n = max(1, int(len(train) * 0.2))
                predict = train.tail(n)[["latitude", "longitude"]].reset_index(drop=True)
                train = train.iloc[: len(train) - n].reset_index(drop=True)
            detail = f"Explicit: {len(train)} measured stations train the model, predicting at {len(predict)} unmeasured locations"
        else:
            # Sparse: all rows with magnetic values train the model
            train = frame.dropna(subset=["magnetic"]).reset_index(drop=True)
            if train.empty:
                raise ValueError("No rows with magnetic field values found.")

            predicted_traverses = task.get("predicted_traverses") or []
            if predicted_traverses:
                # User-defined predicted traverses: build exact prediction points
                import math
                predict_rows = []
                meas_lats = train["latitude"].tolist()
                meas_lons = train["longitude"].tolist()
                lat_range = max(meas_lats) - min(meas_lats)
                lon_range = max(meas_lons) - min(meas_lons)

                for tidx, trav in enumerate(predicted_traverses):
                    ttype = trav.get("type", "offset")
                    spacing_val = float(trav.get("spacing") or 10)
                    spacing_unit = (trav.get("spacing_unit") or "Metres").lower()
                    spacing_m = spacing_val * (1000 if "kilo" in spacing_unit else 0.3048 if "feet" in spacing_unit else 1)
                    spacing_deg = max(spacing_m / 111_320, 0.000001)
                    tol = max(spacing_deg * 3, 0.001)

                    groups = {}
                    for _, row in train.iterrows():
                        k = round(float(row["latitude"]) / tol) if lon_range >= lat_range else round(float(row["longitude"]) / tol)
                        groups.setdefault(k, []).append((float(row["latitude"]), float(row["longitude"])))

                    if ttype == "infill":
                        for pts in groups.values():
                            if len(pts) < 2: continue
                            if lon_range >= lat_range:
                                pts.sort(key=lambda p: p[1])
                                lat_m = sum(p[0] for p in pts) / len(pts)
                                lons_new = np.arange(pts[0][1], pts[-1][1] + spacing_deg * 0.5, spacing_deg)
                                for lon in lons_new:
                                    predict_rows.append({"latitude": lat_m, "longitude": float(lon)})
                            else:
                                pts.sort(key=lambda p: p[0])
                                lon_m = sum(p[1] for p in pts) / len(pts)
                                lats_new = np.arange(pts[0][0], pts[-1][0] + spacing_deg * 0.5, spacing_deg)
                                for lat in lats_new:
                                    predict_rows.append({"latitude": float(lat), "longitude": lon_m})
                    else:
                        distance_val = float(trav.get("distance") or 50)
                        distance_unit = (trav.get("distance_unit") or "Metres").lower()
                        distance_m = distance_val * (1000 if "kilo" in distance_unit else 0.3048 if "feet" in distance_unit else 1)
                        bearing_rad = math.radians(float(trav.get("direction") or 90))
                        lat_mid = sum(meas_lats) / len(meas_lats)
                        cos_lat = max(abs(math.cos(math.radians(lat_mid))), 1e-6)
                        dlat = (distance_m / 111_320) * math.cos(bearing_rad)
                        dlon = (distance_m / 111_320) * math.sin(bearing_rad) / cos_lat
                        for pts in groups.values():
                            if len(pts) < 2: continue
                            if lon_range >= lat_range:
                                pts.sort(key=lambda p: p[1])
                                lat_m = sum(p[0] for p in pts) / len(pts) + dlat
                                lons_new = np.arange(pts[0][1] + dlon, pts[-1][1] + dlon + spacing_deg * 0.5, spacing_deg)
                                for lon in lons_new:
                                    predict_rows.append({"latitude": float(lat_m), "longitude": float(lon)})
                            else:
                                pts.sort(key=lambda p: p[0])
                                lon_m = sum(p[1] for p in pts) / len(pts) + dlon
                                lats_new = np.arange(pts[0][0] + dlat, pts[-1][0] + dlat + spacing_deg * 0.5, spacing_deg)
                                for lat in lats_new:
                                    predict_rows.append({"latitude": float(lat), "longitude": float(lon_m)})

                predict = pd.DataFrame(predict_rows) if predict_rows else pd.DataFrame({"latitude": [], "longitude": []})
                detail = f"Sparse: {len(train)} measured stations, {len(predicted_traverses)} predicted traverse(s), {len(predict)} predicted points"
            else:
                # Legacy: use grid
                grid_x, grid_y = self._build_grid(task, train)
                predict = pd.DataFrame({"longitude": grid_x.ravel(), "latitude": grid_y.ravel()})
                detail = f"Sparse: {len(train)} measured stations, predicting at {len(predict)} grid nodes"

        return {
            "frame": train,
            "train_frame": train,
            "predict_frame": predict,
            "grid_x": grid_x,
            "grid_y": grid_y,
            "detail": detail,
            "scenario": scenario,
        }

    def _build_grid(self, task: dict, frame: pd.DataFrame):
        spacing_value = float(task.get("station_spacing") or 20)
        spacing_unit = (task.get("station_spacing_unit") or "Metres").lower()
        spacing_metres = spacing_value * (1000 if "kilo" in spacing_unit else 0.3048 if "feet" in spacing_unit else 1)
        spacing_degrees = max(spacing_metres / 111_320, 0.0002)

        lon_min, lon_max = frame["longitude"].min(), frame["longitude"].max()
        lat_min, lat_max = frame["latitude"].min(), frame["latitude"].max()

        scenario = (task.get("scenario") or "explicit").lower()
        if scenario == "sparse":
            lon_range_m = (lon_max - lon_min) * 111_320
            lat_range_m = (lat_max - lat_min) * 111_320
            traverse_length_m = max(float(np.sqrt(lon_range_m**2 + lat_range_m**2)), 1.0)
            line_interp = task.get("line_interpolation", True)
            if not line_interp:
                grid_rows = int(task.get("grid_rows") or 0)
                grid_cols = int(task.get("grid_cols") or 0)
                if grid_rows >= 2 and grid_cols >= 2:
                    x_points = min(max(grid_cols, 2), 80)
                    y_points = min(max(grid_rows, 2), 80)
                else:
                    x_points = min(max(int(((lon_max - lon_min) / spacing_degrees) + 1), 25), 80)
                    y_points = min(max(int(((lat_max - lat_min) / spacing_degrees) + 1), 25), 80)
                x_axis = np.linspace(lon_min, lon_max, x_points)
                y_axis = np.linspace(lat_min, lat_max, y_points)
                return np.meshgrid(x_axis, y_axis)
            if spacing_metres > traverse_length_m:
                raise ValueError(
                    f"Station spacing ({spacing_value} {spacing_unit}) exceeds the survey traverse length "
                    f"({traverse_length_m:.0f} m). Enter a spacing between 1 m and {traverse_length_m:.0f} m."
                )
            if spacing_metres < 1.0:
                raise ValueError("Station spacing must be at least 1 metre.")
            lon_range = lon_max - lon_min
            lat_range = lat_max - lat_min
            if lon_range >= lat_range:
                group_col = "latitude"
                line_col = "longitude"
                line_min, line_max = lon_min, lon_max
            else:
                group_col = "longitude"
                line_col = "latitude"
                line_min, line_max = lat_min, lat_max

            group_vals = frame[group_col].values
            sorted_groups = np.sort(np.unique(np.round(group_vals / (spacing_degrees * 2)) * (spacing_degrees * 2)))

            pred_lons, pred_lats = [], []
            for g in sorted_groups:
                mask = np.abs(group_vals - g) <= spacing_degrees * 3
                if mask.sum() < 2:
                    continue
                trav = frame[mask]
                line_start = trav[line_col].min()
                line_end = trav[line_col].max()
                n_pts = max(int((line_end - line_start) / spacing_degrees) + 1, 2)
                pts = np.linspace(line_start, line_end, n_pts)
                for p in pts:
                    if group_col == "latitude":
                        pred_lats.append(g); pred_lons.append(p)
                    else:
                        pred_lats.append(p); pred_lons.append(g)

            if not pred_lons:
                x_pts = min(max(int((lon_max - lon_min) / spacing_degrees + 1), 25), 80)
                y_pts = min(max(int((lat_max - lat_min) / spacing_degrees + 1), 25), 80)
                return np.meshgrid(np.linspace(lon_min, lon_max, x_pts), np.linspace(lat_min, lat_max, y_pts))

            pred_lons_arr = np.array(pred_lons)
            pred_lats_arr = np.array(pred_lats)
            return pred_lons_arr.reshape(1, -1), pred_lats_arr.reshape(1, -1)
        else:
            x_points = min(max(int(((lon_max - lon_min) / spacing_degrees) + 1), 25), 80)
            y_points = min(max(int(((lat_max - lat_min) / spacing_degrees) + 1), 25), 80)
            x_axis = np.linspace(lon_min, lon_max, x_points)
            y_axis = np.linspace(lat_min, lat_max, y_points)
            return np.meshgrid(x_axis, y_axis)

    # ── Stage 5: Modelling (upgraded) ───────────────────────────────────────

    def _generate_surfaces(self, task: dict, prep: dict) -> dict:
        train = prep["train_frame"]
        bs_col = "__is_base_station__"
        if bs_col in train.columns:
            train = train[train[bs_col] != 1].copy()
        x = train["longitude"].to_numpy(dtype=np.float64)
        y = train["latitude"].to_numpy(dtype=np.float64)
        z = train["magnetic"].to_numpy(dtype=np.float64)
        grid_x = prep["grid_x"]
        grid_y = prep["grid_y"]

        analysis = task.get("analysis_config", {})
        requested_model = (analysis.get("model") or "Machine learning").lower()

        kriging_surface, kriging_variance = self._krige(x, y, z, grid_x, grid_y)
        ml_surface, rf_variance = self._rf_surface(x, y, z, grid_x, grid_y)

        if "kriging" in requested_model:
            surface = kriging_surface
            model_used = "kriging"
            variance = kriging_variance
        elif "hybrid" in requested_model:
            surface = (kriging_surface + ml_surface) / 2.0
            model_used = "hybrid"
            variance = kriging_variance
        else:
            surface = ml_surface
            model_used = "machine_learning"
            variance = kriging_variance

        uncertainty = self._uncertainty_surface(x, y, grid_x, grid_y, variance, rf_variance)
        anomaly_threshold = float(np.nanmean(surface) + np.nanstd(surface))
        anomaly_mask = surface >= anomaly_threshold
        scenario = (task.get("scenario") or "explicit").lower()

        result = {
            "grid_x": grid_x,
            "grid_y": grid_y,
            "surface": surface,
            "uncertainty": uncertainty,
            "model_used": model_used,
            "rf_variance": rf_variance,
            "points": prep["frame"][["latitude", "longitude", "magnetic"]
                + (["__is_base_station__"] if "__is_base_station__" in prep["frame"].columns else [])
                + (["_line_id"] if "_line_id" in prep["frame"].columns else [])
            ].rename(columns={"__is_base_station__": "is_base_station", "_line_id": "line_id"}).to_dict(orient="records"),
            "stats": {
                "min": float(np.nanmin(surface)),
                "max": float(np.nanmax(surface)),
                "mean": float(np.nanmean(surface)),
                "std": float(np.nanstd(surface)),
                "point_count": int(len(prep["frame"])),
                "anomaly_count": int(np.count_nonzero(anomaly_mask)),
            },
        }
        if scenario == "sparse":
            result["predicted_points"] = prep["predict_frame"][["latitude", "longitude"]].head(600).to_dict(orient="records")
        else:
            result["predicted_points"] = []
        result["predicted_points"] = self._filter_predicted_to_bounds(result["predicted_points"], prep["frame"])
        _proc_log("5.modelling/surface", surface)
        return result

    def _krige(self, x, y, z, grid_x, grid_y):
        """
        Variogram-informed RBFInterpolator (thin-plate spline) with pykrige fallback.
        """
        if len(z) < 4:
            grid = np.full(grid_x.shape, float(np.mean(z)))
            return grid, np.zeros(grid_x.shape)

        # Attempt variogram-informed RBF
        try:
            h_exp, g_exp = _experimental_variogram(x, y, z)
            vario = _fit_variogram_model(h_exp, g_exp) if len(h_exp) >= 3 else {}
            eps = vario.get("range", 0)
            if eps and eps > 0:
                rbf = RBFInterpolator(
                    np.column_stack([x, y]), z,
                    kernel="thin_plate_spline", epsilon=float(eps),
                )
                pts = np.column_stack([grid_x.ravel(), grid_y.ravel()])
                surface = rbf(pts).reshape(grid_x.shape).astype(np.float64)
                variance = np.zeros(grid_x.shape, dtype=np.float64)
                return surface, variance
        except Exception as exc:
            logger.debug("Variogram RBF failed (%s); falling back to pykrige.", exc)

        # pykrige fallback
        try:
            from pykrige.ok import OrdinaryKriging
            ok = OrdinaryKriging(x, y, z, variogram_model="spherical", verbose=False, enable_plotting=False)
            grid, variance = ok.execute("grid", grid_x[0, :], grid_y[:, 0])
            return np.asarray(grid, dtype=np.float64), np.asarray(variance, dtype=np.float64)
        except Exception:
            pass

        # griddata fallback
        res = griddata((x, y), z, (grid_x, grid_y), method="cubic")
        if np.isnan(res).any():
            res2 = griddata((x, y), z, (grid_x, grid_y), method="linear")
            res = np.where(np.isnan(res), res2, res)
        res = np.where(np.isnan(res), float(np.nanmean(z)), res).astype(np.float64)
        return res, np.zeros(grid_x.shape, dtype=np.float64)

    def _rf_surface(self, x, y, z, grid_x, grid_y):
        """
        Random Forest surface with augmented features and ensemble variance.
        Returns (surface, rf_variance_surface).
        """
        if len(z) < 4:
            flat = np.full(grid_x.shape, float(np.mean(z)), dtype=np.float64)
            return flat, np.zeros(grid_x.shape, dtype=np.float64)

        # Augmented features: x, y, mean-NN distance, local density
        tr_tree = KDTree(np.column_stack([x, y]))

        def _augment(fx, fy):
            base = np.column_stack([fx, fy])
            try:
                k = min(5, len(x) - 1)
                if k < 1:
                    return base
                pts = np.column_stack([fx, fy])
                dist, _ = tr_tree.query(pts, k=k + 1)
                mean_nn = np.mean(dist[:, 1:k + 1], axis=1).reshape(-1, 1)
                radius = 2.0 * float(np.median(mean_nn)) + 1e-9
                counts = np.array(tr_tree.query_ball_point(pts, r=radius, return_length=True), dtype=np.float64).reshape(-1, 1)
                return np.column_stack([base, mean_nn, counts])
            except Exception:
                return base

        feat_tr = _augment(x, y)
        scaler = StandardScaler()
        feat_tr_n = scaler.fit_transform(feat_tr)

        rf = RandomForestRegressor(n_estimators=120, random_state=7, n_jobs=-1)
        rf.fit(feat_tr_n, z)

        feat_pred = _augment(grid_x.ravel(), grid_y.ravel())
        feat_pred_n = scaler.transform(feat_pred)

        tree_preds = np.array([tree.predict(feat_pred_n) for tree in rf.estimators_])
        pred_mean = tree_preds.mean(axis=0).reshape(grid_x.shape).astype(np.float64)
        pred_var = tree_preds.var(axis=0).reshape(grid_x.shape).astype(np.float64)

        return pred_mean, pred_var

    def _xgboost_surface(self, x, y, z, grid_x, grid_y):
        """XGBoost surface (kept for compatibility; RF used by default in _generate_surfaces)."""
        from xgboost import XGBRegressor
        if len(z) < 4:
            return np.full(grid_x.shape, float(np.mean(z)))
        model = XGBRegressor(
            n_estimators=240, max_depth=5, learning_rate=0.06,
            subsample=0.9, colsample_bytree=0.9,
            objective="reg:squarederror", random_state=42,
        )
        model.fit(np.column_stack([x, y]), z)
        predictions = model.predict(np.column_stack([grid_x.ravel(), grid_y.ravel()]))
        return predictions.reshape(grid_x.shape)

    def _nearest_surface(self, x, y, z, grid_x, grid_y):
        from scipy.spatial import cKDTree
        if len(z) == 0:
            return np.zeros_like(grid_x)
        tree = cKDTree(np.column_stack([x, y]))
        _, idx = tree.query(np.column_stack([grid_x.ravel(), grid_y.ravel()]), k=1)
        return z[idx].reshape(grid_x.shape)

    def _uncertainty_surface(self, x, y, grid_x, grid_y, variance, rf_variance=None):
        """
        Combined uncertainty: RF ensemble variance (primary) + distance-weighted kriging variance.
        """
        from scipy.spatial import cKDTree
        tree = cKDTree(np.column_stack([x, y]))
        distance, _ = tree.query(np.column_stack([grid_x.ravel(), grid_y.ravel()]), k=1)
        dist_surface = distance.reshape(grid_x.shape)
        dist_norm = dist_surface / max(float(np.nanmax(dist_surface)), 1e-6)
        variance_norm = variance / max(float(np.nanmax(variance)), 1e-6)
        base_unc = ((dist_norm + variance_norm) / 2.0) * 100.0

        if rf_variance is not None and rf_variance.shape == grid_x.shape:
            rf_norm = rf_variance / max(float(np.nanmax(rf_variance)), 1e-6)
            combined = np.sqrt(base_unc ** 2 + (rf_norm * 100.0) ** 2)
            logger.info("Uncertainty: combined RF variance + distance/kriging variance.")
            return combined
        return base_unc

    # ── Stage 6: Derived layers (upgraded) ──────────────────────────────────

    def _apply_add_ons(self, task: dict, results: dict) -> dict:
        surface = results["surface"]
        rf_variance = results.get("rf_variance")
        add_ons = (task.get("analysis_config") or {}).get("add_ons") or []
        selected = set(add_ons)
        detail_items: list[str] = []

        # Determine pixel spacing from grid
        grid_x = results.get("grid_x")
        if grid_x is not None and grid_x.ndim == 2 and grid_x.shape[1] > 1:
            dx = float(np.abs(np.mean(np.diff(grid_x[0, :]))))
            dy = float(np.abs(np.mean(np.diff(results["grid_y"][:, 0])))) if results["grid_y"].shape[0] > 1 else dx
        else:
            dx = dy = 1.0
        dx = max(dx, 1e-9)
        dy = max(dy, 1e-9)

        # ── Analytic signal (3D, Fourier VDR) ───────────────────────────────
        if surface.ndim == 2 and surface.shape[0] > 1 and surface.shape[1] > 1:
            analytic = _analytic_signal_3d(surface, dx, dy)
            gx, gy = np.gradient(surface.astype(np.float64), dy, dx)
            fvd = _first_vertical_derivative_fft(surface, dx, dy)
            horizontal_derivative = np.sqrt(gx ** 2 + gy ** 2)
        else:
            # Along-line fallback
            s1d = surface.ravel()
            grad = np.gradient(s1d)
            analytic = np.abs(grad).reshape(surface.shape)
            fvd = np.gradient(grad).reshape(surface.shape)
            horizontal_derivative = np.abs(grad).reshape(surface.shape)

        # ── RTP (Fourier domain, ε-damped) ───────────────────────────────────
        config = task.get("analysis_config") or {}
        rtp_inc = config.get("rtp_inclination")
        rtp_dec = config.get("rtp_declination")
        if surface.ndim == 2 and surface.shape[0] > 1 and surface.shape[1] > 1:
            rtp_surface = _rtp_fourier(surface, rtp_inc, rtp_dec, dx, dy)
        else:
            rtp_surface = surface - float(np.nanmean(surface))

        # ── Tilt derivative ───────────────────────────────────────────────────
        if surface.ndim == 2 and surface.shape[0] > 1 and surface.shape[1] > 1:
            tilt = _tilt_derivative(surface, dx, dy)
            total_grad = _total_gradient(surface, dx, dy)
        else:
            tilt = np.zeros_like(surface)
            total_grad = analytic

        # ── EMAG2 regional residual (Gaussian separation) ────────────────────
        from scipy.ndimage import gaussian_filter
        sigma = min(5.0, max(surface.shape) / 4.0) if surface.size > 1 else 0.0
        emag2_residual = surface - gaussian_filter(surface, sigma=sigma) if sigma > 0 else np.zeros_like(surface)

        # ── Filtered surface ─────────────────────────────────────────────────
        filter_type = config.get("filter_type", "")
        if filter_type == "low-pass":
            filtered_surface = gaussian_filter(surface, sigma=1.2)
        elif filter_type == "high-pass":
            filtered_surface = surface - gaussian_filter(surface, sigma=1.2)
        else:
            filtered_surface = surface

        # ── Upward / downward continuation ───────────────────────────────────
        if "upward_continuation" in selected and surface.ndim == 2:
            height = float(config.get("upward_continuation_height", 100.0))
            filtered_surface = _apply_upward_continuation(surface, height, dx, dy)
            detail_items.append(f"upward continuation ({height} m)")
        if "downward_continuation" in selected and surface.ndim == 2:
            height = float(config.get("downward_continuation_height", 50.0))
            filtered_surface = _apply_downward_continuation(surface, height, dx, dy)
            detail_items.append(f"downward continuation ({height} m)")

        # Build detail
        if "analytic_signal" in selected:
            detail_items.append("analytic signal (3D)")
        if "emag2" in selected:
            detail_items.append("regional residual")
        if "rtp" in selected:
            detail_items.append(f"RTP (inc={rtp_inc}, dec={rtp_dec})")
        if "tilt_derivative" in selected:
            detail_items.append("tilt derivative")
        if "total_gradient" in selected:
            detail_items.append("total gradient")
        if "uncertainty" in selected:
            detail_items.append("uncertainty surface")

        return {
            "analytic_signal": analytic.tolist(),
            "first_vertical_derivative": fvd.tolist(),
            "horizontal_derivative": horizontal_derivative.tolist(),
            "filtered_surface": filtered_surface.tolist(),
            "emag2_residual": emag2_residual.tolist(),
            "rtp_surface": rtp_surface.tolist(),
            "tilt_derivative": tilt.tolist(),
            "total_gradient": total_grad.tolist(),
            "selected_add_ons": add_ons,
            "detail": ", ".join(detail_items) if detail_items else "No add-on layers were requested",
        }

    # ── Stage 7: Persist (unchanged) ────────────────────────────────────────

    def _persist_outputs(self, task: dict, prep: dict, results: dict, add_ons: dict) -> dict:
        payload = {
            "grid_x": results["grid_x"].tolist(),
            "grid_y": results["grid_y"].tolist(),
            "surface": results["surface"].tolist(),
            "uncertainty": results["uncertainty"].tolist(),
            "points": results["points"],
            "stats": results["stats"],
            "model_used": results["model_used"],
            **add_ons,
        }
        if "predicted_points" in results:
            payload["predicted_points"] = results["predicted_points"]

        payload = self._sanitize_payload(payload)
        artifacts = []
        json_bytes = json.dumps(payload, allow_nan=False).encode("utf-8")
        results_artifact = self._storage.upload_result(
            project_id=task["project_id"],
            task_id=task["id"],
            file_name="results.json",
            content_type="application/json",
            data=json_bytes,
        ).model_dump(mode="json")
        artifacts.append(results_artifact)

        grid_frame = pd.DataFrame(
            {
                "longitude": results["grid_x"].ravel(),
                "latitude": results["grid_y"].ravel(),
                "predicted_magnetic": results["surface"].ravel(),
                "uncertainty": results["uncertainty"].ravel(),
            }
        )
        artifacts.append(
            self._storage.upload_result(
                project_id=task["project_id"],
                task_id=task["id"],
                file_name="grid.csv",
                content_type="text/csv",
                data=grid_frame.to_csv(index=False).encode("utf-8"),
            ).model_dump(mode="json")
        )

        artifacts.append(
            self._storage.upload_result(
                project_id=task["project_id"],
                task_id=task["id"],
                file_name="train.csv",
                content_type="text/csv",
                data=prep["train_frame"].to_csv(index=False).encode("utf-8"),
            ).model_dump(mode="json")
        )

        artifacts.append(
            self._storage.upload_result(
                project_id=task["project_id"],
                task_id=task["id"],
                file_name="predict.csv",
                content_type="text/csv",
                data=prep["predict_frame"].to_csv(index=False).encode("utf-8"),
            ).model_dump(mode="json")
        )

        for file_name, renderer in (
            ("heatmap.png", self._render_heatmap_png),
            ("contour.png", self._render_contour_png),
            ("surface.png", self._render_surface_png),
        ):
            artifacts.append(
                self._storage.upload_result(
                    project_id=task["project_id"],
                    task_id=task["id"],
                    file_name=file_name,
                    content_type="image/png",
                    data=renderer(results["surface"]),
                ).model_dump(mode="json")
            )

        _2d_keys = {"grid_x", "grid_y", "surface", "uncertainty", "analytic_signal",
                    "first_vertical_derivative", "horizontal_derivative",
                    "filtered_surface", "emag2_residual", "rtp_surface",
                    "tilt_derivative", "total_gradient"}
        firestore_data = {k: v for k, v in payload.items() if k not in _2d_keys}
        if "points" in firestore_data:
            firestore_data["points"] = firestore_data["points"][:500]
        if "predicted_points" in firestore_data:
            firestore_data["predicted_points"] = firestore_data["predicted_points"][:500]
        return {"data": firestore_data, "artifacts": artifacts}

    def _sanitize_payload(self, value):
        if value is None:
            return None
        if isinstance(value, (str, bool, int)):
            return value
        if isinstance(value, float):
            if math.isnan(value) or math.isinf(value):
                return None
            return value
        if isinstance(value, dict):
            return {key: self._sanitize_payload(val) for key, val in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._sanitize_payload(val) for val in value]
        if hasattr(value, "item"):
            return self._sanitize_payload(value.item())
        return value

    def _render_heatmap_png(self, surface) -> bytes:
        from matplotlib import pyplot as plt

        figure, axis = plt.subplots(figsize=(6, 4))
        heatmap = axis.imshow(surface, cmap="viridis", origin="lower")
        figure.colorbar(heatmap, ax=axis, fraction=0.046, pad=0.04)
        axis.set_title("Magnetic Surface")
        axis.set_xlabel("Grid X")
        axis.set_ylabel("Grid Y")
        output = io.BytesIO()
        figure.tight_layout()
        figure.savefig(output, format="png", dpi=180)
        plt.close(figure)
        return output.getvalue()

    def _render_contour_png(self, surface) -> bytes:
        from matplotlib import pyplot as plt

        figure, axis = plt.subplots(figsize=(6, 4))
        if surface.ndim == 2 and surface.shape[0] > 1 and surface.shape[1] > 1:
            contour = axis.contourf(surface, levels=16, cmap="viridis")
            figure.colorbar(contour, ax=axis, fraction=0.046, pad=0.04)
        else:
            axis.plot(surface.ravel(), color="teal")
            axis.set_ylabel("nT")
        axis.set_title("Magnetic Contours")
        output = io.BytesIO()
        figure.tight_layout()
        figure.savefig(output, format="png", dpi=180)
        plt.close(figure)
        return output.getvalue()

    def _render_surface_png(self, surface) -> bytes:
        from matplotlib import pyplot as plt

        figure = plt.figure(figsize=(6, 4))
        if surface.ndim == 2 and surface.shape[0] > 1 and surface.shape[1] > 1:
            axis = figure.add_subplot(111, projection="3d")
            x = np.arange(surface.shape[1])
            y = np.arange(surface.shape[0])
            grid_x, grid_y = np.meshgrid(x, y)
            axis.plot_surface(grid_x, grid_y, surface, cmap="viridis", linewidth=0, antialiased=True)
        else:
            axis = figure.add_subplot(111)
            axis.plot(surface.ravel(), color="teal")
            axis.set_ylabel("nT")
        axis.set_title("3D Magnetic Surface")
        output = io.BytesIO()
        figure.tight_layout()
        figure.savefig(output, format="png", dpi=180)
        plt.close(figure)
        return output.getvalue()

    def _update_run(self, run_id: str, index: int, status: str, detail: str) -> None:
        run = self._store.get_processing_run(run_id)
        steps = run["steps"]
        steps[index]["status"] = status
        steps[index]["detail"] = detail
        logs = list(run.get("logs") or [])
        logs.append(
            {
                "timestamp": utc_now(),
                "step": steps[index]["name"],
                "status": status,
                "detail": detail,
            }
        )
        run_status = "running" if status == "running" else run.get("status", "queued")
        self._store.update_processing_run(
            run_id,
            {
                "steps": steps,
                "logs": logs[-100:],
                "status": run_status,
                "updated_at": utc_now(),
            },
        )
