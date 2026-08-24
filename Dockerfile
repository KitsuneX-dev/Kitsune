# syntax=docker/dockerfile:1

FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VENV_PATH=/opt/venv

RUN apt-get update -qq && apt-get install -y --no-install-recommends \
        build-essential \
        libssl-dev \
        libffi-dev \
        libjpeg-dev \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv "$VENV_PATH"
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

COPY requirements.txt ./
RUN pip install --upgrade pip setuptools wheel \
    && pip install -r requirements.txt

FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    DOCKER=1 \
    KITSUNE_DATA_DIR=/data \
    KITSUNE_WEB_PORT=8080 \
    PATH="/opt/venv/bin:$PATH" \
    HOME=/home/kitsune

RUN apt-get update -qq && apt-get install -y --no-install-recommends \
        git \
        libjpeg62-turbo \
        zlib1g \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -g 1000 kitsune \
    && useradd -u 1000 -g 1000 -m -d /home/kitsune -s /bin/bash kitsune

COPY --from=builder --chown=kitsune:kitsune /opt/venv /opt/venv

WORKDIR /app
COPY --chown=kitsune:kitsune . /app

RUN mkdir -p /data \
    && chown -R kitsune:kitsune /data /app \
    && chmod 700 /data

VOLUME ["/data"]

EXPOSE 8080

USER kitsune

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD ["python", "/app/tools/healthcheck.py"]

CMD ["python", "-m", "kitsune"]
