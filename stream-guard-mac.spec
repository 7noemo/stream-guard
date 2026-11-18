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
        'mss', 'mss.base', 'numpy',
        'obsws_python', 'websocket', 'websocket.client',
        'pynput', 'pynput.keyboard', 'pynput.mouse', 'pynput._util.darwin',
        'Quartz', 'objc',
        'guard', 'guard.capture', 'guard.detector', 'guard.engine', 'guard.gui',
        'guard.hotkeys', 'guard.output', 'guard.state', 'guard.stats',
        'tools', 'tools.region_picker',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'transformers', 'tensorflow', 'matplotlib', 'pandas', 'pystray'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='StreamGuard',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='StreamGuard',
)

app = BUNDLE(
    coll,
    name='Stream Guard.app',
    icon=None,
    bundle_identifier='com.streamguard.app',
    info_plist={
        'NSHighResolutionCapable': True,
        'CFBundleDisplayName': 'Stream Guard',
        'CFBundleName': 'Stream Guard',
    },
)
