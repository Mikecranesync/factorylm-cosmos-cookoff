"""Tests for VFD conflict detection (V001-V006)."""
from net.diagnosis.vfd_conflicts import detect_conflicts, Conflict


def _healthy_vfd():
    """Return a VFD tags dict representing normal operation."""
    return {
        "vfd_connected": True,
        "vfd_control_word": 0x0001,
        "vfd_setpoint_hz": 30.0,
        "vfd_output_hz": 30.0,
        "vfd_output_amps": 3.5,
        "vfd_actual_freq": 30.0,
        "vfd_actual_current": 3.5,
        "vfd_dc_bus_volts": 320.0,
        "vfd_motor_rpm": 1750,
        "vfd_torque_pct": 45.0,
        "vfd_drive_temp_c": 42.0,
        "vfd_fault_code": 0,
        "vfd_warning_code": 0,
        "vfd_fault_description": "No fault",
    }


def _healthy_plc():
    """Return PLC tags dict representing normal operation."""
    return {
        "conveyor_running": True,
        "motor_running": True,
        "motor_speed": 60,
        "motor_current": 3.5,
        "temperature": 45.0,
    }


def _healthy_belt():
    """Return belt status dict representing normal operation."""
    return {
        "belt_rpm": 1750,
        "belt_speed_pct": 85.0,
        "belt_status": "NORMAL",
    }


def test_no_conflicts_normal_operation():
    result = detect_conflicts(_healthy_plc(), _healthy_vfd(), _healthy_belt())
    assert result == []


def test_no_conflicts_when_vfd_none():
    result = detect_conflicts(_healthy_plc(), None, _healthy_belt())
    assert result == []


def test_no_conflicts_when_vfd_disconnected():
    vfd = {"vfd_connected": False}
    result = detect_conflicts(_healthy_plc(), vfd, _healthy_belt())
    assert result == []


def test_v001_belt_stopped_vfd_running():
    vfd = _healthy_vfd()
    belt = {"belt_rpm": 0, "belt_speed_pct": 0, "belt_status": "STOPPED"}

    result = detect_conflicts(_healthy_plc(), vfd, belt)

    codes = [c.code for c in result]
    assert "V001" in codes
    v001 = next(c for c in result if c.code == "V001")
    assert v001.severity == "critical"


def test_v002_no_current():
    vfd = _healthy_vfd()
    vfd["vfd_output_amps"] = 0.0
    vfd["vfd_control_word"] = 0x0001  # FWD

    result = detect_conflicts(_healthy_plc(), vfd, _healthy_belt())

    codes = [c.code for c in result]
    assert "V002" in codes
    v002 = next(c for c in result if c.code == "V002")
    assert v002.severity == "critical"


def test_v003_cant_reach_setpoint():
    vfd = _healthy_vfd()
    vfd["vfd_setpoint_hz"] = 50.0
    vfd["vfd_output_hz"] = 30.0  # 20 Hz short

    result = detect_conflicts(_healthy_plc(), vfd, _healthy_belt())

    codes = [c.code for c in result]
    assert "V003" in codes
    v003 = next(c for c in result if c.code == "V003")
    assert v003.severity == "warning"


def test_v004_belt_speed_mismatch():
    vfd = _healthy_vfd()
    vfd["vfd_motor_rpm"] = 1750
    belt = {"belt_rpm": 1000, "belt_speed_pct": 50.0, "belt_status": "NORMAL"}

    result = detect_conflicts(_healthy_plc(), vfd, belt)

    codes = [c.code for c in result]
    assert "V004" in codes
    v004 = next(c for c in result if c.code == "V004")
    assert v004.severity == "warning"


def test_v005_drive_overtemp_warning():
    vfd = _healthy_vfd()
    vfd["vfd_drive_temp_c"] = 85.0

    result = detect_conflicts(_healthy_plc(), vfd, _healthy_belt())

    codes = [c.code for c in result]
    assert "V005" in codes
    v005 = next(c for c in result if c.code == "V005")
    assert v005.severity == "warning"


def test_v005_drive_overtemp_critical():
    vfd = _healthy_vfd()
    vfd["vfd_drive_temp_c"] = 95.0

    result = detect_conflicts(_healthy_plc(), vfd, _healthy_belt())

    v005 = next(c for c in result if c.code == "V005")
    assert v005.severity == "critical"


def test_v006_vfd_fault_plc_running():
    vfd = _healthy_vfd()
    vfd["vfd_fault_code"] = 8  # Drive overtemperature
    plc = _healthy_plc()
    plc["conveyor_running"] = True

    result = detect_conflicts(plc, vfd, _healthy_belt())

    codes = [c.code for c in result]
    assert "V006" in codes
    v006 = next(c for c in result if c.code == "V006")
    assert v006.severity == "critical"
    assert "overtemperature" in v006.description.lower()


def test_skips_vision_checks_when_belt_none():
    """V001 and V004 require belt data — should be skipped when None."""
    vfd = _healthy_vfd()
    vfd["vfd_output_hz"] = 30.0

    result = detect_conflicts(_healthy_plc(), vfd, None)

    codes = [c.code for c in result]
    assert "V001" not in codes
    assert "V004" not in codes
