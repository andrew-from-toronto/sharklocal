"""Map decoding and room-command encoding for the SharkIQ MQTT protocol.

The robot publishes two kinds of map-bearing frames on the status topic, both
inside top-level field ``7``:

* **Live frames** (~27 KB, every few seconds while a job runs) — the occupancy
  grid, the path cleaned so far and the robot's pose history.
* **Persisted frame** (~92 KB, once, as the robot reaches the dock; flagged by
  top-level field ``3 = 1``) — the saved map with rooms, wall and door vectors,
  the dock pose, job statistics and the robot's own event log.

Coordinates are metres in the map frame; ``cell = (m - origin) / resolution``.
Everything here was reverse-engineered from live captures, so field meanings
are documented at the point of use rather than by a ``.proto`` name.
"""

from __future__ import annotations

import json
import struct
from typing import Any, Dict, List, Optional

from . import protobuf
from .models import (
    MapFeature,
    MapGrid,
    MapPoint,
    MapPose,
    MapRoom,
    VacuumLogEntry,
    VacuumMap,
)

# Top-level fields of a status frame that carry map data.
FIELD_MAP = 7
FIELD_PERSISTED_FLAG = 3

# Room-record fields the app adds to a room selected for Matrix (deep) Clean.
_DEEP_CLEAN_FIELDS = ((7, 2), (9, 0), (10, 2))
# Spot Clean is a synthetic room of this name with a square polygon around the pin.
SPOT_ROOM_NAME = "PinDrop"
SPOT_HALF_SIZE = 0.762  # metres — the app draws a ~1.5 m square


def _fields(data: bytes) -> Dict[int, List[Any]]:
    return protobuf.decode_fields(data)


def _first(fields: Dict[int, List[Any]], num: int, default: Any = None) -> Any:
    values = fields.get(num)
    return values[0] if values else default


def _text(value: Optional[bytes]) -> Optional[str]:
    return value.decode("utf-8", errors="replace") if value is not None else None


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------


def has_map(fields: Dict[int, List[Any]]) -> bool:
    """``True`` if a decoded status frame carries an occupancy grid."""
    blob = _first(fields, FIELD_MAP)
    return isinstance(blob, bytes) and 5 in _fields(blob)


def decode_map(fields: Dict[int, List[Any]]) -> Optional[VacuumMap]:
    """Decode the map carried in a status frame.

    Args:
        fields: The frame as returned by :func:`sharklocal.protobuf.decode_fields`.

    Returns:
        A :class:`~sharklocal.models.VacuumMap`, or ``None`` if the frame has
        no grid (ordinary status frames).
    """
    blob = _first(fields, FIELD_MAP)
    if not isinstance(blob, bytes):
        return None
    m = _fields(blob)
    if 5 not in m:
        return None

    grid = _decode_grid(m[5][0])
    persisted = _first(fields, FIELD_PERSISTED_FLAG) == 1

    vacuum_map = VacuumMap(
        grid=grid,
        path=_decode_points(_first(m, 8)),
        poses=_decode_poses(_first(m, 10)),
        persisted=persisted,
        map_id=_text(_first(m, 3)),
        name=_text(_first(m, 2)),
        dock=_decode_pose_f32(_first(m, 7)),
        rooms=[_decode_room(r) for r in m.get(15, [])],
        features=[f for f in (_decode_feature(r) for r in m.get(28, [])) if f],
    )

    # Field 21 is the persisted grid; its sub-field 19 is the room-id raster.
    persisted_grid = _first(m, 21)
    if isinstance(persisted_grid, bytes):
        g21 = _fields(persisted_grid)
        room_ids = _first(g21, 19)
        if isinstance(room_ids, bytes) and len(room_ids) == len(grid.cells):
            grid.room_ids = room_ids

    # Field 11 is the job summary: .1 start epoch, .3 duration s, .6 cleaned cells.
    stats = _first(m, 11)
    if isinstance(stats, bytes):
        s = _fields(stats)
        vacuum_map.job_started = _first(s, 1)
        vacuum_map.job_duration = _first(s, 3)
        vacuum_map.cleaned_cells = _first(s, 6)

    # Field 20.3.6 is the robot's event log as a JSON array of {key, time, code}.
    vacuum_map.log = _decode_log(_first(m, 20))

    return vacuum_map


def _decode_grid(data: bytes) -> MapGrid:
    """Field 7.5: ``.1`` resolution f32, ``.2`` origin {x,y} f32, ``.3``/``.4``
    width/height, ``.6`` one byte per cell."""
    g = _fields(data)
    origin = _fields(_first(g, 2, b""))
    return MapGrid(
        resolution=protobuf.float32(_first(g, 1, 0)),
        width=_first(g, 3, 0),
        height=_first(g, 4, 0),
        origin=MapPoint(
            protobuf.float32(_first(origin, 1, 0)),
            protobuf.float32(_first(origin, 2, 0)),
        ),
        cells=_first(g, 6, b""),
    )


def _decode_int16_list(data: Optional[bytes], stride: int) -> List[tuple]:
    """Fields 7.8 / 7.10: ``.1`` scale f32, ``.3`` packed little-endian int16 tuples.

    Every component (metres, and radians for the heading) is ``int16 * scale``.
    """
    if not isinstance(data, bytes):
        return []
    p = _fields(data)
    scale = protobuf.float32(_first(p, 1, 0))
    raw = _first(p, 3, b"")
    count = len(raw) // (2 * stride)
    values = struct.unpack(f"<{count * stride}h", raw[: count * stride * 2])
    return [
        tuple(v * scale for v in values[i : i + stride])
        for i in range(0, count * stride, stride)
    ]


def _decode_points(data: Optional[bytes]) -> List[MapPoint]:
    return [MapPoint(x, y) for x, y in _decode_int16_list(data, 2)]


def _decode_poses(data: Optional[bytes]) -> List[MapPose]:
    return [MapPose(x, y, h) for x, y, h in _decode_int16_list(data, 3)]


def _decode_pose_f32(data: Optional[bytes]) -> Optional[MapPose]:
    """Field 7.7: ``.1`` x, ``.2`` y, ``.3`` heading — all f32."""
    if not isinstance(data, bytes):
        return None
    p = _fields(data)
    return MapPose(
        protobuf.float32(_first(p, 1, 0)),
        protobuf.float32(_first(p, 2, 0)),
        protobuf.float32(_first(p, 3, 0)),
    )


def _decode_point_f32(data: bytes) -> MapPoint:
    """``.1`` x f32, ``.2`` y f32 — used by room polygons and features."""
    p = _fields(data)
    return MapPoint(
        protobuf.float32(_first(p, 1, 0)),
        protobuf.float32(_first(p, 2, 0)),
    )


def _decode_room(data: bytes) -> MapRoom:
    """Field 7.15: ``.2`` name, ``.4`` polygon of ``.1`` points, ``.5`` selected,
    ``.6`` coverage fraction (f32)."""
    r = _fields(data)
    polygon = _fields(_first(r, 4, b""))
    coverage = _first(r, 6)
    return MapRoom(
        name=_text(_first(r, 2, b"")) or "",
        polygon=[_decode_point_f32(pt) for pt in polygon.get(1, [])],
        selected=_first(r, 5) == 1,
        coverage=protobuf.float32(coverage) if coverage is not None else None,
    )


def _decode_feature(data: bytes) -> Optional[MapFeature]:
    """Field 7.28: ``.2`` kind ("edge" / "door"), ``.4`` polyline of ``.1`` points."""
    f = _fields(data)
    kind = _text(_first(f, 2))
    polyline = _first(f, 4)
    if kind is None or not isinstance(polyline, bytes):
        return None
    points = [_decode_point_f32(pt) for pt in _fields(polyline).get(1, [])]
    return MapFeature(kind=kind, points=points)


def _decode_log(data: Optional[bytes]) -> List[VacuumLogEntry]:
    """Field 7.20.3.6: JSON ``[{"key": ..., "time": "<epoch>s", "code": ...}]``."""
    if not isinstance(data, bytes):
        return []
    inner = _first(_fields(data), 3)
    if not isinstance(inner, bytes):
        return []
    text = _first(_fields(inner), 6)
    if not isinstance(text, bytes):
        return []
    try:
        entries = json.loads(text.decode("utf-8", errors="replace"))
    except ValueError:
        return []
    log: List[VacuumLogEntry] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        time_text = str(entry.get("time", "0")).rstrip("s")
        log.append(
            VacuumLogEntry(
                key=str(entry.get("key", "")),
                time=int(time_text) if time_text.isdigit() else 0,
                code=str(entry.get("code", "")),
            )
        )
    return log


# ---------------------------------------------------------------------------
# Encoding — room and spot selection
# ---------------------------------------------------------------------------


def _encode_point(point: MapPoint) -> bytes:
    return protobuf.encode_bytes_field(
        1,
        protobuf.encode_float_field(1, point.x) + protobuf.encode_float_field(2, point.y),
    )


def _encode_room(room: MapRoom, *, deep: bool, spot: bool = False) -> bytes:
    """One field-15 room record, in the shape the app sends it."""
    polygon = b"".join(_encode_point(pt) for pt in room.polygon)
    record = (
        protobuf.encode_string_field(2, room.name)
        + protobuf.encode_string_field(3, room.name)
        + protobuf.encode_bytes_field(4, polygon)
    )
    if deep or spot:
        for num, value in _DEEP_CLEAN_FIELDS:
            record += protobuf.encode_varint_field(num, value)
            if spot and num == 7:
                record += protobuf.encode_varint_field(8, 1)
    return record


def encode_room_selection(
    vacuum_map: VacuumMap,
    room_names: List[str],
    *,
    deep: bool = False,
) -> bytes:
    """Build the "set cleaning area" message for a room clean.

    Mirrors what the SharkClean app publishes before ``start_cleaning``: the
    map's full room definition (field ``6``), the command ``16 = 11``, and the
    selected room names in field ``41``. Rooms named in *room_names* are marked
    for Matrix Clean when *deep* is set.

    Args:
        vacuum_map: A persisted map carrying the room definition.
        room_names: Names of the rooms to clean, as shown in the app.
        deep: Request a Matrix (two-pass) clean of the selected rooms.

    Raises:
        ValueError: If a name is not a room of *vacuum_map*, or the map has no id.
    """
    if vacuum_map.map_id is None:
        raise ValueError("Map has no id; room cleaning needs a persisted map")
    known = {room.name: room for room in vacuum_map.rooms}
    missing = [name for name in room_names if name not in known]
    if missing:
        raise ValueError(f"Unknown room(s) {missing}; map has {sorted(known)}")

    rooms = b"".join(
        protobuf.encode_bytes_field(
            15, _encode_room(room, deep=deep and room.name in room_names)
        )
        for room in vacuum_map.rooms
    )
    return _encode_selection(vacuum_map.map_id, rooms, room_names)


def encode_spot_selection(vacuum_map: VacuumMap, x: float, y: float) -> bytes:
    """Build the "set cleaning area" message for a Spot Clean centred on ``(x, y)``.

    The app models a spot clean as an extra room named ``"PinDrop"`` with a
    square polygon around the pin, appended to the map's room definition.
    """
    if vacuum_map.map_id is None:
        raise ValueError("Map has no id; spot cleaning needs a persisted map")
    d = SPOT_HALF_SIZE
    spot = MapRoom(
        name=SPOT_ROOM_NAME,
        polygon=[
            MapPoint(x - d, y + d),
            MapPoint(x + d, y + d),
            MapPoint(x + d, y - d),
            MapPoint(x - d, y - d),
        ],
    )
    rooms = b"".join(
        protobuf.encode_bytes_field(15, _encode_room(room, deep=False))
        for room in vacuum_map.rooms
    ) + protobuf.encode_bytes_field(15, _encode_room(spot, deep=True, spot=True))
    return _encode_selection(vacuum_map.map_id, rooms, [SPOT_ROOM_NAME])


def _encode_selection(map_id: str, rooms: bytes, names: List[str]) -> bytes:
    definition = protobuf.encode_string_field(3, map_id) + rooms
    selection = b"".join(protobuf.encode_string_field(1, name) for name in names)
    selection += protobuf.encode_string_field(3, map_id)
    return (
        protobuf.encode_bytes_field(6, definition)
        + protobuf.encode_varint_field(16, 11)
        + protobuf.encode_varint_field(39, 2)
        + protobuf.encode_bytes_field(41, selection)
    )
