# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Dalal AI (one-folder, windowed).

Two things about this build are easy to get wrong and were both wrong before:

1.  `dalal_ai/` and `utils/` must be shipped BOTH as importable modules and as
    files on disk.  Streamlit is started by *path* (`streamlit run <app.py>`),
    so `dalal_ai/ui/app.py` has to exist as a real file — but shipping the tree
    as `datas` alone means PyInstaller never parses those files, so every
    third-party package imported only from inside them is left out of the
    build.  That is exactly how `pyperclip` went missing: it is imported inside
    `browser_manager._paste_text`, nowhere else, and it was absent from dist/
    entirely.  Declaring the packages as hidden imports makes PyInstaller walk
    them and pick up their dependencies.

2.  `response_script.js` is read at import time with `Path(__file__).with_name`,
    so it must land next to the on-disk copy of browser_manager.py.
"""

import os
import sys

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_submodules,
    copy_metadata,
)

# The app packages live next to this spec; make them importable during analysis.
if SPECPATH not in sys.path:                                   # noqa: F821
    sys.path.insert(0, SPECPATH)                               # noqa: F821

datas = [
    ('config.yaml', '.'),
    # On-disk copies: Streamlit runs app.py by path, and browser_manager reads
    # response_script.js relative to its own file.
    ('dalal_ai', 'dalal_ai'),
    ('utils', 'utils'),
]
datas += collect_data_files('streamlit')
datas += copy_metadata('streamlit')
# This also collects playwright/driver (node.exe + driver/package).  Without
# the driver, sync_playwright().start() fails on any machine that has no
# separate Playwright install — verified present by build.py afterwards.
datas += collect_data_files('playwright')

hiddenimports = [
    'streamlit',
    'streamlit.runtime.scriptrunner.magic_funcs',
    'streamlit.runtime.scriptrunner.script_run_context',
    'streamlit.web.cli',
    'yaml',
    'colorama',
    # Imported lazily inside BrowserManager._paste_text — invisible to the
    # analyser unless the app packages below are parsed, and required for
    # clipboard paste of long prompts.
    'pyperclip',
    'tkinter',
]

# Parse the application's own code so its imports are followed.  Explicit list
# first so the build cannot silently lose a module if walking the package fails.
hiddenimports += [
    'dalal_ai',
    'dalal_ai.browser',
    'dalal_ai.browser.browser_manager',
    'dalal_ai.core',
    'dalal_ai.core.context_compressor',
    'dalal_ai.core.context_manager',
    'dalal_ai.core.flagged_context_manager',
    'dalal_ai.core.orchestrator',
    'dalal_ai.core.swarm_orchestrator',
    'dalal_ai.ui',
    'dalal_ai.ui.app',
    'utils',
    'utils.exceptions',
    'utils.logger',
    'utils.paths',
]
for _pkg in ('dalal_ai', 'utils', 'playwright'):
    try:
        hiddenimports += collect_submodules(_pkg)
    except Exception as _exc:                                   # pragma: no cover
        print(f"[spec] WARNING: could not walk {_pkg}: {_exc}")

hiddenimports = sorted(set(hiddenimports))

a = Analysis(
    ['run_ui.py'],
    pathex=[SPECPATH],                                          # noqa: F821
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Heavy scientific stack the app never touches.  'unittest' is
        # deliberately NOT excluded: several third-party packages do
        # `import unittest.mock` at import time.
        'numpy', 'scipy', 'pandas', 'matplotlib', 'IPython',
        'pytest', 'PyQt5', 'pyarrow',
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
    # UPX corrupts the Playwright Node driver and some Windows runtime DLLs.
    upx_exclude=[
        'node.exe',
        'vcruntime140.dll',
        'vcruntime140_1.dll',
        'msvcp140.dll',
        'python3.dll',
        'python313.dll',
    ],
    name='DalalAI',
)
