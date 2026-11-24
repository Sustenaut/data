# The ingest job's image: this repository's code and the packages requirements.lock pins,
# each checked against its sha256. It runs one pipeline and exits; the Cloud
# Run job gives it the store (a mounted bucket) and the run log (BigQuery)
# through DATA_STORE, DATA_STORE_URI and DATA_RUN_LOG.
FROM python:3.13-slim-trixie@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN useradd --system --uid 10001 --home-dir /app runner
WORKDIR /app

COPY requirements.lock ./
RUN pip install --require-hashes --only-binary=:all: -r requirements.lock

COPY src ./src
COPY pipelines ./pipelines
COPY corrections ./corrections

ARG DATA_COMMIT=dev
ENV PYTHONPATH=/app/src \
    DATA_COMMIT=${DATA_COMMIT}

USER runner
ENTRYPOINT ["python", "-m", "ingest"]
CMD ["run", "pipelines/eex-french-go-auctions.yaml", "--trigger", "schedule"]
