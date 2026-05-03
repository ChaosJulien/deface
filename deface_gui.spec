# -*- mode: python ; coding: utf-8 -*-
# Windows GUI build (CPU only). Run on Windows:
#   pip install -e . pyside6 onnxruntime pillow pytesseract pyinstaller
#   # 准备 vendor/tesseract/(tesseract.exe + *.dll + tessdata/*.traineddata)
#   pyinstaller deface_gui.spec --clean

from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, copy_metadata

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

# 一些包启动会调 importlib.metadata.version(self),PyInstaller 默认不带 metadata。
# 不带的话报 PackageNotFoundError。
for pkg in ('imageio', 'imageio_ffmpeg', 'numpy', 'pillow', 'onnxruntime',
            'opencv-python', 'pyside6', 'pytesseract', 'tqdm', 'scikit-image'):
    try:
        datas += copy_metadata(pkg)
    except Exception as e:
        print(f"[spec] copy_metadata({pkg!r}) skipped: {e}")

# 可选:打包 vendor/tesseract/ 进 exe(关键词 OCR 在 Windows 上能用)
binaries = []
vendor_tess = Path('vendor/tesseract')
if vendor_tess.is_dir():
    for p in vendor_tess.glob('*.exe'):
        binaries.append((str(p), 'tesseract'))
    for p in vendor_tess.glob('*.dll'):
        binaries.append((str(p), 'tesseract'))
    tessdata = vendor_tess / 'tessdata'
    if tessdata.is_dir():
        for p in tessdata.glob('*.traineddata'):
            datas.append((str(p), 'tesseract/tessdata'))
    print(f"[spec] vendored tesseract: {len(binaries)} bin, {sum(1 for _ in tessdata.glob('*.traineddata')) if tessdata.is_dir() else 0} traineddata")
else:
    print("[spec] vendor/tesseract/ not found — built exe will lack OCR. Install tesseract on target machine or rerun build with vendor populated.")

a = Analysis(
    ['deface/docx_gui.py'],
    pathex=[],
    binaries=binaries,
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
