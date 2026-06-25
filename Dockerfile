FROM python:3.12-slim AS builder

WORKDIR /app
RUN pip install --no-cache-dir hatchling

COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --ignore-installed --no-cache-dir --prefix=/install '.[dev]'

# ── Runtime image ──────────────────────────────────────────────
FROM python:3.12-slim

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
CMD ["scheduler"]

# ── Nautilus runtime image (separate target; default stays paper-safe) ──
FROM builder AS nautilus-builder
RUN pip install --ignore-installed --no-cache-dir --prefix=/install-nautilus '.[dev,nautilus]'

FROM python:3.12-slim AS nautilus-runtime
WORKDIR /app
COPY --from=nautilus-builder /install-nautilus /usr/local
COPY pyproject.toml ./
COPY config/ config/
COPY src/ src/
COPY scripts/ scripts/
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN mkdir -p data logs state && chmod +x /app/docker-entrypoint.sh
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["nautilus"]
