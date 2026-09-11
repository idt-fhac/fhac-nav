# syntax=docker/dockerfile:1.25@sha256:0adf442eae370b6087e08edc7c50b552d80ddf261576f4ebd6421006b2461f12
FROM ubuntu:26.04@sha256:3131b4cc82a783df6c9df078f86e01819a13594b865c2cad47bd1bca2b7063bb as base
ARG BASE_IMAGE_NAME=ubuntu:26.04
ARG BASE_IMAGE_DIGEST=sha256:3131b4cc82a783df6c9df078f86e01819a13594b865c2cad47bd1bca2b7063bb
ARG TARGETARCH

LABEL org.opencontainers.image.base.name="docker.io/library/$BASE_IMAGE_NAME" \
      org.opencontainers.image.base.digest="$BASE_IMAGE_DIGEST" \
      org.opencontainers.image.source="https://github.com/c3nav/c3nav" \
      org.opencontainers.image.url="https://c3nav.de" \
      org.opencontainers.image.authors="c3nav team"

ENV DEBIAN_FRONTEND noninteractive

RUN --mount=type=cache,target=/var/cache/apt,id=apt_$TARGETARCH --mount=type=tmpfs,target=/var/lib/apt/lists \
    rm /etc/apt/apt.conf.d/docker-clean && \
    apt-get update && apt-get install -y --no-install-recommends \
    python3.14 \
    libpython3.14 \
    python3.14-venv \
    python3-pip \
    libpq5 \
    postgresql-client-18 \
    curl \
    libpcre2-posix3 \
    librsvg2-2 \
    librsvg2-bin \
    gir1.2-rsvg-2.0 \
    libcairo2 \
    libgirepository-2.0-dev \
    libmemcached11t64 \
    gettext \
    tzdata \
    ca-certificates \
    zstd \
    libspatialindex-dev \
    libcrypt1
ENV PATH="/usr/lib/postgresql/18/bin/:$PATH"


FROM base as builder
RUN --mount=type=cache,target=/var/cache/apt,id=apt_$TARGETARCH --mount=type=tmpfs,target=/var/lib/apt/lists \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3.14-dev \
    libpcre2-dev \
    libpq-dev \
    libcairo2-dev \
    libgirepository1.0-dev \
    libmemcached-dev \
    libcrypt-dev


RUN mkdir /app
WORKDIR /app

RUN --mount=type=cache,target=/pip-cache \
    --mount=type=bind,source=/src/requirements,target=/app/requirements \
    python3.14 -m venv env && \
    . /app/env/bin/activate && \
    pip install --cache-dir /pip-cache --upgrade pip wheel && \
    pip install --cache-dir /pip-cache \
    -r requirements/production.txt \
    -r requirements/htmlmin.txt \
    -r requirements/postgres.txt \
    -r requirements/redis.txt \
    -r requirements/memcached.txt \
    -r requirements/rsvg-pygobject.txt \
    -r requirements/sentry.txt \
    -r requirements/metrics.txt \
    -r requirements/uwu.txt \
    -r requirements/sso.txt \
    -r requirements/server-asgi.txt && \
    pip install --cache-dir /pip-cache uwsgi django_extensions

FROM base as final
ARG COMMIT
RUN groupadd -r -g 500 c3nav && useradd -r -u 500 -g 500 -G www-data c3nav
RUN mkdir /data /etc/c3nav && chown -R c3nav:c3nav /data /etc/c3nav
VOLUME /data

COPY --chown=500:500 /src /app
COPY --from=builder --chown=500:500 /app/env /app/env
COPY --chown=root:root --chmod=0755 /docker/entrypoint.sh /usr/bin/entrypoint

ENV C3NAV_DEBUG="" \
    C3NAV_LOGLEVEL="INFO" \
    C3NAV_DATA_DIR="/data" \
    C3NAV_AUTOMIGRATE="yes" \
    C3NAV_VERSION="${COMMIT}" \
    MPLBACKEND="agg" \
    UWSGI_WORKERS="4" \
    PATH="/app/env/bin/:$PATH"

USER c3nav
WORKDIR /app

RUN /app/env/bin/python manage.py makemessages --ignore "site-packages" -l en_UW && \
    /app/env/bin/python genuwu.py && \
    /app/env/bin/python manage.py compilemessages --ignore "site-packages" && \
    /app/env/bin/python manage.py collectstatic -l --no-input && \
    /app/env/bin/python manage.py compress && \
    rm -r /data/*

EXPOSE 8000 5000
#HEALTHCHECK --start-period=5s --interval=10s --timeout=1s CMD curl -f http://localhost:8000/check || exit 1
ENTRYPOINT ["/usr/bin/entrypoint"]
CMD ["web"]
