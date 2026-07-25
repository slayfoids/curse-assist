# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec — one self-contained ``CursorAssist.exe``.

Build it with::

    py tools/build_exe.py

or directly::

    py -m PyInstaller CursorAssist.spec --noconfirm --clean

The result is ``dist/CursorAssist.exe``: a single file carrying its own Python,
OpenCV, numpy and the web/overlay UI, so it runs on a Windows box with nothing
installed. Nothing here is obfuscated — the binary is plainly named and its
contents are inspectable with any standard PyInstaller archive viewer.
"""

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[],
    # `mouse`, `keyboard`, `winsound` and the legacy Tk panel are all imported
    # lazily *inside functions*. Name them explicitly so a static-analysis miss
    # can never ship an exe whose hotkeys silently do nothing.
    hiddenimports=[
        'mouse',
        'keyboard',
        'winsound',
        'cursor_assist.gui',
        'cursor_assist.overlay',
        'cursor_assist.webserver',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Trim the Qt/plotting/science stacks that opencv-python can otherwise drag
    # in — they're unused here and cost hundreds of MB in the bundle.
    excludes=[
        'matplotlib', 'scipy', 'pandas', 'IPython', 'pytest',
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='CursorAssist',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX off on purpose: it buys little against an already-compressed archive
    # and packed binaries trip antivirus heuristics for no good reason.
    upx=False,
    runtime_tmpdir=None,
    # Console kept on: this is what someone screenshots when it fails to start.
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
