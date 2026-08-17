# Multi-stage build.
#
# NOTE: this image has not been built or executed — Docker was unavailable on the authoring
# machine. CI builds it (.github/workflows/ci.yml) so a broken Dockerfile fails there.
#
# Base images are pinned by digest, not by mutable tag, so an upstream retag cannot silently
# change what we deploy. The digests below were resolved from the Docker Hub registry API for
# python:3.13-slim; Dependabot raises PRs when a newer digest is published.
#
# Dependencies install from uv.lock with --locked, so the image resolves to exactly the
# dependency graph committed alongside the source.

FROM python:3.13-slim@sha256:ffb752e139c0a19692a43af8d8523b274222dd68eebad5d583b45c2201c6e30a AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Install into a self-contained venv we can copy wholesale into the runtime stage.
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    # Use the interpreter already in the image; never fetch a second one.
    UV_PYTHON=/usr/local/bin/python3 \
    UV_PYTHON_DOWNLOADS=never

RUN pip install --no-cache-dir uv==0.12.5

WORKDIR /build

# Dependencies are installed before the source is copied, so editing application code does
# not invalidate the dependency layer. --no-install-project defers the project itself.
COPY pyproject.toml uv.lock README.md ./
COPY src/aedifex/__init__.py src/aedifex/__init__.py
RUN uv sync --locked --no-dev --no-install-project

COPY src/ src/
COPY apps/ apps/
COPY migrations/ migrations/
COPY alembic.ini ./
RUN uv sync --locked --no-dev


FROM python:3.13-slim@sha256:ffb752e139c0a19692a43af8d8523b274222dd68eebad5d583b45c2201c6e30a AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# Run as an unprivileged user. This process parses untrusted documents downloaded from the
# public internet, so it must not be root.
RUN groupadd --system --gid 1001 aedifex \
 && useradd --system --uid 1001 --gid aedifex --create-home aedifex

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=aedifex:aedifex src/ src/
COPY --chown=aedifex:aedifex apps/ apps/
COPY --chown=aedifex:aedifex migrations/ migrations/
COPY --chown=aedifex:aedifex config/ config/
COPY --chown=aedifex:aedifex alembic.ini ./

USER aedifex

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health').read()"

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
