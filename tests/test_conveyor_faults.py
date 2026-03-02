"""Tests for conveyor fault detection and classification."""

from net.diagnosis.conveyor_faults import (
    FaultDiagnosis,
    FaultSeverity,
    detect_faults,
    format_diagnosis_for_technician,
)


def _base_tags(**overrides):
    """Return healthy baseline tags with optional overrides."""
    tags = {
        "motor_running": True,
        "motor_speed": 60,
        "motor_current": 2.5,
        "temperature": 40.0,
        "pressure": 80,
        "conveyor_running": True,
        "conveyor_speed": 50,
        "sensor_1": False,
        "sensor_2": False,
        "fault_alarm": False,
        "e_stop": False,
        "error_code": 0,
        "error_message": "",
    }
    tags.update(overrides)
    return tags


# ── Normal / Idle ─────────────────────────────────────────────────────

def test_normal_operation():
    faults = detect_faults(_base_tags())
    assert len(faults) == 1
    assert faults[0].fault_code == "OK"
    assert faults[0].severity == FaultSeverity.INFO


def test_idle_system():
    faults = detect_faults(_base_tags(motor_running=False, conveyor_running=False, conveyor_speed=0))
    assert any(f.fault_code == "IDLE" for f in faults)


# ── Emergency ─────────────────────────────────────────────────────────

def test_estop_detected():
    faults = detect_faults(_base_tags(e_stop=True))
    assert any(f.fault_code == "E001" for f in faults)
    estop = [f for f in faults if f.fault_code == "E001"][0]
    assert estop.severity == FaultSeverity.EMERGENCY
    assert estop.requires_safety_review is True


# ── Motor Overcurrent ─────────────────────────────────────────────────

def test_motor_overcurrent():
    faults = detect_faults(_base_tags(motor_current=6.5))
    assert any(f.fault_code == "M001" for f in faults)
    m001 = [f for f in faults if f.fault_code == "M001"][0]
    assert m001.severity == FaultSeverity.CRITICAL
    assert m001.requires_maintenance is True


def test_no_overcurrent_when_motor_off():
    faults = detect_faults(_base_tags(motor_running=False, motor_current=6.5, conveyor_running=False))
    assert not any(f.fault_code == "M001" for f in faults)


# ── Over-temperature ──────────────────────────────────────────────────

def test_critical_temperature():
    faults = detect_faults(_base_tags(temperature=85.0))
    assert any(f.fault_code == "T001" for f in faults)


def test_elevated_temperature():
    faults = detect_faults(_base_tags(temperature=70.0))
    assert any(f.fault_code == "T002" for f in faults)


def test_normal_temperature_no_fault():
    faults = detect_faults(_base_tags(temperature=50.0))
    assert not any(f.fault_code in ("T001", "T002") for f in faults)


# ── Conveyor Jam ──────────────────────────────────────────────────────

def test_conveyor_jam():
    faults = detect_faults(_base_tags(sensor_1=True, sensor_2=True))
    assert any(f.fault_code == "C001" for f in faults)


# ── Motor Stopped Unexpectedly ────────────────────────────────────────

def test_motor_stopped_unexpectedly():
    faults = detect_faults(_base_tags(motor_running=False, conveyor_speed=60, conveyor_running=False))
    assert any(f.fault_code == "M002" for f in faults)


# ── Low Pressure ──────────────────────────────────────────────────────

def test_low_pressure():
    faults = detect_faults(_base_tags(pressure=40))
    assert any(f.fault_code == "P001" for f in faults)


# ── PLC Fault Code ────────────────────────────────────────────────────

def test_plc_fault_code():
    faults = detect_faults(_base_tags(fault_alarm=True, error_code=3, error_message="Jam"))
    assert any(f.fault_code == "PLC003" for f in faults)


# ── Severity ordering ────────────────────────────────────────────────

def test_faults_sorted_by_severity():
    tags = _base_tags(
        e_stop=True,
        motor_current=7.0,
        temperature=70.0,
    )
    faults = detect_faults(tags)
    assert len(faults) >= 3
    # Emergency should come first
    assert faults[0].severity == FaultSeverity.EMERGENCY


# ── Multiple faults at once ──────────────────────────────────────────

def test_multiple_faults_simultaneously():
    tags = _base_tags(motor_current=6.0, temperature=85.0, pressure=40)
    faults = detect_faults(tags)
    codes = {f.fault_code for f in faults}
    assert "M001" in codes  # overcurrent
    assert "T001" in codes  # over-temp
    assert "P001" in codes  # low pressure


# ── Formatter ─────────────────────────────────────────────────────────

def test_format_diagnosis():
    d = FaultDiagnosis(
        fault_code="TEST",
        severity=FaultSeverity.WARNING,
        title="Test Fault",
        description="A test fault.",
        likely_causes=["Cause A"],
        suggested_checks=["Check A"],
        affected_tags=["tag_x"],
    )
    text = format_diagnosis_for_technician(d)
    assert "[WARNING] TEST: Test Fault" in text
    assert "Cause A" in text
    assert "Check A" in text


def test_format_safety_review():
    d = FaultDiagnosis(
        fault_code="E001",
        severity=FaultSeverity.EMERGENCY,
        title="E-Stop",
        description="Emergency stop.",
        likely_causes=[],
        suggested_checks=[],
        affected_tags=[],
        requires_safety_review=True,
    )
    text = format_diagnosis_for_technician(d)
    assert "SAFETY" in text
