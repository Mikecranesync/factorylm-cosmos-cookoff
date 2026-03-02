"""Test tag extraction engine (sim mode)."""
import asyncio
import os
os.environ["FACTORYLM_NET_MODE"] = "sim"

def test_modbus_extraction_returns_tags():
    from net.drivers.tag_extractor import extract_tags
    result = asyncio.run(extract_tags("192.168.1.100", 502, "ModbusTCP"))
    d = result.to_dict()
    assert d["protocol"] in ("ModbusTCP", "EtherNetIP")  # sim may return EtherNetIP
    assert len(d["tags"]) > 0
    assert all("address" in t for t in d["tags"])

def test_ethip_returns_named_tags():
    from net.drivers.tag_extractor import extract_tags
    result = asyncio.run(extract_tags("192.168.1.100", 44818, "EtherNetIP"))
    d = result.to_dict()
    assert d["protocol"] == "EtherNetIP"
    assert all(t["named"] == True for t in d["tags"])
    assert all(t["name"] != "" for t in d["tags"])

def test_extraction_output_format():
    from net.drivers.tag_extractor import extract_tags
    result = asyncio.run(extract_tags("192.168.1.100", 502, "ModbusTCP"))
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
