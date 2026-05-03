# -*- mode: python ; coding: utf-8 -*-
# Windows GUI build (CPU only). Run on Windows:
#   pip install -e . pyside6 onnxruntime pillow pyinstaller
#   pyinstaller deface_gui.spec --clean

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

hiddenimports = []
hiddenimports += collect_submodules('imageio')
hiddenimports += collect_submodules('imageio_ffmpeg')
hiddenimports += collect_submodules('onnxruntime')

datas = [
    ('deface/centerface.onnx', 'deface'),
    ('deface/face_detection_yunet_2023mar.onnx', 'deface'),
]
datas += collect_data_files('imageio_ffmpeg')   # bundle ffmpeg.exe
datas += collect_data_files('onnxruntime')

a = Analysis(
    ['deface/docx_gui.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'onnxruntime-gpu',
        'onnxruntime-directml',
        'torch', 'tensorflow', 'matplotlib',
    ],
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
    name='deface_gui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,            # UPX often breaks Qt/onnxruntime DLLs
    console=False,        # windowed app, no console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='deface/app.ico',  # 需要图标的话放一个 .ico 进去再开这行
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='deface_gui',
)
