@echo off
echo ===================================
echo Enhanced Ollama Book Generator Setup
echo ===================================

REM Check if Python is installed
python --version 2>NUL
if %ERRORLEVEL% NEQ 0 (
    echo Python is not installed or not in PATH. Please install Python 3.8+ and try again.
    pause
    exit /b 1
)

REM Check if Ollama is installed
echo Checking Ollama installation...
curl -s http://localhost:11434/api/tags >NUL 2>NUL
if %ERRORLEVEL% NEQ 0 (
    echo WARNING: Ollama doesn't appear to be running.
    echo Please make sure Ollama is installed and running before generating content.
    echo Visit https://ollama.com to download and install Ollama.
    echo.
    echo Press any key to continue setup anyway...
    pause >NUL
)

REM Create book_output directory if it doesn't exist
if not exist book_output\ (
    echo Creating book_output directory...
    mkdir book_output
)

REM Check if virtual environment exists
if not exist venv\ (
    echo Creating virtual environment...
    python -m venv venv
    if %ERRORLEVEL% NEQ 0 (
        echo Failed to create virtual environment.
        pause
        exit /b 1
    )
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat
if %ERRORLEVEL% NEQ 0 (
    echo Failed to activate virtual environment.
    pause
    exit /b 1
)

REM Install required packages
echo Installing required packages...
pip install gradio>=4.0.0 requests>=2.25.0 markdown>=3.3.0 pyyaml>=6.0

REM Install optional packages for export formats
echo Installing optional packages for export formats...
pip install reportlab ebooklib python-docx

REM Run the application
echo Starting the Enhanced Ollama Book Generator...
python simple_ollama_app.py
if %ERRORLEVEL% NEQ 0 (
    echo Application exited with an error. See above for details.
    pause
)

REM Deactivate virtual environment
call venv\Scripts\deactivate.bat

echo ===================================
echo Exiting Enhanced Ollama Book Generator
echo ===================================
pause