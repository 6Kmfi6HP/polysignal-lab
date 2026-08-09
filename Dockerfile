FROM python:3.12-slim AS builder

WORKDIR /app
RUN pip install --no-cache-dir hatchling

COPY pyproject.toml README.md ./
COPY docs/runtime_verification/nautilus-polysignal-wheel.json /tmp/nautilus-wheel.json
COPY src/ src/
RUN pip install --ignore-installed --no-cache-dir --only-binary=nautilus-trader --pre \
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
      io.polysignal.nautilus.patch-sha="d16b3462a1178a762e65eaada8b49a478e186143" \
      io.polysignal.nautilus.release-tag="nightly" \
      io.polysignal.nautilus.version="1.231.0a20260802" \
      io.polysignal.nautilus.wheel-sha256="a5067497f370b4e2b35375bbf237a144a6affabb3f11a96fbe8dbd77f8907a4c"

WORKDIR /app

# Install runtime deps at known paths
COPY --from=builder /install /usr/local

# Application code & config
COPY pyproject.toml ./
COPY build-info.json /app/build-info.json
COPY config/ config/
COPY src/ src/
COPY scripts/ scripts/
COPY tests/ tests/
COPY docker-entrypoint.sh /app/docker-entrypoint.sh

# Persistence directories (bind-mount from host)
RUN touch /app/.require-build-info && \
    PYTHONPATH=src python -c 'from polysignal_lab.build_info import BUILD_INFO; assert BUILD_INFO.commit_sha' && \
    mkdir -p data logs state && chmod +x /app/docker-entrypoint.sh

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["nautilus"]
