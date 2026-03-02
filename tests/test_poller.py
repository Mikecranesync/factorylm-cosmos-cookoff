"""Tests for the background Poller service."""

import os
import tempfile
import time

os.environ["FACTORYLM_NET_MODE"] = "sim"
os.environ["FACTORYLM_NET_DB"] = os.path.join(tempfile.mkdtemp(), "poller_test.db")

from net.services.poller import Poller


def _make_poller():
    db = os.path.join(tempfile.mkdtemp(), "p.db")
    p = Poller(db_path=db)
    return p


def test_poller_init_creates_tables():
    p = _make_poller()
    # Should not raise — tables created during __init__
    assert p.latest is None
    assert p.is_running is False
    assert p.plc_connected is False


def test_poller_configure_and_start():
    p = _make_poller()
    p.configure(ip="192.168.1.100", port=502)
    p.start()
    time.sleep(1)
    assert p.is_running
    assert p.latest is not None  # sim should produce data
    p.stop()
    assert not p.is_running


def test_poller_latest_has_tags():
    p = _make_poller()
    p.configure(ip="192.168.1.100")
    p.start()
    time.sleep(1)
    tags = p.latest
    assert isinstance(tags, dict)
    # Sim should produce some tag keys
    assert len(tags) > 0
    p.stop()


def test_poller_writes_history():
    import sqlite3
    p = _make_poller()
    p.configure(ip="192.168.1.100")
    p.start()
    time.sleep(2)  # Give enough for 1Hz write
    p.stop()
    conn = sqlite3.connect(p.db_path)
    rows = conn.execute("SELECT COUNT(*) FROM tag_history").fetchone()[0]
    conn.close()
    assert rows >= 1


def test_poller_save_plc_config():
    import sqlite3, json
    p = _make_poller()
    p.save_plc_config(
        plc_id="plc-test",
        ip="10.0.0.1",
        port=502,
        brand="TestBrand",
        template_name="micro820",
        tags_json=json.dumps({"coils": {}, "registers": {}}),
    )
    conn = sqlite3.connect(p.db_path)
    row = conn.execute("SELECT ip, brand FROM plc_configs WHERE plc_id = 'plc-test'").fetchone()
    conn.close()
    assert row[0] == "10.0.0.1"
    assert row[1] == "TestBrand"


def test_poller_gateway_config():
    p = _make_poller()
    p.save_gateway_config("gateway_id", "flm-test123")
    assert p.get_gateway_id() == "flm-test123"


def test_poller_tag_names():
    p = _make_poller()
    p.save_tag_name("plc-x", "HR100", "Motor Speed")
    names = p.get_tag_names("plc-x")
    assert names == {"HR100": "Motor Speed"}


def test_poller_double_start_is_safe():
    p = _make_poller()
    p.configure(ip="192.168.1.100")
    p.start()
    p.start()  # Should warn but not crash
    assert p.is_running
    p.stop()


def test_poller_stop_without_start():
    p = _make_poller()
    p.stop()  # Should not raise
