# Monet: one image, one process. Built on a laptop or in CI, never on the droplet.
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY monet ./monet
RUN uv sync --frozen --no-dev

FROM python:3.12-slim
# the CAD kernel (OCP) links against these even when nothing is ever drawn
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libxrender1 libxext6 libsm6 libfontconfig1 \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --uid 1000 --create-home monet && mkdir -p /storage /data && chown monet:monet /storage /data
WORKDIR /app
COPY --from=build /app/.venv ./.venv
COPY monet ./monet
COPY canvas ./canvas
COPY notes ./notes
COPY profiles ./profiles
COPY skill ./skill
ARG COMMIT=unknown
ENV COMMIT=$COMMIT PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    MONET_HOST=0.0.0.0 PORT=8080 MONET_STORAGE=/storage MONET_DATA=/data FORWARDED_ALLOW_IPS=* HOME=/tmp
USER monet
VOLUME /storage /data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s CMD python -c "import urllib.request as u; u.urlopen('http://localhost:8080/healthz', timeout=2)"
CMD ["python", "-m", "monet"]
