@echo off
setlocal enabledelayedexpansion
color 0A

echo ==========================================
echo    UPLOAD PROGETTO SU GITHUB
echo ==========================================
echo/

REM ===== CONFIGURAZIONE PROGETTO =====
REM Inserisci qui l'URL del repository GitHub associato a questo progetto.
REM Esempio: set "REPO_URL=https://github.com/trandafile/NOME-REPO.git"
set "REPO_URL=https://github.com/trandafile/maic-tasks.git"
set "BRANCH=main"
REM ===================================

set "PUSH_LOG=%TEMP%\maic_git_push_%RANDOM%.log"
set "VERSION_FILE=.upload_version.txt"

REM Nome progetto GitHub mancante: non fare nulla e avvisa l'utente
if "%REPO_URL%"=="" (
    color 0C
    echo [ERRORE] Nome progetto GitHub non configurato per questo progetto.
    echo/
    echo          Apri questo file ^(upload.bat^) con un editor di testo e compila la riga:
    echo              set "REPO_URL=https://github.com/trandafile/NOME-REPO.git"
    echo          con il nome del repository GitHub associato a questo progetto.
    echo/
    echo          Finche' REPO_URL e' vuoto, l'upload non viene eseguito.
    color 07
    pause
    exit /b 1
)

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
set "LAST_VERSION="
if exist "%VERSION_FILE%" (
    for /f "usebackq delims=" %%V in ("%VERSION_FILE%") do set "LAST_VERSION=%%V"
)

set "SUGGESTED_VERSION=alfa 1.0.0"
if not "%LAST_VERSION%"=="" (
    set "LAST_VERSION_ENV=%LAST_VERSION%"
    for /f "usebackq delims=" %%V in (`powershell -NoProfile -Command "$v=$env:LAST_VERSION_ENV; if($v -match '^(.*?)(\d+(?:\.\d+)*)$'){ $p=$matches[1]; $n=$matches[2].Split('.'); $n[$n.Length-1]=[string]([int]$n[$n.Length-1]+1); Write-Output ($p + ($n -join '.')) } else { Write-Output $v }"`) do set "SUGGESTED_VERSION=%%V"
)

set "VERSION_NAME="
if not "%LAST_VERSION%"=="" (
    echo [*] Ultima versione salvata: %LAST_VERSION%
)
set /p VERSION_NAME=Inserisci nome versione (INVIO per automatico: %SUGGESTED_VERSION%):
if "%VERSION_NAME%"=="" set "VERSION_NAME=%SUGGESTED_VERSION%"
> "%VERSION_FILE%" echo %VERSION_NAME%
echo [*] Versione salvata in %VERSION_FILE%: %VERSION_NAME%
echo [*] Versione in upload: %VERSION_NAME%

set "COMMIT_MSG="
set /p COMMIT_MSG=Inserisci messaggio commit (INVIO per automatico):
if "%COMMIT_MSG%"=="" set "COMMIT_MSG=[%VERSION_NAME%] Project upload - %date% %time%"

REM Commit (puo fallire se nulla da committare)
echo [*] Commit in corso...
git commit -m "%COMMIT_MSG%" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Nessuna modifica da committare, continuo con push.
)

REM Push: usa token se presente, altrimenti credential manager
echo [*] Push su GitHub...
set "AUTH_URL=%REPO_URL%"
if not "%GITHUB_TOKEN%"=="" set "AUTH_URL=https://%GITHUB_TOKEN%@!REPO_URL:https://=!"
if "%GITHUB_TOKEN%"=="" (
    git push -u origin %BRANCH% > "%PUSH_LOG%" 2>&1
) else (
    git push -u %AUTH_URL% %BRANCH% > "%PUSH_LOG%" 2>&1
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