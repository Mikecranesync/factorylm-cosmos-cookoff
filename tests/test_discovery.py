"""Test PLC discovery — fake_scan_result utility function."""


def test_finds_plc_on_known_subnet():
    from net.drivers.discovery import fake_scan_result
    results = fake_scan_result()
    assert any(d.ip == "192.168.1.100" for d in results)
    assert len(results) > 0
