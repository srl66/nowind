# 一条命令启动两件事：Vite 前端 + 本地屏幕感知中间件（127.0.0.1:8737）
# 每个进程各占一个窗口，关掉对应窗口即停止；互不影响。
# 可用环境变量覆盖：AI_SCREEN_MIDDLEWARE=中间件目录，AI_SCREEN_DURATION=中间件运行秒数。

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root

function Resolve-Npm {
    if (Get-Command npm -ErrorAction SilentlyContinue) { return $true }
    # Trae 终端里 Node 常常不在 PATH：去 winget 安装目录兜底找一次
    $node = Get-ChildItem -Path "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" `
        -Filter node.exe -Recurse -Depth 4 -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($node) {
        $env:PATH = "$($node.DirectoryName);$env:PATH"
        return $true
    }
    return $false
}

if (-not (Resolve-Npm)) {
    Write-Host "[错误] 找不到 npm。请先安装 Node.js，或把 node 加入 PATH 后重试。" -ForegroundColor Red
    exit 1
}

$bundledMw = Join-Path $root "middleware"
$mwDir = if ($env:AI_SCREEN_MIDDLEWARE) {
    $env:AI_SCREEN_MIDDLEWARE
} elseif (Test-Path -LiteralPath (Join-Path $bundledMw "src\daemon.py")) {
    $bundledMw
} else {
    Join-Path $env:USERPROFILE "Desktop\ai-screen-perception-mvp"
}
$mwDaemon = Join-Path $mwDir "src\daemon.py"
$mwDuration = if ($env:AI_SCREEN_DURATION) { $env:AI_SCREEN_DURATION } else { "86400" }

# 中间件已在跑就复用，避免 8737 端口冲突
$mwOnline = $false
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8737/state" -UseBasicParsing -TimeoutSec 2
    $mwOnline = ($r.StatusCode -eq 200)
} catch {
    $mwOnline = $false
}

if ($mwOnline) {
    Write-Host "[中间件] 127.0.0.1:8737 已在线，复用现有实例。" -ForegroundColor DarkGray
} elseif (Test-Path -LiteralPath $mwDaemon) {
    Write-Host "[中间件] 启动 $mwDaemon" -ForegroundColor DarkGray
    Start-Process -FilePath "powershell.exe" -WorkingDirectory $mwDir -ArgumentList @(
        "-NoExit", "-Command", "python src\daemon.py --duration $mwDuration --quiet"
    )
} else {
    Write-Host "[中间件] 没找到 $mwDaemon，只启动前端。可用 AI_SCREEN_MIDDLEWARE 指定中间件目录。" -ForegroundColor Yellow
}

Write-Host "[前端] 启动 Vite ..." -ForegroundColor DarkGray
Start-Process -FilePath "powershell.exe" -WorkingDirectory $root -ArgumentList @(
    "-NoExit", "-Command", "npm run dev"
)

Write-Host ""
Write-Host "已启动：前端 http://localhost:1420（Vite 会自动打开浏览器），中间件占用 8737。" -ForegroundColor Green
Write-Host "停止：关闭对应窗口，或在窗口里按 Ctrl+C。"
