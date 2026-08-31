from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np

from . import data as data_mod


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _ensure_utc(dt: datetime) -> datetime:
    """Return a timezone-aware UTC datetime."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


def _distance_and_relative_speed(
    sat_a,
    sat_b,
    t: datetime,
):
    """
    Propagate both satellites at time t.

    Returns:
        distance_km
        relative_speed_km_s
    """

    t = _ensure_utc(t)

    pos_a, vel_a = data_mod.propagate_eci(sat_a, t)
    pos_b, vel_b = data_mod.propagate_eci(sat_b, t)

    pos_a = np.asarray(pos_a, dtype=float)
    pos_b = np.asarray(pos_b, dtype=float)

    vel_a = np.asarray(vel_a, dtype=float)
    vel_b = np.asarray(vel_b, dtype=float)

    relative_position = pos_a - pos_b
    relative_velocity = vel_a - vel_b

    distance_km = float(np.linalg.norm(relative_position))
    relative_speed_km_s = float(np.linalg.norm(relative_velocity))

    return distance_km, relative_speed_km_s


# --------------------------------------------------------------------------
# Hard-body radius
# --------------------------------------------------------------------------

def hard_body_radius_km(
    object_type_a: str | None,
    object_type_b: str | None,
) -> float:
    """
    Return a conservative combined hard-body radius in km.

    These are prototype-level values used by OrbitSentinel's
    decision-support risk model.
    """

    def radius_for_type(object_type: str | None) -> float:
        if not object_type:
            return 0.005

        value = str(object_type).strip().lower()

        if "debris" in value:
            return 0.005

        if "rocket" in value or "r/b" in value:
            return 0.010

        if "inactive" in value or "dead" in value:
            return 0.010

        # Active / operational / unknown spacecraft
        return 0.015

    return radius_for_type(object_type_a) + radius_for_type(object_type_b)


# --------------------------------------------------------------------------
# Close approach calculation
# --------------------------------------------------------------------------

def find_close_approach(
    sat_a,
    sat_b,
    start: datetime,
    end: datetime,
    coarse_step_seconds: float = 30.0,
) -> dict:
    """
    Find the closest approach between two satellites.

    The calculation:
        1. Samples the orbits using the requested coarse step.
        2. Finds the sample with minimum separation.
        3. Refines the minimum using a golden-section search.
        4. Returns TCA, miss distance and relative velocity.

    All distances are in km.
    All velocities are in km/s.
    """

    start = _ensure_utc(start)
    end = _ensure_utc(end)

    if end <= start:
        raise ValueError("end time must be after start time")

    try:
        coarse_step_seconds = float(coarse_step_seconds)
    except (TypeError, ValueError):
        coarse_step_seconds = 30.0

    if not math.isfinite(coarse_step_seconds) or coarse_step_seconds <= 0:
        coarse_step_seconds = 30.0

    # Prevent an accidentally enormous number of samples.
    coarse_step_seconds = max(1.0, coarse_step_seconds)

    # ----------------------------------------------------------------------
    # 1. Coarse search
    # ----------------------------------------------------------------------

    samples: list[tuple[datetime, float]] = []

    t = start

    while t <= end:
        distance_km, _ = _distance_and_relative_speed(
            sat_a,
            sat_b,
            t,
        )

        if math.isfinite(distance_km):
            samples.append((t, distance_km))

        t += timedelta(seconds=coarse_step_seconds)

    # Make sure the end point is included.
    if not samples or samples[-1][0] < end:
        distance_km, _ = _distance_and_relative_speed(
            sat_a,
            sat_b,
            end,
        )

        if math.isfinite(distance_km):
            samples.append((end, distance_km))

    if not samples:
        raise RuntimeError(
            "Unable to propagate either satellite during the search window."
        )

    # Find coarse minimum.
    min_index = min(
        range(len(samples)),
        key=lambda i: samples[i][1],
    )

    best_time = samples[min_index][0]
    best_distance = samples[min_index][1]

    # ----------------------------------------------------------------------
    # 2. Create refinement bracket
    # ----------------------------------------------------------------------

    left_index = max(0, min_index - 1)
    right_index = min(len(samples) - 1, min_index + 1)

    left_time = samples[left_index][0]
    right_time = samples[right_index][0]

    # If the minimum happens at a boundary, refine inside a reasonable
    # bracket around that boundary without moving outside the search window.
    if left_time == right_time:

        half_step = timedelta(seconds=coarse_step_seconds)

        left_time = max(
            start,
            best_time - half_step,
        )

        right_time = min(
            end,
            best_time + half_step,
        )

    # ----------------------------------------------------------------------
    # 3. Golden-section refinement
    # ----------------------------------------------------------------------

    golden_ratio = (math.sqrt(5.0) - 1.0) / 2.0

    for _ in range(50):

        span_seconds = (
            right_time - left_time
        ).total_seconds()

        if span_seconds <= 0.05:
            break

        t1 = left_time + timedelta(
            seconds=(1.0 - golden_ratio) * span_seconds
        )

        t2 = left_time + timedelta(
            seconds=golden_ratio * span_seconds
        )

        d1, _ = _distance_and_relative_speed(
            sat_a,
            sat_b,
            t1,
        )

        d2, _ = _distance_and_relative_speed(
            sat_a,
            sat_b,
            t2,
        )

        if d1 < d2:

            right_time = t2

            if d1 < best_distance:
                best_distance = d1
                best_time = t1

        else:

            left_time = t1

            if d2 < best_distance:
                best_distance = d2
                best_time = t2

    # Check the final bracket midpoint as well.
    midpoint = left_time + (
        right_time - left_time
    ) / 2

    midpoint_distance, _ = _distance_and_relative_speed(
        sat_a,
        sat_b,
        midpoint,
    )

    if midpoint_distance < best_distance:
        best_distance = midpoint_distance
        best_time = midpoint

    # ----------------------------------------------------------------------
    # 4. Final relative velocity
    # ----------------------------------------------------------------------

    final_distance, relative_speed = _distance_and_relative_speed(
        sat_a,
        sat_b,
        best_time,
    )

    best_distance = min(
        best_distance,
        final_distance,
    )

    # ----------------------------------------------------------------------
    # 5. Coarse timeline for frontend/debugging
    # ----------------------------------------------------------------------

    coarse_timeline = [
        {
            "time": sample_time.isoformat(),
            "separation_km": round(distance, 3),
        }
        for sample_time, distance in samples
    ]

    # ----------------------------------------------------------------------
    # 6. Return result
    # ----------------------------------------------------------------------

    return {
        "tca_utc": best_time.isoformat(),

        "miss_distance_km": round(
            float(best_distance),
            4,
        ),

        "relative_speed_km_s": round(
            float(relative_speed),
            4,
        ),

        "coarse_timeline": coarse_timeline,
    }
