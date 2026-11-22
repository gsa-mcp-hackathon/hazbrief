# syntax=docker/dockerfile:1
# Container image for remote (streamable-HTTP) deployment.
#
# Used by:
#   - IBM Code Engine (deploy/ibm/)
#   - cloud.gov (docker image path) and any other container host
#
# The server serves MCP over streamable-HTTP at :8080/mcp with a health check
# at :8080/health. app.py auto-selects HTTP because PORT is set below. No remote is
# published (server.json, HB-89): run it locally, published on 127.0.0.1.
#
# The install follows uv's Docker guide (docs.astral.sh/uv/guides/integration/docker/):
# uv's image pinned by version and digest, dependencies from uv.lock with --locked
# (the build fails if the lock is stale), in their own layer before the project.
# test_container_image.py (a test held privately) holds every rule below (HB-34).

# uv 0.10.7, the version that wrote uv.lock. A tag can move; the digest cannot.
FROM ghcr.io/astral-sh/uv:0.10.7@sha256:edd1fd89f3e5b005814cc8f777610445d7b7e3ed05361f9ddfae67bebfe8456a AS uv

# Python 3.11.17 on Debian slim: the index digest HB-34 read on 2026-10-24 and HB-35 confirmed on
# 2026-10-25 (registry-1.docker.io, image created 2026-10-21). A tag can move; the digest cannot.
FROM python:3.11-slim@sha256:b7a9e5f6a93d6d4a31f129bbd4bdee69efccb6ded0fb230d78aafaf37af98377

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
# HB-89: the server binds 127.0.0.1 unless MCP_HOST widens it (config.py). Inside the container
# the bind is widened to every interface of the container's own network namespace, or the
# published port could not reach it. What reaches the host is decided by `docker run -p`: the
# README publishes it on 127.0.0.1 only (`-p 127.0.0.1:8080:8080`). The route carries no
# authentication (docs/SECURITY.md); the Host guard (app.py http_options) still admits only
# loopback names unless MCP_ALLOWED_HOSTS lists another.
ENV MCP_HOST=0.0.0.0
# uv: compile bytecode at install, copy rather than link from the cache, and never download a
# Python (the base image's 3.11 is the interpreter).
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_PYTHON_DOWNLOADS=0

WORKDIR /app

COPY --from=uv /uv /uvx /usr/local/bin/

# Dependencies first, from the lockfile, for layer caching. LICENSE and LICENSE-TEMPLATE are
# pyproject.toml's `license-files`, which the project's install reads, and the MIT notice every
# copy of the software carries (HB-87R).
COPY pyproject.toml uv.lock README.md LICENSE LICENSE-TEMPLATE ./
RUN uv sync --locked --no-dev --no-install-project

COPY src ./src
# The commander stylebook (HB-02): the prompt, the resources and stylecheck read it beside src/
# (src/hazbrief/stylebook_files.py).
COPY docs/stylebook ./docs/stylebook
# The knowledge packs (HB-03; packs/SCHEMA.md): src/hazbrief/packs.py reads /app/packs, beside
# /app/src. No database at runtime (DN-001 section 4 invariant 3).
COPY packs ./packs
# The cached LODES workplace files (HB-09) and CMS hospital and nursing home files (HB-10):
# config.py's hazbrief_lodes_dir and hazbrief_cms_dir. Read per incident, never downloaded per
# incident. Without them receiving_hospitals returns an error, facilities_in_footprint loses its
# nursing homes and daytime jobs report every state missing (HB-26, D-11).
COPY fixtures/lodes ./fixtures/lodes
COPY fixtures/cms ./fixtures/cms

# The project itself, installed editable, so hazbrief resolves to /app/src and its REPO_ROOT
# (config.py) to /app, where the copies above are.
RUN uv sync --locked --no-dev
ENV PATH="/app/.venv/bin:$PATH"

# A non-root user. The server writes nothing in the image: the recorder, which writes
# fixtures/exchanges/, runs only in record mode, and the image runs live.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin hazbrief
USER hazbrief

EXPOSE 8080

# PORT=8080 (set above) makes app.py run HTTP on that port automatically.
CMD ["python", "-m", "hazbrief.app"]
