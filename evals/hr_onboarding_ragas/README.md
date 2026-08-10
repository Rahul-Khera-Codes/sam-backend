# HR Onboarding Ragas Evaluation

Developer-only Ragas evaluation harness for the HR onboarding chatbot.

This folder is intentionally separate from the FastAPI app and LiveKit agents. It is not imported by the production request path, does not add user-facing latency, and does not expose an API or UI route.

## What It Evaluates

The harness calls the existing typed HR onboarding service directly and records:

- user question
- generated chatbot answer
- retrieved HR policy contexts
- source document names
- reference answer/criteria

It then runs Ragas metrics:

- `Faithfulness`
- `LLMContextRecall`
- `FactualCorrectness`

The first version is report-only. It does not fail CI based on thresholds.

## Install

Use an isolated virtualenv in this eval folder. Do not install these packages into your system Python or the frontend project.

This eval harness should use Python 3.11, matching the backend Docker image. Python 3.9 can fail to install the backend's pinned `guardrails-ai==0.10.2`.

## Recommended Safe Path: Docker-Isolated Runner

If your local terminal is using Python 3.9, use the Docker runner instead of a local venv:

```bash
cd /Users/exceltech/Sam/sam-backend/evals/hr_onboarding_ragas
bash run_eval_docker.sh --help
```

This runner:

- uses `python:3.11-slim`
- creates a temporary venv inside the container
- installs eval dependencies inside the container only
- mounts `sam-backend` read/write so reports can be saved under `experiments/`
- does not install anything into your system Python
- does not modify the backend, frontend, or production Docker images

Example report-only collection without Ragas scoring:

```bash
bash run_eval_docker.sh --user-email "rahul.excel2011@gmail.com" --skip-ragas
```

Full Ragas run for a specific tenant:

```bash
bash run_eval_docker.sh --business-id "<business-id>"
```

The first run can take a while because it installs Python dependencies in the temporary container. Later runs still reinstall because the container is intentionally disposable and isolated.

## Local Python 3.11 venv

From this directory:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-eval.txt
```

If `python3.11` is not available on macOS:

```bash
brew install python@3.11
python3.11 -m venv .venv
```

If you already created a Python 3.9 venv, remove and recreate only the eval venv:

```bash
deactivate 2>/dev/null || true
rm -rf .venv
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-eval.txt
```

The requirements file is intentionally eval-only. It installs the backend dependencies needed by the HR onboarding service path plus `ragas`, without adding Ragas to the production app image.

## Tenant Selection

You can evaluate any tenant by passing a business id:

```bash
python evals.py --business-id "<business-id>"
```

Or by using an environment variable:

```bash
export RAGAS_EVAL_BUSINESS_ID="<business-id>"
python evals.py
```

If no business id is provided, the harness can resolve a business from a user email by looking up `profiles.email` and `user_roles.business_id`. It prefers a business that already has published, ready HR onboarding documents.

```bash
python evals.py --user-email "rahul.excel2011@gmail.com"
```

## Dev vs Production

The same harness can evaluate different environments by loading different env files.

Development:

```bash
python evals.py \
  --env-file ../../backend/.env \
  --business-id "<dev-business-id>"
```

Production or staging:

```bash
python evals.py \
  --env-file /secure/path/to/production.env \
  --business-id "<production-business-id>"
```

The env file must contain the backend settings needed by the existing service path, including:

- `OPENAI_API_KEY`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- any other backend settings required by `app.core.config`

## Cache Behavior

The harness sets:

```bash
HR_ONBOARDING_CACHE_ENABLED=false
```

by default, before importing backend services. This keeps answer-quality evals from reusing old cached responses. Cache performance should be evaluated separately with BetterDB/Valkey.

## Dataset

Starter cases live in:

```text
datasets/hr_policy_eval_cases.jsonl
```

Each line is one JSON object:

```json
{"id":"benefits-summary","question":"Summarize the benefits policies.","reference":"The answer should summarize only benefits information found in the business's published HR policy documents.","category":"Benefits"}
```

You can add cases for each tenant or category. If a case has `document_id`, the eval will pass it through to the same active-document retrieval path used by the chatbot.

## Outputs

Reports are saved under:

```text
experiments/<run-name>/
```

Files:

- `summary.json` - run metadata and aggregate Ragas scores
- `rows.csv` - per-case question/answer/reference/source summary
- `ragas_scores.csv` - per-row metric details when available from Ragas

## Useful Commands

Collect chatbot outputs without running Ragas metrics:

```bash
python evals.py --business-id "<business-id>" --skip-ragas
```

Name a run:

```bash
python evals.py --business-id "<business-id>" --run-name "reranker-baseline"
```

Use the committed starter dataset explicitly:

```bash
python evals.py \
  --business-id "<business-id>" \
  --dataset datasets/hr_policy_eval_cases.jsonl
```

## CI Usage

For CI, run this harness as a separate job after backend dependencies are available. Store `summary.json`, `rows.csv`, and `ragas_scores.csv` as build artifacts.

This first version should be report-only. Once baseline scores are stable, add threshold gates for metrics like faithfulness and factual correctness.
