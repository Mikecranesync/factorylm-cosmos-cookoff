"""Test fault detection engine."""
import os
os.environ["FACTORYLM_NET_MODE"] = "sim"

def test_fault_engine_detects_overload():
    from net.diagnosis.fault_engine import FaultEngine
    engine = FaultEngine()
    snapshot = {
        "motor_running": True,
        "motor_current": 15.0,
        "temperature": 30.0,
        "motor_speed": 60,
        "conveyor_speed": 50,
        "conveyor_running": True,
        "e_stop": False,
        "sensor_1": True,
        "sensor_2": True,
    }
    result = engine.analyze_snapshot(snapshot)
    assert result["active_faults"] > 0
    fault_codes = [f["code"] for f in result["faults"]]
    # Should detect either motor overload or speed deviation
    assert len(fault_codes) > 0

def test_fault_engine_no_faults_normal():
    from net.diagnosis.fault_engine import FaultEngine
    engine = FaultEngine()
    snapshot = {
        "motor_running": True,
        "motor_current": 3.0,
        "temperature": 30.0,
        "motor_speed": 60,
        "conveyor_speed": 60,
        "conveyor_running": True,
        "e_stop": False,
        "sensor_1": True,
        "sensor_2": True,
    }
    result = engine.analyze_snapshot(snapshot)
    # With normal values and matching speeds, should have minimal or no faults
    assert result["critical_count"] == 0
