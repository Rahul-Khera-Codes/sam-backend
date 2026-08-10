#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAM_BACKEND_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

docker run --rm -it \
  --user "$(id -u):$(id -g)" \
  -v "$SAM_BACKEND_DIR:/workspace" \
  -w /workspace/evals/hr_onboarding_ragas \
  -e RAGAS_EVAL_BUSINESS_ID \
  -e RAGAS_EVAL_USER_EMAIL \
  -e RAGAS_EVAL_ENV_FILE \
  -e RAGAS_EVAL_RUN_NAME \
  python:3.11-slim \
  bash -lc '
    python -m venv /tmp/hr-ragas-eval-venv
    source /tmp/hr-ragas-eval-venv/bin/activate
    python -m pip install --upgrade pip
    python -m pip install -r requirements-eval.txt
    python evals.py "$@"
  ' bash "$@"
