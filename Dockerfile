FROM python:3.12-slim AS builder

WORKDIR /app
RUN pip install --no-cache-dir hatchling

COPY pyproject.toml README.md ./
COPY docs/runtime_verification/nautilus-polysignal-wheel.json /tmp/nautilus-wheel.json
COPY src/ src/
# The pinned nautilus wheel (2.0.0rc3.dev20260818+17674, contains the upstream
# c73bba6 Polymarket heartbeat fix) is no longer served by the official index;
# build from the local copy in wheels/ and point the pyproject URL pin at it.
COPY wheels/*.whl /tmp/
RUN sed -i \
    's|https://packages.nautechsystems.io/simple/nautilus-trader/[^"#]*#[^"]*|file:///tmp/nautilus_trader-2.0.0rc3.dev20260818+17674-cp312-cp312-manylinux_2_34_x86_64.whl|' \
    pyproject.toml
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

LABEL io.polysignal.nautilus.upstream-sha="1e960b3b215c" \
      io.polysignal.nautilus.patch-sha="1e960b3b215c" \
      io.polysignal.nautilus.release-tag="nightly" \
      io.polysignal.nautilus.version="2.0.0rc3.dev20260818+17674" \
      io.polysignal.nautilus.wheel-sha256="dbcd8057b29fae014fb313e55b13f1f0860ded90d39f063938ff3549c4326b14"

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
