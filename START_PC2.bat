@echo off
REM ============================================================
REM PC-2 STARTUP SCRIPT (Remote Storage Node)
REM Run this on PC-2 after configuring .env
REM ============================================================

echo ==========================================
echo   PC-2: Distributed Storage Node
echo ==========================================
echo.

REM Step 1: Verify database connection to PC-1
echo [1/3] Checking database connection to PC-1...
python -c "from db import get_pool; get_pool(); print('Database OK')" 2>nul
if %errorlevel% neq 0 (
    echo ERROR: Cannot connect to PC-1's database.
    echo.
    echo Troubleshooting:
    echo   1. Is PC-1's MySQL running?
    echo   2. Is port 3306 forwarded on PC-1's router?
    echo   3. Is DB_HOST set to PC-1's IP in .env?
    echo   4. Test: telnet ^<PC-1-IP^> 3306
    echo.
    pause
    exit /b 1
)
echo Database connection successful.
echo.

REM Step 2: Verify node token matches PC-1
echo [2/3] Verifying shared token...
python -c "import os; token=os.getenv('NODE_SHARED_TOKEN',''); print('Token set:', bool(token))" 2>nul
echo Make sure NODE_SHARED_TOKEN in .env matches PC-1's token.
echo.

REM Step 3: Start node agent
echo [3/3] Starting PC-2 Node Agent on port 7002...
start "PC-2 Node Agent" /min python node_agent.py --name pc-2-node --storage-dir ./node_storage_pc2 --host 0.0.0.0 --port 7002

timeout /t 2 /nobreak > nul

echo.
echo ==========================================
echo   PC-2 Node Agent Started!
echo ==========================================
echo   Node Agent:  http://127.0.0.1:7002
echo   Storage Dir: ./node_storage_pc2
echo.
echo Keep this window open. The node agent runs in background.
echo To stop: close the "PC-2 Node Agent" terminal window.
echo.
echo IMPORTANT: Tell PC-1 admin to run seed.py again
echo so PC-2's URL gets registered in the database.
pause