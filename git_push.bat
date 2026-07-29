@echo off
setlocal
cd /d "%~dp0"
title push para github.com/Rhayron/pose

echo === estado local ===
git log --oneline -3
echo.
git status --short
echo.

echo === buscando o remoto ===
git fetch origin 2>nul
git rev-parse --verify origin/main >nul 2>&1
if errorlevel 1 (
  echo Remoto vazio. Enviando direto.
) else (
  echo O remoto ja tem commits ^(o README criado pelo GitHub^).
  echo Como as duas historias nasceram separadas, vou reaplicar os commits
  echo locais por cima do remoto antes de enviar.
  git pull --rebase --allow-unrelated-histories origin main
  if errorlevel 1 (
    echo.
    echo [erro] o rebase parou. Provavel conflito no README.md.
    echo Resolva o arquivo, rode:  git add README.md ^&^& git rebase --continue
    echo e execute este .bat de novo.
    pause
    exit /b 1
  )
)

echo.
echo === enviando ===
git push -u origin main
if errorlevel 1 (
  echo.
  echo [erro] o push falhou. Causas comuns:
  echo   - autenticacao: o Windows deve abrir a janela do GitHub na primeira vez
  echo   - repositorio errado: confira com  git remote -v
  pause
  exit /b 1
)

echo.
echo [ok] enviado. Confira em https://github.com/Rhayron/pose
pause
