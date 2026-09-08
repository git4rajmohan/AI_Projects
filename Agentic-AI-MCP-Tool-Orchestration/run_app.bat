@echo off
cd /d %~dp0
python -m streamlit run src\mcp_app\ui\app.py --server.port 8502
