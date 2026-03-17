# ────────────────────────────────────────────────────────────────
#  Kitsune Userbot — Dockerfile
#  Developer: Yushi (@Mikasu32)
# ────────────────────────────────────────────────────────────────

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DOCKER=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ── System deps ───────────────────────────────────────────────────
RUN apt-get update -qq && apt-get install -y --no-install-recommends \
    git curl build-essential libssl-dev libffi-dev libjpeg-dev \
    && rm -rf /var/lib/apt/lists/*

# ── Python deps ───────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt && \
    pip install hydrogram tgcrypto || true

# ── Source ────────────────────────────────────────────────────────
COPY . .

# ── Data volume ───────────────────────────────────────────────────
RUN mkdir -p /data
VOLUME ["/data"]

# ── Run ──────────────────────────────────────────────────────────
CMD ["python", "-m", "kitsune"]
