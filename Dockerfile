# syntax=docker/dockerfile:1
# Source-build variant replacing the reviewed zaheria985 Docker contribution's
# binary download approach. See docs/DOCKER-117-PROGRESS.md for attribution.
FROM debian:13-slim AS orca-base
ARG WITH_ORCA=false
ARG ORCA_STABLE_REF=8500fcdccaa10b5099ac20d252af3a7c560046f1
ARG ORCA_ALPHA_REF=3880f2c58ec392ed2bd5938ab31c9c7c496c0eb2
# Parallel compile jobs: auto (memory-aware, below the CPU count; see docker/orca-build-jobs.sh)
# or an explicit 1-64. Applied to every dependency and to the application build.
ARG ORCA_BUILD_JOBS=auto
ARG ORCA_BUILD_MEM_PER_JOB_MIB=2560
ARG ORCA_CCACHE_MAXSIZE=5G
# The fixed CMake option set below. Rename it when those options change.
ARG ORCA_BUILD_PROFILE=release-static-fhs-nopch
ARG TARGETARCH
ENV DEBIAN_FRONTEND=noninteractive
COPY docker/orca-build-jobs.sh /usr/local/bin/orca-build-jobs
COPY docker/orca-build.sh /usr/local/bin/orca-build
RUN mkdir -p /out && chmod +x /usr/local/bin/orca-build-jobs /usr/local/bin/orca-build && \
    case "$WITH_ORCA" in true|false) ;; *) echo 'WITH_ORCA must be true or false' >&2; exit 2;; esac && \
    orca-build-jobs "$ORCA_BUILD_JOBS" >/dev/null && \
    if [ "$WITH_ORCA" = true ]; then \
      apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates git cmake ninja-build build-essential autoconf automake \
        libtool pkg-config gettext texinfo curl wget file m4 ccache \
        eglexternalplatform-dev extra-cmake-modules libcurl4-openssl-dev \
        libdbus-1-dev libglew-dev libgstreamerd-3-dev libgtk-3-dev \
        libmspack-dev libsecret-1-dev libspnav-dev libssl-dev libudev-dev \
        libwebkit2gtk-4.1-dev gstreamer1.0-gtk3 && \
      rm -rf /var/lib/apt/lists/*; \
    fi

FROM orca-base AS orca-stable
ARG WITH_ORCA=false
ARG ORCA_STABLE_REF=8500fcdccaa10b5099ac20d252af3a7c560046f1
ARG ORCA_BUILD_JOBS=auto
ARG ORCA_CCACHE_MAXSIZE=5G
ARG ORCA_BUILD_PROFILE=release-static-fhs-nopch
ARG TARGETARCH
RUN --mount=type=cache,id=print-buddy-orca-${TARGETARCH}-stable-${ORCA_STABLE_REF}-${ORCA_BUILD_PROFILE},target=/cache,sharing=locked \
    if [ "$WITH_ORCA" = true ]; then \
      /usr/local/bin/orca-build stable "$ORCA_STABLE_REF" "$ORCA_BUILD_JOBS" \
        "$ORCA_CCACHE_MAXSIZE" "$ORCA_BUILD_PROFILE" "$TARGETARCH"; \
    fi

FROM orca-base AS orca-alpha
ARG WITH_ORCA=false
ARG ORCA_ALPHA_REF=3880f2c58ec392ed2bd5938ab31c9c7c496c0eb2
ARG ORCA_BUILD_JOBS=auto
ARG ORCA_CCACHE_MAXSIZE=5G
ARG ORCA_BUILD_PROFILE=release-static-fhs-nopch
ARG TARGETARCH
RUN --mount=type=cache,id=print-buddy-orca-${TARGETARCH}-alpha-${ORCA_ALPHA_REF}-${ORCA_BUILD_PROFILE},target=/cache,sharing=locked \
    if [ "$WITH_ORCA" = true ]; then \
      /usr/local/bin/orca-build alpha "$ORCA_ALPHA_REF" "$ORCA_BUILD_JOBS" \
        "$ORCA_CCACHE_MAXSIZE" "$ORCA_BUILD_PROFILE" "$TARGETARCH"; \
    fi

FROM debian:13-slim AS bambu-build
# Bambu Studio is the default slicer for Bambu Lab printers. Built from pinned source like Orca:
# never an AppImage, never patched. WITH_BAMBU=false omits it and Bambu Lab slicing fails closed.
ARG WITH_BAMBU=false
ARG BAMBU_REF=926a7192574bcb9b3a732e1ec59a46d79cb45466
ARG BAMBU_BUILD_PROFILE=release-static-fhs
ARG ORCA_BUILD_JOBS=auto
ARG ORCA_BUILD_MEM_PER_JOB_MIB=2560
ARG ORCA_CCACHE_MAXSIZE=5G
ARG TARGETARCH
ENV DEBIAN_FRONTEND=noninteractive
COPY docker/orca-build-jobs.sh /usr/local/bin/orca-build-jobs
RUN mkdir -p /out && chmod +x /usr/local/bin/orca-build-jobs && \
    case "$WITH_BAMBU" in true|false) ;; *) echo 'WITH_BAMBU must be true or false' >&2; exit 2;; esac
RUN --mount=type=cache,id=print-buddy-bambu-${TARGETARCH}-${BAMBU_REF}-${BAMBU_BUILD_PROFILE},target=/cache,sharing=locked \
    if [ "$WITH_BAMBU" = true ]; then \
      apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates git cmake ninja-build build-essential autoconf automake \
        libtool pkg-config gettext texinfo curl wget file m4 ccache nasm yasm \
        eglexternalplatform-dev extra-cmake-modules libcurl4-openssl-dev \
        libdbus-1-dev libglew-dev libgstreamerd-3-dev libgtk-3-dev libosmesa6-dev \
        libgl1-mesa-dev libxkbcommon-dev libunwind-dev libx264-dev libbz2-dev \
        libmspack-dev libsecret-1-dev libssl-dev libudev-dev \
        libwebkit2gtk-4.1-dev gstreamer1.0-gtk3 && \
      ref="$BAMBU_REF" && \
      jobs="$(orca-build-jobs "$ORCA_BUILD_JOBS")" && \
      export CMAKE_BUILD_PARALLEL_LEVEL="$jobs" CC=/usr/lib/ccache/gcc CXX=/usr/lib/ccache/g++ \
        CCACHE_DIR=/cache/ccache CCACHE_MAXSIZE="$ORCA_CCACHE_MAXSIZE" && \
      toolchain="$(. /etc/os-release && printf '%s\n' "$ID-$VERSION_ID" "$(gcc -dumpfullversion)" \
        "$(cmake --version | head -n 1)" "$CC" "$CXX" "$BAMBU_BUILD_PROFILE" | sha256sum | cut -c1-16)" && \
      if [ "$(cat /cache/toolchain 2>/dev/null)" != "$toolchain" ]; then \
        rm -rf /cache/bambu/deps/build /cache/bambu/build && printf '%s\n' "$toolchain" > /cache/toolchain; \
      fi && \
      if [ "$(git -C /cache/bambu rev-parse HEAD 2>/dev/null)" != "$ref" ]; then \
        rm -rf /cache/bambu && git init /cache/bambu && \
        git -C /cache/bambu remote add origin https://github.com/bambulab/BambuStudio.git && \
        git -C /cache/bambu fetch --depth 1 origin "$ref" && git -C /cache/bambu checkout --detach FETCH_HEAD; \
      fi && \
      cd /cache/bambu && \
      test "$(git rev-parse HEAD)" = "$ref" && \
      test -z "$(git status --porcelain --untracked-files=no)" && \
      cmake -S deps -B deps/build -G Ninja -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DDEP_WX_GTK3=ON && \
      cmake --build deps/build --parallel 1 && \
      cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
        -DCMAKE_PREFIX_PATH="$PWD/deps/build/destdir/usr/local" \
        -DSLIC3R_STATIC=1 -DSLIC3R_GTK=3 -DSLIC3R_FHS=ON -DSLIC3R_PCH=OFF \
        -DBBL_RELEASE_TO_PUBLIC=1 -DBBL_INTERNAL_TESTING=0 -DCMAKE_INSTALL_PREFIX=/usr && \
      cmake --build build --parallel "$jobs" --target BambuStudio && \
      DESTDIR=/out cmake --install build && \
      test -x /out/usr/bin/bambu-studio && \
      printf '%s\n' "$ref" > /out/bambu-source-revision && \
      printf 'revision=%s\narch=%s\nprofile=%s\ntoolchain=%s\njobs=%s\n' \
        "$ref" "$TARGETARCH" "$BAMBU_BUILD_PROFILE" "$toolchain" "$jobs" > /out/bambu-build-info && \
      ccache --show-stats; \
    fi

FROM debian:13-slim AS runtime
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv ca-certificates ffmpeg xvfb xauth tini openscad \
    libwebkit2gtk-4.1-0 libgstreamer1.0-0 libgstreamer-plugins-base1.0-0 \
    libgtk-3-0t64 libglew2.2 libsecret-1-0 libspnav0 libgstreamerd-3-0 \
    libosmesa6 libunwind8 libx264-164 \
    fonts-liberation && rm -rf /var/lib/apt/lists/* && \
    python3 -m venv /opt/venv && \
    useradd --uid 1000 --create-home buddy
COPY --from=orca-stable /out/ /
COPY --from=orca-alpha /out/ /
COPY --from=bambu-build /out/ /
ARG APP_CHANNEL=development
RUN case "$APP_CHANNEL" in stable|development) ;; *) echo 'APP_CHANNEL must be stable or development' >&2; exit 2;; esac
LABEL org.print-buddy.app-channel=$APP_CHANNEL
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PRINT_BUDDY_CONFIG=/app/config/docker.yaml HOME=/data \
    PRINT_BUDDY__BOT__MODE=standalone PRINT_BUDDY_ORCA_CHANNEL=stable
RUN mkdir -p /data/hermes/state /data/archive /data/records /data/cache && \
    chown -R buddy:buddy /data && chmod +x /app/docker/entrypoint.sh
USER buddy
ENTRYPOINT ["/usr/bin/tini", "--", "/app/docker/entrypoint.sh"]
CMD ["python3", "-m", "print_buddy.bot"]
