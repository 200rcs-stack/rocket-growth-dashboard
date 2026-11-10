$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    python -m venv .venv
    & $pythonPath -m pip install -r requirements.txt
}
try { $response = Invoke-WebRequest -Uri 'http://127.0.0.1:8501/_stcore/health' -TimeoutSec 2 } catch { $response = $null }
if (-not $response -or $response.StatusCode -ne 200) {
    Start-Process -FilePath $pythonPath -ArgumentList @('-m','streamlit','run','app.py','--server.address','127.0.0.1','--server.port','8501','--server.headless','true') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot 'data/server.log') -RedirectStandardError (Join-Path $PSScriptRoot 'data/server-error.log')
}
$collectorPython = Join-Path $PSScriptRoot '.venv/Scripts/pythonw.exe'
Start-Process -FilePath $collectorPython -ArgumentList @('-W','ignore','-m','src.web_sync') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
Start-Process 'http://127.0.0.1:8501'
