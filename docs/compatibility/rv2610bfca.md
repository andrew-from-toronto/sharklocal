# RV2610BFCA — Compatibility Matrix

---

## Actions

| Feature | REST | MQTT | Supported mappings |
|---------|:----:|:----:|--------------------|
| Start cleaning | ❌ | ✅ | MQTT: `sharkiq_v1` |
| Stop | ❌ | ✅ | MQTT: `sharkiq_v1` |
| Return to dock | ❌ | ✅ | MQTT: `sharkiq_v1` |
| Explore / Map | ❌ | ❌ | |
| Get status | ❌ | ✅ | MQTT: `sharkiq_v1` |
| Get event log | ❌ | ✅ ¹ | MQTT: `sharkiq_v1` |
| Get robot ID | ❌ | ❌ | |
| Get Wi-Fi status | ❌ | ❌ | |
| Find robot | ❌ | ✅ | MQTT: `sharkiq_v1` |
| Set suction (eco / normal / max) | ❌ | ✅ | MQTT: `sharkiq_v1` |
| Recharge & Resume on / off | ❌ | ✅ | MQTT: `sharkiq_v1` |
| Evac & Resume on / off | ❌ | ✅ | MQTT: `sharkiq_v1` |
| Clean rooms (incl. Matrix Clean) | ❌ | ✅ | MQTT: `sharkiq_v1` |
| Spot clean | ❌ | ✅ | MQTT: `sharkiq_v1` |

> ¹ Via the event log embedded in the persisted map frame the robot publishes when it docks (`VacuumMap.log`), not via a request.

---

## Status Fields

| Field | REST | MQTT | Supported mappings |
|-------|:----:|:----:|--------------------|
| Operating mode | ❌ | ✅ | MQTT: `sharkiq_v1` |
| Battery level | ❌ | ✅ | MQTT: `sharkiq_v1` |
| Charging status | ❌ | ✅ ² | MQTT: `sharkiq_v1` |
| Job active / deep clean | ❌ | ✅ | MQTT: `sharkiq_v1` |
| Recharge & Resume / Evac & Resume | ❌ | ✅ | MQTT: `sharkiq_v1` |
| Live map (grid, cleaned path, robot pose with heading) | ❌ | ✅ | MQTT: `sharkiq_v1` |
| Persisted map (rooms, room raster, walls, doors, dock, job stats, event log) | ❌ | ✅ | MQTT: `sharkiq_v1` |

> ² `charging` reads `true` in every status frame on this model, including mid-clean — `BatteryInfo.ChargingState` is a constant `3` here, so do not infer docked from it.

---

## Operating Modes

| Mode | REST | MQTT | Supported mappings |
|------|:----:|:----:|--------------------|
| `cleaning` | ❌ | ✅ | MQTT: `sharkiq_v1` |
| `returning_to_dock` | ❌ | ✅ | MQTT: `sharkiq_v1` |
| `docking` | ❌ | ✅ | MQTT: `sharkiq_v1` |
| `docked` | ❌ | ✅ | MQTT: `sharkiq_v1` |
| `idle` | ❌ | ✅ | MQTT: `sharkiq_v1` |
| `exploring` | ❌ | ❌ | |

---

## Known Issues / Notes

- **REST API:** Port 443 is closed/refused. Port 80 is open, but `/get/status` and `/get/wifi_status` return `404 Not Found`, and `/` returns a forbidden HTML page.
- **MQTT:** Uses standard `sharkiq_v1` protobuf format. Status requests, passive monitoring, and basic commands work.
- **Observed MQTT status:** `mode=docked`, `battery_level=100`, `charging=true`.
- **Command test:** `start_cleaning` returned `True` and status changed to `cleaning` within about 2 seconds. `stop` returned `True` and status changed to `returning_to_dock` within about 2 seconds. `go_home` returned `True`; the robot reported `docked` about 28 seconds after the first return-to-dock command.
- **Lifecycle** (firmware `V6.6.10-P7.N3308.17.0`): `docked (14)` → `cleaning (6)` → `returning_to_dock (7)` → `docking (13)` → `docked (14)`; the persisted map frame is published on the `13 → 14` edge. Mode `4` (`idle`) is reported when stopped off the dock or lifted.
- **Suction:** accepted while docked (the app only greys the control out). Echoed once on change; no status field.
- **Battery:** counts down through a job and snaps back to 100 within seconds of docking.
- **Maps:** a ~27 KB live frame every ~4 s during a job (0.06 m grid, cleaned path, pose log with heading); a ~92 KB persisted frame on docking with rooms, room-id raster, wall/door polylines, dock pose, job stats and the event log.
- **Room commands re-upload the room definition**, names included. Build them from the latest persisted map.
- **Not observed:** pause, an in-job error field (no fault occurred during testing), `exploring`.
