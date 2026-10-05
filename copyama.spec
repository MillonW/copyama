# -*- mode: python ; coding: utf-8 -*-
"""
Copyama PyInstaller 打包配置。
用法：pyinstaller copyama.spec

输出：dist/Copyama/ （目录模式，双击 Copyama.exe 运行）
"""

import os
import sys

block_cipher = None

# 源码根目录（src/）
src_path = os.path.join(os.path.abspath(SPECPATH), 'src')

a = Analysis(
    ['src/copyama/__main__.py'],
    pathex=[src_path],
    binaries=[],
    datas=[
        ('assets/app.ico', 'assets'),
    ],
    hiddenimports=[
        # PySide6 插件（PyInstaller 通常能自动收集，但保险起见列一下核心的）
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除不需要的 Qt 模块，减小体积
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtQuick',
        'PySide6.QtQml',
        'PySide6.QtMultimedia',
        'PySide6.QtMultimediaWidgets',
        'PySide6.QtNetwork',
        'PySide6.QtSql',
        'PySide6.QtSvg',
        'PySide6.QtTest',
        'PySide6.QtWebChannel',
        'PySide6.QtPositioning',
        'PySide6.QtPrintSupport',
        'tkinter',
        'unittest',
        'pytest',
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
    exclude_binaries=True,          # 目录模式：dll 不打进 exe
    name='Copyama',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,                       # 启用 UPX 压缩（如果系统有 upx 的话，没有也不影响）
    console=False,                  # 无控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/app.ico',          # 应用图标
    version='version_info.txt' if os.path.exists('version_info.txt') else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Copyama',
)
