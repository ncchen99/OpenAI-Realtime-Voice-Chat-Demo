@echo off
echo 🎤 Starting OpenAI Realtime Voice Chat API...
echo.

REM 檢查是否存在 .env 檔案
if not exist .env (
    echo [WARNING] .env file not found!
    echo Please create .env file with your OpenAI API key:
    echo OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
    echo.
    pause
    exit /b 1
)

REM 檢查 Python 是否安裝
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH
    pause
    exit /b 1
)

REM 安裝依賴套件
echo Installing dependencies...
pip install -r requirements.txt

REM 啟動服務
echo.
echo 🚀 Starting FastAPI server with OpenAI Realtime API support...
echo Open your browser and go to: http://localhost:8000
echo.
echo 💡 Features:
echo - Real-time voice conversation with OpenAI
echo - Speech-to-text transcription  
echo - Text-to-speech responses (no audio overlap)
echo - Voice activity detection
echo - Beautiful chat interface with avatars
echo - Single button call control (green/red toggle)
echo.
python main.py 