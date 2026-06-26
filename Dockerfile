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
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ca-certificates clang curl git pkg-config \
    && rm -rf /var/lib/apt/lists/*
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain stable
ENV PATH="/root/.cargo/bin:${PATH}"
RUN pip install --ignore-installed --no-cache-dir --prefix=/install-nautilus '.[dev]' 'nautilus_trader[polymarket] @ git+https://github.com/nautechsystems/nautilus_trader.git@a3a72b2'

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
