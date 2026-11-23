# The power-auctions app's image: soldera and the packages
# requirements-app.lock pins (the app extra), each checked against its
# sha256. It serves the app on Cloud Run's PORT and reads the newest database
# the merge stage published in SOLDERA_STORE (gs://BUCKET, over its API).
FROM python:3.13-slim-trixie@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN useradd --system --uid 10001 --home-dir /app soldera
WORKDIR /app

COPY requirements-app.lock ./
RUN pip install --require-hashes --only-binary=:all: -r requirements-app.lock

COPY src ./src
COPY pipelines ./pipelines
COPY corrections ./corrections

ARG SOLDERA_COMMIT=dev
ENV PYTHONPATH=/app/src \
    SOLDERA_COMMIT=${SOLDERA_COMMIT} \
    PORT=8080

USER soldera
EXPOSE 8080
ENTRYPOINT ["python", "-m", "soldera", "app"]
