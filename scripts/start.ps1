$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$PythonExe = "python"

if (Test-Path $VenvPython) {
    $venvReady = $false
    try {
        & $VenvPython -c "import streamlit" 1>$null 2>$null
        $venvReady = ($LASTEXITCODE -eq 0)
    } catch {
        $venvReady = $false
    }
    if ($venvReady) {
        $PythonExe = $VenvPython
    }
    else {
        Write-Warning ".venv 不可用或未安装 streamlit，已回退到系统 Python。可先执行 scripts\setup.ps1。"
    }
}

Write-Host "使用 Python: $PythonExe"
Write-Host "启动 Streamlit ..."

& $PythonExe -m streamlit run (Join-Path $RepoRoot "app.py") --browser.gatherUsageStats false
