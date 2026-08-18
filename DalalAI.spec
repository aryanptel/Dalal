# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import copy_metadata

datas = [
    ('config.yaml', '.'),
    ('dalal_ai', 'dalal_ai'),
]
datas += collect_data_files('streamlit')
datas += copy_metadata('streamlit')

# Optionally add Playwright browsers if they should be bundled, but typically Playwright downloads them or they are external.
# We will just package the app, and Playwright will use the system's browser as configured.

a = Analysis(
    ['run_ui.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'streamlit',
        'streamlit.runtime.scriptrunner.magic_funcs',
        'streamlit.runtime.scriptrunner.script_run_context',
        'playwright',
        'yaml',
        'colorama',
        'dalal_ai.core',
        'dalal_ai.browser',
        'dalal_ai.ui'
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'numpy', 'scipy', 'pandas', 'matplotlib', 'IPython', 
        'pytest', 'unittest', 'PyQt5', 'pyarrow'
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DalalAI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='DalalAI',
)
