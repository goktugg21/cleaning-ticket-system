FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev gettext \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt

RUN pip install --upgrade pip \
    && pip install -r /app/requirements.txt

COPY . /app/

# Create a non-root user for services that opt in via compose `user:`.
# Backend service still runs as root by default in this image; only the
# worker service overrides `user:` in compose. Backend non-root is a
# separate hardening change (it must verify writable paths for media,
# staticfiles, and uploads).
RUN groupadd --system app && useradd --system --gid app --home-dir /app app \
    && chown -R app:app /app
