"""Tests for sharklocal.codes and the live error/warning fields."""

import base64
from pathlib import Path

import pytest

from sharklocal import codes, protobuf
from sharklocal.mappings import load_mqtt_mapping
from sharklocal.models import VacuumMode
from sharklocal.mqtt_client import _decode_sharkiq_protobuf_v1

FIXTURES = Path(__file__).parent / "fixtures"


def _status_frame() -> bytes:
    return base64.b64decode((FIXTURES / "sharkiq_status_frame.b64").read_text().strip())


def test_names_agree_with_the_event_log():
    # The log writes these as strings; the schema numbers them.
    assert codes.WARNING_CODES[43] == "WARN_MM_LOWLIGHT"
    assert codes.DOCK_EVENTS[7] == "DE_USR_CTR_DOCK"
    assert codes.DOCK_EVENTS[8] == "DE_CLEAN_FINISH"
    assert codes.SYSTEM_STATES[13] == "SYS_ST_CHARGING"
    assert codes.ERROR_CODES[0] == "ERROR_NONE"


def test_unknown_numbers_stay_visible():
    assert codes.names(codes.WARNING_CODES, [43, 9999]) == ["WARN_MM_LOWLIGHT", "UNKNOWN_9999"]


def _decode(extra: bytes):
    mapping = load_mqtt_mapping("sharkiq_v1")
    return _decode_sharkiq_protobuf_v1(_status_frame() + extra, mapping.modes)


def test_a_real_status_frame_has_no_active_errors():
    status = _decode(b"")
    assert status.errors == []
    assert status.warnings == []


def test_packed_errors_and_warnings_are_decoded():
    packed = protobuf.encode_bytes_field(5, bytes([21, 64])) + protobuf.encode_bytes_field(6, bytes([43]))
    status = _decode(packed)
    assert status.errors == [21, 64]
    assert codes.names(codes.ERROR_CODES, status.errors)[0] == codes.ERROR_CODES[21]
    assert status.warnings == [43]


def test_unpacked_errors_are_decoded():
    status = _decode(protobuf.encode_varint_field(5, 64) + protobuf.encode_varint_field(5, 150))
    assert status.errors == [64, 150]


@pytest.mark.parametrize(
    "state, mode",
    [
        (3, VacuumMode.IDLE),
        (4, VacuumMode.PAUSED),
        (5, VacuumMode.ERROR),
        (6, VacuumMode.CLEANING),
        (7, VacuumMode.RETURNING_TO_DOCK),
        (8, VacuumMode.CLEANING),
        (13, VacuumMode.DOCKED),  # charging on the dock: observed after every job
        (14, VacuumMode.DOCKED),
        (16, VacuumMode.CLEANING),
    ],
)
def test_system_states_map_to_modes(state, mode):
    assert load_mqtt_mapping("sharkiq_v1").modes[state] == mode.value
