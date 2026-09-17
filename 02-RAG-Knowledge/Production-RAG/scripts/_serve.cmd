@echo off
set PYTHONPATH=D:\RMFolder\RMPythonProjects\AI02\05_RAG_Production\.venv\Lib\site-packages
"C:\Users\svraj\AppData\Local\Programs\Python\Python311\python.exe" -m uvicorn ui.server:app --port 8000
