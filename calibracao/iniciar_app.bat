@echo off
setlocal
cd /d "%~dp0"
title Calibracao - WP1

rem Toda a saida vai para ultimo_inicio.log alem da tela, para ficar diagnosticavel.
set "LOG=%~dp0ultimo_inicio.log"

rem Usa a .venv do treino_fiducial se existir; senao, o python do PATH.
set "PY=%~dp0..\treino_fiducial\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

> "%LOG%" 2>&1 (
  echo === iniciar_app.bat  %date% %time% ===
  echo Interpretador: %PY%
  "%PY%" -c "import sys, cv2, tkinter; print('python', sys.version); print('opencv', cv2.__version__); print('tk ok')"
)
type "%LOG%"

findstr /C:"tk ok" "%LOG%" >nul
if errorlevel 1 (
  echo.
  echo [erro] faltam dependencias. Detalhes acima e em ultimo_inicio.log
  echo Instale com:  "%PY%" -m pip install opencv-contrib-python pillow
  echo.
  pause
  exit /b 1
)

echo.
echo Abrindo o app... ^(feche esta janela so depois de fechar o app^)
>> "%LOG%" 2>&1 "%PY%" app.py
set "RC=%errorlevel%"
if not "%RC%"=="0" (
  echo.
  echo [o app terminou com erro %RC%] - traceback em ultimo_inicio.log:
  type "%LOG%"
  echo.
  pause
)
