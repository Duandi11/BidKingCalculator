#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

ENV_NAME="bidking"
APP_ARGS=()

print_usage() {
    cat <<EOF
Usage: bash scripts/start.sh [options] [-- <streamlit args>]

Options:
  --env-name <name>  Conda environment name (default: bidking)
  -h, --help         Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --env-name)
            ENV_NAME="$2"
            shift 2
            ;;
        -h|--help)
            print_usage
            exit 0
            ;;
        --)
            shift
            APP_ARGS+=("$@")
            break
            ;;
        *)
            APP_ARGS+=("$1")
            shift
            ;;
    esac
done

if ! command -v conda >/dev/null 2>&1; then
    echo "Conda command not found. Please install Miniconda/Anaconda and ensure 'conda' is in PATH."
    exit 1
fi

if ! conda run -n "${ENV_NAME}" python -c "import streamlit" >/dev/null 2>&1; then
    echo "Conda env '${ENV_NAME}' is not ready. Run: bash scripts/setup.sh --env-name ${ENV_NAME}"
    exit 1
fi

echo "Using Conda env: ${ENV_NAME}"
conda run -n "${ENV_NAME}" python -m streamlit run "${REPO_ROOT}/app.py" --browser.gatherUsageStats false "${APP_ARGS[@]}"
