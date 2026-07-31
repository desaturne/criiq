FROM python:3.14-slim

# Some scientific wheels may need compiling on arm64; curl is for the healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# --- 1. model-training's own venv (heavy ML deps, kept isolated) -------------
COPY model-training/requirements.txt /tmp/model-requirements.txt
RUN python -m venv /opt/venv-model \
    && /opt/venv-model/bin/pip install --no-cache-dir -r /tmp/model-requirements.txt

# --- 2. backend deps (system python) ----------------------------------------
COPY backend/requirements.txt /tmp/backend-requirements.txt
RUN pip install --no-cache-dir -r /tmp/backend-requirements.txt

# --- 3. source code ----------------------------------------------------------
WORKDIR /app
COPY backend/ /app/backend/
COPY model-training/criiq_models/ /app/model-training/criiq_models/

ENV MODEL_TRAINING_DIR=/app/model-training \
    MODEL_TRAINING_PYTHON=/opt/venv-model/bin/python \
    CRIIQ_DB=/data/criiq.db \
    CRIIQ_MODEL_ARTIFACTS=/artifacts \
    APP_DB=/state/app.db \
    AUTH_DB=/state/auth.db \
    PYTHONUNBUFFERED=1

RUN mkdir -p /state
WORKDIR /app/backend
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
