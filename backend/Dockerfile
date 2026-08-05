# syntax=docker/dockerfile:1.7
FROM python:3.11-slim

WORKDIR /app
ARG GUARDRAILS_TOKEN=""
ARG GUARDRAILS_HUB_INSTALL_TIMEOUT_SECONDS=90

# Install dependencies
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Cacheable Guardrails validator layer. This runs at image build time, before app
# source is copied, so app-code changes do not force validator reinstall.
RUN --mount=type=secret,id=backend_env,required=false \
    --mount=type=cache,target=/root/.cache/pip \
    SECRET_GUARDRAILS_TOKEN="$(awk -F= '$1 == "GUARDRAILS_TOKEN" {sub(/^[^=]*=/, ""); print; exit}' /run/secrets/backend_env 2>/dev/null || true)" ; \
    EFFECTIVE_GUARDRAILS_TOKEN="${GUARDRAILS_TOKEN:-$SECRET_GUARDRAILS_TOKEN}" ; \
    if [ -n "$EFFECTIVE_GUARDRAILS_TOKEN" ]; then \
        guardrails configure --enable-metrics --enable-remote-inferencing --token "$EFFECTIVE_GUARDRAILS_TOKEN" ; \
        for validator in \
            hub://guardrails/llamaguard_7b \
            hub://guardrails/detect_pii \
            hub://guardrails/profanity_free \
            hub://guardrails/unusual_prompt; do \
            timeout "$GUARDRAILS_HUB_INSTALL_TIMEOUT_SECONDS" guardrails hub install "$validator" --no-install-local-models \
            || echo "Skipping Guardrails Hub validator after install failure or timeout: $validator"; \
        done; \
    else \
        echo "Skipping Guardrails Hub validator install because GUARDRAILS_TOKEN is not available."; \
    fi

# Copy app code
COPY . .

# Run the API server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
