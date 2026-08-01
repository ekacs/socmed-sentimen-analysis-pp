# -*- mode: python ; coding: utf-8 -*-

import sys
import os
from PyInstaller.utils.hooks import copy_metadata, collect_data_files

block_cipher = None

datas = [
    ('target_config.json', '.'),
    ('models', 'models'),
]

if os.path.exists('sentimen_kebijakan.db'):
    datas.append(('sentimen_kebijakan.db', '.'))

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
    ['desktop_launcher.py'],
    pathex=['.', '.'],
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
    console=True,
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
