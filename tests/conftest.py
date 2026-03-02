"""Shared test fixtures for FactoryLM Connect."""
import os
import tempfile

# Use a unique temp DB to avoid permission conflicts across sessions
_test_db = os.path.join(tempfile.mkdtemp(), "factorylm_test.db")
os.environ["FACTORYLM_NET_MODE"] = "sim"
os.environ["FACTORYLM_NET_DB"] = _test_db

import pytest
from fastapi.testclient import TestClient

# Initialize DB before importing app
from net.api.main import _init_db, app
_init_db()

@pytest.fixture
def client():
    return TestClient(app)
