# syntax=docker/dockerfile:1.7

# Stage 1: build dependencies on a Debian 13 (trixie) Python image so the
# resulting wheels are ABI-compatible with the distroless runtime.
FROM python:3.13-slim-trixie AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libffi-dev \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir --target=/install -r requirements.txt

# App code + writable runtime directories owned by the distroless nonroot UID (65532).
COPY app/ /app/app/
RUN mkdir -p /app/logs /app/database \
 && chown -R 65532:65532 /app /install


# Stage 2: distroless Debian 13 runtime, rootless (uid 65532).
FROM gcr.io/distroless/python3-debian13:nonroot

WORKDIR /app

COPY --from=builder --chown=65532:65532 /install /app/deps
COPY --from=builder --chown=65532:65532 /app /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/deps

USER 65532:65532

# The distroless python3 image entrypoint is /usr/bin/python3.
CMD ["app/main.py"]
