from datetime import datetime, timedelta
import math

from . import conjunction as conj_mod
from . import data as data_mod


# ============================================================
# WHAT-IF SIMULATION ENGINE
# ============================================================

def run_what_if(
    rec_a,
    rec_b,
    maneuver_time,
    start,
    end,
    altitude_change_km=None,
    delta_v_rtn_m_s=None,
):
    """
    Run a what-if maneuver on the primary satellite.

    The primary satellite is modified while the secondary
    satellite remains unchanged.

    Supported modes:
        1. altitude_change_km
        2. delta_v_rtn_m_s = (radial, transverse, normal) m/s

    Returns:
        dict containing modified conjunction information and
        modified trajectory for visualization.
    """

    if altitude_change_km is None and delta_v_rtn_m_s is None:
        raise ValueError(
            "provide altitude_change_km or delta_v_rtn_m_s"
        )

    if altitude_change_km is not None and delta_v_rtn_m_s is not None:
        raise ValueError(
            "provide only one maneuver type at a time"
        )

    if maneuver_time < start:
        raise ValueError(
            "maneuver time cannot be before simulation start"
        )

    if maneuver_time > end:
        raise ValueError(
            "maneuver time cannot be after simulation end"
        )

    # --------------------------------------------------------
    # ORIGINAL TRACKS
    # --------------------------------------------------------

    primary_track = data_mod.propagate_track(
        rec_a.satrec,
        start,
        end,
        step_seconds=30,
    )

    secondary_track = data_mod.propagate_track(
        rec_b.satrec,
        start,
        end,
        step_seconds=30,
    )

    if not primary_track:
        raise ValueError(
            "unable to generate primary satellite trajectory"
        )

    if not secondary_track:
        raise ValueError(
            "unable to generate secondary satellite trajectory"
        )

    # --------------------------------------------------------
    # CREATE MODIFIED TRACK
    # --------------------------------------------------------

    modified_track = []

    # Convert altitude change to a simple orbital-radius
    # adjustment.  This is a directional what-if model,
    # not a full maneuver/propulsion model.
    altitude_delta = 0.0

    if altitude_change_km is not None:
        altitude_delta = float(altitude_change_km)

    # Delta-V RTN
    dv_rtn = None

    if delta_v_rtn_m_s is not None:
        if not isinstance(delta_v_rtn_m_s, (list, tuple)):
            raise ValueError(
                "delta_v_rtn_m_s must contain three values"
            )

        if len(delta_v_rtn_m_s) != 3:
            raise ValueError(
                "delta_v_rtn_m_s must contain exactly "
                "three values: radial, transverse, normal"
            )

        try:
            dv_rtn = tuple(
                float(x) for x in delta_v_rtn_m_s
            )
        except (TypeError, ValueError):
            raise ValueError(
                "delta_v_rtn_m_s values must be numeric"
            )

    # --------------------------------------------------------
    # MANEUVER MODEL
    # --------------------------------------------------------

    # Estimate an equivalent altitude displacement from RTN
    # delta-V when that mode is selected.
    #
    # This is intentionally conservative and directional.
    # It is designed for the decision-support visualization,
    # not for operational maneuver execution.

    if dv_rtn is not None:

        radial_dv = dv_rtn[0]
        transverse_dv = dv_rtn[1]
        normal_dv = dv_rtn[2]

        # Approximate displacement accumulated after maneuver.
        #
        # The factors below keep the visualization physically
        # reasonable without pretending to be a high-fidelity
        # orbital maneuver solver.
        altitude_delta = radial_dv * 0.25

        # Transverse and normal components are retained so
        # that the trajectory can also receive directional
        # offsets.
        cross_track_offset = transverse_dv * 0.02
        normal_offset = normal_dv * 0.02

    else:
        cross_track_offset = 0.0
        normal_offset = 0.0

    # --------------------------------------------------------
    # BUILD MODIFIED PRIMARY TRAJECTORY
    # --------------------------------------------------------

    for point in primary_track:

        # Support the common track dictionary formats.
        if isinstance(point, dict):

            timestamp = (
                point.get("time")
                or point.get("time_iso")
                or point.get("timestamp")
            )

            # data.propagate_track() stores ECI coordinates as a
            # nested [x, y, z] list under "position_km" — pull that
            # apart first, and only fall back to flat x/y/z (or
            # x_km/y_km/z_km) keys for other track formats.
            pos_km = point.get("position_km")

            if isinstance(pos_km, (list, tuple)) and len(pos_km) == 3:
                x, y, z = pos_km
            else:
                x = point.get("x", point.get("x_km"))
                y = point.get("y", point.get("y_km"))
                z = point.get("z", point.get("z_km"))

        else:
            continue

        if timestamp is None:
            continue

        if x is None or y is None or z is None:
            continue

        try:
            t = datetime.fromisoformat(
                str(timestamp).replace("Z", "+00:00")
            )
        except ValueError:
            continue

        x = float(x)
        y = float(y)
        z = float(z)

        # Before maneuver -> original trajectory
        if t < maneuver_time:

            modified_track.append(
                {
                    "time": str(timestamp),
                    "x": x,
                    "y": y,
                    "z": z,
                }
            )

            continue

        # ----------------------------------------------------
        # APPLY MODIFICATION
        # ----------------------------------------------------

        radius = math.sqrt(
            x * x +
            y * y +
            z * z
        )

        if radius <= 0:
            modified_track.append(
                {
                    "time": str(timestamp),
                    "x": x,
                    "y": y,
                    "z": z,
                }
            )
            continue

        # Radial displacement
        radial_shift = altitude_delta

        scale = (
            radius + radial_shift
        ) / radius

        new_x = x * scale
        new_y = y * scale
        new_z = z * scale

        # Apply small directional offsets for RTN mode.
        #
        # These offsets are deliberately small because this
        # module is a what-if decision-support model.
        if dv_rtn is not None:

            horizontal_radius = math.sqrt(
                new_x * new_x +
                new_y * new_y
            )

            if horizontal_radius > 0:

                new_x += (
                    -new_y /
                    horizontal_radius
                ) * cross_track_offset

                new_y += (
                    new_x /
                    horizontal_radius
                ) * cross_track_offset

            new_z += normal_offset

        modified_track.append(
            {
                "time": str(timestamp),
                "x": new_x,
                "y": new_y,
                "z": new_z,
            }
        )

    if not modified_track:
        raise ValueError(
            "unable to generate modified trajectory"
        )

    # --------------------------------------------------------
    # FIND MODIFIED CLOSE APPROACH
    # --------------------------------------------------------
    #
    # We calculate the modified conjunction directly from
    # the generated tracks instead of calling
    # find_close_approach(), because that function propagates
    # the original SGP4 satellites and therefore would ignore
    # the maneuver.
    # --------------------------------------------------------

    secondary_by_time = {}

    for point in secondary_track:

        if not isinstance(point, dict):
            continue

        timestamp = (
            point.get("time")
            or point.get("time_iso")
            or point.get("timestamp")
        )

        if timestamp is None:
            continue

        # Same fix as above: pull x/y/z out of the nested
        # "position_km" list produced by data.propagate_track().
        pos_km = point.get("position_km")

        if isinstance(pos_km, (list, tuple)) and len(pos_km) == 3:
            x, y, z = pos_km
        else:
            x = point.get("x", point.get("x_km"))
            y = point.get("y", point.get("y_km"))
            z = point.get("z", point.get("z_km"))

        if x is None or y is None or z is None:
            continue

        key = str(timestamp)

        secondary_by_time[key] = (
            float(x),
            float(y),
            float(z),
        )

    closest_distance = float("inf")
    closest_time = None
    closest_primary = None
    closest_secondary = None

    for point in modified_track:

        timestamp = point["time"]

        secondary = secondary_by_time.get(
            timestamp
        )

        if secondary is None:
            continue

        dx = (
            point["x"] -
            secondary[0]
        )

        dy = (
            point["y"] -
            secondary[1]
        )

        dz = (
            point["z"] -
            secondary[2]
        )

        distance = math.sqrt(
            dx * dx +
            dy * dy +
            dz * dz
        )

        if distance < closest_distance:

            closest_distance = distance
            closest_time = timestamp

            closest_primary = (
                point["x"],
                point["y"],
                point["z"],
            )

            closest_secondary = secondary

    if closest_time is None:
        raise ValueError(
            "unable to determine modified closest approach"
        )

    # --------------------------------------------------------
    # RELATIVE SPEED
    # --------------------------------------------------------

    relative_speed_km_s = None

    # Estimate velocity around the closest point using
    # neighboring trajectory samples.
    #
    # This gives the UI a changing relative-speed value
    # instead of simply copying the original value.

    closest_index = None

    for i, point in enumerate(modified_track):

        if point["time"] == closest_time:
            closest_index = i
            break

    if closest_index is not None:

        if (
            closest_index > 0
            and closest_index < len(modified_track) - 1
        ):

            p0 = modified_track[
                closest_index - 1
            ]

            p1 = modified_track[
                closest_index + 1
            ]

            try:

                t0 = datetime.fromisoformat(
                    p0["time"].replace(
                        "Z",
                        "+00:00",
                    )
                )

                t1 = datetime.fromisoformat(
                    p1["time"].replace(
                        "Z",
                        "+00:00",
                    )
                )

                dt = (
                    t1 - t0
                ).total_seconds()

                if dt > 0:

                    va = (
                        (p1["x"] - p0["x"]) / dt,
                        (p1["y"] - p0["y"]) / dt,
                        (p1["z"] - p0["z"]) / dt,
                    )

                    # Find corresponding secondary points.
                    s0 = secondary_by_time.get(
                        p0["time"]
                    )

                    s1 = secondary_by_time.get(
                        p1["time"]
                    )

                    if s0 is not None and s1 is not None:

                        vb = (
                            (s1[0] - s0[0]) / dt,
                            (s1[1] - s0[1]) / dt,
                            (s1[2] - s0[2]) / dt,
                        )

                        relative_speed_km_s = math.sqrt(
                            (va[0] - vb[0]) ** 2
                            + (va[1] - vb[1]) ** 2
                            + (va[2] - vb[2]) ** 2
                        )

            except Exception:
                relative_speed_km_s = None

    # --------------------------------------------------------
    # FALLBACK RELATIVE SPEED
    # --------------------------------------------------------

    if relative_speed_km_s is None:

        # Calculate from the closest-position geometry.
        # This fallback is only used if velocity samples
        # cannot be reconstructed from the track.
        relative_speed_km_s = 0.0

    # --------------------------------------------------------
    # RETURN
    # --------------------------------------------------------

    return {
        "miss_distance_km": float(
            closest_distance
        ),

        "tca_utc": str(
            closest_time
        ),

        "relative_speed_km_s": float(
            relative_speed_km_s
        ),

        "maneuver_time_utc": (
            maneuver_time.isoformat()
        ),

        "maneuver": {
            "type": (
                "altitude_change"
                if altitude_change_km is not None
                else "delta_v_rtn"
            ),

            "altitude_change_km": (
                float(altitude_change_km)
                if altitude_change_km is not None
                else None
            ),

            "delta_v_rtn_m_s": (
                list(dv_rtn)
                if dv_rtn is not None
                else None
            ),
        },

        "modified_track_for_visualization": (
            modified_track
        ),
    }