# Data Models

All transport clients return normalized model objects independent of the underlying protocol.

---

## VacuumStatus

```python
@dataclass
class VacuumStatus:
    mode: VacuumMode           # Normalized operating mode
    battery_level: int | None  # 0–100, or None if unavailable
    charging: bool | None      # True = "connected", False = "unconnected"
    raw: dict                  # Full original response

    @property
    def is_cleaning(self) -> bool: ...
    @property
    def is_docked(self) -> bool: ...  # True for DOCKED and DOCKING only
```

---

## VacuumMode

```python
class VacuumMode(str, Enum):
    UNKNOWN           = "unknown"
    CLEANING          = "cleaning"
    RETURNING_TO_DOCK = "returning_to_dock"
    DOCKING           = "docking"
    DOCKED            = "docked"
    IDLE              = "idle"       # Stopped and off the dock (mode=ready, charging=unconnected)
    EXPLORING         = "exploring"  # Mapping/exploration run in progress
```

The REST API does not expose `docked` directly. `DOCKED` is derived automatically from two fields:
- `mode: "ready"` **and** `charging: "connected"` → `DOCKED`
- `mode: "ready"` **and** `charging: "unconnected"` → `IDLE` (stopped, off dock)

This combined evaluation is handled automatically by the library — `mode_map` alone is insufficient for the `"ready"` state.

`is_docked` returns `True` only for `DOCKED` and `DOCKING`. `IDLE` and `EXPLORING` vacuums are not considered docked.

---

## VacuumEvent

```python
@dataclass
class VacuumEvent:
    id: int
    type: str              # e.g. "status_water_tank_removed" (also dustbin on vacuums)
    type_id: int
    timestamp: dict        # {"year": ..., "month": ..., ...}
    current_status: str
    source_type: str
    raw: dict
```

---

## DeviceInfo

```python
@dataclass
class DeviceInfo:
    firmware: str | None
    mac_address: str | None  # Use this as unique_id in Home Assistant
    ip_address: str | None
    ssid: str | None
    rssi: int | None
    raw: dict
```

> **Note:** The MAC address returned by `get_wifi_status()` is the recommended value to use as `unique_id` when configuring a Home Assistant device. The robot ID endpoint does not expose a serial number.

---

## SuctionLevel

```python
class SuctionLevel(str, Enum):
    ECO    = "eco"
    NORMAL = "normal"
    MAX    = "max"
```

Named as in the SharkClean app. Used by `VacuumClient.set_suction()`.

---

## VacuumStatus — MQTT-only fields

The SharkIQ MQTT status decoder fills in a few more fields; other transports leave them `None`:

```python
job_active: bool | None       # A job is in progress
deep_clean: bool | None       # Matrix / spot clean in progress (only set during a job)
recharge_resume: bool | None  # Recharge & Resume setting
evac_resume: bool | None      # Evac & Resume setting
map: VacuumMap | None         # Only on map-bearing frames
```

The suction level is deliberately absent: the robot does not report it in status, only echoes it once when it changes.

---

## VacuumMap

Decoded from the map frames the robot publishes over MQTT. Live frames arrive every few seconds during a job; the *persisted* frame arrives once, as the robot reaches the dock, and carries everything the live frame does plus rooms, vectors, the dock pose, job statistics and the robot's event log.

```python
@dataclass
class VacuumMap:
    grid: MapGrid
    path: list[MapPoint]           # Cleaned path so far, ~1 point per 0.12 m
    poses: list[MapPose]           # Pose log with heading, ~1 pose per 0.22 m
    persisted: bool                # True for the end-of-job frame
    map_id: str | None             # e.g. "3CDBBC59" — persisted only
    name: str | None               # persisted only
    dock: MapPose | None           # persisted only
    rooms: list[MapRoom]           # persisted only
    features: list[MapFeature]     # persisted only: wall "edge" and "door" polylines
    log: list[VacuumLogEntry]      # persisted only: the robot's event log
    job_started: int | None        # Unix epoch seconds — persisted only
    job_duration: int | None       # seconds — persisted only
    cleaned_cells: int | None      # persisted only
    raw: dict

    @property
    def robot(self) -> MapPose | None: ...       # last pose, i.e. where the robot is
    @property
    def cleaned_area(self) -> float | None: ...  # m², from cleaned_cells × resolution²
```

All coordinates are metres in the map frame; headings are radians, `0` along +x, anticlockwise positive. Convert to grid cells with `col = (x - grid.origin.x) / grid.resolution` and `row = (y - grid.origin.y) / grid.resolution`; row 0 is the bottom of the map.

### MapGrid

```python
@dataclass
class MapGrid:
    resolution: float        # metres per cell (0.06 on the RV2610BFCA)
    width: int
    height: int
    origin: MapPoint         # world position of cell (0, 0)
    cells: bytes             # width × height occupancy values, row-major
    room_ids: bytes | None   # persisted only: room segment id per cell, 0 = unassigned

    UNKNOWN = 0x4B           # unexplored
    VOID = 0x00

    @staticmethod
    def is_wall(value: int) -> bool: ...   # 0x50 and above
    @staticmethod
    def is_floor(value: int) -> bool: ...  # explored free floor
    def cell(self, col: int, row: int) -> int: ...
    def room_id(self, col: int, row: int) -> int | None: ...
```

### MapPoint, MapPose, MapRoom, MapFeature, VacuumLogEntry

```python
@dataclass
class MapPoint:
    x: float
    y: float

@dataclass
class MapPose:
    x: float
    y: float
    heading: float           # radians

@dataclass
class MapRoom:
    name: str                # as shown in the app
    polygon: list[MapPoint]  # bounding polygon drawn in the app
    selected: bool           # included in the most recent job
    coverage: float | None   # fraction cleaned in the most recent job

@dataclass
class MapFeature:
    kind: str                # "edge" (wall outline) or "door"
    points: list[MapPoint]

@dataclass
class VacuumLogEntry:
    key: str                 # e.g. "DT_STATE_CHANGE", "DT_WARNING_CODE"
    time: int                # Unix epoch seconds, as reported by the robot
    code: str                # e.g. "SYS_ST_CLEANING", "WARN_MM_LOWLIGHT"
```

Room segment ids in `room_ids` do not necessarily map one-to-one onto `rooms`: the robot segments the floor itself, and the app's named rooms are polygons drawn over those segments (two named rooms can share one segment). Use the polygons to name a location and the raster to colour it.

The event log's `time` values can jump when the robot re-syncs its clock mid-job; rely on list order, not `time`, for sequence.
