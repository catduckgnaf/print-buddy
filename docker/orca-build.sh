#!/bin/sh
# Build one pinned OrcaSlicer channel into its isolated /out directory.
set -eu
channel=$1
ref=$2
requested_jobs=$3
ccache_max=$4
profile=$5
arch=$6
case "$channel" in stable|alpha) ;; *) echo "channel must be stable or alpha" >&2; exit 2;; esac
jobs="$(orca-build-jobs "$requested_jobs")"
export CMAKE_BUILD_PARALLEL_LEVEL="$jobs" CC=/usr/lib/ccache/gcc CXX=/usr/lib/ccache/g++
export CCACHE_DIR=/cache/ccache CCACHE_MAXSIZE="$ccache_max"
toolchain="$(. /etc/os-release && printf '%s\n' "$ID-$VERSION_ID" "$(gcc -dumpfullversion)" \
  "$(cmake --version | head -n 1)" "$CC" "$CXX" "$profile" | sha256sum | cut -c1-16)"
if [ "$(cat /cache/toolchain 2>/dev/null)" != "$toolchain" ]; then
  rm -rf /cache/orca/deps/build /cache/orca/build
  printf '%s\n' "$toolchain" > /cache/toolchain
fi
if [ "$(git -C /cache/orca rev-parse HEAD 2>/dev/null)" != "$ref" ]; then
  rm -rf /cache/orca
  git init /cache/orca
  git -C /cache/orca remote add origin https://github.com/OrcaSlicer/OrcaSlicer.git
  git -C /cache/orca fetch --depth 1 origin "$ref"
  git -C /cache/orca checkout --detach FETCH_HEAD
fi
cd /cache/orca
test "$(git rev-parse HEAD)" = "$ref"
test -z "$(git status --porcelain --untracked-files=no)"
cmake -S deps -B deps/build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build deps/build --parallel 1
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DSLIC3R_STATIC=ON -DSLIC3R_FHS=ON -DSLIC3R_PCH=OFF \
  -DCMAKE_INSTALL_PREFIX="/opt/orca-$channel"
# Configuring does not compile the application. Install must only follow a
# successful bounded build (otherwise CMake cannot find src/orca-slicer).
cmake --build build --parallel "$jobs" --target OrcaSlicer
mkdir -p /out/usr/local/bin
DESTDIR=/out cmake --install build
binary="/out/opt/orca-$channel/bin/orca-slicer"
test -x "$binary"
printf '#!/bin/sh\nexec /opt/orca-%s/bin/orca-slicer "$@"\n' "$channel" > "/out/usr/local/bin/orca-slicer-$channel"
chmod 0755 "/out/usr/local/bin/orca-slicer-$channel"
# Only stable owns the generic name: alpha is copied last and must not take it over.
if [ "$channel" = stable ]; then ln -sf orca-slicer-stable /out/usr/local/bin/orca-slicer; fi
printf '%s\n' "$binary" > "/out/orca-$channel-binary-path"
printf '%s\n' "$ref" > "/out/orca-$channel-source-revision"
printf 'channel=%s\nrevision=%s\narch=%s\nprofile=%s\ntoolchain=%s\njobs=%s\n' \
  "$channel" "$ref" "$arch" "$profile" "$toolchain" "$jobs" > "/out/orca-$channel-build-info"
ccache --show-stats
