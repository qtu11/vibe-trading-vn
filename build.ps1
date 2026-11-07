<#
.SYNOPSIS
    Script tự động hóa Build, Đóng gói và Khởi chạy Vibe-Trading Desktop trên Windows.
.DESCRIPTION
    Tự động giải phóng tiến trình cũ, thiết lập biến môi trường, biên dịch frontend,
    build Electron process, đóng gói bộ cài đặt .exe (NSIS Installer) và tạo shortcut Desktop.
.PARAMETER Target
    - All        : Build toàn diện (Frontend + Electron + Installer .exe + Shortcut) [Mặc định]
    - Dev        : Khởi chạy chế độ Development kết hợp Hot-Reload
    - Run        : Khởi chạy ứng dụng Desktop đã build
    - Backend    : Khởi động riêng API Server (Python FastAPI)
    - Frontend   : Chỉ biên dịch Frontend React
    - Installer  : Chỉ đóng gói lại file cài đặt NSIS .exe
#>

[CmdletBinding()]
param(
    [ValidateSet("All", "Dev", "Run", "Backend", "Frontend", "Installer")]
    [string]$Target = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = $PSScriptRoot
if (-not $RepoRoot) { $RepoRoot = (Get-Location).Path }

$FrontendDir = Join-Path $RepoRoot "frontend"
$ElectronDir = Join-Path $RepoRoot "desktop\electron"
$VenvPython  = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$VibeExe     = Join-Path $RepoRoot ".venv\Scripts\vibe-trading.exe"
$ReleaseDir  = Join-Path $ElectronDir "release"
$InstallerExe= Join-Path $ReleaseDir "Vibe-Trading-Desktop-Unofficial-0.3.0-x64.exe"
$UnpackedExe = Join-Path $ReleaseDir "win-unpacked\Vibe-Trading Desktop (Unofficial Community Build).exe"
$DesktopDir  = [Environment]::GetFolderPath("Desktop")
$ShortcutLnk = Join-Path $DesktopDir "Vibe-Trading.lnk"

function Write-Step {
    param([string]$Message)
    Write-Host "`n>>> $Message" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Write-WarnMsg {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Stop-RunningApp {
    $processes = Get-Process | Where-Object { 
        $_.ProcessName -like "*Vibe-Trading*" -or 
        $_.ProcessName -like "*makensis*" 
    }
    if ($processes) {
        Write-Step "Dang giai phong cac tien trinh Vibe-Trading cu..."
        $processes | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
        Write-Success "Da dong tien trinh cu thanh cong."
    }
}

function Set-EnvironmentBridge {
    Write-Step "Cau hinh bien moi truong backend VIBE_TRADING_EXECUTABLE..."
    if (Test-Path -LiteralPath $VibeExe) {
        [Environment]::SetEnvironmentVariable("VIBE_TRADING_EXECUTABLE", $VibeExe, "User")
        $env:VIBE_TRADING_EXECUTABLE = $VibeExe
        Write-Success "Backend target: $VibeExe"
    } else {
        Write-WarnMsg "Khong tim thay $VibeExe. Vui long cai dat moi truong Python truoc."
    }
}

function Build-FrontendApp {
    Write-Step "Bien dich Frontend Production Bundle (Vite + React)..."
    Push-Location $FrontendDir
    try {
        & npm run build
        if ($LASTEXITCODE -ne 0) { throw "Build frontend that bai (exit code $LASTEXITCODE)." }
        Write-Success "Frontend build hoan tat -> frontend/dist"
    } finally {
        Pop-Location
    }
}

function Build-ElectronDist {
    Write-Step "Bien dich Electron Process va sao chep asset..."
    Push-Location $ElectronDir
    try {
        & npm run build
        if ($LASTEXITCODE -ne 0) { throw "Build electron dist that bai." }
        Write-Success "Electron build hoan tat -> desktop/electron/dist"
    } finally {
        Pop-Location
    }
}

function Build-InstallerExe {
    Write-Step "Dong goi bo cai dat Windows (NSIS Installer .exe)..."
    Push-Location $ElectronDir
    try {
        & npx electron-builder --publish never --win nsis
        if ($LASTEXITCODE -ne 0) { throw "Dong goi installer that bai." }
        Write-Success "Installer .exe da tao thanh cong!"
    } finally {
        Pop-Location
    }
}

function Create-DesktopShortcut {
    Write-Step "Cap nhat Shortcut ngoai Desktop..."
    try {
        $iconSource = Join-Path $ElectronDir "dist\icon.ico"
        if (-not (Test-Path -LiteralPath $iconSource)) {
            $iconSource = Join-Path $RepoRoot "assets\icon.png"
        }
        $targetToLaunch = if (Test-Path -LiteralPath $UnpackedExe) { $UnpackedExe } else { $InstallerExe }

        $wsh = New-Object -ComObject WScript.Shell
        $shortcut = $wsh.CreateShortcut($ShortcutLnk)
        $shortcut.TargetPath = $targetToLaunch
        $shortcut.WorkingDirectory = Split-Path -Parent $targetToLaunch
        $shortcut.IconLocation = "$iconSource, 0"
        $shortcut.Description = "Vibe-Trading Desktop - Your Personal Trading Agent"
        $shortcut.Save()
        Write-Success "Shortcut Desktop san sang: $ShortcutLnk"
    } catch {
        Write-WarnMsg "Khong the tao shortcut: $_"
    }
}

function Show-Menu {
    Clear-Host
    Write-Host "==========================================================" -ForegroundColor Cyan
    Write-Host "      VIBE-TRADING DESKTOP - TRINH BUILD & DIEU KHIEN     " -ForegroundColor Yellow
    Write-Host "==========================================================" -ForegroundColor Cyan
    Write-Host "  1. Build toan bo (Frontend + Electron + Installer .exe)" -ForegroundColor White
    Write-Host "  2. Chay ung dung Desktop da build" -ForegroundColor White
    Write-Host "  3. Chay che do Development (Hot-Reload)" -ForegroundColor White
    Write-Host "  4. Chi bien dich Frontend (npm run build)" -ForegroundColor White
    Write-Host "  5. Chi dong goi file Installer .exe" -ForegroundColor White
    Write-Host "  6. Khoi dong Backend API server" -ForegroundColor White
    Write-Host "  0. Thoat" -ForegroundColor Gray
    Write-Host "==========================================================" -ForegroundColor Cyan
    $choice = Read-Host "Nhap lua chon cua chu tich [1-6, 0]"
    switch ($choice) {
        "1" { return "All" }
        "2" { return "Run" }
        "3" { return "Dev" }
        "4" { return "Frontend" }
        "5" { return "Installer" }
        "6" { return "Backend" }
        default { return "Exit" }
    }
}

# --- DIEU HUONG THUC THI ---
if (-not $Target) {
    $Target = Show-Menu
}

if ($Target -eq "Exit") {
    Write-Host "Ket thuc." -ForegroundColor Gray
    exit 0
}

switch ($Target) {
    "All" {
        Stop-RunningApp
        Set-EnvironmentBridge
        Build-FrontendApp
        Build-ElectronDist
        Build-InstallerExe
        Create-DesktopShortcut
        Write-Host "`n==========================================================" -ForegroundColor Green
        Write-Host " BUILD THANH CONG TOAN DIEN HE THONG VIBE-TRADING DESKTOP " -ForegroundColor Yellow
        Write-Host "==========================================================" -ForegroundColor Green
        Write-Host " File cai dat: $InstallerExe" -ForegroundColor White
        Write-Host " Ban unpacked: $UnpackedExe" -ForegroundColor White
        Write-Host " Shortcut:     $ShortcutLnk" -ForegroundColor White
        Write-Host "==========================================================`n" -ForegroundColor Green
    }
    "Frontend" {
        Build-FrontendApp
    }
    "Installer" {
        Stop-RunningApp
        Build-InstallerExe
        Create-DesktopShortcut
    }
    "Dev" {
        Stop-RunningApp
        Set-EnvironmentBridge
        Write-Step "Khoi dong Desktop o che do Development..."
        Push-Location $ElectronDir
        try {
            & npm start
        } finally {
            Pop-Location
        }
    }
    "Run" {
        if (Test-Path -LiteralPath $UnpackedExe) {
            Write-Step "Khoi chay ban build Desktop..."
            Start-Process -FilePath $UnpackedExe
        } elseif (Test-Path -LiteralPath $InstallerExe) {
            Write-Step "Khoi chay bo cai dat..."
            Start-Process -FilePath $InstallerExe
        } else {
            Write-WarnMsg "Chua co ban build. Vui long chon tuy chon 1 de build truoc."
        }
    }
    "Backend" {
        Write-Step "Khoi dong Backend API server..."
        if (Test-Path -LiteralPath $VibeExe) {
            & $VibeExe serve
        } else {
            & $VenvPython -c "import api_server; raise SystemExit(api_server.serve_main())"
        }
    }
}

