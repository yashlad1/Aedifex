# Multi-stage build.
#
# This image is built, hardened, and smoke-tested on every CI run (.github/workflows/ci.yml):
# it must import its own package, refuse placeholder production credentials, run as a non-root
# user, and serve /health before the build is considered green.
#
# Base images are pinned by digest, not by mutable tag, so an upstream retag cannot silently
# change what we deploy. The digests below were resolved from the Docker Hub registry API for
# python:3.13-slim; Dependabot raises PRs when a newer digest is published.
#
# Dependencies install from uv.lock with --locked, so the image resolves to exactly the
# dependency graph committed alongside the source.

FROM python:3.13-slim@sha256:ffb752e139c0a19692a43af8d8523b274222dd68eebad5d583b45c2201c6e30a AS builder

# UV_PROJECT_ENVIRONMENT installs into a self-contained venv we can copy wholesale into the
# runtime stage. UV_PYTHON points at the interpreter already in the image so uv never fetches a
# second one, and UV_PYTHON_DOWNLOADS=never makes that a hard guarantee rather than a preference.
#
# These comments sit above the instruction rather than inside it on purpose. BuildKit tolerates
# a comment between line continuations, but Semgrep's Dockerfile parser does not: it treated the
# first one as a syntax error and abandoned lines 19-104, so `p/dockerfile` silently analysed
# nothing while still reporting "0 findings" and exit 0. CI now runs Semgrep with --strict, which
# turns a partial-parse warning into a build failure, so this cannot regress unnoticed.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON=/usr/local/bin/python3 \
    UV_PYTHON_DOWNLOADS=never

RUN pip install --no-cache-dir uv==0.12.5

WORKDIR /build

# Dependencies are installed before the source is copied, so editing application code does
# not invalidate the dependency layer. --no-install-project defers the project itself.
COPY pyproject.toml uv.lock README.md ./
COPY src/aedifex/__init__.py src/aedifex/__init__.py
RUN uv sync --locked --no-dev --no-install-project --no-editable

COPY src/ src/
COPY apps/ apps/
COPY migrations/ migrations/
COPY alembic.ini ./
# --no-editable is required, not cosmetic. `uv sync` installs the project in editable mode by
# default, which writes an _editable_impl_aedifex.pth pointing at /build/src. That path does
# not exist in the runtime stage, so the copied venv could not import `aedifex` at all and the
# image failed at startup with ModuleNotFoundError. Installing non-editable puts the package
# into site-packages, which is what makes the venv self-contained enough to copy.
RUN uv sync --locked --no-dev --no-editable


FROM python:3.13-slim@sha256:ffb752e139c0a19692a43af8d8523b274222dd68eebad5d583b45c2201c6e30a AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# Security remediation on top of the pinned base image.
#
# Pinning by digest buys reproducibility but freezes the base image's package versions, so
# security updates have to be applied explicitly rather than arriving with a moving tag. The
# first real CI Trivy scan found 11 fixable HIGH findings, all of them in the base image and
# none in our locked dependencies:
#
#   CVE-2026-53615  (x9)  util-linux family; integer overflow in libblkid partition parsing
#   CVE-2025-47273        setuptools path traversal — vendored inside pip as pkg_resources
#   GHSA-6v7p-g79w-8964   msgpack out-of-bounds read — also vendored inside pip
#
# Upstream python:3.13-slim had not been rebuilt (the pinned digest was still the current one),
# so waiting for a new digest was not an option.
RUN apt-get update \
 && apt-get install --only-upgrade --no-install-recommends -y \
      bsdutils libblkid1 libmount1 libsmartcols1 libuuid1 mount util-linux \
 && rm -rf /var/lib/apt/lists/*

# Remove pip from the runtime image. The venv is self-contained and installed non-editable, so
# nothing here needs pip, setuptools, or pkg_resources — and pip vendors both msgpack and
# pkg_resources, which is where two of the HIGH findings live. Deleting it fixes those and
# removes a package installer from an image that parses hostile documents.
RUN rm -rf /usr/local/lib/python3.13/site-packages/pip \
           /usr/local/lib/python3.13/site-packages/pip-*.dist-info \
           /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.13

# Run as an unprivileged user. This process parses untrusted documents downloaded from the
# public internet, so it must not be root.
RUN groupadd --system --gid 1001 aedifex \
 && useradd --system --uid 1001 --gid aedifex --create-home aedifex

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
# `src/` is deliberately absent: the aedifex package is installed into the venv's
# site-packages (non-editable), so copying the sources again would ship two copies of the same
# code that could diverge. `apps/` is not part of the installed package and is imported from
# the working directory, so it must be here.
COPY --chown=aedifex:aedifex apps/ apps/
COPY --chown=aedifex:aedifex migrations/ migrations/
COPY --chown=aedifex:aedifex config/ config/
COPY --chown=aedifex:aedifex alembic.ini ./

USER aedifex

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health').read()"

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
