# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for FactoryLM Demo — Cosmos Cookoff 2026."""

a = Analysis(
    ['demo/__main__.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('demo/prompts', 'demo/prompts'),
        ('demo/clips', 'demo/clips'),
        ('config', 'config'),
        ('.env.demo', '.'),
    ],
    hiddenimports=[
        'demo.diagnosis_engine',
        'demo.capture_fio',
        'demo.test_session',
        'demo._paths',
        'cosmos.watcher',
        'cosmos.agent',
        'cosmos.client',
        'cosmos.models',
        'cosmos.reasoner',
        'cosmos.belt_tachometer',
        'video.cosmos_analyzer',
        'video.ingester',
        'video.highlight_selector',
        'video.short_builder',
        'diagnosis.conveyor_faults',
        'diagnosis.prompts',
        'services.matrix.app',
        'sim.factoryio_bridge',
        'pymodbus.client',
        'yaml',
        'mss',
        'mss.tools',
        'dotenv',
        'uvicorn',
        'fastapi',
        'httpx',
        'aiosqlite',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FactoryLM-Demo',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FactoryLM-Demo',
)
