# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=['.'],
    binaries=[],
    datas=[('config.json', '.')],
    hiddenimports=[
        'tkinter', 'tkinter.scrolledtext', 'tkinter.filedialog', 'tkinter.messagebox',
        'PIL', 'PIL.Image', 'PIL.ImageDraw',
        'mss', 'mss.windows', 'numpy',
        'obsws_python', 'websocket', 'websocket.client',
        'pynput', 'pynput.keyboard', 'pynput.mouse',
        'pystray', 'pystray._win32', 'pywintypes', 'win32api', 'win32con', 'win32gui',
        'dxcam',
        'guard', 'guard.capture', 'guard.detector', 'guard.engine', 'guard.gui',
        'guard.hotkeys', 'guard.output', 'guard.state', 'guard.stats',
        'tools', 'tools.region_picker',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'transformers', 'tensorflow', 'matplotlib', 'pandas'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='StreamGuard',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
