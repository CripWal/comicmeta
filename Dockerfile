# comicmeta — headless Docker image for batch metadata operations on a NAS.
#
# Local users with files on disk do not need this image; install via
# `pip install comicmeta` (or Homebrew) and run directly. This image is for
# deployments where the comic library lives on a remote/always-on host
# (TrueNAS, unRAID, a NAS box) and you want comicmeta I/O to be local to that
# host instead of crossing a network mount (SMB-WAN rename of large CBZ files
# is unreliable; see baselines/redesign-2026-08-06.md and BACKBURNER.md).
#
# Interactive review/browse/dashboard stay on your workstation against synced
# state files — those phases are network-irrelevant (pure local JSON, <0.1 s).
# This container runs the I/O-heavy headless commands: discover, inspect,
# write --yes, health, backup, convert, organize, validate, stage, mapping,
# missing, flags, fetch-issues. Runs one command and exits (no daemon).
#
# Build:  docker build -t comicmeta:1.0.1 .
#          (or `docker build --build-arg VERSION=1.0.0 -t comicmeta:1.0.1 .`
#           to install the released PyPI sdist instead of the local checkout.)
# Run:    docker run --rm -v /srv/comics:/comics -v comicmeta-data:/data \
#           comicmeta:1.0.1 inspect --quick --source /comics

ARG VERSION=local

FROM python:3.11-slim AS runtime

LABEL org.opencontainers.image.title="comicmeta"
LABEL org.opencontainers.image.source="https://github.com/CripWal/comicmeta"
LABEL org.opencontainers.image.licenses="MIT"

ARG VERSION
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN --mount=type=bind,source=.,target=/src \
    if [ "$VERSION" = "local" ]; then \
        pip install --no-cache-dir /src; \
    else \
        pip install --no-cache-dir "comicmeta==$VERSION"; \
    fi

ENV COMICMETA_SOURCE=/comics
ENV XDG_CONFIG_HOME=/data/config
ENV XDG_CACHE_HOME=/data/cache

RUN mkdir -p /comics /data/config /data/cache /data/backups

VOLUME ["/comics", "/data"]

WORKDIR /comics

ENTRYPOINT ["comicmeta"]