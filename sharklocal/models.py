"""Data models for vacuum state and device information."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class VacuumMode(str, Enum):
    """Normalized operating modes across all transports."""

    UNKNOWN = "unknown"
    CLEANING = "cleaning"
    RETURNING_TO_DOCK = "returning_to_dock"
    DOCKING = "docking"
    DOCKED = "docked"
    IDLE = "idle"  # Powered on but not cleaning and not on the charging dock
    EXPLORING = "exploring"  # Mapping/exploration run in progress


class SuctionLevel(str, Enum):
    """Suction power levels, named as in the SharkClean app."""

    ECO = "eco"
    NORMAL = "normal"
    MAX = "max"


@dataclass
class VacuumStatus:
    """Normalized vacuum status, independent of transport protocol.

    The optional fields after ``raw`` are only populated by transports that
    carry them (currently the SharkIQ MQTT protocol) and stay ``None``
    otherwise. ``map`` is set only on frames that include map data.
    """

    mode: VacuumMode
    battery_level: Optional[int] = None
    charging: Optional[bool] = None
    raw: Dict[str, Any] = field(default_factory=dict)
    job_active: Optional[bool] = None
    deep_clean: Optional[bool] = None  # Matrix / spot clean in progress
    recharge_resume: Optional[bool] = None
    evac_resume: Optional[bool] = None
    map: Optional["VacuumMap"] = None

    @property
    def is_cleaning(self) -> bool:
        return self.mode == VacuumMode.CLEANING

    @property
    def is_docked(self) -> bool:
        return self.mode in (VacuumMode.DOCKED, VacuumMode.DOCKING)


# ---------------------------------------------------------------------------
# Map models (SharkIQ MQTT map frames)
# ---------------------------------------------------------------------------


@dataclass
class MapPoint:
    """A point in map world coordinates, in metres."""

    x: float
    y: float


@dataclass
class MapPose:
    """A position with heading, in metres and radians (0 = +x, anticlockwise)."""

    x: float
    y: float
    heading: float


@dataclass
class MapGrid:
    """An occupancy grid, row-major from the map origin (bottom-left).

    ``cells`` holds one byte per cell; ``room_ids`` (persisted maps only) holds
    one room segment id per cell, ``0`` meaning unassigned. World-to-cell:
    ``col = (x - origin.x) / resolution``, ``row = (y - origin.y) / resolution``.
    """

    resolution: float  # metres per cell
    width: int
    height: int
    origin: MapPoint
    cells: bytes
    room_ids: Optional[bytes] = None

    # Cell values observed in SharkIQ grids.
    UNKNOWN = 0x4B
    VOID = 0x00

    @staticmethod
    def is_wall(value: int) -> bool:
        """``True`` for wall/obstacle cells (``0x50`` and above)."""
        return value >= 0x50

    @staticmethod
    def is_floor(value: int) -> bool:
        """``True`` for free-floor cells (explored, not wall, not void)."""
        return 0 < value < 0x4B

    def cell(self, col: int, row: int) -> int:
        """Return the occupancy value at ``(col, row)``."""
        return self.cells[row * self.width + col]

    def room_id(self, col: int, row: int) -> Optional[int]:
        """Return the room segment id at ``(col, row)``, or ``None`` if unavailable."""
        if self.room_ids is None:
            return None
        return self.room_ids[row * self.width + col]


@dataclass
class MapRoom:
    """A named room as drawn in the app, with its bounding polygon."""

    name: str
    polygon: List[MapPoint]
    selected: bool = False  # Included in the most recent job
    coverage: Optional[float] = None  # Fraction cleaned in the most recent job


@dataclass
class MapFeature:
    """A vector feature of the persisted map — a wall outline or a door."""

    kind: str  # "edge" or "door"
    points: List[MapPoint]


@dataclass
class VacuumLogEntry:
    """One entry of the robot's own event log, carried in the persisted map."""

    key: str  # e.g. "DT_STATE_CHANGE", "DT_WARNING_CODE"
    time: int  # Unix epoch seconds as reported by the robot
    code: str


@dataclass
class VacuumMap:
    """Map data decoded from a SharkIQ MQTT map frame.

    Live frames (every few seconds during a job) carry the grid, the path
    cleaned so far and the robot's pose history. The larger *persisted* frame,
    published once when the robot reaches the dock, adds rooms, wall and door
    vectors, the dock pose, job statistics and the robot's event log.
    """

    grid: MapGrid
    path: List[MapPoint] = field(default_factory=list)
    poses: List[MapPose] = field(default_factory=list)
    persisted: bool = False
    map_id: Optional[str] = None
    name: Optional[str] = None
    dock: Optional[MapPose] = None
    rooms: List[MapRoom] = field(default_factory=list)
    features: List[MapFeature] = field(default_factory=list)
    log: List[VacuumLogEntry] = field(default_factory=list)
    job_started: Optional[int] = None  # Unix epoch seconds
    job_duration: Optional[int] = None  # seconds
    cleaned_cells: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def robot(self) -> Optional[MapPose]:
        """Current robot pose: the last recorded pose, if any."""
        return self.poses[-1] if self.poses else None

    @property
    def cleaned_area(self) -> Optional[float]:
        """Cleaned area of the job in square metres, if reported."""
        if self.cleaned_cells is None:
            return None
        return self.cleaned_cells * self.grid.resolution**2


@dataclass
class VacuumEvent:
    """A single event from the vacuum event log."""

    id: int
    type: str
    type_id: int
    timestamp: Dict[str, int]
    current_status: str
    source_type: str
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DeviceInfo:
    """Device identity and connectivity information."""

    firmware: Optional[str] = None
    mac_address: Optional[str] = None
    ip_address: Optional[str] = None
    ssid: Optional[str] = None
    rssi: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProbeResult:
    """Result of a :meth:`VacuumClient.probe` call."""

    rest_mapping: Optional[str] = None
    """``id`` of the REST mapping that responded successfully, or ``None``."""

    mqtt_mapping: Optional[str] = None
    """``id`` of the MQTT mapping that responded successfully, or ``None``."""

    @property
    def has_rest(self) -> bool:
        """``True`` if a working REST mapping was found."""
        return self.rest_mapping is not None

    @property
    def has_mqtt(self) -> bool:
        """``True`` if a working MQTT mapping was found."""
        return self.mqtt_mapping is not None

    @property
    def is_connected(self) -> bool:
        """``True`` if at least one transport responded successfully."""
        return self.has_rest or self.has_mqtt
