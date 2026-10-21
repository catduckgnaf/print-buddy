FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    ORCA_VERSION=2.4.2

# System deps for Python, OrcaSlicer CLI (AppImage extract), ffmpeg, xvfb for headless
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-venv \
        ca-certificates \
        curl \
        wget \
        ffmpeg \
        xvfb \
        libwebkit2gtk-4.1-0 \
        libgstreamer1.0-0 \
        libgstreamer-plugins-base1.0-0 \
        libgtk-3-0 \
        libfuse2 \
        fonts-liberation \
        && rm -rf /var/lib/apt/lists/*

# Pin and extract OrcaSlicer AppImage matching the CI Flathub generation (v2.4.2)
RUN mkdir -p /opt/orcaslicer && cd /opt/orcaslicer && \
    curl -fsSL -o OrcaSlicer.AppImage \
        "https://github.com/OrcaSlicer/OrcaSlicer/releases/download/v${ORCA_VERSION}/OrcaSlicer_Linux_AppImage_Ubuntu2404_V${ORCA_VERSION}.AppImage" && \
    chmod +x OrcaSlicer.AppImage && \
    ./OrcaSlicer.AppImage --appimage-extract && \
    mv squashfs-root/* . && rmdir squashfs-root && \
    ln -sf /opt/orcaslicer/AppRun /usr/local/bin/orca-slicer && \
    rm -f OrcaSlicer.AppImage && \
    orca-slicer --help >/dev/null 2>&1 || true

WORKDIR /app

# Runtime Python deps (core + previews + websockets)
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Application code
COPY . .

# Docker-specific defaults (Orca binary path, container paths).
# Scalars can be overridden with PRINT_BUDDY__SECTION__KEY.
# YAML is the default; the legacy TOML file remains selectable with PRINT_BUDDY_CONFIG.
ENV PRINT_BUDDY_CONFIG=/app/config/docker.yaml \
    HOME=/data

# Ensure data dirs exist at runtime
RUN mkdir -p /data/hermes /data/archive /data/records /data/cache

# Headless wrapper for the Moonraker listener
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python3", "-m", "print_buddy.hermes.moonraker_event_listener"]
