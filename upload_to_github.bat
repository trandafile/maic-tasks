@echo off
setlocal enabledelayedexpansion
color 0A

echo ==========================================
echo    UPLOAD PROGETTO SU GITHUB (NO HIPA)
echo ==========================================
echo/

set "REPO_URL=https://github.com/trandafile/maic-tasks.git"
set "BRANCH=main"
set "PUSH_LOG=%TEMP%\maic_git_push_%RANDOM%.log"

REM Config Git identity (opzionale: commenta se gia configurata globalmente)
git config user.email "lu.boccia@gmail.com"
git config user.name "trandafile"
git config core.safecrlf false

REM Verifica Git disponibile
git --version >nul 2>&1
if errorlevel 1 (
    echo [ERRORE] Git non trovato nel PATH.
    goto ERRORE
)

REM Inizializza repository se non esiste
if not exist ".git" (
    echo [*] Inizializzazione repository...
    git init
    if errorlevel 1 goto ERRORE
)

REM Rimuove eventuale lock file rimasto da processi Git interrotti
if exist ".git\index.lock" (
    echo [*] Rilevato index.lock, rimozione in corso...
    del /f /q ".git\index.lock" >nul 2>&1
    if exist ".git\index.lock" (
        echo [ERRORE] Impossibile rimuovere .git\index.lock. Chiudi processi Git/editor aperti.
        goto ERRORE
    )
)

REM Crea o aggiorna remote origin
git remote get-url origin >nul 2>&1
if errorlevel 1 (
    echo [*] Aggiunta remote origin...
    git remote add origin %REPO_URL%
) else (
    echo [*] Aggiornamento remote origin...
    git remote set-url origin %REPO_URL%
)
if errorlevel 1 goto ERRORE

REM Assicura esclusione permanente di hipa
if not exist ".gitignore" (
    > .gitignore echo # Esclusioni progetto
)
findstr /R /X /C:"hipa/" .gitignore >nul 2>&1
if errorlevel 1 (
    echo hipa/>> .gitignore
)

REM Rimuove hipa dallo staging/tracking se presente
if exist "hipa" (
    echo [*] Rimozione cartella hipa dal tracking Git...
    git rm -r --cached --ignore-unmatch hipa >nul 2>&1
)

REM Staging
echo [*] Staging file...
git add -A
if errorlevel 1 (
    if exist ".git\index.lock" (
        echo [*] Git lock durante staging, nuovo tentativo...
        del /f /q ".git\index.lock" >nul 2>&1
        git add -A
    )
)
if errorlevel 1 goto ERRORE

REM Assicura branch main (DOPO lo staging per evitare "untracked would be overwritten")
set "CURR_BRANCH="
for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "CURR_BRANCH=%%B"
if /i not "%CURR_BRANCH%"=="%BRANCH%" (
    echo [*] Checkout branch %BRANCH%...
    git checkout -B %BRANCH%
    if errorlevel 1 goto ERRORE
) else (
    echo [*] Branch corrente: %BRANCH%
)

REM Commit message
set "COMMIT_MSG="
set /p COMMIT_MSG=Inserisci messaggio commit (INVIO per automatico): 
if "%COMMIT_MSG%"=="" set "COMMIT_MSG=Project upload excluding hipa - %date% %time%"

REM Commit (puo fallire se nulla da committare)
echo [*] Commit in corso...
git commit -m "%COMMIT_MSG%" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Nessuna modifica da committare, continuo con push.
)

REM Push: usa token se presente, altrimenti credential manager
echo [*] Push su GitHub...
if "%GITHUB_TOKEN%"=="" (
    git push -u origin %BRANCH% > "%PUSH_LOG%" 2>&1
) else (
    git push -u https://%GITHUB_TOKEN%@github.com/trandafile/maic-tasks.git %BRANCH% > "%PUSH_LOG%" 2>&1
)
type "%PUSH_LOG%"
if errorlevel 1 goto ERRORE

echo [*] Verifica sincronizzazione branch...
git status --short --branch
findstr /C:"ahead" "%PUSH_LOG%" >nul 2>&1

echo/
echo ==========================================
echo    SUCCESSO! UPLOAD COMPLETATO.
echo ==========================================
if exist "%PUSH_LOG%" del /f /q "%PUSH_LOG%" >nul 2>&1
color 07
pause
exit /b 0

:ERRORE
color 0C
if exist "%PUSH_LOG%" (
    echo/
    echo [*] Diagnostica push:
    findstr /C:"GH013" /C:"Push cannot contain secrets" "%PUSH_LOG%" >nul 2>&1
    if not errorlevel 1 (
        echo [ERRORE] GitHub ha bloccato il push per un secret presente nei commit locali.
        echo          Rimuovi il file sensibile dalla cronologia locale e riprova il push.
    )
    echo/
    echo [*] Stato branch:
    git status --short --branch
    del /f /q "%PUSH_LOG%" >nul 2>&1
)
echo/
echo ==========================================
echo    ERRORE DURANTE LA PROCEDURA
echo ==========================================
echo Controlla: remote GitHub, credenziali, connessione, permessi file.
color 07
pause
exit /b 1
