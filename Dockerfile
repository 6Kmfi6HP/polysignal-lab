FROM python:3.12-slim AS builder

WORKDIR /app
RUN pip install --no-cache-dir hatchling

COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --ignore-installed --no-cache-dir --only-binary=nautilus-trader --pre \
    --extra-index-url https://packages.nautechsystems.io/simple \
    --prefix=/install '.[dev,nautilus]'
RUN PYTHONPATH=/install/lib/python3.12/site-packages python - <<'PY'
import importlib.metadata
print("nautilus-trader", importlib.metadata.version("nautilus-trader"))
PY

# ── Runtime image (Nautilus LiveNode is the default path) ──────
FROM python:3.12-slim AS nautilus-runtime

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
