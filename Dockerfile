FROM python:3.12-slim AS builder

WORKDIR /app
RUN pip install --no-cache-dir hatchling

COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --ignore-installed --no-cache-dir --only-binary=nautilus-trader \
    --extra-index-url https://packages.nautechsystems.io/simple \
    --prefix=/install '.[dev,nautilus]'

# ── Runtime image (Nautilus LiveNode is the default path) ──────
FROM python:3.12-slim AS nautilus-runtime

ARG NAUTILUS_UPSTREAM_SHA=a930c8afe380025fc0a10c6b2cd6907d6b983e86
ARG NAUTILUS_PATCH_SHA=623eb74a52aa6520b3b9a1f569045110fe14180f
ARG NAUTILUS_VERSION=1.231.0a20260730+polysignal.1
ARG NAUTILUS_WHEEL_SHA256=6fde27a2f4ed14b1e6a11c38c8a066aaca139afd02e47a1afc7719171109e55c

LABEL io.polysignal.nautilus.upstream-sha=$NAUTILUS_UPSTREAM_SHA \
      io.polysignal.nautilus.patch-sha=$NAUTILUS_PATCH_SHA \
      io.polysignal.nautilus.version=$NAUTILUS_VERSION \
      io.polysignal.nautilus.wheel-sha256=$NAUTILUS_WHEEL_SHA256

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
