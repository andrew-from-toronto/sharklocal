# VacuumClient

`VacuumClient` is the recommended entry point. It wraps both transport clients, handles transport selection automatically, and supports real-time MQTT monitoring alongside polled REST calls.

```python
from sharklocal import VacuumClient

async with VacuumClient(
    host="192.168.1.100",
    rest_mappings="sharkiq_v1",          # single string or list
    mqtt_mappings="sharkiq_v1",          # single string or list
    mapping_search_paths=["/custom/mappings"],  # optional
) as vacuum:
    ...
```

Either mapping may be omitted. If only one transport is configured, it is used exclusively.

---

## Mapping Probe

When multiple mapping candidates are supplied, call `probe()` during setup. It tests each mapping by requesting the vacuum status and pins the first one that responds. All subsequent calls use the pinned mapping.

```python
async with VacuumClient(
    "192.168.1.100",
    rest_mappings=["sharkiq_v1", "other_model_v1"],
    mqtt_mappings=["sharkiq_v1"],
) as vacuum:
    result = await vacuum.probe()

    print(result.rest_mapping)   # "sharkiq_v1" or None
    print(result.mqtt_mapping)   # "sharkiq_v1" or None
    print(result.is_connected)   # True if at least one transport responded

    if not result.is_connected:
        raise RuntimeError("Vacuum not reachable")

    status = await vacuum.get_status()
```

With a single mapping per transport, `probe()` is not required — the mapping is pinned automatically.

`probe()` can be called again to re-test and re-pin (e.g. after a firmware update changes the API).

---

## Active Mapping Inspection

```python
vacuum.active_rest_mapping   # "sharkiq_v1" or None
vacuum.active_mqtt_mapping   # "sharkiq_v1" or None
```

---

## `via` — Primary Transport in Use

`vacuum.via` is a string attribute that reflects which transport is the primary connection. It is set automatically on init (single mapping) or after `probe()` (multiple candidates).

| Value | Meaning |
|---|---|
| `"REST"` | REST mapping is pinned and was the first to respond |
| `"MQTT"` | No REST mapping responded; MQTT is the primary transport |
| `"NONE"` | No transport has been confirmed yet (multiple candidates, `probe()` not called, or all candidates failed) |

```python
# Single mapping — via is set immediately on init
vacuum = VacuumClient("192.168.1.100", rest_mappings="sharkiq_v1")
print(vacuum.via)   # "REST"

vacuum = VacuumClient("192.168.1.100", mqtt_mappings="sharkiq_v1")
print(vacuum.via)   # "MQTT"

vacuum = VacuumClient("192.168.1.100", rest_mappings="sharkiq_v1", mqtt_mappings="sharkiq_v1")
print(vacuum.via)   # "REST"  (REST takes priority)

# Multiple candidates — via is NONE until probe() runs
vacuum = VacuumClient("192.168.1.100", rest_mappings=["sharkiq_v1", "other_v1"])
print(vacuum.via)   # "NONE"

result = await vacuum.probe()
print(vacuum.via)   # "REST", "MQTT", or "NONE" depending on what responded
```

---

## Actions

| Method | REST endpoint | MQTT action |
|---|---|---|
| `get_status()` | `GET /get/status` | `get_status` (status request) |
| `start_cleaning()` | `GET /set/clean_all` | `start_cleaning` (command) |
| `stop()` | `GET /set/stop` | `stop` (command) |
| `go_home()` | `GET /set/go_home` | `go_home` (command) |
| `explore()` | `GET /set/explore` | *(not in MQTT mapping)* |
| `get_events()` | `GET /get/event_log` | *(not in MQTT mapping)* |
| `get_device_info()` | `GET /get/robot_id` | *(not in MQTT mapping)* |
| `get_wifi_status()` | `GET /get/wifi_status` | *(not in MQTT mapping)* |
| `find_robot()` | *(not in REST mapping)* | `find_robot` (command) |
| `set_suction(level)` | *(not in REST mapping)* | `set_suction_eco` / `_normal` / `_max` (command) |
| `set_recharge_resume(enabled)` | *(not in REST mapping)* | `recharge_resume_on` / `_off` (command) |
| `set_evac_resume(enabled)` | *(not in REST mapping)* | `evac_resume_on` / `_off` (command) |
| `clean_rooms(names, deep=False, vacuum_map=None)` | *(not in REST mapping)* | runtime-built payload, then `start_cleaning` |
| `clean_spot(x, y, vacuum_map=None)` | *(not in REST mapping)* | runtime-built payload, then `start_cleaning` |

### Return Types

- **`get_status()`** → `VacuumStatus`
- **`get_events()`** → `list[VacuumEvent]`
- **`get_device_info()`**, **`get_wifi_status()`** → `DeviceInfo`
- Command methods → `bool` (`True` on success)

See [data-models.md](data-models.md) for field definitions of each return type.

---

## Real-Time Monitoring (MQTT)

`VacuumClient` can subscribe to the vacuum's MQTT status topic and invoke a callback on every update. Both sync and `async` callables are supported.

```python
async with VacuumClient("192.168.1.100", mqtt_mappings="sharkiq_v1") as vacuum:
    vacuum.on_status_update(lambda s: print(s.mode, s.battery_level))
    await vacuum.start_monitoring()

    # Monitoring runs as a background task.
    await asyncio.sleep(60)

    await vacuum.stop_monitoring()
```

While monitoring, the client keeps the most recent status in `vacuum.last_status` and the most recent **persisted** map in `vacuum.last_map` (see below). Live map frames update `last_status.map` but never replace `last_map`, so the room definition stays available through a job.

---

## Maps, Rooms and Settings

These are MQTT-only and, today, specific to the `sharkiq_v1` mapping. Models that publish map frames deliver them through monitoring: every `VacuumStatus` that carries map data has `status.map` set to a `VacuumMap`.

```python
def on_status(status: VacuumStatus) -> None:
    if status.map is None:
        return
    robot = status.map.robot                      # MapPose(x, y, heading) or None
    print(len(status.map.path), "path points, robot at", robot)
    if status.map.persisted:                      # the end-of-job frame
        print([room.name for room in status.map.rooms])
        print([e.code for e in status.map.log if e.key == "DT_WARNING_CODE"])

vacuum.on_status_update(on_status)
await vacuum.start_monitoring()
```

### Settings and locate

```python
await vacuum.find_robot()                          # play the locate sound
await vacuum.set_suction(SuctionLevel.MAX)         # "eco" | "normal" | "max"
await vacuum.set_recharge_resume(True)
await vacuum.set_evac_resume(False)
```

Recharge & Resume and Evac & Resume are read back from `VacuumStatus.recharge_resume` / `evac_resume`. The suction level is **not** reported in status — the robot echoes a change once and is then silent about it — so keep the last value you set if you need to display it.

### Room, Matrix and spot cleaning

```python
# Needs a persisted map for the room definition: either the one the client
# cached while monitoring (vacuum.last_map) or one you pass in.
await vacuum.clean_rooms(["Kitchen", "Hallway"])
await vacuum.clean_rooms(["Kitchen"], deep=True)   # Matrix Clean (two passes)
await vacuum.clean_spot(1.2, -0.4)                 # ~1.5 m square around (x, y) metres
```

Each of these publishes the map's room definition with the selection, then `start_cleaning`. Room names must match `VacuumMap.rooms` exactly (`ValueError` otherwise); with no persisted map available a `SharklocalError` is raised. Because the room definition is re-uploaded in full, **always use the latest persisted map** — a stale one renames rooms back to the names it was captured with.

---

## Transport Introspection

```python
vacuum.via                              # "REST", "MQTT", or "NONE"
vacuum.active_rest_mapping              # "sharkiq_v1" or None
vacuum.active_mqtt_mapping              # "sharkiq_v1" or None
vacuum.supported_actions()              # ["explore", "get_events", "get_status", ...]
vacuum.transports_for("get_status")     # ["rest", "mqtt"]
vacuum.transports_for("explore")        # ["rest"]
```
