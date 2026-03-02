"""Validate that all files referenced by the build-image GitHub Action exist.

This doesn't run pi-gen — it verifies the build manifest is consistent
so the real GH Actions build won't fail due to missing files.
"""

import os
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_pigen_config_exists():
    assert (ROOT / "factorylm-image" / "pi-gen" / "config").exists()


def test_pigen_stage_directory():
    stage = ROOT / "factorylm-image" / "pi-gen" / "stage-factorylm"
    assert stage.is_dir()
    # Must have at least the 3 sub-stages
    subs = sorted(d.name for d in stage.iterdir() if d.is_dir())
    assert "00-install-deps" in subs
    assert "01-install-app" in subs
    assert "02-configure" in subs


def test_install_deps_scripts():
    base = ROOT / "factorylm-image" / "pi-gen" / "stage-factorylm" / "00-install-deps"
    scripts = list(base.glob("*.sh"))
    assert len(scripts) >= 1


def test_install_app_script():
    path = ROOT / "factorylm-image" / "pi-gen" / "stage-factorylm" / "01-install-app" / "00-run.sh"
    assert path.exists()
    content = path.read_text()
    assert "ROOTFS_DIR" in content  # Must reference pi-gen rootfs variable


def test_configure_files():
    files_dir = ROOT / "factorylm-image" / "pi-gen" / "stage-factorylm" / "02-configure" / "files"
    assert files_dir.is_dir()
    assert (files_dir / "hostapd.conf").exists()
    assert (files_dir / "dnsmasq.conf").exists()


def test_configure_script():
    path = ROOT / "factorylm-image" / "pi-gen" / "stage-factorylm" / "02-configure" / "00-run.sh"
    assert path.exists()
    content = path.read_text()
    assert "hostapd" in content
    assert "dnsmasq" in content


def test_requirements_txt():
    req = ROOT / "requirements.txt"
    assert req.exists()
    content = req.read_text()
    assert "fastapi" in content.lower() or "uvicorn" in content.lower()


def test_first_boot_script():
    fb = ROOT / "pi-factory" / "first_boot.sh"
    assert fb.exists()
    content = fb.read_text()
    assert "pi-factory" in content.lower() or "GATEWAY_ID" in content


def test_systemd_services():
    svc_dir = ROOT / "pi-factory" / "systemd"
    assert svc_dir.is_dir()
    services = list(svc_dir.glob("*.service"))
    assert len(services) >= 2  # pi-factory.service + watchdog at minimum


def test_setup_script():
    setup = ROOT / "pi-factory" / "setup.sh"
    assert setup.exists()
    content = setup.read_text()
    assert "Pi Factory" in content


def test_releases_manifest():
    manifest = ROOT / "releases" / "latest.json"
    assert manifest.exists()


def test_build_image_workflow():
    wf = ROOT / ".github" / "workflows" / "build-image.yml"
    assert wf.exists()
    content = wf.read_text()
    assert "pi-gen" in content
    assert "stage-factorylm" in content
    assert "upload-artifact" in content
