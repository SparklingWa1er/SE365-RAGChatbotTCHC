# Chay frontend (Vite + React) tren cong 5173.
# Cach dung:  .\run-frontend.ps1   (mo terminal thu 2, CAN backend chay truoc)
Set-Location "$PSScriptRoot\frontend"
Write-Host "Frontend: http://127.0.0.1:5173  (proxy /api -> :8000)" -ForegroundColor Green
npm run dev
