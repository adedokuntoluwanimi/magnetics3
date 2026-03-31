"""GAIA Magnetics – Processing Service
Industry-grade geophysical magnetic data processing pipeline.
Scientific auditability, numerical stability, Oasis Montaj-comparable outputs.
"""
from __future__ import annotations

import io
import json
import math
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats
from scipy.fft import rfft, irfft, rfftfreq
from scipy.interpolate import CubicSpline, RBFInterpolator, griddata, interp1d
from scipy.ndimage import gaussian_filter, median_filter
from scipy.optimize import curve_fit
from scipy.signal import correlate, windows
from scipy.spatial import KDTree, cKDTree
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import StandardScaler

from backend.logging_utils import log_event
from backend.models import (
    MetricSummary,
    PipelineRun,
    PipelineStep,
    ProcessingFallbackEvent,
    ProcessingStageSummary,
    QAReport,
    ValidationIssue,
    ValidationSummary,
)

logger = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ProcessingRuntime:
    validation_summary: dict = field(default_factory=dict)
    stage_reports: list[dict] = field(default_factory=list)
    fallback_events: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    correction_path: list[str] = field(default_factory=list)


def _safe_float(value: float | int | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _metric_summary(arr: np.ndarray, affected_count: int = 0) -> dict:
    values = np.asarray(arr, dtype=np.float64).ravel()
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return MetricSummary(affected_count=affected_count).model_dump(mode="json")
    return MetricSummary(
        min=float(np.min(finite)),
        max=float(np.max(finite)),
        mean=float(np.mean(finite)),
        std=float(np.std(finite)),
        point_count=int(finite.size),
        affected_count=int(affected_count),
    ).model_dump(mode="json")


def _decimal_year_from_datetime(dt: datetime) -> float:
    dt_utc = dt.astimezone(timezone.utc)
    start = datetime(dt_utc.year, 1, 1, tzinfo=timezone.utc)
    end = datetime(dt_utc.year + 1, 1, 1, tzinfo=timezone.utc)
    return dt_utc.year + ((dt_utc - start).total_seconds() / max((end - start).total_seconds(), 1.0))


def _mad(values: np.ndarray) -> float:
    finite = np.asarray(values, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return 0.0
    median = np.median(finite)
    return float(np.median(np.abs(finite - median)))


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
    demeaned = mag_filled - float(np.mean(mag_filled))
    taper = windows.hann(n, sym=False) if n > 4 else np.ones(n, dtype=np.float64)
    tapered = demeaned * taper

    energy_before = _spectral_energy(tapered)

    spectrum = rfft(tapered)
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

    filtered = (irfft(filt, n=n) / np.where(taper > 1e-6, taper, 1.0)).astype(np.float64)
    filtered = filtered + float(np.mean(mag_filled))
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

    @staticmethod
    def _build_default_steps() -> list[PipelineStep]:
        return [
            PipelineStep(name="Load and validate", status="queued", detail="Waiting to start"),
            PipelineStep(name="Clean and standardize", status="queued", detail="Queued"),
            PipelineStep(name="Line-domain corrections", status="queued", detail="Queued"),
            PipelineStep(name="Leveling and crossover", status="queued", detail="Queued"),
            PipelineStep(name="Prediction target preparation", status="queued", detail="Queued"),
            PipelineStep(name="Modelling and interpolation", status="queued", detail="Queued"),
            PipelineStep(name="Grid-domain transforms", status="queued", detail="Queued"),
            PipelineStep(name="Uncertainty synthesis", status="queued", detail="Queued"),
            PipelineStep(name="QA report", status="queued", detail="Queued"),
            PipelineStep(name="Save results", status="queued", detail="Queued"),
        ]

    def _push_stage_report(
        self,
        runtime: ProcessingRuntime,
        *,
        name: str,
        status: str,
        detail: str,
        metrics: dict | None = None,
        warnings: list[str] | None = None,
        fallbacks: list[dict] | None = None,
        metadata: dict | None = None,
    ) -> None:
        runtime.stage_reports.append(
            ProcessingStageSummary(
                name=name,
                status=status,
                detail=detail,
                metrics=MetricSummary(**metrics) if metrics else None,
                warnings=warnings or [],
                fallbacks=[ProcessingFallbackEvent(**item) for item in (fallbacks or [])],
                metadata=metadata or {},
            ).model_dump(mode="json")
        )

    def _push_fallback(
        self,
        runtime: ProcessingRuntime,
        *,
        stage: str,
        requested: str,
        actual: str,
        reason: str,
        severity: str = "warning",
    ) -> None:
        event = ProcessingFallbackEvent(
            stage=stage,
            requested=requested,
            actual=actual,
            reason=reason,
            severity=severity,
        ).model_dump(mode="json")
        runtime.fallback_events.append(event)
        if severity in {"warning", "critical"}:
            runtime.warnings.append(f"{stage}: {reason}")

    def _resolve_survey_datetime(self, task: dict) -> datetime:
        analysis = task.get("analysis_config") or {}
        metadata = task.get("metadata") or {}
        candidates = [
            analysis.get("survey_date"),
            metadata.get("survey_date"),
            metadata.get("acquisition_date"),
            task.get("updated_at"),
            task.get("created_at"),
        ]
        for candidate in candidates:
            if not candidate:
                continue
            if isinstance(candidate, datetime):
                return candidate if candidate.tzinfo else candidate.replace(tzinfo=timezone.utc)
            try:
                parsed = datetime.fromisoformat(str(candidate).replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except Exception:
                continue
        return datetime.now(timezone.utc)

    def start_run(self, task_id: str) -> dict:
        task = self._store.get_task(task_id)
        if not task:
            raise ValueError("Task not found.")

        run = PipelineRun(
            task_id=task_id,
            status="queued",
            steps=self._build_default_steps(),
        )
        payload = run.model_dump(mode="json")
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

        runtime = ProcessingRuntime()

        try:
            self._update_run(run_id, 0, "running", "Loading and validating uploaded survey data...")
            raw_frame = self._load_dataframe(task)
            runtime.validation_summary = self._validate_loaded_frame(task, raw_frame)
            frame, n_removed = self._remove_coordinate_outliers(raw_frame)
            validation_detail = f"{len(frame)} rows validated"
            if n_removed > 0:
                validation_detail += f" ({n_removed} out-of-area points removed)"
            self._update_run(run_id, 0, "completed", validation_detail)
            self._push_stage_report(
                runtime,
                name="Load and validate",
                status="completed",
                detail=validation_detail,
                metrics=_metric_summary(frame["magnetic"].to_numpy(dtype=np.float64), n_removed),
                warnings=list(runtime.validation_summary.get("warnings") or []),
                metadata={"validation_summary": runtime.validation_summary},
            )

            self._update_run(run_id, 1, "running", "Cleaning duplicates, line IDs, and survey ordering...")
            cleaned = self._clean_dataframe(task, frame)
            clean_report = cleaned.attrs.get("cleaning_report", {})
            clean_detail = clean_report.get("detail") or f"{len(cleaned)} readings ready after cleaning"
            self._update_run(run_id, 1, "completed", clean_detail)
            self._push_stage_report(
                runtime,
                name="Clean and standardize",
                status="completed",
                detail=clean_detail,
                metrics=_metric_summary(cleaned["magnetic"].to_numpy(dtype=np.float64), int(clean_report.get("duplicates_removed", 0))),
                warnings=list(clean_report.get("warnings") or []),
                metadata=clean_report,
            )

            self._update_run(run_id, 2, "running", "Applying line-domain corrections...")
            corrected, correction_summary = self._apply_corrections(task, cleaned)
            correction_report = corrected.attrs.get("correction_report", {})
            runtime.correction_path = list(correction_report.get("applied_order") or [])
            for fallback in correction_report.get("fallbacks") or []:
                self._push_fallback(runtime, **fallback)
            self._update_run(run_id, 2, "completed", correction_summary)
            self._push_stage_report(
                runtime,
                name="Line-domain corrections",
                status="completed",
                detail=correction_summary,
                metrics=_metric_summary(corrected["magnetic"].to_numpy(dtype=np.float64), int(correction_report.get("affected_points", 0))),
                warnings=list(correction_report.get("warnings") or []),
                fallbacks=list(correction_report.get("fallbacks") or []),
                metadata=correction_report,
            )

            self._update_run(run_id, 3, "running", "Running crossover checks and leveling...")
            leveled, leveling_summary = self._apply_leveling_and_crossover(task, corrected)
            leveling_report = leveled.attrs.get("leveling_report", {})
            for fallback in leveling_report.get("fallbacks") or []:
                self._push_fallback(runtime, **fallback)
            self._update_run(run_id, 3, "completed", leveling_summary)
            self._push_stage_report(
                runtime,
                name="Leveling and crossover",
                status=leveling_report.get("status", "completed"),
                detail=leveling_summary,
                metrics=_metric_summary(leveled["magnetic"].to_numpy(dtype=np.float64), int(leveling_report.get("affected_points", 0))),
                warnings=list(leveling_report.get("warnings") or []),
                fallbacks=list(leveling_report.get("fallbacks") or []),
                metadata=leveling_report,
            )

            config = task.get("analysis_config") or {}
            run_prediction = config.get("run_prediction", True)

            if run_prediction:
                self._update_run(run_id, 4, "running", "Preparing prediction targets from the survey geometry...")
                prep = self._prepare_prediction_inputs(task, leveled)
                self._update_run(run_id, 4, "completed", prep["detail"])
                self._push_stage_report(
                    runtime,
                    name="Prediction target preparation",
                    status="completed",
                    detail=prep["detail"],
                    metadata=prep.get("metadata") or {},
                )

                self._update_run(run_id, 5, "running", "Running the interpolation and modelling path...")
                results = self._generate_surfaces(task, prep)
                model_detail = f"Model complete - used {results['model_used']} approach"
                self._update_run(run_id, 5, "completed", model_detail)
                self._push_stage_report(
                    runtime,
                    name="Modelling and interpolation",
                    status="completed",
                    detail=model_detail,
                    metrics=_metric_summary(results["surface"]),
                    warnings=list((results.get("model_metadata") or {}).get("warnings") or []),
                    metadata=results.get("model_metadata") or {},
                )

                self._update_run(run_id, 6, "running", "Calculating derived grid-domain layers...")
                add_on_payload = self._apply_add_ons(task, results)
                for fallback in (add_on_payload.get("metadata") or {}).get("fallbacks") or []:
                    self._push_fallback(runtime, **fallback)
                self._update_run(run_id, 6, "completed", add_on_payload["detail"])
                self._push_stage_report(
                    runtime,
                    name="Grid-domain transforms",
                    status="completed",
                    detail=add_on_payload["detail"],
                    warnings=list((add_on_payload.get("metadata") or {}).get("warnings") or []),
                    fallbacks=list((add_on_payload.get("metadata") or {}).get("fallbacks") or []),
                    metadata=add_on_payload.get("metadata") or {},
                )
            else:
                self._update_run(run_id, 4, "completed", "Prediction modelling disabled - skipped")
                self._update_run(run_id, 5, "completed", "Prediction modelling disabled - skipped")
                grid_x, grid_y = self._build_grid(task, leveled)
                surface = self._nearest_surface(
                    leveled["longitude"].to_numpy(),
                    leveled["latitude"].to_numpy(),
                    leveled["magnetic"].to_numpy(),
                    grid_x,
                    grid_y,
                )
                uncertainty = self._uncertainty_surface(
                    leveled["longitude"].to_numpy(),
                    leveled["latitude"].to_numpy(),
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
                    "points": leveled[["latitude", "longitude", "magnetic"]
                        + (["__is_base_station__"] if "__is_base_station__" in leveled.columns else [])
                        + (["_line_id"] if "_line_id" in leveled.columns else [])
                    ].rename(columns={"__is_base_station__": "is_base_station", "_line_id": "line_id"}).to_dict(orient="records"),
                    "stats": {
                        "min": float(leveled["magnetic"].min()), "max": float(leveled["magnetic"].max()),
                        "mean": float(leveled["magnetic"].mean()), "std": float(leveled["magnetic"].std()),
                        "point_count": len(leveled), "anomaly_count": 0,
                    },
                    "predicted_points": [],
                    "model_metadata": {
                        "algorithm": "observed_data_surface",
                        "warnings": ["Prediction disabled; output is a nearest-neighbour observed-data surface."],
                    },
                    "uncertainty_metadata": {"algorithm": "distance_only", "detail": "Distance-based uncertainty prepared"},
                }
                add_on_payload = self._apply_add_ons(task, results)
                self._update_run(run_id, 6, "completed", add_on_payload["detail"])
                prep = {
                    "frame": leveled,
                    "train_frame": leveled,
                    "predict_frame": pd.DataFrame({"latitude": [], "longitude": []}),
                    "grid_x": grid_x,
                    "grid_y": grid_y,
                    "detail": "Prediction disabled",
                    "scenario": self._resolve_scenario(task),
                    "metadata": {"run_prediction": False},
                }
                self._push_stage_report(
                    runtime,
                    name="Prediction target preparation",
                    status="completed",
                    detail="Prediction disabled - existing observed data carried forward",
                    metadata=prep["metadata"],
                )
                self._push_stage_report(
                    runtime,
                    name="Grid-domain transforms",
                    status="completed",
                    detail=add_on_payload["detail"],
                    warnings=list((add_on_payload.get("metadata") or {}).get("warnings") or []),
                    fallbacks=list((add_on_payload.get("metadata") or {}).get("fallbacks") or []),
                    metadata=add_on_payload.get("metadata") or {},
                )

            self._update_run(run_id, 7, "running", "Synthesizing uncertainty and support confidence...")
            uncertainty_detail = (results.get("uncertainty_metadata") or {}).get("detail") or "Uncertainty surface prepared"
            self._update_run(run_id, 7, "completed", uncertainty_detail)
            self._push_stage_report(
                runtime,
                name="Uncertainty synthesis",
                status="completed",
                detail=uncertainty_detail,
                metrics=_metric_summary(results["uncertainty"]),
                warnings=list((results.get("uncertainty_metadata") or {}).get("warnings") or []),
                metadata=results.get("uncertainty_metadata") or {},
            )

            self._update_run(run_id, 8, "running", "Building the QA report and scientific provenance...")
            qa_report = self._build_qa_report(task, prep, results, add_on_payload, runtime)
            self._update_run(run_id, 8, "completed", f"QA status: {qa_report['status']}")
            self._push_stage_report(
                runtime,
                name="QA report",
                status="completed",
                detail=f"QA status: {qa_report['status']}",
                warnings=list(qa_report.get("warnings") or []),
                metadata=qa_report,
            )

            self._update_run(run_id, 9, "running", "Saving results, QA metadata, and artifacts...")
            stored = self._persist_outputs(task, prep, results, add_on_payload, qa_report, runtime.validation_summary)
            self._update_run(run_id, 9, "completed", "Saved outputs, QA report, and grid artifacts")

            self._store.update_processing_run(
                run_id,
                {
                    "status": "completed",
                    "qa_status": qa_report["status"],
                    "validation_summary": runtime.validation_summary,
                    "qa_report": qa_report,
                    "stage_reports": runtime.stage_reports,
                    "warnings": runtime.warnings[-100:],
                    "metadata": runtime.metadata,
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
                    "validation_summary": runtime.validation_summary or None,
                    "stage_reports": runtime.stage_reports,
                    "warnings": runtime.warnings[-100:],
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

    def _validate_loaded_frame(self, task: dict, frame: pd.DataFrame) -> dict:
        mapping = task.get("column_mapping") or {}
        issues: list[ValidationIssue] = []
        warnings: list[str] = []
        coord_sys = (mapping.get("coordinate_system") or "wgs84").lower()
        survey_date = self._resolve_survey_datetime(task)
        duplicate_timestamp_count = 0

        if coord_sys == "utm":
            zone = mapping.get("utm_zone")
            hemi = (mapping.get("utm_hemisphere") or "").upper() or None
            if zone is None or not (1 <= int(zone) <= 60):
                issues.append(ValidationIssue(code="utm_zone_missing", severity="warning", message="UTM zone was missing or outside 1-60."))
            if hemi not in {None, "N", "S"}:
                issues.append(ValidationIssue(code="utm_hemisphere_invalid", severity="warning", message="UTM hemisphere was not N or S."))

        lat = frame.get("latitude", pd.Series(dtype=float)).to_numpy(dtype=np.float64)
        lon = frame.get("longitude", pd.Series(dtype=float)).to_numpy(dtype=np.float64)
        impossible_mask = (
            (~np.isfinite(lat)) | (~np.isfinite(lon))
            | (lat < -90.0) | (lat > 90.0)
            | (lon < -180.0) | (lon > 180.0)
        )
        impossible_count = int(np.count_nonzero(impossible_mask))
        if impossible_count:
            issues.append(ValidationIssue(code="impossible_coordinates", severity="critical", message="Some coordinates fall outside valid geographic bounds.", count=impossible_count))

        if {"_hour", "_minute"}.issubset(frame.columns):
            sec = frame["_second"] if "_second" in frame.columns else 0.0
            times = (frame["_hour"].fillna(0) * 3600.0 + frame["_minute"].fillna(0) * 60.0 + sec).to_numpy(dtype=np.float64)
            duplicate_timestamp_count = int(pd.Series(times).duplicated().sum())
            if duplicate_timestamp_count:
                warnings.append(f"{duplicate_timestamp_count} duplicate timestamps detected across the survey rows.")

        status = "valid"
        if any(issue.severity == "critical" for issue in issues):
            status = "degraded"
        elif issues or warnings:
            status = "valid_with_warnings"

        return ValidationSummary(
            status=status,
            row_count=int(len(frame)),
            valid_row_count=int(len(frame) - impossible_count),
            dropped_row_count=0,
            coordinate_system=coord_sys,
            utm_zone=mapping.get("utm_zone"),
            utm_hemisphere=mapping.get("utm_hemisphere"),
            survey_date=survey_date,
            line_count=int(frame["_line_id"].nunique()) if "_line_id" in frame.columns else 0,
            base_station_count=int(frame["__is_base_station__"].sum()) if "__is_base_station__" in frame.columns else 0,
            duplicate_timestamp_count=duplicate_timestamp_count,
            non_monotonic_line_count=0,
            issues=issues,
            warnings=warnings,
        ).model_dump(mode="json")

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
                from pyproj import CRS, Transformer

                utm_zone = mapping.get("utm_zone")
                utm_hemi = (mapping.get("utm_hemisphere") or "N").upper()
                if not utm_zone:
                    first_n = float(frame["_raw_lat"].iloc[0])
                    utm_zone = 32
                    utm_hemi = "N" if first_n < 5_000_000 else "S"
                if not 1 <= int(utm_zone) <= 60:
                    raise ValueError(f"Invalid UTM zone: {utm_zone}")
                epsg = 32600 + int(utm_zone) if utm_hemi != "S" else 32700 + int(utm_zone)
                transformer = Transformer.from_crs(CRS.from_epsg(epsg), CRS.from_epsg(4326), always_xy=True)
                easting = frame["_raw_lon"].to_numpy(dtype=np.float64)
                northing = frame["_raw_lat"].to_numpy(dtype=np.float64)
                lon_vals, lat_vals = transformer.transform(easting, northing, errcheck=False)
                frame["latitude"] = np.asarray(lat_vals, dtype=np.float64)
                frame["longitude"] = np.asarray(lon_vals, dtype=np.float64)
            else:
                frame["latitude"] = frame["_raw_lat"]
                frame["longitude"] = frame["_raw_lon"]

            if "__is_base_station__" in frame.columns:
                frame["__is_base_station__"] = pd.to_numeric(frame["__is_base_station__"], errors="coerce").fillna(0).astype(int)

            frame = frame.dropna(subset=["latitude", "longitude"])
            if not frame.empty:
                frames.append(frame)

        if not frames:
            raise ValueError("No valid coordinate rows found in the survey file(s).")

        return pd.concat(frames, ignore_index=True)

    @staticmethod
    def _remove_coordinate_outliers(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
        original_len = len(frame)
        if frame.empty:
            return frame.reset_index(drop=True), 0

        frame = frame[np.isfinite(frame["latitude"]) & np.isfinite(frame["longitude"])].copy()
        frame = frame[
            frame["latitude"].between(-90.0, 90.0)
            & frame["longitude"].between(-180.0, 180.0)
        ]

        keep_mask = np.ones(len(frame), dtype=bool)
        for col in ("latitude", "longitude"):
            vals = frame[col].to_numpy(dtype=np.float64)
            med = np.nanmedian(vals)
            mad = _mad(vals)
            if mad > 0:
                robust_z = 0.6745 * (vals - med) / mad
                keep_mask &= np.abs(robust_z) <= 6.0
            q1 = np.nanpercentile(vals, 25)
            q3 = np.nanpercentile(vals, 75)
            iqr = q3 - q1
            if iqr > 0:
                lo = q1 - 3.0 * iqr
                hi = q3 + 3.0 * iqr
                keep_mask &= (vals >= lo) & (vals <= hi)
        frame = frame.loc[keep_mask]
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

    def _resolve_scenario(self, task: dict) -> str:
        scenario = str(task.get("scenario") or "").strip().lower()
        if scenario in {"explicit", "sparse"}:
            return scenario
        return "automatic"

    def _clean_dataframe(self, task: dict, frame: pd.DataFrame) -> pd.DataFrame:
        cleaned = frame.copy()
        warnings: list[str] = []

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
            n_jumps = 0
            if pos_dists.size > 0:
                median_dist = float(np.median(pos_dists))
                n_jumps = int(np.sum(dists > median_dist * 10.0))
            if pos_dists.size > 0 and n_jumps > 0:
                logger.warning(
                    "Stage 2.clean: %d unrealistic spatial jumps detected (threshold=%.4f)",
                    n_jumps, median_dist * 10.0,
                )
                warnings.append(f"{n_jumps} large spatial jumps were detected during cleaning.")

        # Build time_s for time-aware corrections
        if "_hour" in cleaned.columns and "_minute" in cleaned.columns:
            _sec = cleaned["_second"].fillna(0) if "_second" in cleaned.columns else 0
            cleaned["time_s"] = (
                cleaned["_hour"].fillna(0) * 3600.0
                + cleaned["_minute"].fillna(0) * 60.0
                + _sec
            ).astype(np.float64)
        else:
            cleaned["time_s"] = np.arange(len(cleaned), dtype=np.float64)

        lat_range = float(cleaned["latitude"].max() - cleaned["latitude"].min()) if len(cleaned) else 0.0
        lon_range = float(cleaned["longitude"].max() - cleaned["longitude"].min()) if len(cleaned) else 0.0
        group_by_lat = lat_range < lon_range
        grouping_col = "latitude" if group_by_lat else "longitude"
        along_col = "longitude" if group_by_lat else "latitude"

        if str(task.get("processing_mode") or "").lower() == "single":
            cleaned["_line_id"] = 0
        else:
            step = np.median(np.abs(np.diff(np.sort(cleaned[grouping_col].to_numpy(dtype=np.float64))))) if len(cleaned) > 2 else 0.0
            step = float(step) if np.isfinite(step) and step > 0 else max((lat_range if group_by_lat else lon_range) / max(math.sqrt(max(len(cleaned), 1)), 1.0), 0.0001)
            tol_group = max(step * 2.5, 0.0001)
            cleaned["_line_id"] = np.round(cleaned[grouping_col].to_numpy(dtype=np.float64) / tol_group).astype(int)
        cleaned = cleaned.sort_values(["_line_id", "time_s", along_col], na_position="last").reset_index(drop=True)

        along_m = np.zeros(len(cleaned), dtype=np.float64)
        for line_id, idx in cleaned.groupby("_line_id").groups.items():
            line = cleaned.loc[idx]
            lon = line["longitude"].to_numpy(dtype=np.float64)
            lat = line["latitude"].to_numpy(dtype=np.float64)
            if len(line) <= 1:
                continue
            dlat = np.diff(lat) * 111_320.0
            dlon = np.diff(lon) * 111_320.0 * np.cos(np.radians(np.nanmean(lat)))
            cumulative = np.concatenate([[0.0], np.cumsum(np.sqrt(dlat ** 2 + dlon ** 2))])
            along_m[np.asarray(idx)] = cumulative
        cleaned["along_line_m"] = along_m

        non_monotonic_lines = 0
        if "time_s" in cleaned.columns:
            for _line_id, line in cleaned.groupby("_line_id"):
                t = line["time_s"].to_numpy(dtype=np.float64)
                if len(t) > 1 and np.any(np.diff(t) < 0):
                    non_monotonic_lines += 1
        if non_monotonic_lines:
            warnings.append(f"{non_monotonic_lines} inferred line(s) have non-monotonic time ordering.")

        _proc_log("2.clean/magnetic", cleaned["magnetic"].to_numpy(dtype=np.float64))
        cleaned.attrs["cleaning_report"] = {
            "duplicates_removed": int(n_removed),
            "warnings": warnings,
            "line_count": int(cleaned["_line_id"].nunique()) if "_line_id" in cleaned.columns else 0,
            "grouping_axis": grouping_col,
            "detail": f"{len(cleaned)} readings ready after cleaning across {int(cleaned['_line_id'].nunique()) if '_line_id' in cleaned.columns else 0} inferred line(s)",
        }
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
        warnings: list[str] = []
        fallbacks: list[dict] = []
        igrf_applied = False
        affected_points = 0

        mag_before = out["magnetic"].to_numpy(dtype=np.float64).copy()

        survey_dt = self._resolve_survey_datetime(task)
        decimal_yr = _decimal_year_from_datetime(survey_dt)

        # ── 3.0 Spike removal ───────────────────────────────────────────────
        if "filtering" in selected or True:  # always run spike check
            out, spike_note = self._apply_spike_removal(out)
            if spike_note:
                notes.append(spike_note)
            spike_report = out.attrs.get("spike_report", {})
            affected_points += int(spike_report.get("removed_count", 0))

        # ── 3.1 IGRF correction ──────────────────────────────────────────────
        if "igrf" in selected:
            lat = out["latitude"].to_numpy(dtype=np.float64)
            lon = out["longitude"].to_numpy(dtype=np.float64)
            igrf_vals = _compute_igrf_total(lat, lon, decimal_yr)
            if igrf_vals is not None:
                valid_igrf = ~np.isnan(igrf_vals)
                if valid_igrf.sum() > 0:
                    igrf_min = float(np.nanmin(igrf_vals))
                    igrf_max = float(np.nanmax(igrf_vals))
                    if igrf_min < 20000 or igrf_max > 70000:
                        warnings.append("IGRF values fell outside the expected geomagnetic total-field range.")
                    igrf_mean = float(np.nanmean(igrf_vals))
                    out["magnetic"] = out["magnetic"] - igrf_vals
                    igrf_applied = True
                    logger.info(
                        "IGRF applied: mean_field=%.2f nT, min=%.2f, max=%.2f",
                        igrf_mean, igrf_min, igrf_max,
                    )
                    notes.append(f"IGRF-13 correction (mean ref={igrf_mean:.1f} nT)")
                    _proc_log("3.1.igrf", out["magnetic"].to_numpy(dtype=np.float64))
            else:
                logger.critical("IGRF correction requested but pyIGRF was unavailable.")
                notes.append("IGRF requested but unavailable - output kept without IGRF removal")
                fallbacks.append(
                    {
                        "stage": "igrf",
                        "requested": "igrf",
                        "actual": "uncorrected_field",
                        "reason": "pyIGRF was unavailable, so true IGRF removal could not be applied.",
                        "severity": "critical",
                    }
                )

        # ── 3.2 Diurnal correction ───────────────────────────────────────────
        if "diurnal" in selected:
            out, diurnal_note = self._apply_diurnal_correction(out, task)
            notes.append(diurnal_note)
            diurnal_report = out.attrs.get("diurnal_report", {})
            warnings.extend(diurnal_report.get("warnings") or [])
            fallbacks.extend(diurnal_report.get("fallbacks") or [])
            affected_points += int(diurnal_report.get("affected_points", 0))

        # ── 3.3 Lag correction ───────────────────────────────────────────────
        if "lag" in selected and len(out) > 3:
            out, lag_note = self._apply_lag_correction(out)
            notes.append(lag_note)
            lag_report = out.attrs.get("lag_report", {})
            warnings.extend(lag_report.get("warnings") or [])
            fallbacks.extend(lag_report.get("fallbacks") or [])
            affected_points += int(lag_report.get("affected_points", 0))

        # ── 3.4 Heading correction ───────────────────────────────────────────
        if "heading" in selected and len(out) > 3:
            out, heading_note = self._apply_heading_correction(out)
            notes.append(heading_note)
            heading_report = out.attrs.get("heading_report", {})
            warnings.extend(heading_report.get("warnings") or [])
            fallbacks.extend(heading_report.get("fallbacks") or [])
            affected_points += int(heading_report.get("affected_points", 0))

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
                if energy_ratio < 0.15:
                    warnings.append("FFT filter retained less than 15% of the original signal energy.")
                _proc_log(f"3.5.fft_{fft_type}", out["magnetic"].to_numpy(dtype=np.float64))

        mag_after = out["magnetic"].to_numpy(dtype=np.float64)
        _proc_log("3.final", mag_after)
        logger.info("Corrections complete: igrf_applied=%s, steps=%s", igrf_applied, notes)

        detail = ", ".join(notes) if notes else "No additional corrections were requested"
        out.attrs["correction_report"] = {
            "applied_order": notes,
            "warnings": warnings,
            "fallbacks": fallbacks,
            "affected_points": int(affected_points),
            "igrf_applied": bool(igrf_applied),
            "survey_date": survey_dt.isoformat(),
            "decimal_year": decimal_yr,
            "spike": out.attrs.get("spike_report", {}),
            "diurnal": out.attrs.get("diurnal_report", {}),
            "lag": out.attrs.get("lag_report", {}),
            "heading": out.attrs.get("heading_report", {}),
        }
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
        out.attrs["spike_report"] = {
            "candidate_count": int(n_stat),
            "removed_count": int(n_removed),
            "preserved_anomaly_count": int(n_preserved),
        }
        return out, note

    def _apply_diurnal_correction(self, frame: pd.DataFrame, task: dict) -> tuple[pd.DataFrame, str]:
        """Base-station diurnal correction with explicit fallback reporting."""
        out = frame.copy()
        bs_col = "__is_base_station__"
        has_bs = bs_col in frame.columns and frame[bs_col].sum() > 0
        has_time = "time_s" in frame.columns
        report = {
            "status": "skipped",
            "algorithm": "none",
            "quality": 0.0,
            "warnings": [],
            "fallbacks": [],
            "affected_points": 0,
        }

        if has_bs and has_time:
            bs = out[out[bs_col] == 1].dropna(subset=["time_s", "magnetic"])
            survey = out[out[bs_col] != 1].copy()
            if not bs.empty and not survey.empty:
                bs_sorted = bs.sort_values("time_s").reset_index(drop=True)
                bs_sorted = bs_sorted[np.isfinite(bs_sorted["time_s"].to_numpy(dtype=np.float64))]
                bs_sorted = bs_sorted.groupby("time_s", as_index=False)["magnetic"].median()
                t_bs = bs_sorted["time_s"].to_numpy(dtype=np.float64)
                m_bs = bs_sorted["magnetic"].to_numpy(dtype=np.float64)
                survey_t = survey["time_s"].fillna(t_bs[0]).to_numpy(dtype=np.float64)
                gaps = np.diff(t_bs)
                max_gap = float(np.max(gaps)) if gaps.size else 0.0
                overlap_mask = (survey_t >= float(np.min(t_bs))) & (survey_t <= float(np.max(t_bs)))
                overlap_ratio = float(np.mean(overlap_mask)) if survey_t.size else 0.0
                extrapolated = int(np.count_nonzero(~overlap_mask))
                report.update(
                    {
                        "status": "completed",
                        "algorithm": "base_station_cubic_spline",
                        "overlap_ratio": overlap_ratio,
                        "max_gap_seconds": max_gap,
                        "extrapolated_points": extrapolated,
                        "affected_points": int(len(survey)),
                    }
                )
                try:
                    cs = CubicSpline(t_bs, m_bs, extrapolate=True)
                    diurnal_at_survey = cs(survey_t)
                except Exception:
                    diurnal_at_survey = np.interp(survey_t, t_bs, m_bs)
                    report["algorithm"] = "base_station_linear_interpolation"
                    report["fallbacks"].append(
                        {
                            "stage": "diurnal",
                            "requested": "base_station_cubic_spline",
                            "actual": "base_station_linear_interpolation",
                            "reason": "CubicSpline failed, so linear interpolation was used.",
                            "severity": "warning",
                        }
                    )
                bs_mean = float(np.mean(m_bs))
                before = survey["magnetic"].to_numpy(dtype=np.float64)
                survey = survey.copy()
                survey["magnetic"] = before - diurnal_at_survey + bs_mean
                out = pd.concat([bs, survey]).sort_values("time_s").reset_index(drop=True)
                residual_before = float(np.nanstd(before - bs_mean))
                residual_after = float(np.nanstd(survey["magnetic"].to_numpy(dtype=np.float64) - bs_mean))
                report["residual_drift_before"] = residual_before
                report["residual_drift_after"] = residual_after
                report["quality"] = float(max(0.0, min(1.0, (overlap_ratio * 0.7) + (0.3 if residual_after <= residual_before else 0.1))))
                if max_gap > 3600.0 * 2:
                    report["warnings"].append("Base-station data contain gaps larger than two hours.")
                if extrapolated:
                    report["warnings"].append(f"{extrapolated} survey points were extrapolated outside the base-station time range.")
                _proc_log("3.2.diurnal", out["magnetic"].to_numpy(dtype=np.float64))
                out.attrs["diurnal_report"] = report
                return out, "diurnal correction via base-station interpolation"

        # FFT physical fallback
        if has_time:
            mag = out["magnetic"].to_numpy(dtype=np.float64)
            t = out["time_s"].to_numpy(dtype=np.float64)
            trend = _diurnal_fft_fallback(mag, t, min_period_s=3600.0)
            trend_mean = float(np.nanmean(trend))
            out["magnetic"] = out["magnetic"] - trend + trend_mean
            report.update(
                {
                    "status": "completed",
                    "algorithm": "fft_trend_removal",
                    "quality": 0.35,
                    "affected_points": int(len(out)),
                    "fallbacks": [
                        {
                            "stage": "diurnal",
                            "requested": "base_station_diurnal_correction",
                            "actual": "fft_trend_removal",
                            "reason": "No valid overlapping base-station data were available.",
                            "severity": "warning",
                        }
                    ],
                }
            )
            _proc_log("3.2.diurnal_fft", out["magnetic"].to_numpy(dtype=np.float64))
            out.attrs["diurnal_report"] = report
            return out, "diurnal trend removal via FFT low-pass fallback"

        # Last resort: median normalisation
        out["magnetic"] = out["magnetic"] - out["magnetic"].median()
        report.update(
            {
                "status": "completed",
                "algorithm": "median_normalisation",
                "quality": 0.1,
                "affected_points": int(len(out)),
                "fallbacks": [
                    {
                        "stage": "diurnal",
                        "requested": "base_station_diurnal_correction",
                        "actual": "median_normalisation",
                        "reason": "No usable time data were available.",
                        "severity": "warning",
                    }
                ],
            }
        )
        out.attrs["diurnal_report"] = report
        return out, "diurnal normalisation fallback (no time data)"

    def _apply_lag_correction(self, frame: pd.DataFrame) -> tuple[pd.DataFrame, str]:
        """Cross-correlation lag estimation using best-quality flight lines."""
        out = frame.copy()
        report = {"status": "skipped", "warnings": [], "fallbacks": [], "affected_points": 0}
        if "time_s" not in out.columns or "_line_id" not in out.columns:
            # Fallback: interpolation-based shift of 0
            report["fallbacks"].append(
                {
                    "stage": "lag",
                    "requested": "cross_correlation_lag",
                    "actual": "skipped",
                    "reason": "No line IDs or time axis were available.",
                    "severity": "warning",
                }
            )
            out.attrs["lag_report"] = report
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
                report["fallbacks"].append(
                    {
                        "stage": "lag",
                        "requested": "cross_correlation_lag",
                        "actual": "skipped",
                        "reason": "Fewer than two supported lines were available.",
                        "severity": "warning",
                    }
                )
                out.attrs["lag_report"] = report
                return out, "lag correction skipped (insufficient lines)"

            ref_line = out[out["_line_id"] == best_line]["magnetic"].dropna().to_numpy(dtype=np.float64)
            # Pick second best line
            lines_other = [l for l in lines if l != best_line]
            other_line = out[out["_line_id"] == lines_other[0]]["magnetic"].dropna().to_numpy(dtype=np.float64)

            min_len = min(len(ref_line), len(other_line), 500)
            a = ref_line[:min_len]
            b = other_line[:min_len]

            taper = windows.hann(min_len, sym=False)
            a_n = ((a - np.mean(a)) * taper) / (np.std(a) + 1e-9)
            b_n = ((b - np.mean(b)) * taper) / (np.std(b) + 1e-9)
            corr = correlate(a_n, b_n, mode="full")
            lags = np.arange(-(len(b_n) - 1), len(a_n))
            peak_idx = int(np.argmax(np.abs(corr)))
            lag = int(lags[peak_idx])
            peak_val = float(corr[peak_idx])
            confidence = abs(peak_val) / (len(a_n) + 1e-9)

            # Reject unrealistic lag
            if abs(lag) > 15:
                logger.warning("Lag %d samples exceeds threshold (15); skipping lag correction.", lag)
                report["fallbacks"].append(
                    {
                        "stage": "lag",
                        "requested": "cross_correlation_lag",
                        "actual": "skipped",
                        "reason": f"Estimated lag {lag} samples exceeded the allowed threshold.",
                        "severity": "warning",
                    }
                )
                out.attrs["lag_report"] = report
                return out, f"lag correction skipped (estimated lag {lag} samples exceeds threshold)"
            if confidence < 0.2:
                report["fallbacks"].append(
                    {
                        "stage": "lag",
                        "requested": "cross_correlation_lag",
                        "actual": "skipped",
                        "reason": f"Lag confidence was too low ({confidence:.3f}).",
                        "severity": "warning",
                    }
                )
                out.attrs["lag_report"] = report
                return out, f"lag correction skipped (low confidence {confidence:.3f})"

            # Apply via interpolation shift
            if lag != 0 and "time_s" in out.columns:
                t = out["time_s"].to_numpy(dtype=np.float64)
                mag = out["magnetic"].to_numpy(dtype=np.float64)
                valid = ~np.isnan(mag)
                if valid.sum() > 3:
                    dt = _compute_dt_median(t[valid])
                    t_shift = t + lag * dt
                    interp_fn = interp1d(
                        t[valid],
                        mag[valid],
                        bounds_error=False,
                        fill_value=(float(mag[valid][0]), float(mag[valid][-1])),
                    )
                    out["magnetic"] = interp_fn(t_shift)
                    _proc_log("3.3.lag", out["magnetic"].to_numpy(dtype=np.float64))
                    report.update(
                        {
                            "status": "completed",
                            "lag_samples": int(lag),
                            "lag_distance_m": float(lag * dt),
                            "confidence": float(confidence),
                            "affected_points": int(valid.sum()),
                        }
                    )

            out.attrs["lag_report"] = report
            return out, f"lag correction ({lag} samples, confidence={confidence:.3f})"
        except Exception as exc:
            logger.warning("Lag correction failed (%s); skipping.", exc)
            report["fallbacks"].append(
                {
                    "stage": "lag",
                    "requested": "cross_correlation_lag",
                    "actual": "skipped",
                    "reason": f"Error during lag estimation: {exc}",
                    "severity": "warning",
                }
            )
            out.attrs["lag_report"] = report
            return out, "lag correction skipped (error)"

    def _apply_heading_correction(self, frame: pd.DataFrame) -> tuple[pd.DataFrame, str]:
        """Adaptive equal-count bin heading bias correction."""
        out = frame.copy()
        lon = out["longitude"].to_numpy(dtype=np.float64)
        lat = out["latitude"].to_numpy(dtype=np.float64)
        mag = out["magnetic"].to_numpy(dtype=np.float64)
        report = {"status": "skipped", "warnings": [], "fallbacks": [], "affected_points": 0}

        if len(lon) < 4:
            out.attrs["heading_report"] = report
            return out, "heading correction skipped (insufficient points)"

        dx = np.diff(lon, prepend=lon[0])
        dy = np.diff(lat, prepend=lat[0])
        heading = np.arctan2(dy, dx + 1e-12)
        heading = median_filter(heading, size=3, mode="nearest")

        n_bins = max(4, min(16, int(math.sqrt(len(heading)))))
        percentiles = np.linspace(0, 100, n_bins + 1)
        bin_edges = np.percentile(heading, percentiles)
        bin_edges[-1] += 1e-9

        corrected_mag = mag.copy()
        overall_median = float(np.nanmedian(mag))
        bin_stats = []
        for i in range(n_bins):
            mask = (heading >= bin_edges[i]) & (heading < bin_edges[i + 1])
            if mask.sum() >= 4:
                bin_bias = float(np.nanmedian(mag[mask]))
                corrected_mag[mask] = mag[mask] - (bin_bias - overall_median)
                bin_stats.append({"count": int(mask.sum()), "bias": bin_bias})
            elif mask.sum() > 0:
                report["warnings"].append(f"Heading bin {i + 1} had sparse support and was left uncorrected.")

        out["magnetic"] = corrected_mag
        _proc_log("3.4.heading", out["magnetic"].to_numpy(dtype=np.float64))
        report.update(
            {
                "status": "completed",
                "affected_points": int(len(out)),
                "bin_count": int(n_bins),
                "bin_stats": bin_stats,
            }
        )
        out.attrs["heading_report"] = report
        return out, f"heading correction ({n_bins} adaptive bins)"

    # ── Stage 4: Grid prep (unchanged) ──────────────────────────────────────

    def _apply_leveling_and_crossover(self, task: dict, frame: pd.DataFrame) -> tuple[pd.DataFrame, str]:
        out = frame.copy()
        report = {"status": "degraded", "warnings": [], "fallbacks": [], "affected_points": 0}
        if "_line_id" not in out.columns or out["_line_id"].nunique() < 2:
            report["fallbacks"].append(
                {
                    "stage": "leveling",
                    "requested": "crossover_leveling",
                    "actual": "skipped",
                    "reason": "At least two supported lines are required for crossover leveling.",
                    "severity": "warning",
                }
            )
            out.attrs["leveling_report"] = report
            return out, "leveling skipped (insufficient line support)"

        line_ids = list(out["_line_id"].dropna().unique())
        coords = out[["longitude", "latitude"]].to_numpy(dtype=np.float64)
        if len(coords) < 4:
            out.attrs["leveling_report"] = report
            return out, "leveling skipped (insufficient coordinates)"

        tree = cKDTree(coords)
        distance_scale = tree.query(coords, k=min(4, len(coords)))[0][:, -1]
        threshold = max(float(np.nanmedian(distance_scale)) * 1.5, 0.0002)
        line_offsets: dict[int, float] = {int(line_ids[0]): 0.0}
        pair_rows = []

        for line_id in line_ids:
            line_mask = out["_line_id"] == line_id
            line = out.loc[line_mask]
            others = out.loc[~line_mask]
            if line.empty or others.empty:
                continue
            other_tree = cKDTree(others[["longitude", "latitude"]].to_numpy(dtype=np.float64))
            distances, indices = other_tree.query(line[["longitude", "latitude"]].to_numpy(dtype=np.float64), k=1)
            for row_idx, dist, other_idx in zip(line.index.to_numpy(), distances, indices):
                if not np.isfinite(dist) or dist > threshold:
                    continue
                other_row = others.iloc[int(other_idx)]
                if int(other_row["_line_id"]) == int(line_id):
                    continue
                pair_rows.append(
                    {
                        "line_a": int(line_id),
                        "line_b": int(other_row["_line_id"]),
                        "diff": float(out.at[row_idx, "magnetic"] - other_row["magnetic"]),
                    }
                )

        if len(pair_rows) < max(2, len(line_ids) - 1):
            report["fallbacks"].append(
                {
                    "stage": "leveling",
                    "requested": "crossover_leveling",
                    "actual": "skipped",
                    "reason": "Not enough crossovers were found to solve line offsets.",
                    "severity": "warning",
                }
            )
            out.attrs["leveling_report"] = report
            return out, "leveling skipped (insufficient crossovers)"

        unresolved = set(map(int, line_ids[1:]))
        while unresolved:
            progress = False
            for pair in pair_rows:
                a = int(pair["line_a"])
                b = int(pair["line_b"])
                diff = float(pair["diff"])
                if a in line_offsets and b not in line_offsets:
                    line_offsets[b] = line_offsets[a] - diff
                    unresolved.discard(b)
                    progress = True
                elif b in line_offsets and a not in line_offsets:
                    line_offsets[a] = line_offsets[b] + diff
                    unresolved.discard(a)
                    progress = True
            if not progress:
                for line_id in list(unresolved):
                    line_offsets[line_id] = 0.0
                    unresolved.discard(line_id)

        before_rmse = float(np.sqrt(np.mean([row["diff"] ** 2 for row in pair_rows])))
        for line_id, offset in line_offsets.items():
            if line_id == int(line_ids[0]):
                continue
            mask = out["_line_id"] == line_id
            out.loc[mask, "magnetic"] = out.loc[mask, "magnetic"] - offset
            report["affected_points"] += int(mask.sum())

        after_diffs = []
        for pair in pair_rows:
            a_off = line_offsets.get(int(pair["line_a"]), 0.0)
            b_off = line_offsets.get(int(pair["line_b"]), 0.0)
            after_diffs.append(float(pair["diff"] - (a_off - b_off)))
        after_rmse = float(np.sqrt(np.mean(np.square(after_diffs)))) if after_diffs else before_rmse

        report.update(
            {
                "status": "completed" if after_rmse <= before_rmse else "degraded",
                "line_offsets": {str(key): float(val) for key, val in line_offsets.items()},
                "crossover_count": int(len(pair_rows)),
                "threshold_degrees": threshold,
                "before_rmse": before_rmse,
                "after_rmse": after_rmse,
            }
        )
        if after_rmse > before_rmse:
            report["warnings"].append("Leveling did not reduce crossover RMSE; QA was downgraded.")

        out.attrs["leveling_report"] = report
        return out, f"leveling complete ({len(pair_rows)} crossovers, RMSE {before_rmse:.2f} -> {after_rmse:.2f} nT)"

    def _prepare_prediction_inputs(self, task: dict, frame: pd.DataFrame) -> dict:
        grid_x, grid_y = self._build_grid(task, frame)
        scenario = self._resolve_scenario(task)

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
            metadata = {
                "scenario": "explicit",
                "observed_points": int(len(train)),
                "prediction_points": int(len(predict)),
                "preserve_observed_values": True,
            }
        elif scenario == "sparse":
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

                def _len_ext(trav, s, e, mid_lat, axis="lon"):
                    if trav.get("length_same_as_original", True):
                        return s, e
                    lv = float(trav.get("length") or 1000)
                    lu = (trav.get("length_unit") or "Metres").lower()
                    lm = lv * (1000 if "kilo" in lu else 0.3048 if "feet" in lu else 1)
                    if axis == "lon":
                        cos_lat = max(abs(math.cos(math.radians(mid_lat))), 1e-6)
                        half = (lm / 111_320) / cos_lat / 2
                    else:
                        half = (lm / 111_320) / 2
                    mid = (s + e) / 2
                    return mid - half, mid + half

                for tidx, trav in enumerate(predicted_traverses):
                    ttype = trav.get("type", "offset")
                    traverse_label = trav.get("label") or f"Predicted Traverse {tidx + 1}"
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
                                ls, le = _len_ext(trav, pts[0][1], pts[-1][1], lat_m, "lon")
                                lons_new = np.arange(ls, le + spacing_deg * 0.5, spacing_deg)
                                for lon in lons_new:
                                    predict_rows.append({
                                        "latitude": lat_m,
                                        "longitude": float(lon),
                                        "point_kind": "infill",
                                        "traverse_label": traverse_label,
                                    })
                            else:
                                pts.sort(key=lambda p: p[0])
                                lon_m = sum(p[1] for p in pts) / len(pts)
                                ls, le = _len_ext(trav, pts[0][0], pts[-1][0], (pts[0][0] + pts[-1][0]) / 2, "lat")
                                lats_new = np.arange(ls, le + spacing_deg * 0.5, spacing_deg)
                                for lat in lats_new:
                                    predict_rows.append({
                                        "latitude": float(lat),
                                        "longitude": lon_m,
                                        "point_kind": "infill",
                                        "traverse_label": traverse_label,
                                    })
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
                                rs, re = pts[0][1] + dlon, pts[-1][1] + dlon
                                ls, le = _len_ext(trav, rs, re, lat_m, "lon")
                                lons_new = np.arange(ls, le + spacing_deg * 0.5, spacing_deg)
                                for lon in lons_new:
                                    predict_rows.append({
                                        "latitude": float(lat_m),
                                        "longitude": float(lon),
                                        "point_kind": "offset",
                                        "traverse_label": traverse_label,
                                    })
                            else:
                                pts.sort(key=lambda p: p[0])
                                lon_m = sum(p[1] for p in pts) / len(pts) + dlon
                                rs, re = pts[0][0] + dlat, pts[-1][0] + dlat
                                ls, le = _len_ext(trav, rs, re, (rs + re) / 2, "lat")
                                lats_new = np.arange(ls, le + spacing_deg * 0.5, spacing_deg)
                                for lat in lats_new:
                                    predict_rows.append({
                                        "latitude": float(lat),
                                        "longitude": float(lon_m),
                                        "point_kind": "offset",
                                        "traverse_label": traverse_label,
                                    })

                predict = pd.DataFrame(predict_rows) if predict_rows else pd.DataFrame({"latitude": [], "longitude": []})
                detail = f"Sparse: {len(train)} measured stations, {len(predicted_traverses)} predicted traverse(s), {len(predict)} predicted points"
                metadata = {
                    "scenario": "sparse",
                    "prediction_geometry": "predicted_traverses",
                    "observed_points": int(len(train)),
                    "prediction_points": int(len(predict)),
                }
            else:
                # Legacy: use grid
                grid_x, grid_y = self._build_grid(task, train)
                predict = pd.DataFrame({"longitude": grid_x.ravel(), "latitude": grid_y.ravel()})
                detail = f"Sparse: {len(train)} measured stations, predicting at {len(predict)} grid nodes"
                metadata = {
                    "scenario": "sparse",
                    "prediction_geometry": "grid",
                    "observed_points": int(len(train)),
                    "prediction_points": int(len(predict)),
                }

        else:
            train = frame.dropna(subset=["magnetic"]).reset_index(drop=True)
            if train.empty:
                raise ValueError("No rows with magnetic field values found.")
            predict = pd.DataFrame({"latitude": [], "longitude": []})
            detail = f"Automatic: {len(train)} measured stations will be processed without prediction targets"
            metadata = {
                "scenario": "automatic",
                "observed_points": int(len(train)),
                "prediction_points": 0,
                "preserve_observed_values": True,
            }

        return {
            "frame": train,
            "train_frame": train,
            "predict_frame": predict,
            "grid_x": grid_x,
            "grid_y": grid_y,
            "detail": detail,
            "scenario": scenario,
            "metadata": metadata,
        }

    def _build_grid(self, task: dict, frame: pd.DataFrame):
        spacing_value = float(task.get("station_spacing") or 20)
        spacing_unit = (task.get("station_spacing_unit") or "Metres").lower()
        spacing_metres = spacing_value * (1000 if "kilo" in spacing_unit else 0.3048 if "feet" in spacing_unit else 1)
        observed_spacing = None
        if "_line_id" in frame.columns and "along_line_m" in frame.columns:
            spacing_samples = []
            for _, line in frame.groupby("_line_id"):
                along = np.sort(line["along_line_m"].to_numpy(dtype=np.float64))
                diffs = np.diff(along)
                diffs = diffs[np.isfinite(diffs) & (diffs > 0)]
                if diffs.size:
                    spacing_samples.extend(diffs.tolist())
            if spacing_samples:
                observed_spacing = float(np.median(spacing_samples))
        base_spacing_m = observed_spacing if observed_spacing and observed_spacing > 0 else spacing_metres
        spacing_degrees = max(base_spacing_m / 111_320, 0.0002)

        lon_min, lon_max = frame["longitude"].min(), frame["longitude"].max()
        lat_min, lat_max = frame["latitude"].min(), frame["latitude"].max()

        scenario = self._resolve_scenario(task)
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
        predictor = self._build_rf_predictor(x, y, z)
        ml_surface, rf_variance = self._predict_rf_surface(predictor, grid_x, grid_y)
        train_ml, _ = self._predict_rf_surface(predictor, x, y)
        train_ml = np.asarray(train_ml, dtype=np.float64).reshape(-1)
        residuals = z - train_ml
        hybrid_surface = None
        hybrid_variance = None
        hybrid_metadata = {}
        if predictor is not None and len(residuals) >= 4:
            residual_surface, residual_variance = self._krige(x, y, residuals, grid_x, grid_y)
            hybrid_surface = ml_surface + residual_surface
            hybrid_variance = residual_variance + rf_variance
            hybrid_metadata = {
                "algorithm": "rf_trend_plus_kriged_residual",
                "residual_std": float(np.nanstd(residuals)),
            }

        model_metadata = {"requested_model": requested_model, "warnings": []}
        if "kriging" in requested_model:
            surface = kriging_surface
            model_used = "kriging"
            variance = kriging_variance
            model_metadata["algorithm"] = "variogram_rbf_or_pykrige"
        elif "hybrid" in requested_model:
            if hybrid_surface is not None:
                surface = hybrid_surface
                variance = hybrid_variance
                model_metadata.update(hybrid_metadata)
            else:
                surface = (kriging_surface + ml_surface) / 2.0
                variance = (kriging_variance + rf_variance) / 2.0
                model_metadata["algorithm"] = "weighted_blend_fallback"
                model_metadata["warnings"].append("Hybrid residual kriging was unavailable, so a weighted blend fallback was used.")
            model_used = "hybrid"
        else:
            surface = ml_surface
            model_used = "machine_learning"
            variance = rf_variance
            model_metadata["algorithm"] = "random_forest_surface"

        uncertainty = self._uncertainty_surface(x, y, grid_x, grid_y, variance, rf_variance)
        anomaly_threshold = float(np.nanmean(surface) + np.nanstd(surface))
        anomaly_mask = surface >= anomaly_threshold
        scenario = self._resolve_scenario(task)
        support_tree = cKDTree(np.column_stack([x, y]))
        support_distance, _ = support_tree.query(np.column_stack([grid_x.ravel(), grid_y.ravel()]), k=1)
        support_distance = support_distance.reshape(grid_x.shape)
        support_mask = support_distance <= max(float(np.nanmedian(support_distance)) * 2.5, 0.0005)
        rmse = float(np.sqrt(mean_squared_error(z, train_ml))) if len(train_ml) == len(z) and len(z) else None
        mae = float(mean_absolute_error(z, train_ml)) if len(train_ml) == len(z) and len(z) else None
        r2 = float(r2_score(z, train_ml)) if len(train_ml) == len(z) and len(z) > 1 else None
        model_metadata.update(
            {
                "rmse": rmse,
                "mae": mae,
                "r2": r2,
                "support_fraction": float(np.mean(support_mask)),
            }
        )

        result = {
            "grid_x": grid_x,
            "grid_y": grid_y,
            "surface": surface,
            "uncertainty": uncertainty,
            "model_used": model_used,
            "rf_variance": rf_variance,
            "model_metadata": model_metadata,
            "support_mask": support_mask.tolist(),
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
            "uncertainty_metadata": {
                "algorithm": "distance_variance_density",
                "detail": "Combined distance, model variance, and density penalties were synthesized",
                "warnings": [],
            },
        }
        if scenario == "sparse" and {"latitude", "longitude"}.issubset(prep["predict_frame"].columns):
            predicted_points = []
            grid_x = np.asarray(result["grid_x"], dtype=float)
            grid_y = np.asarray(result["grid_y"], dtype=float)
            surface_array = np.asarray(surface, dtype=float)
            for _, row in prep["predict_frame"].head(600).iterrows():
                record = row.to_dict()
                lat = float(record.get("latitude"))
                lon = float(record.get("longitude"))
                if np.isfinite(lat) and np.isfinite(lon) and grid_x.ndim >= 2 and grid_y.ndim >= 2 and surface_array.ndim >= 2:
                    row_idx = int(np.argmin(np.abs(grid_y[:, 0] - lat)))
                    col_idx = int(np.argmin(np.abs(grid_x[0, :] - lon)))
                    predicted_value = float(surface_array[row_idx, col_idx])
                    record["magnetic"] = predicted_value
                    record["predicted_magnetic"] = predicted_value
                predicted_points.append(record)
            result["predicted_points"] = predicted_points
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
        try:
            res = griddata((x, y), z, (grid_x, grid_y), method="cubic")
        except Exception:
            try:
                res = griddata((x, y), z, (grid_x, grid_y), method="linear")
            except Exception:
                res = self._nearest_surface(x, y, z, grid_x, grid_y)
        if np.isnan(res).any():
            try:
                res2 = griddata((x, y), z, (grid_x, grid_y), method="linear")
                res = np.where(np.isnan(res), res2, res)
            except Exception:
                res = np.where(np.isnan(res), self._nearest_surface(x, y, z, grid_x, grid_y), res)
        res = np.where(np.isnan(res), float(np.nanmean(z)), res).astype(np.float64)
        return res, np.zeros(grid_x.shape, dtype=np.float64)

    def _build_rf_predictor(self, x, y, z):
        if len(z) < 4:
            return None

        train_tree = KDTree(np.column_stack([x, y]))

        def _augment(fx, fy):
            base = np.column_stack([fx, fy])
            k = min(5, len(x) - 1)
            if k < 1:
                return base
            pts = np.column_stack([fx, fy])
            dist, _ = train_tree.query(pts, k=k + 1)
            mean_nn = np.mean(dist[:, 1:k + 1], axis=1).reshape(-1, 1)
            radius = 2.0 * float(np.median(mean_nn)) + 1e-9
            counts = np.array(train_tree.query_ball_point(pts, r=radius, return_length=True), dtype=np.float64).reshape(-1, 1)
            return np.column_stack([base, mean_nn, counts])

        feat_tr = _augment(x, y)
        scaler = StandardScaler()
        feat_tr_n = scaler.fit_transform(feat_tr)
        rf = RandomForestRegressor(n_estimators=120, random_state=7, n_jobs=1)
        rf.fit(feat_tr_n, z)
        return {"augment": _augment, "scaler": scaler, "model": rf}

    def _predict_rf_surface(self, predictor, px, py):
        if predictor is None:
            shape = np.shape(px)
            zeros = np.zeros(shape, dtype=np.float64)
            return zeros, zeros

        feat_pred = predictor["augment"](np.ravel(px), np.ravel(py))
        feat_pred_n = predictor["scaler"].transform(feat_pred)
        tree_preds = np.array([tree.predict(feat_pred_n) for tree in predictor["model"].estimators_])
        mean = tree_preds.mean(axis=0).reshape(np.shape(px)).astype(np.float64)
        var = tree_preds.var(axis=0).reshape(np.shape(px)).astype(np.float64)
        return mean, var

    def _rf_surface(self, x, y, z, grid_x, grid_y):
        """
        Random Forest surface with augmented features and ensemble variance.
        Returns (surface, rf_variance_surface).
        """
        if len(z) < 4:
            flat = np.full(grid_x.shape, float(np.mean(z)), dtype=np.float64)
            return flat, np.zeros(grid_x.shape, dtype=np.float64)
        predictor = self._build_rf_predictor(x, y, z)
        return self._predict_rf_surface(predictor, grid_x, grid_y)

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
        Combined uncertainty from model variance, distance-to-data, and local density.
        """
        tree = cKDTree(np.column_stack([x, y]))
        distance, _ = tree.query(np.column_stack([grid_x.ravel(), grid_y.ravel()]), k=1)
        dist_surface = distance.reshape(grid_x.shape)
        dist_norm = dist_surface / max(float(np.nanmax(dist_surface)), 1e-6)
        variance_norm = variance / max(float(np.nanmax(variance)), 1e-6)
        neighbour_dist, _ = tree.query(np.column_stack([grid_x.ravel(), grid_y.ravel()]), k=min(4, len(x)))
        if neighbour_dist.ndim == 1:
            density_term = neighbour_dist.reshape(grid_x.shape)
        else:
            density_term = np.mean(neighbour_dist, axis=1).reshape(grid_x.shape)
        density_norm = density_term / max(float(np.nanmax(density_term)), 1e-6)
        base_unc = ((dist_norm + variance_norm + density_norm) / 3.0) * 100.0

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
        metadata = {"warnings": [], "fallbacks": [], "layer_labels": {}}

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
        if rtp_inc is None or rtp_dec is None:
            metadata["fallbacks"].append(
                {
                    "stage": "rtp",
                    "requested": "reduction_to_pole",
                    "actual": "mean_centered_surface",
                    "reason": "Inclination or declination was missing, so RTP could not be computed physically.",
                    "severity": "warning",
                }
            )
            metadata["warnings"].append("RTP inputs were incomplete; a mean-centred fallback surface was produced instead.")

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
        regional_residual = surface - gaussian_filter(surface, sigma=sigma) if sigma > 0 else np.zeros_like(surface)
        metadata["layer_labels"]["emag2_residual"] = "Regional residual"
        metadata["layer_labels"]["regional_residual"] = "Regional residual"

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
            "emag2_residual": regional_residual.tolist(),
            "regional_residual": regional_residual.tolist(),
            "rtp_surface": rtp_surface.tolist(),
            "tilt_derivative": tilt.tolist(),
            "total_gradient": total_grad.tolist(),
            "selected_add_ons": add_ons,
            "detail": ", ".join(detail_items) if detail_items else "No add-on layers were requested",
            "metadata": metadata,
        }

    # ── Stage 7: Persist (unchanged) ────────────────────────────────────────

    def _build_qa_report(self, task: dict, prep: dict, results: dict, add_ons: dict, runtime: ProcessingRuntime) -> dict:
        correction_report = runtime.stage_reports[2]["metadata"] if len(runtime.stage_reports) > 2 else {}
        leveling_report = runtime.stage_reports[3]["metadata"] if len(runtime.stage_reports) > 3 else {}
        integrity = _validate_integrity(
            np.asarray(results["surface"], dtype=np.float64),
            prep["train_frame"]["magnetic"].to_numpy(dtype=np.float64),
            prep["frame"]["magnetic"].to_numpy(dtype=np.float64),
        )
        model_meta = results.get("model_metadata") or {}
        quality_score = _compute_quality_score(
            integrity,
            bool(correction_report.get("igrf_applied")),
            model_meta.get("rmse"),
            float(np.nanstd(prep["frame"]["magnetic"].to_numpy(dtype=np.float64))) if len(prep["frame"]) else 0.0,
        )
        warnings = list(runtime.warnings)
        warnings.extend(add_ons.get("metadata", {}).get("warnings") or [])
        blocking_issues = []
        if any(item.get("severity") == "critical" for item in runtime.fallback_events):
            blocking_issues.append("One or more requested scientific paths could not be run physically and were downgraded.")
        qa_status = "valid"
        if blocking_issues:
            qa_status = "degraded"
        elif warnings:
            qa_status = "valid_with_warnings"

        return QAReport(
            status=qa_status,
            warnings=warnings,
            blocking_issues=blocking_issues,
            validation=ValidationSummary(**(runtime.validation_summary or {})) if runtime.validation_summary else None,
            fallback_events=[ProcessingFallbackEvent(**item) for item in runtime.fallback_events],
            correction_path=list(runtime.correction_path),
            crossover=leveling_report,
            lag=correction_report.get("lag", {}),
            heading=correction_report.get("heading", {}),
            model=model_meta,
            uncertainty=results.get("uncertainty_metadata") or {},
            derived_layers=add_ons.get("metadata") or {},
            integrity=integrity,
            quality_score=quality_score,
            metadata={
                "scenario": prep.get("scenario"),
                "observed_points": int(len(prep["train_frame"])),
                "predicted_points": int(len(prep["predict_frame"])),
                "support_fraction": model_meta.get("support_fraction"),
            },
        ).model_dump(mode="json")

    def _persist_outputs(
        self,
        task: dict,
        prep: dict,
        results: dict,
        add_ons: dict,
        qa_report: dict | None = None,
        validation_summary: dict | None = None,
    ) -> dict:
        payload = {
            "grid_x": results["grid_x"].tolist(),
            "grid_y": results["grid_y"].tolist(),
            "surface": results["surface"].tolist(),
            "uncertainty": results["uncertainty"].tolist(),
            "points": results["points"],
            "stats": results["stats"],
            "model_used": results["model_used"],
            "model_metadata": results.get("model_metadata") or {},
            "uncertainty_metadata": results.get("uncertainty_metadata") or {},
            "support_mask": results.get("support_mask"),
            "validation_summary": validation_summary or {},
            "qa_report": qa_report or {},
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
                    "filtered_surface", "emag2_residual", "regional_residual", "rtp_surface",
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
