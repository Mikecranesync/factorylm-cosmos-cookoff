"""Test sim mode works without PLC hardware."""
import os
os.environ["FACTORYLM_NET_MODE"] = "sim"

def test_sim_mode_works_without_plc():
    from net.sim.plc_simulator import PLCSimulator
    sim = PLCSimulator(node_id="test-sim", db_path=None)
    snap = sim.tick()
    assert snap is not None
    d = snap.to_dict()
    assert "motor_running" in d
    assert "motor_speed" in d
    assert "temperature" in d

def test_sim_mode_fault_injection():
    from net.sim.plc_simulator import PLCSimulator
    sim = PLCSimulator(node_id="test-sim", db_path=None)
    result = sim.inject_fault("jam")
    assert "jam" in result.lower() or "Conveyor" in result
    snap = sim.tick()
    assert snap.error_code == 3

def test_sim_mode_tag_extraction():
    import asyncio
    from net.drivers.tag_extractor import extract_tags
    result = asyncio.run(extract_tags("192.168.1.100", 502, "ModbusTCP"))
    d = result.to_dict()
    assert len(d["tags"]) > 0
