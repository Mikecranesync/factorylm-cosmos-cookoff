"""Test tag extraction engine — mocks, no sim mode."""
import asyncio
from unittest.mock import patch, MagicMock

from net.drivers.tag_extractor import TagExtractor, ExtractionResult, Tag


def test_modbus_extraction_returns_tags():
    """Mock the Modbus brute force scan to return tags."""
    mock_tags = [
        {"name": "Conveyor", "plc_address": "coil:0", "type": "BOOL", "value": True,
         "address": None, "named": True, "writable": True},
        {"name": "motor_speed", "plc_address": "hr:101", "type": "INT", "value": 85,
         "address": None, "named": True, "writable": True},
    ]

    with patch("net.drivers.tag_extractor.TagExtractor._do_extract") as mock_extract:
        mock_extract.return_value = ExtractionResult(
            gateway_id="flm-test",
            plc_ip="192.168.1.100",
            protocol="Modbus",
            extraction_method="modbus_brute_force",
            extracted_at="2025-01-01T00:00:00Z",
            tags=mock_tags,
        )
        extractor = TagExtractor("flm-test", "192.168.1.100")
        result = asyncio.run(extractor.extract())
        d = result.to_dict()
        assert len(d["tags"]) > 0
        assert d["protocol"] == "Modbus"


def test_extraction_output_format():
    """Verify ExtractionResult has all required fields."""
    result = ExtractionResult(
        gateway_id="flm-test",
        plc_ip="192.168.1.100",
        protocol="Modbus",
        extraction_method="modbus_brute_force",
        extracted_at="2025-01-01T00:00:00Z",
        tags=[
            {"name": "motor_speed", "type": "INT", "value": 85,
             "address": None, "plc_address": "hr:101", "named": True, "writable": True},
        ],
    )
    d = result.to_dict()
    assert "gateway_id" in d
    assert "plc_ip" in d
    assert "protocol" in d
    assert "extraction_method" in d
    assert "extracted_at" in d
    assert "tags" in d
    for tag in d["tags"]:
        assert "name" in tag
        assert "type" in tag
        assert "value" in tag
        assert "named" in tag
        assert "writable" in tag
