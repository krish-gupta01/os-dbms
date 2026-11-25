@echo off
REM ============================================================
REM PC-1 STARTUP SCRIPT (Main Server)
REM Run this on PC-1 after configuring .env
REM ============================================================

echo ==========================================
echo   PC-1: Distributed File Management System
echo ==========================================
echo.

REM Step 1: Verify database exists
echo [1/4] Checking database connection...
python -c "from db import get_pool; get_pool(); print('Database OK')" 2>nul
if %errorlevel% neq 0 (
    echo ERROR: Cannot connect to database.
    echo Make sure MySQL is running and .env is configured correctly.
    echo Run: python -c "from db import get_pool; get_pool()" to test.
    pause
    exit /b 1
)
echo Database connection successful.
echo.

REM Step 2: Initialize schema if needed
echo [2/4] Ensuring database schema exists...
python -c "from db import fetch_one; fetch_one('SELECT 1 FROM users LIMIT 1')" 2>nul
if %errorlevel% neq 0 (
    echo Schema not found. Running schema.sql...
    echo Run this manually in MySQL Workbench or CLI:
    echo   mysql -u root -p ^< schema.sql
    echo.
    pause
)

REM Step 3: Seed users and register nodes
echo [3/4] Seeding users and registering storage nodes...
python seed.py
if %errorlevel% neq 0 (
    echo ERROR: Seed failed.
    pause
    exit /b 1
)
echo.

REM Step 4: Start node agent and main app
echo [4/4] Starting services...
echo Starting PC-1 Node Agent on port 7001...
start "PC-1 Node Agent" /min python node_agent.py --name pc-1-node --storage-dir ./node_storage_pc1 --host 0.0.0.0 --port 7001

timeout /t 2 /nobreak > nul

echo Starting Main Application on port 5000...
start "PC-1 Main App" /min python app.py

timeout /t 2 /nobreak > nul

echo.
echo ==========================================
echo   PC-1 Services Started!
echo ==========================================
echo   Node Agent:  http://127.0.0.1:7001
echo   Main App:    http://127.0.0.1:5000
echo   Admin login: http://127.0.0.1:5000/admin
echo                 (admin/admin123)
echo.
echo Keep this window open. Services run in background.
echo To stop: close the "PC-1 Node Agent" and "PC-1 Main App" terminal windows.
pause