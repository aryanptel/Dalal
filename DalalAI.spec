# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import copy_metadata
from PyInstaller.utils.hooks import collect_submodules

datas = [
    ('config.yaml', '.'),
    ('dalal_ai', 'dalal_ai'),
    ('utils', 'utils'),
]
datas += collect_data_files('streamlit')
datas += copy_metadata('streamlit')
datas += collect_data_files('playwright')

# Optionally add Playwright browsers if they should be bundled, but typically Playwright downloads them or they are external.
# We will just package the app, and Playwright will use the system's browser as configured.

hiddenimports = [
    'streamlit',
    'streamlit.runtime.scriptrunner.magic_funcs',
    'streamlit.runtime.scriptrunner.script_run_context',
    'yaml',
    'colorama',
    'dalal_ai.core',
    'dalal_ai.browser',
    'dalal_ai.ui',
    'utils',
    'utils.exceptions',
    'utils.logger',
    'utils.paths',
]
hiddenimports += collect_submodules('playwright')

a = Analysis(
    ['run_ui.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
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
    icon='icon.ico',
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
