@echo off
setlocal EnableDelayedExpansion
REM ---------------------------------------------------------------------------
REM Importa um CSV (do seu PC) para o banco do app fcsd como uma tabela,
REM associando a uma Tabela Diamante (Diamond Layer) e/ou DataMart.
REM Copia o CSV para o container, roda o importador Python e limpa o temporario.
REM
REM Uso (Prompt de Comando):
REM   scripts\import_csv.cmd <csv> [--diamond-layer NOME] [--datamart NOME] ^
REM       [--table NOME] [--mode replace^|append] [--sep auto] [--encoding utf-8] [--owner-login LOGIN]
REM
REM Exemplos:
REM   scripts\import_csv.cmd pagamentos.csv --diamond-layer Financeiro
REM   scripts\import_csv.cmd dados.csv --datamart default --table fato_pagamentos --mode replace
REM ---------------------------------------------------------------------------

if "%CONTAINER%"=="" set "CONTAINER=fcsd-app"

set "CSV=%~1"
if "%CSV%"=="" goto :usage
if not exist "%CSV%" (
  echo CSV nao encontrado: %CSV%
  exit /b 1
)

for %%F in ("%CSV%") do set "BN=%%~nxF"
set "TMPDIR=/tmp/fcsd_imp_%RANDOM%%RANDOM%"
set "TMP=%TMPDIR%/%BN%"

REM Junta os argumentos a partir do 2o (preserva ordem) em PYARGS
set "PYARGS="
:loop
shift
if "%~1"=="" goto :run
set "PYARGS=!PYARGS! %~1"
goto :loop

:run
docker exec %CONTAINER% mkdir -p %TMPDIR% >nul 2>&1
docker cp "%CSV%" "%CONTAINER%:%TMP%"
if errorlevel 1 (
  echo Falha no docker cp
  exit /b 1
)
docker exec %CONTAINER% python /app/scripts/import_csv.py %TMP%!PYARGS!
set "RC=!errorlevel!"
docker exec %CONTAINER% rm -rf %TMPDIR% >nul 2>&1
exit /b !RC!

:usage
echo Uso: scripts\import_csv.cmd ^<csv^> [--diamond-layer NOME] [--datamart NOME] [--table NOME] [--mode replace^|append] [--sep auto] [--encoding utf-8] [--owner-login LOGIN]
exit /b 1
