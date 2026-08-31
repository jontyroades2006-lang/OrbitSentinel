from __future__ import annotations

import math
from datetime import datetime

from . import data as data_mod
from .model import get_model


def estimate_position_error_km(satrec, at_time: datetime, tca_time: datetime) -> dict:
    """Estimate expected SGP4 position error (km) for `satrec` at `tca_time`,
    given the TLE was generated/loaded as of `at_time` (used for age)."""
    model = get_model()
    summary = data_mod.orbital_elements_summary(satrec)
    tle_age = data_mod.tle_age_days(satrec, at_time)
    propagation_hours = (tca_time - at_time).total_seconds() / 3600.0

    error_km = model.predict_error_km(
        propagation_hours=max(propagation_hours, 0.0),
        tle_age_days=max(tle_age, 0.0),
        perigee_alt_km=summary["perigee_alt_km"],
        eccentricity=summary["eccentricity"],
        inclination_deg=summary["inclination_deg"],
    )
    return {
        "error_km": round(error_km, 3),
        "propagation_hours": round(propagation_hours, 2),
        "tle_age_days": round(tle_age, 2),
    }


def combined_uncertainty(sat_a_record, sat_b_record, reference_time: datetime,
                          tca_time: datetime) -> dict:
    """Combine independent per-object errors into a joint miss-distance
    uncertainty (root-sum-square, a standard approach for combining
    independent covariances along the miss-distance axis)."""
    err_a = estimate_position_error_km(sat_a_record.satrec, reference_time, tca_time)
    err_b = estimate_position_error_km(sat_b_record.satrec, reference_time, tca_time)
    combined_km = math.sqrt(err_a["error_km"] ** 2 + err_b["error_km"] ** 2)
    return {
        "object_a_error_km": err_a["error_km"],
        "object_b_error_km": err_b["error_km"],
        "combined_uncertainty_km": round(combined_km, 3),
        "object_a_details": err_a,
        "object_b_details": err_b,
    }


def confidence_from_miss_distance(miss_distance_km: float, combined_uncertainty_km: float) -> dict:
    """Convert (miss distance, uncertainty) into a human-readable confidence
    label and a 0-1 numeric confidence score.

    Heuristic: if the predicted miss distance is many uncertainty-widths
    away from zero, we're confident about the *separation* (whether or not
    it's risky). If the miss distance is comparable to or smaller than the
    uncertainty, the prediction is "shaky" — the objects might actually
    pass closer or farther than predicted.
    """
    if combined_uncertainty_km <= 1e-6:
        ratio = 999.0
    else:
        ratio = miss_distance_km / combined_uncertainty_km

    # Logistic-style squashing of the ratio into a 0-1 confidence score.
    score = 1.0 / (1.0 + math.exp(-1.1 * (ratio - 1.5)))
    score = max(0.02, min(0.99, score))

    if score >= 0.75:
        label = "high"
    elif score >= 0.45:
        label = "medium"
    else:
        label = "low"

    return {
        "confidence_score": round(score, 3),
        "confidence_pct": round(score * 100, 1),
        "confidence_label": label,
        "miss_to_uncertainty_ratio": round(ratio, 2) if ratio < 999 else None,
    }
