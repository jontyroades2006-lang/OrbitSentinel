"""
risk.py — OrbitSentinel risk scoring.

The score combines:

    1. Miss distance
    2. Relative velocity
    3. Mission criticality
    4. Prediction confidence

The distance component uses a smooth exponential decay rather than
a hard 100 km cutoff. This allows the What-If simulator to show
meaningful risk changes even when the miss distance is >100 km.
"""

from __future__ import annotations

import math


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _safe_exp(value: float) -> float:
    """
    Safe exponential to prevent math range errors.
    """
    value = max(-60.0, min(60.0, float(value)))
    return math.exp(value)


def _severity_score(
    miss_distance_km: float,
    relative_speed_km_s: float,
    combined_hard_body_radius_km: float,
) -> float:
    """
    Convert physical conjunction parameters into a 0–1 severity.

    Distance uses an exponential decay so that:
        10 km  -> very high severity
        50 km  -> high severity
        100 km -> moderate severity
        200+ km -> lower, but still distinguishable severity

    Relative speed increases severity because a faster encounter
    provides less time for intervention.
    """

    miss_distance_km = max(0.0, float(miss_distance_km))
    relative_speed_km_s = max(0.0, float(relative_speed_km_s))
    combined_hard_body_radius_km = max(
        0.01,
        float(combined_hard_body_radius_km),
    )

    # Express miss distance relative to the combined physical radius.
    radii_multiple = miss_distance_km / combined_hard_body_radius_km

    # Smooth distance severity.
    #
    # ~0.5 at roughly 100 km
    # ~0.25 around 200 km
    # still changes smoothly at larger distances.
    distance_severity = _safe_exp(-miss_distance_km / 100.0)

    # Stronger weighting around the actual hard-body region.
    hard_body_factor = 1.0 / (
        1.0 + max(0.0, radii_multiple - 1.0) / 8.0
    )

    # Relative velocity factor.
    speed_factor = _clamp(
        1.0 + relative_speed_km_s / 20.0,
        1.0,
        1.5,
    )

    severity = (
        distance_severity
        * hard_body_factor
        * speed_factor
    )

    return _clamp(severity)


def _log_scale(
    value: float,
    low: float,
    high: float,
) -> float:
    """
    Normalize a value to [0,1] using a logarithmic scale.
    """

    value = max(0.0, float(value))
    low = max(0.0, float(low))
    high = max(low + 0.001, float(high))

    lo = math.log(low + 1.0)
    hi = math.log(high + 1.0)
    v = math.log(value + 1.0)

    return _clamp((v - lo) / (hi - lo))


def _metadata_value(
    obj: dict,
    key: str,
    default: float,
) -> float:
    """
    Safely retrieve a numeric metadata field.
    """

    try:
        value = obj.get(key, default)

        if value is None:
            return float(default)

        return float(value)

    except (TypeError, ValueError):
        return float(default)


def _criticality_score(obj: dict) -> float:
    """
    Calculate mission criticality from satellite metadata.

    Supported metadata:

        mission_criticality
        population_served
        population_millions
        replacement_cost
        replacement_cost_musd
    """

    mission = _metadata_value(
        obj,
        "mission_criticality",
        0.70,
    )

    population = _metadata_value(
        obj,
        "population_millions",
        _metadata_value(obj, "population_served", 10.0),
    )

    replacement = _metadata_value(
        obj,
        "replacement_cost_musd",
        _metadata_value(obj, "replacement_cost", 100.0),
    )

    mission = _clamp(mission)

    population_norm = _log_scale(
        population,
        0.0,
        500.0,
    )

    replacement_norm = _log_scale(
        replacement,
        0.0,
        1000.0,
    )

    score = (
        0.50 * mission
        + 0.25 * population_norm
        + 0.25 * replacement_norm
    )

    return _clamp(score)


def _risk_category(score: float) -> str:
    """
    Convert numeric risk into a human-readable category.
    """

    if score >= 75:
        return "CRITICAL"

    if score >= 50:
        return "HIGH"

    if score >= 25:
        return "ELEVATED"

    return "LOW"


def compute_risk(
    miss_distance_km: float,
    relative_speed_km_s: float,
    object_a: dict,
    object_b: dict,
    combined_hard_body_radius_km: float,
    confidence: float | None = None,
    weights: dict | None = None,
) -> dict:
    """
    Calculate the final OrbitSentinel risk score.

    Returns a dictionary so the frontend can display both the
    final score and the individual components.
    """

    miss_distance_km = max(
        0.0,
        float(miss_distance_km),
    )

    relative_speed_km_s = max(
        0.0,
        float(relative_speed_km_s),
    )

    if confidence is None:
        confidence = 0.90

    confidence = _clamp(confidence)

    weights = weights or {
        "distance": 0.40,
        "velocity": 0.15,
        "criticality": 0.30,
        "confidence": 0.15,
    }

    # Normalize weights in case the caller provides
    # weights that do not sum exactly to 1.
    weight_total = sum(
        max(0.0, float(v))
        for v in weights.values()
    )

    if weight_total <= 0:
        weights = {
            "distance": 0.40,
            "velocity": 0.15,
            "criticality": 0.30,
            "confidence": 0.15,
        }
        weight_total = 1.0

    distance_weight = weights["distance"] / weight_total
    velocity_weight = weights["velocity"] / weight_total
    criticality_weight = weights["criticality"] / weight_total
    confidence_weight = weights["confidence"] / weight_total

    # ----------------------------------------------------------
    # Distance component
    # ----------------------------------------------------------

    distance_component = _safe_exp(
        -miss_distance_km / 100.0
    )

    # ----------------------------------------------------------
    # Velocity component
    # ----------------------------------------------------------

    velocity_component = _clamp(
        relative_speed_km_s / 15.0
    )

    # ----------------------------------------------------------
    # Criticality component
    # ----------------------------------------------------------

    criticality_a = _criticality_score(object_a)
    criticality_b = _criticality_score(object_b)

    criticality = max(
        criticality_a,
        criticality_b,
    )

    # ----------------------------------------------------------
    # Final score
    # ----------------------------------------------------------

    score = 100.0 * (
        distance_weight * distance_component
        + velocity_weight * velocity_component
        + criticality_weight * criticality
        + confidence_weight * confidence
    )

    score = max(
        0.0,
        min(100.0, score),
    )

    return {
        "risk_score": round(score, 1),
        "risk_category": _risk_category(score),

        "components": {
            "distance": round(distance_component, 4),
            "velocity": round(velocity_component, 4),
            "criticality": round(criticality, 4),
            "confidence": round(confidence, 4),
        },

        "weights": {
            "distance": round(distance_weight, 4),
            "velocity": round(velocity_weight, 4),
            "criticality": round(criticality_weight, 4),
            "confidence": round(confidence_weight, 4),
        },

        "criticality": {
            "primary": round(criticality_a, 4),
            "secondary": round(criticality_b, 4),
        },

        "inputs": {
            "miss_distance_km": round(
                miss_distance_km,
                4,
            ),
            "relative_speed_km_s": round(
                relative_speed_km_s,
                4,
            ),
            "confidence": round(
                confidence,
                4,
            ),
            "hard_body_radius_km": round(
                combined_hard_body_radius_km,
                4,
            ),
        },
    }