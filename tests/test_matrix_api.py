"""Tests for the Matrix API service."""

import os
import tempfile

os.environ["MATRIX_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "matrix_test.db")

from services.matrix.app import app, init_db

init_db()

from fastapi.testclient import TestClient

client = TestClient(app)


def test_root_dashboard():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Pi Factory" in resp.text


def test_ingest_tags():
    from datetime import datetime, timezone
    resp = client.post("/api/tags", json={
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "node_id": "test-node",
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
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "tag_id" in data


def test_get_tags():
    # Ingest first
    client.post("/api/tags", json={
        "node_id": "test-node-2",
        "motor_running": True,
        "motor_speed": 50,
        "motor_current": 2.0,
        "temperature": 35.0,
        "pressure": 75,
    })
    resp = client.get("/api/tags")
    assert resp.status_code == 200
    data = resp.json()
    # Should return list or object with tags
    assert data is not None


def test_get_incidents():
    resp = client.get("/api/incidents")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, (list, dict))


def test_get_insights():
    resp = client.get("/api/insights")
    assert resp.status_code == 200
