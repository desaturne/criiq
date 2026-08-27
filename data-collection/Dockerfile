FROM python:3.14-slim

# lxml/pyarrow may need a compiler if a wheel isn't available for this arch.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY criiq_data/ /app/criiq_data/
COPY run.py /app/run.py

# This container OWNS criiq.db — /data is mounted read-write here, unlike the
# backend, which only ever reads it.
ENV CRIIQ_DATA_DIR=/data \
    CRIIQ_DB=/data/criiq.db \
    PYTHONUNBUFFERED=1

# Run pipeline stages as:  docker compose run --rm data-collection refresh
ENTRYPOINT ["python", "run.py"]
CMD ["--help"]
