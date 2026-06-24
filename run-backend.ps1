# Chay backend FastAPI (DVC RAG API) tren cong 8000.
# Cach dung:  .\run-backend.ps1
# Yeu cau: da chay setup (.venv + index tai C:\ktem_data).
$env:PYTHONUTF8 = "1"            # tranh loi encoding tieng Viet tren console Windows
$env:PYTHONIOENCODING = "utf-8"
Set-Location $PSScriptRoot
Write-Host "Backend: http://127.0.0.1:8000  (Swagger: /docs)" -ForegroundColor Cyan
& "$PSScriptRoot\.venv\Scripts\python.exe" -m uvicorn app.api.main:app --port 8000
