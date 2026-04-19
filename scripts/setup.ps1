param(
    [switch]$UseCurrentPython,
    [switch]$WithOCR,
    [string]$BasePython = "python"
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Requirements = Join-Path $RepoRoot "requirements.txt"
$OCRRequirements = Join-Path $RepoRoot "requirements_ocr.txt"
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"

function Test-PythonModule {
    param(
        [string]$PythonPath,
        [string]$ModuleName
    )
    try {
        & $PythonPath -c "import $ModuleName" 1>$null 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

if (-not (Test-Path $Requirements)) {
    throw "未找到 requirements.txt: $Requirements"
}

$PythonExe = "python"

if (-not $UseCurrentPython) {
    Write-Host "[1/3] 创建虚拟环境 .venv ..."
    if (Test-Path -Path (Join-Path $RepoRoot ".venv")) {
        Write-Host "检测到已存在的 .venv，将重新创建 ..."
        Remove-Item -Path (Join-Path $RepoRoot ".venv") -Recurse -Force
    }
    try {
        & $BasePython -m venv (Join-Path $RepoRoot ".venv")
    } catch {
        Write-Warning "创建 .venv 失败，将回退到当前 Python 环境。错误: $($_.Exception.Message)"
    }

    if (Test-Path $VenvPython) {
        $PythonExe = $VenvPython
        if (-not (Test-PythonModule -PythonPath $PythonExe -ModuleName "pip")) {
            Write-Host "检测到 .venv 缺少 pip，尝试补齐 ..."
            & $PythonExe -m ensurepip --upgrade
        }
    } else {
        Write-Warning "未检测到 .venv\Scripts\python.exe，继续使用当前 Python。"
    }
}

Write-Host "[2/3] 安装基础依赖 ..."
& $PythonExe -m pip install -r $Requirements

if ($WithOCR) {
    if (Test-Path $OCRRequirements) {
        Write-Host "检测到 -WithOCR，正在安装 OCR 高级识别依赖 (PaddleOCR/OpenCV/PyQt5等) ..."
        & $PythonExe -m pip install -r $OCRRequirements
    } else {
        Write-Warning "未找到 requirements_ocr.txt，跳过安装 OCR 依赖。"
    }
}

if (-not (Test-PythonModule -PythonPath $PythonExe -ModuleName "streamlit")) {
    Write-Warning "当前解释器未检测到 streamlit，回退到系统 Python 安装依赖。"
    & $PythonExe -m pip install -r $Requirements
    if ($WithOCR -and (Test-Path $OCRRequirements)) {
        & $PythonExe -m pip install -r $OCRRequirements
    }
}

Write-Host "[3/3] 环境准备完成。"
Write-Host "启动命令: powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1"
