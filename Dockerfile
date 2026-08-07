FROM python:3.12-slim AS builder

WORKDIR /app
RUN pip install --no-cache-dir hatchling

COPY pyproject.toml README.md ./
COPY docs/runtime_verification/nautilus-polysignal-wheel.json /tmp/nautilus-wheel.json
COPY src/ src/
RUN pip install --ignore-installed --no-cache-dir --only-binary=nautilus-trader \
    --extra-index-url https://packages.nautechsystems.io/simple \
    --prefix=/install '.[dev,nautilus]'
RUN PYTHONPATH=/install/lib/python3.12/site-packages python - <<'PY'
import importlib.metadata
import json

with open("/tmp/nautilus-wheel.json", encoding="utf-8") as manifest_file:
    manifest = json.load(manifest_file)
assert importlib.metadata.version("nautilus-trader") == manifest["version"]
PY

# ── Runtime image (Nautilus LiveNode is the default path) ──────
FROM python:3.12-slim AS nautilus-runtime

LABEL io.polysignal.nautilus.upstream-sha="a930c8afe380025fc0a10c6b2cd6907d6b983e86" \
      io.polysignal.nautilus.patch-sha="3064b29f070be71a30d739cc00f5acb69f43b5f1" \
      io.polysignal.nautilus.version="1.231.0a20260730+polysignal.10" \
      io.polysignal.nautilus.wheel-sha256="537a62b83a72289f3334f0acc26be6f414c7d770d054e346979cff84aabbc004"

WORKDIR /app

# Install runtime deps at known paths
COPY --from=builder /install /usr/local

# Application code & config
COPY pyproject.toml ./
COPY config/ config/
COPY src/ src/
COPY scripts/ scripts/
COPY tests/ tests/
COPY docker-entrypoint.sh /app/docker-entrypoint.sh

# Persistence directories (bind-mount from host)
RUN mkdir -p data logs state && chmod +x /app/docker-entrypoint.sh

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["nautilus"]
