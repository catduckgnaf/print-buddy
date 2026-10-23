# syntax=docker/dockerfile:1
# Print Buddy release image: Print Buddy, a pinned OrcaSlicer CLI and their runtime, nothing else.
# Klipper/Moonraker/Fluidd, OctoPrint and Spoolman are external endpoints. Hermes is not installed.
# Build and run notes: docs/DOCKER.md.

ARG BASE_IMAGE=ubuntu:24.04

# Optional local copies of the pinned OrcaSlicer AppImages, for offline or cached builds:
#   docker buildx build --build-context orca-cache=/dir/with/appimages .
# Files are still checked against docker/orcaslicer.lock.
FROM scratch AS orca-cache

# OrcaSlicer is unpacked, never executed, so this stage runs natively on the build host.
FROM --platform=$BUILDPLATFORM ${BASE_IMAGE} AS orca
ARG TARGETARCH
# alpha = 2.5.0-alpha (default). stable = 2.5.0 once it is pinned in docker/orcaslicer.lock.
ARG ORCA_CHANNEL=alpha
# Optional: when set (CI sets it from the lock for the image label), it must match the lock.
ARG ORCA_VERSION=
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl python3 squashfs-tools \
    && rm -rf /var/lib/apt/lists/*
COPY docker/orcaslicer.lock docker/install-orcaslicer.sh /build/
RUN --mount=type=bind,from=orca-cache,target=/cache \
    EXPECT_VERSION="$ORCA_VERSION" sh /build/install-orcaslicer.sh "$ORCA_CHANNEL" "$TARGETARCH" /opt/orcaslicer /cache

FROM ${BASE_IMAGE} AS runtime
ARG ORCA_CHANNEL=alpha
ARG ORCA_VERSION=
ARG PRINT_BUDDY_VERSION=dev

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/opt/venv/bin:$PATH

# Python, the OrcaSlicer GUI toolkit it links even in CLI mode, a virtual display, and the
# tools Print Buddy shells out to (ffmpeg/ffprobe, curl/jq for bin/moonrakerctl, ssh for timelapses).
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-venv \
        ca-certificates \
        tini \
        bash \
        curl \
        jq \
        openssh-client \
        ffmpeg \
        xvfb \
        xauth \
        libgl1 \
        libegl1 \
        libglu1-mesa \
        libwebkit2gtk-4.1-0 \
        libgstreamer1.0-0 \
        libgstreamer-plugins-base1.0-0 \
        libgtk-3-0 \
        libsecret-1-0 \
        fonts-liberation \
        tzdata \
    && rm -rf /var/lib/apt/lists/*
# uid/gid 1000 belong to the image's own unprivileged user, not the base image's ubuntu user
RUN if id ubuntu >/dev/null 2>&1; then userdel --remove ubuntu; fi \
    && groupadd --gid 1000 printbuddy \
    && useradd --uid 1000 --gid 1000 --no-create-home --home-dir /data/cache/home --shell /usr/sbin/nologin printbuddy

COPY --from=orca /opt/orcaslicer /opt/orcaslicer
RUN ln -s /opt/orcaslicer/AppRun /usr/local/bin/orca-slicer

WORKDIR /app
COPY requirements.txt .
RUN python3 -m venv /opt/venv && pip install --no-cache-dir -r requirements.txt

# Application code (.dockerignore keeps tests, docs, Hermes profile templates and local config out)
COPY . .
RUN python3 -m compileall -q print_buddy \
    && install -m 0755 docker/entrypoint.sh /usr/local/bin/print-buddy-entrypoint \
    && mkdir -p /data/hermes /data/archive /data/records /data/cache/home \
    && chown -R printbuddy:printbuddy /data

# Docker-specific defaults (Orca binary path, container paths).
# Scalars can be overridden with PRINT_BUDDY__SECTION__KEY.
# YAML is the default; the legacy TOML file remains selectable with PRINT_BUDDY_CONFIG.
ENV PRINT_BUDDY_CONFIG=/app/config/docker.yaml
ENV HOME=/data/cache/home \
    TMPDIR=/data/cache/tmp \
    PYTHONPATH=/app \
    DISPLAY=:99 \
    PRINT_BUDDY_VERSION=${PRINT_BUDDY_VERSION} \
    ORCA_CHANNEL=${ORCA_CHANNEL}

LABEL org.opencontainers.image.title="Print Buddy" \
      org.opencontainers.image.description="Discord-driven 3D printing pipeline with a pinned OrcaSlicer CLI; printers and Spoolman are external services" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${PRINT_BUDDY_VERSION}" \
      io.print-buddy.orcaslicer.channel="${ORCA_CHANNEL}" \
      io.print-buddy.orcaslicer.version="${ORCA_VERSION}"

USER 1000:1000
# OrcaSlicer writes its log into the current directory and /app is read-only, so `docker exec`
# sessions (doctor, health check) start in /tmp; the entrypoint moves the runtime to the cache volume.
WORKDIR /tmp

# Healthy = settings load, the slicer is installed, and the runtime's event loop wrote a heartbeat
# within the last 90 s from a live process (print_buddy/healthcheck.py). A powered-off printer is
# reported in the heartbeat but does not make the container unhealthy.
HEALTHCHECK --interval=30s --timeout=15s --start-period=60s --retries=3 \
    CMD ["python3", "-m", "print_buddy.healthcheck"]

ENTRYPOINT ["tini", "--", "print-buddy-entrypoint"]
# RUNTIME ENTRY POINT. The only place that names the process the container runs.
# Today: the Moonraker event listener. When standalone mode (#73) lands, replace this line with
# the standalone bot's module; it must call print_buddy.healthcheck.beat() like the listener does.
CMD ["python3", "-m", "print_buddy.hermes.moonraker_event_listener"]
