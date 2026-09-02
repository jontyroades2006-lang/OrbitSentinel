from __future__ import annotations

import os
import math
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from . import data as data_mod
from . import conjunction as conj_mod
from . import uncertainty as unc_mod
from . import risk as risk_mod
from . import what_if as whatif_mod
from . import visualization as viz_mod
from .model import get_model


# ==========================================================================
# CONFIGURATION
# ==========================================================================

FRONTEND_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "frontend"
)


# ==========================================================================
# FLASK APP
# ==========================================================================

app = Flask(
    __name__,
    static_folder=FRONTEND_DIR,
    static_url_path=""
)

CORS(app)


# ==========================================================================
# CATALOG
# ==========================================================================

catalog = data_mod.build_live_catalog(groups=("stations", "active"), max_per_group=40)

# Load/warm ML uncertainty model
get_model()


# ==========================================================================
# HELPERS
# ==========================================================================

def now_utc() -> datetime:
    """Return current UTC time."""
    return datetime.now(timezone.utc)


def _error(msg, code=400):
    """Return a standard JSON error response."""
    return jsonify({
        "error": msg
    }), code


def _eci_track_to_geodetic(raw_track):
    """
    Convert a list of {"time", "x", "y", "z"} ECI points (the shape
    what_if.run_what_if() produces) into {"time", "lon", "lat", "alt_km"}
    points (the shape visualization.modified_track_packet() / CZML
    expect, matching what data.propagate_track() normally returns).

    This is the missing conversion step that caused
    "What-if visualization failed: 'lon'" — the what-if engine works in
    raw ECI cartesian coordinates, but the CZML builder needs geodetic
    lat/lon/altitude to place points on the globe.
    """
    geo_track = []

    for point in raw_track:

        if not isinstance(point, dict):
            continue

        timestamp = point.get("time")
        x = point.get("x")
        y = point.get("y")
        z = point.get("z")

        if timestamp is None or x is None or y is None or z is None:
            continue

        try:
            t = datetime.fromisoformat(
                str(timestamp).replace("Z", "+00:00")
            )
        except ValueError:
            continue

        try:
            geo = data_mod.eci_to_geodetic((float(x), float(y), float(z)), t)
        except Exception:
            continue

        geo_track.append({
            "time": str(timestamp),
            "lon": geo["lon"],
            "lat": geo["lat"],
            "alt_km": geo["alt_km"],
        })

    return geo_track


# ==========================================================================
# FRONTEND
# ==========================================================================

@app.route("/")
def index():
    return send_from_directory(
        FRONTEND_DIR,
        "index.html"
    )


# ==========================================================================
# SATELLITE CATALOG
# ==========================================================================

@app.route("/api/satellites")
def list_satellites():

    return jsonify({
        "satellites": catalog.list_dicts()
    })


# ==========================================================================
# SATELLITE DETAIL
# ==========================================================================

@app.route("/api/satellites/<norad_id>")
def satellite_detail(norad_id):

    rec = catalog.get(norad_id)

    if not rec:
        return _error(
            f"Satellite {norad_id} not found",
            404
        )

    start = now_utc()

    end = start + timedelta(
        hours=2
    )

    track = data_mod.propagate_track(
        rec.satrec,
        start,
        end,
        step_seconds=60
    )

    detail = rec.to_dict()

    detail["current_state"] = (
        track[0]
        if track
        else None
    )

    return jsonify(detail)


# ==========================================================================
# SEARCH
# ==========================================================================

@app.route("/api/search")
def search():

    q = request.args.get(
        "q",
        ""
    )

    results = [
        r.to_dict()
        for r in catalog.search(q)
    ]

    return jsonify({
        "query": q,
        "results": results
    })


# ==========================================================================
# CATALOG CZML
# ==========================================================================

@app.route("/api/catalog/czml")
def catalog_czml():

    try:
        hours = float(
            request.args.get(
                "hours",
                3
            )
        )

        step = float(
            request.args.get(
                "step_seconds",
                60
            )
        )

    except ValueError:
        return _error(
            "hours and step_seconds must be numbers"
        )

    if hours <= 0:
        return _error(
            "hours must be greater than 0"
        )

    if step <= 0:
        return _error(
            "step_seconds must be greater than 0"
        )

    start = now_utc()

    end = start + timedelta(
        hours=hours
    )

    highlight_param = request.args.get(
        "highlight",
        ""
    )

    highlighted = (
        set(
            highlight_param.split(",")
        )
        if highlight_param
        else set()
    )

    records_with_tracks = []

    for rec in catalog.all():

        track = data_mod.propagate_track(
            rec.satrec,
            start,
            end,
            step_seconds=step
        )

        records_with_tracks.append(
            (
                rec.to_dict(),
                track
            )
        )

    czml = viz_mod.build_catalog_czml(
        records_with_tracks,
        start.isoformat(),
        end.isoformat(),
        highlighted_ids=highlighted
    )

    return jsonify(czml)


# ==========================================================================
# CONJUNCTION ANALYSIS
# ==========================================================================

@app.route("/api/conjunction")
def conjunction_analysis():

    a_id = request.args.get("a")
    b_id = request.args.get("b")

    try:

        hours = float(
            request.args.get(
                "hours",
                48
            )
        )

        step_seconds = float(
            request.args.get(
                "step_seconds",
                30
            )
        )

    except ValueError:

        return _error(
            "hours and step_seconds must be numbers"
        )

    # ----------------------------------------------------------------------
    # VALIDATION
    # ----------------------------------------------------------------------

    if not a_id or not b_id:

        return _error(
            "query params 'a' and 'b' "
            "(NORAD ids) are required"
        )

    if a_id == b_id:

        return _error(
            "choose two different objects"
        )

    if hours <= 0:

        return _error(
            "hours must be greater than 0"
        )

    if step_seconds <= 0:

        return _error(
            "step_seconds must be greater than 0"
        )

    # ----------------------------------------------------------------------
    # FIND SATELLITES
    # ----------------------------------------------------------------------

    rec_a = catalog.get(a_id)
    rec_b = catalog.get(b_id)

    if not rec_a or not rec_b:

        return _error(
            "one or both satellite ids not found",
            404
        )

    # ----------------------------------------------------------------------
    # TIME WINDOW
    # ----------------------------------------------------------------------

    start = now_utc()

    end = start + timedelta(
        hours=hours
    )

    # ----------------------------------------------------------------------
    # CONJUNCTION
    # ----------------------------------------------------------------------

    try:

        result = conj_mod.find_close_approach(
            rec_a.satrec,
            rec_b.satrec,
            start,
            end,
            coarse_step_seconds=step_seconds
        )

    except Exception as exc:

        app.logger.exception(
            "Conjunction analysis failed"
        )

        return _error(
            f"Conjunction analysis failed: {exc}",
            500
        )

    # ----------------------------------------------------------------------
    # TCA
    # ----------------------------------------------------------------------

    try:

        tca_time = datetime.fromisoformat(
            result["tca_utc"]
        )

    except Exception:

        return _error(
            "Invalid TCA returned by conjunction analysis",
            500
        )

    # ----------------------------------------------------------------------
    # HARD BODY RADIUS
    # ----------------------------------------------------------------------

    hb_radius = conj_mod.hard_body_radius_km(
        rec_a.object_type,
        rec_b.object_type
    )

    # ----------------------------------------------------------------------
    # UNCERTAINTY
    # ----------------------------------------------------------------------

    try:

        combined_unc = unc_mod.combined_uncertainty(
            rec_a,
            rec_b,
            start,
            tca_time
        )

        confidence = (
            unc_mod.confidence_from_miss_distance(
                result["miss_distance_km"],
                combined_unc[
                    "combined_uncertainty_km"
                ]
            )
        )

    except Exception as exc:

        app.logger.exception(
            "Uncertainty calculation failed"
        )

        return _error(
            f"Uncertainty calculation failed: {exc}",
            500
        )

    # ----------------------------------------------------------------------
    # RISK
    # ----------------------------------------------------------------------

    try:

        # NOTE: confidence_from_miss_distance() returns the key
        # "confidence_score" (0-1), not "confidence" — reading the wrong
        # key here silently fell back to a hardcoded 0.90 every time,
        # so the risk score was never actually being discounted by the
        # real computed confidence. Fixed to read the correct key.
        confidence_value = float(
            confidence.get(
                "confidence_score",
                0.90
            )
        )

        score = risk_mod.compute_risk(
            result["miss_distance_km"],
            result["relative_speed_km_s"],
            rec_a.to_dict(),
            rec_b.to_dict(),
            hb_radius,
            confidence=confidence_value
        )

    except Exception as exc:

        app.logger.exception(
            "Risk calculation failed"
        )

        return _error(
            f"Risk calculation failed: {exc}",
            500
        )

    # ----------------------------------------------------------------------
    # TCA LOCATION
    # ----------------------------------------------------------------------

    try:

        pos_a, _ = data_mod.propagate_eci(
            rec_a.satrec,
            tca_time
        )

        geo_a = data_mod.eci_to_geodetic(
            pos_a,
            tca_time
        )

    except Exception as exc:

        app.logger.exception(
            "TCA location calculation failed"
        )

        return _error(
            f"TCA location calculation failed: {exc}",
            500
        )

    # ----------------------------------------------------------------------
    # TRACKS
    # ----------------------------------------------------------------------

    try:

        track_a = data_mod.propagate_track(
            rec_a.satrec,
            start,
            end,
            step_seconds=90
        )

        track_b = data_mod.propagate_track(
            rec_b.satrec,
            start,
            end,
            step_seconds=90
        )

    except Exception as exc:

        app.logger.exception(
            "Track generation failed"
        )

        return _error(
            f"Track generation failed: {exc}",
            500
        )

    # ----------------------------------------------------------------------
    # CZML
    # ----------------------------------------------------------------------

    try:

        czml = viz_mod.build_conjunction_czml(
            (rec_a.to_dict(), track_a),
            (rec_b.to_dict(), track_b),

            tca_marker={
                "marker_id": "tca-marker",

                "lon": geo_a["lon"],

                "lat": geo_a["lat"],

                "alt_km": geo_a["alt_km"],

                "time_iso": result["tca_utc"],

                "label": (
                    f"TCA: "
                    f"{result['miss_distance_km']:.2f} km"
                ),
            },

            start_iso=start.isoformat(),

            end_iso=end.isoformat()
        )

    except Exception as exc:

        app.logger.exception(
            "CZML generation failed"
        )

        return _error(
            f"CZML generation failed: {exc}",
            500
        )

    # ----------------------------------------------------------------------
    # RESPONSE
    # ----------------------------------------------------------------------

    return jsonify({

        "object_a": rec_a.to_dict(),

        "object_b": rec_b.to_dict(),

        "search_window_hours": hours,

        "conjunction": result,

        "uncertainty": combined_unc,

        "confidence": confidence,

        "risk": score,

        "alert": {

            "headline": (
                f"Conjunction: "
                f"{rec_a.name} vs {rec_b.name}"
            ),

            "closest_approach_km": (
                result["miss_distance_km"]
            ),

            "time_of_closest_approach_utc": (
                result["tca_utc"]
            ),

            "confidence_pct": (
                confidence["confidence_pct"]
            ),

            "confidence_label": (
                confidence["confidence_label"]
            ),

            "risk_score": (
                score["risk_score"]
            ),

            "risk_category": (
                score["risk_category"]
            ),
        },

        "czml": czml
    })


# ==========================================================================
# WHAT-IF SIMULATION
# ==========================================================================

@app.route(
    "/api/whatif",
    methods=["POST"]
)
def whatif():

    # ----------------------------------------------------------------------
    # READ JSON
    # ----------------------------------------------------------------------

    payload = request.get_json(
        force=True,
        silent=True
    ) or {}

    a_id = payload.get(
        "primary_id"
    )

    b_id = payload.get(
        "secondary_id"
    )

    # ----------------------------------------------------------------------
    # BASIC INPUTS
    # ----------------------------------------------------------------------

    try:

        hours = float(
            payload.get(
                "hours",
                48
            )
        )

        maneuver_offset_minutes = float(
            payload.get(
                "maneuver_offset_minutes",
                10
            )
        )

    except (TypeError, ValueError):

        return _error(
            "hours and maneuver_offset_minutes "
            "must be numbers"
        )

    altitude_change_km = payload.get(
        "altitude_change_km"
    )

    delta_v_rtn_m_s = payload.get(
        "delta_v_rtn_m_s"
    )

    # ----------------------------------------------------------------------
    # VALIDATION
    # ----------------------------------------------------------------------

    if not a_id or not b_id:

        return _error(
            "primary_id and secondary_id are required"
        )

    if str(a_id) == str(b_id):

        return _error(
            "primary_id and secondary_id "
            "must be different"
        )

    if (
        altitude_change_km is None
        and delta_v_rtn_m_s is None
    ):

        return _error(
            "provide altitude_change_km "
            "or delta_v_rtn_m_s"
        )

    if hours <= 0:

        return _error(
            "hours must be greater than 0"
        )

    if maneuver_offset_minutes < 0:

        return _error(
            "maneuver_offset_minutes "
            "cannot be negative"
        )

    if maneuver_offset_minutes >= hours * 60:

        return _error(
            "maneuver time must be "
            "inside the analysis window"
        )

    # ----------------------------------------------------------------------
    # ALTITUDE CHANGE
    # ----------------------------------------------------------------------

    if altitude_change_km is not None:

        try:

            altitude_change_km = float(
                altitude_change_km
            )

        except (TypeError, ValueError):

            return _error(
                "altitude_change_km must be a number"
            )

    # ----------------------------------------------------------------------
    # DELTA-V
    # ----------------------------------------------------------------------

    if delta_v_rtn_m_s is not None:

        if not isinstance(
            delta_v_rtn_m_s,
            (list, tuple)
        ):

            return _error(
                "delta_v_rtn_m_s must be an array "
                "[radial, in_track, cross_track]"
            )

        if len(delta_v_rtn_m_s) != 3:

            return _error(
                "delta_v_rtn_m_s must contain "
                "exactly 3 values"
            )

        try:

            delta_v_rtn_m_s = tuple(
                float(value)
                for value in delta_v_rtn_m_s
            )

        except (TypeError, ValueError):

            return _error(
                "delta_v_rtn_m_s values "
                "must be numbers"
            )

    # ----------------------------------------------------------------------
    # GET SATELLITES
    # ----------------------------------------------------------------------

    rec_a = catalog.get(
        str(a_id)
    )

    rec_b = catalog.get(
        str(b_id)
    )

    if not rec_a or not rec_b:

        return _error(
            "one or both satellite ids not found",
            404
        )

    # ----------------------------------------------------------------------
    # TIME
    # ----------------------------------------------------------------------

    start = now_utc()

    end = start + timedelta(
        hours=hours
    )

    maneuver_time = (
        start
        + timedelta(
            minutes=maneuver_offset_minutes
        )
    )

    # ----------------------------------------------------------------------
    # RUN WHAT-IF (modified trajectory + modified miss distance/TCA)
    # ----------------------------------------------------------------------

    try:

        result = whatif_mod.run_what_if(
            rec_a,
            rec_b,
            maneuver_time,
            start,
            end,

            altitude_change_km=(
                altitude_change_km
                if altitude_change_km is not None
                else None
            ),

            delta_v_rtn_m_s=(
                delta_v_rtn_m_s
                if delta_v_rtn_m_s is not None
                else None
            )
        )

    except ValueError as exc:

        return _error(
            str(exc),
            400
        )

    except Exception as exc:

        app.logger.exception(
            "What-if simulation failed"
        )

        return _error(
            f"What-if simulation failed: {exc}",
            500
        )

    # ----------------------------------------------------------------------
    # ORIGINAL vs. MODIFIED RISK/CONFIDENCE + COMPARISON
    #
    # what_if.run_what_if() only returns the modified geometry
    # (miss_distance_km / tca_utc / relative_speed_km_s / maneuver /
    # modified_track_for_visualization) — it does not compute the
    # original conjunction, risk, or confidence, or compare the two.
    # We build all of that here so the response always has the
    # "original" / "modified" / "comparison" shape the frontend expects,
    # regardless of what a given what_if.py implementation returns.
    # ----------------------------------------------------------------------

    try:

        hb_radius = conj_mod.hard_body_radius_km(
            rec_a.object_type,
            rec_b.object_type
        )

        # --- ORIGINAL: full SGP4 conjunction, confidence, risk ---
        original_conj = conj_mod.find_close_approach(
            rec_a.satrec,
            rec_b.satrec,
            start,
            end,
        )
        original_tca_time = datetime.fromisoformat(
            original_conj["tca_utc"]
        )

        original_unc = unc_mod.combined_uncertainty(
            rec_a, rec_b, start, original_tca_time
        )
        original_confidence = unc_mod.confidence_from_miss_distance(
            original_conj["miss_distance_km"],
            original_unc["combined_uncertainty_km"],
        )
        original_risk = risk_mod.compute_risk(
            original_conj["miss_distance_km"],
            original_conj["relative_speed_km_s"],
            rec_a.to_dict(),
            rec_b.to_dict(),
            hb_radius,
            confidence=original_confidence["confidence_score"],
        )

        # --- MODIFIED: from what_if's post-maneuver geometry ---
        modified_tca_time = datetime.fromisoformat(
            str(result["tca_utc"]).replace("Z", "+00:00")
        )

        # Post-maneuver uncertainty: the primary's trajectory is no
        # longer on its original SGP4 mean elements, so we combine the
        # secondary's normal SGP4-based error with a fixed modeling-error
        # term representing the simplified post-maneuver propagation.
        secondary_err = unc_mod.estimate_position_error_km(
            rec_b.satrec, start, modified_tca_time
        )
        two_body_model_error_km = 0.5 + 0.05 * max(
            (modified_tca_time - maneuver_time).total_seconds() / 3600.0,
            0.0,
        )
        modified_combined_unc = math.sqrt(
            two_body_model_error_km ** 2 + secondary_err["error_km"] ** 2
        )
        modified_confidence = unc_mod.confidence_from_miss_distance(
            result["miss_distance_km"],
            modified_combined_unc,
        )
        modified_risk = risk_mod.compute_risk(
            result["miss_distance_km"],
            result["relative_speed_km_s"],
            rec_a.to_dict(),
            rec_b.to_dict(),
            hb_radius,
            confidence=modified_confidence["confidence_score"],
        )

        comparison = {
            "miss_distance_delta_km": round(
                result["miss_distance_km"] - original_conj["miss_distance_km"], 4
            ),
            "risk_score_delta": round(
                modified_risk["risk_score"] - original_risk["risk_score"], 1
            ),
            "improved": result["miss_distance_km"] > original_conj["miss_distance_km"],
        }

    except Exception as exc:

        app.logger.exception(
            "What-if comparison calculation failed"
        )

        return _error(
            f"What-if comparison calculation failed: {exc}",
            500
        )


    # ----------------------------------------------------------------------
    # VISUALIZATION
    #
    # IMPORTANT:
    # run_what_if() returns modified_track_for_visualization as raw ECI
    # {"time", "x", "y", "z"} points. The CZML builder needs geodetic
    # {"time", "lon", "lat", "alt_km"} points instead — that mismatch is
    # exactly what produced "What-if visualization failed: 'lon'".
    # _eci_track_to_geodetic() converts between the two before we ever
    # touch the CZML builder.
    # ----------------------------------------------------------------------

    try:

        track_a = data_mod.propagate_track(
            rec_a.satrec,
            start,
            end,
            step_seconds=90
        )

        track_b = data_mod.propagate_track(
            rec_b.satrec,
            start,
            end,
            step_seconds=90
        )

        czml = [
            viz_mod.document_packet(
                "OrbitSentinel What-If",
                start.isoformat(),
                end.isoformat()
            )
        ]

        # Original primary trajectory
        czml.append(
            viz_mod.satellite_point_and_path_packet(
                rec_a.to_dict(),
                track_a,
                color=viz_mod.PRIMARY_HIGHLIGHT,
                highlight=True,
                id_suffix="-orig"
            )
        )

        # Secondary trajectory
        czml.append(
            viz_mod.satellite_point_and_path_packet(
                rec_b.to_dict(),
                track_b,
                color=viz_mod.SECONDARY_HIGHLIGHT,
                highlight=True
            )
        )

        # Modified primary trajectory — convert ECI x/y/z to lon/lat/alt_km
        # before building its CZML packet.
        modified_track_raw = result.get(
            "modified_track_for_visualization",
            []
        )

        modified_track_geo = _eci_track_to_geodetic(modified_track_raw)

        if modified_track_geo:

            czml.append(
                viz_mod.modified_track_packet(
                    rec_a.to_dict(),
                    modified_track_geo
                )
            )

    except Exception as exc:

        app.logger.exception(
            "What-if visualization failed"
        )

        return _error(
            f"What-if visualization failed: {exc}",
            500
        )

    # ----------------------------------------------------------------------
    # BUILD RESPONSE
    # ----------------------------------------------------------------------

    response = {

        # Satellite information
        "primary": rec_a.to_dict(),

        "secondary": rec_b.to_dict(),

        # Simulation information
        "search_window_hours": hours,

        "maneuver_time": (
            maneuver_time.isoformat()
        ),

        # Maneuver information
        "maneuver": result.get(
            "maneuver",
            {}
        ),

        # --------------------------------------------------------------
        # ORIGINAL (full SGP4 conjunction + confidence + risk)
        # --------------------------------------------------------------

        "original": {
            "conjunction": original_conj,
            "confidence": original_confidence,
            "risk": original_risk,
        },

        # --------------------------------------------------------------
        # MODIFIED (post-maneuver conjunction + confidence + risk)
        # --------------------------------------------------------------

        "modified": {
            "conjunction": {
                "tca_utc": result["tca_utc"],
                "miss_distance_km": result["miss_distance_km"],
                "relative_speed_km_s": result["relative_speed_km_s"],
                "note": (
                    "Post-maneuver trajectory uses a simplified "
                    "geometric displacement model, not full SGP4 or "
                    "two-body propagation — treat as directional guidance."
                ),
            },
            "confidence": modified_confidence,
            "risk": modified_risk,
        },

        # --------------------------------------------------------------
        # COMPARISON
        # --------------------------------------------------------------

        "comparison": comparison,

        # --------------------------------------------------------------
        # CZML
        # --------------------------------------------------------------

        "czml": czml,

        # Keep modified trajectory (raw ECI form, as returned by
        # what_if.run_what_if()) for any client that wants the raw data.
        "modified_track_for_visualization": result.get(
            "modified_track_for_visualization",
            []
        )
    }

    return jsonify(response)


# ==========================================================================
# MODEL INFORMATION
# ==========================================================================

@app.route("/api/model/info")
def model_info():

    model = get_model()

    return jsonify({

        "model_type": (
            "GradientBoostingRegressor "
            "(scikit-learn)"
        ),

        "target": (
            "expected SGP4 3D position error (km)"
        ),

        "metrics": model.metrics
    })


# ==========================================================================
# RUN SERVER
# ==========================================================================

if __name__ == "__main__":

    debug = (
        os.environ.get(
            "ORBITSENTINEL_DEBUG",
            "0"
        ) == "1"
    )

    app.run(
        host="0.0.0.0",
        port=5055,
        debug=debug
    )
