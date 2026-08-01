# -*- mode: python ; coding: utf-8 -*-

import sys
import os
from PyInstaller.utils.hooks import copy_metadata, collect_data_files

block_cipher = None

datas = [
    (r'D:/Documents/#ptincap/socmed-sentimen-analysis-pp/target_config.json', '.'),
    (r'D:/Documents/#ptincap/socmed-sentimen-analysis-pp/models', 'models'),
]

if os.path.exists(r'D:/Documents/#ptincap/socmed-sentimen-analysis-pp/sentimen_kebijakan.db'):
    datas.append((r'D:/Documents/#ptincap/socmed-sentimen-analysis-pp/sentimen_kebijakan.db', '.'))

datas += copy_metadata('streamlit')
datas += collect_data_files('streamlit')
datas += collect_data_files('plotly')

hidden_imports = [
    'streamlit',
    'plotly',
    'plotly.express',
    'pandas',
    'sklearn',
    'joblib',
    'apify_client',
    'google.genai',
    'psycopg2',
    'sqlalchemy',
    'webview',
    'license_manager',
    'db_manager',
    'session_credentials',
    'nlg_generator',
    'config_parser'
]

a = Analysis(
    [r'D:/Documents/#ptincap/socmed-sentimen-analysis-pp/desktop_launcher.py'],
    pathex=[r'D:/Documents/#ptincap/socmed-sentimen-analysis-pp'],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='SocMedSentimentAnalysis',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # Set True untuk memudahkan debugging/log terminal saat testing
    icon=None
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SocMedSentimentAnalysis',
)
