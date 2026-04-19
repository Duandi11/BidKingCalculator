#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
REQUIREMENTS_FILE="${REPO_ROOT}/requirements.txt"
OCR_REQUIREMENTS_FILE="${REPO_ROOT}/requirements_ocr.txt"

ENV_NAME="bidking"
PYTHON_VERSION="3.10"
WITH_OCR=0
FORCE_RECREATE=0

print_usage() {
    cat <<EOF
Usage: bash scripts/setup.sh [options]

Options:
  --env-name <name>       Conda environment name (default: bidking)
  --python-version <ver>  Python version for Conda env (default: 3.10)
  --with-ocr              Install OCR dependencies from requirements_ocr.txt
  --recreate              Remove existing env and recreate it
  -h, --help              Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --env-name)
            ENV_NAME="$2"
            shift 2
            ;;
        --python-version)
            PYTHON_VERSION="$2"
            shift 2
            ;;
        --with-ocr)
            WITH_OCR=1
            shift
            ;;
        --recreate)
            FORCE_RECREATE=1
            shift
            ;;
        -h|--help)
            print_usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            print_usage
            exit 1
            ;;
    esac
done

if [[ ! -f "${REQUIREMENTS_FILE}" ]]; then
    echo "requirements.txt not found: ${REQUIREMENTS_FILE}"
    exit 1
fi

if ! command -v conda >/dev/null 2>&1; then
    echo "Conda command not found. Please install Miniconda/Anaconda and ensure 'conda' is in PATH."
    exit 1
fi

env_exists=0
if conda run -n "${ENV_NAME}" python -c "import sys" >/dev/null 2>&1; then
    env_exists=1
fi

if [[ ${FORCE_RECREATE} -eq 1 && ${env_exists} -eq 1 ]]; then
    echo "[1/3] Removing existing Conda env: ${ENV_NAME}"
    conda env remove -n "${ENV_NAME}" -y
    env_exists=0
fi

if [[ ${env_exists} -eq 0 ]]; then
    echo "[1/3] Creating Conda env '${ENV_NAME}' with Python ${PYTHON_VERSION}"
    conda create -n "${ENV_NAME}" "python=${PYTHON_VERSION}" pip -y
else
    echo "[1/3] Reusing existing Conda env: ${ENV_NAME}"
fi

echo "[2/3] Installing base dependencies"
conda run -n "${ENV_NAME}" python -m pip install -r "${REQUIREMENTS_FILE}"

if [[ ${WITH_OCR} -eq 1 ]]; then
    echo "Installing PaddlePaddle with GPU support via Conda (using Tsinghua mirror)..."
    conda install -n "${ENV_NAME}" cudatoolkit=11.7 cudnn=8.4 -c https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge/ -y
    
    echo "Installing paddlepaddle-gpu..."
    conda run -n "${ENV_NAME}" python -m pip install "paddlepaddle-gpu==2.6.1.post117" -f https://www.paddlepaddle.org.cn/whl/windows/mkl/avx/stable.html
    
    if [[ -f "${OCR_REQUIREMENTS_FILE}" ]]; then
        echo "Installing OCR dependencies"
        conda run -n "${ENV_NAME}" python -m pip install -r "${OCR_REQUIREMENTS_FILE}"
    else
        echo "requirements_ocr.txt not found, skipping OCR dependencies"
    fi
fi

echo "[3/3] Verifying Streamlit"
conda run -n "${ENV_NAME}" python -c "import streamlit"

echo "Environment is ready."
echo "Start with: bash scripts/start.sh --env-name ${ENV_NAME}"
