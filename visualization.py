from __future__ import annotations

from datetime import datetime

DEFAULT_COLORS = {
    "active": [66, 200, 255, 255],
    "inactive": [255, 200, 60, 255],
    "debris": [180, 180, 180, 200],
    "unknown": [200, 200, 200, 255],
}

PRIMARY_HIGHLIGHT = [255, 80, 80, 255]
SECONDARY_HIGHLIGHT = [255, 200, 0, 255]
MODIFIED_COLOR = [80, 255, 140, 255]
CONJUNCTION_MARKER_COLOR = [255, 0, 0, 255]


def _track_to_cartographic_degrees(track: list[dict]) -> list:
    out = []
    for point in track:
        out.append(point["time"])
        out.append(point["lon"])
        out.append(point["lat"])
        out.append(point["alt_km"] * 1000.0)  # CZML heights are meters
    return out


def satellite_point_and_path_packet(record_dict: dict, track: list[dict],
                                     color: list | None = None,
                                     highlight: bool = False,
                                     id_suffix: str = "") -> dict:
    """Build a single CZML packet (point + label + path) for one satellite."""
    status = record_dict.get("status", "unknown")
    packet_color = color or DEFAULT_COLORS.get(status, DEFAULT_COLORS["unknown"])
    if not track:
        raise ValueError("track must contain at least one sample")

    start = track[0]["time"]
    end = track[-1]["time"]

    return {
        "id": f"sat-{record_dict['norad_id']}{id_suffix}",
        "name": record_dict["name"],
        "availability": f"{start}/{end}",
        "point": {
            "pixelSize": 10 if highlight else 7,
            "color": {"rgba": packet_color},
            "outlineColor": {"rgba": [0, 0, 0, 255]},
            "outlineWidth": 1,
        },
        "label": {
            "text": record_dict["name"],
            "font": "13px sans-serif",
            "fillColor": {"rgba": [255, 255, 255, 255]},
            "outlineColor": {"rgba": [0, 0, 0, 255]},
            "outlineWidth": 2,
            "style": "FILL_AND_OUTLINE",
            "verticalOrigin": "BOTTOM",
            "pixelOffset": {"cartesian2": [0, -10]},
            "show": highlight,
        },
        "path": {
            "material": {"solidColor": {"color": {"rgba": packet_color}}},
            "width": 2 if highlight else 1,
            "leadTime": 0,
            "trailTime": 6000,
            "resolution": 30,
        },
        "position": {
            "interpolationAlgorithm": "LAGRANGE",
            "interpolationDegree": 2,
            "epoch": start,
            "cartographicDegrees": _track_to_cartographic_degrees(track),
        },
    }


def modified_track_packet(record_dict: dict, track: list[dict], id_suffix="-whatif") -> dict:
    """Dashed-style path (achieved via a distinct color + polyline dash
    material) representing the post-maneuver two-body trajectory."""
    if not track:
        raise ValueError("track must contain at least one sample")
    start = track[0]["time"]
    end = track[-1]["time"]
    return {
        "id": f"sat-{record_dict['norad_id']}{id_suffix}",
        "name": f"{record_dict['name']} (what-if)",
        "availability": f"{start}/{end}",
        "point": {
            "pixelSize": 9,
            "color": {"rgba": MODIFIED_COLOR},
            "outlineColor": {"rgba": [0, 0, 0, 255]},
            "outlineWidth": 1,
        },
        "label": {
            "text": f"{record_dict['name']} (what-if)",
            "font": "12px sans-serif",
            "fillColor": {"rgba": MODIFIED_COLOR},
            "outlineWidth": 2,
            "outlineColor": {"rgba": [0, 0, 0, 255]},
            "style": "FILL_AND_OUTLINE",
            "verticalOrigin": "TOP",
            "pixelOffset": {"cartesian2": [0, 10]},
        },
        "path": {
            "material": {
                "polylineDash": {
                    "color": {"rgba": MODIFIED_COLOR},
                    "dashLength": 16,
                }
            },
            "width": 3,
            "leadTime": 0,
            "trailTime": 6000,
            "resolution": 30,
        },
        "position": {
            "interpolationAlgorithm": "LAGRANGE",
            "interpolationDegree": 2,
            "epoch": start,
            "cartographicDegrees": _track_to_cartographic_degrees(track),
        },
    }


def conjunction_marker_packet(marker_id: str, lon: float, lat: float, alt_km: float,
                               time_iso: str, label: str) -> dict:
    """A single-instant marker (e.g. time of closest approach location)."""
    return {
        "id": marker_id,
        "name": label,
        "position": {"cartographicDegrees": [lon, lat, alt_km * 1000.0]},
        "point": {
            "pixelSize": 16,
            "color": {"rgba": CONJUNCTION_MARKER_COLOR},
            "outlineColor": {"rgba": [255, 255, 255, 255]},
            "outlineWidth": 2,
        },
        "label": {
            "text": label,
            "font": "14px sans-serif bold",
            "fillColor": {"rgba": [255, 60, 60, 255]},
            "outlineColor": {"rgba": [0, 0, 0, 255]},
            "outlineWidth": 3,
            "style": "FILL_AND_OUTLINE",
            "verticalOrigin": "BOTTOM",
            "pixelOffset": {"cartesian2": [0, -14]},
        },
    }


def document_packet(name: str, start_iso: str, end_iso: str) -> dict:
    return {
        "id": "document",
        "name": name,
        "version": "1.0",
        "clock": {
            "interval": f"{start_iso}/{end_iso}",
            "currentTime": start_iso,
            "multiplier": 60,
            "range": "LOOP_STOP",
            "step": "SYSTEM_CLOCK_MULTIPLIER",
        },
    }


def build_catalog_czml(records_with_tracks: list[tuple], start_iso: str, end_iso: str,
                        highlighted_ids: set | None = None) -> list[dict]:
    """records_with_tracks: list of (record_dict, track) tuples."""
    highlighted_ids = highlighted_ids or set()
    packets = [document_packet("OrbitSentinel Catalog", start_iso, end_iso)]
    for record_dict, track in records_with_tracks:
        is_hl = record_dict["norad_id"] in highlighted_ids
        color = None
        if record_dict["norad_id"] in highlighted_ids:
            color = PRIMARY_HIGHLIGHT
        packets.append(satellite_point_and_path_packet(record_dict, track, color=color, highlight=is_hl))
    return packets


def build_conjunction_czml(primary: tuple, secondary: tuple, tca_marker: dict | None,
                            start_iso: str, end_iso: str) -> list[dict]:
    """primary/secondary: (record_dict, track) tuples, colored distinctly."""
    packets = [document_packet("OrbitSentinel Conjunction View", start_iso, end_iso)]
    p_record, p_track = primary
    s_record, s_track = secondary
    packets.append(satellite_point_and_path_packet(p_record, p_track, color=PRIMARY_HIGHLIGHT, highlight=True))
    packets.append(satellite_point_and_path_packet(s_record, s_track, color=SECONDARY_HIGHLIGHT, highlight=True))
    if tca_marker:
        packets.append(conjunction_marker_packet(**tca_marker))
    return packets
