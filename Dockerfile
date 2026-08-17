# Multi-stage build.
#
# NOTE: this image has not been built or executed — Docker was unavailable on the authoring
# machine. CI builds it (.github/workflows/ci.yml) so a broken Dockerfile fails there.
#
# Stage 1 installs dependencies into a virtualenv; stage 2 copies only that virtualenv and
# the application, so build tools and caches never reach the runtime image.

FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy

RUN pip install --no-cache-dir uv==0.12.5

WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Dependencies are installed before the source is copied so that editing application code
# does not invalidate the dependency layer.
COPY pyproject.toml README.md ./
COPY src/aedifex/__init__.py src/aedifex/__init__.py
RUN uv pip install --no-cache .

COPY src/ src/
COPY apps/ apps/
COPY migrations/ migrations/
COPY alembic.ini ./
RUN uv pip install --no-cache --no-deps .


FROM python:3.13-slim AS runtime

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
