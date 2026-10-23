#!/bin/sh
# Install the pinned OrcaSlicer AppImage for one channel and architecture into $3.
#   install-orcaslicer.sh <channel: alpha|stable> <arch: amd64|arm64> <dest> [cache dir]
# The AppImage is unpacked with unsquashfs, never executed, so the build stage may run on
# any platform. A file named like the asset in [cache dir] is used instead of downloading;
# its SHA-256 is checked either way.
set -eu

channel=$1 arch=$2 dest=$3 cache=${4:-}
here=$(dirname "$0")
# shellcheck source=docker/orcaslicer.lock
. "$here/orcaslicer.lock"

prefix=$(echo "ORCA_${channel}" | tr '[:lower:]' '[:upper:]')
upper_arch=$(echo "$arch" | tr '[:lower:]' '[:upper:]')
eval "version=\${${prefix}_VERSION:-}"
eval "asset=\${${prefix}_${upper_arch}_ASSET:-}"
eval "sha=\${${prefix}_${upper_arch}_SHA256:-}"
if [ -z "$version" ] || [ -z "$asset" ] || [ -z "$sha" ]; then
    echo "install-orcaslicer: channel '$channel' has no pinned $arch release in orcaslicer.lock" >&2
    exit 1
fi
if [ -n "${EXPECT_VERSION:-}" ] && [ "$EXPECT_VERSION" != "$version" ]; then
    echo "install-orcaslicer: ORCA_VERSION=$EXPECT_VERSION but orcaslicer.lock pins $version for '$channel'" >&2
    exit 1
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
image="$work/$asset"
if [ -n "$cache" ] && [ -f "$cache/$asset" ]; then
    cp "$cache/$asset" "$image"
else
    curl -fsSL --retry 3 -o "$image" \
        "https://github.com/OrcaSlicer/OrcaSlicer/releases/download/v${version}/${asset}"
fi
echo "$sha  $image" | sha256sum -c -

# A type 2 AppImage is an ELF runtime followed by a squashfs image that starts where the
# ELF section headers end.
offset=$(python3 -c '
import struct, sys
head = open(sys.argv[1], "rb").read(64)
assert head[:4] == b"\x7fELF" and head[4] == 2, "not a 64-bit ELF AppImage"
shoff, = struct.unpack_from("<Q", head, 0x28)
shentsize, shnum = struct.unpack_from("<HH", head, 0x3A)
print(shoff + shentsize * shnum)
' "$image")
unsquashfs -quiet -no-progress -offset "$offset" -dest "$work/root" "$image" >/dev/null
mkdir -p "$(dirname "$dest")"
rm -rf "$dest"
mv "$work/root" "$dest"
# Upstream packs some directories as 0700; the image runs OrcaSlicer as an unprivileged user.
chmod -R a+rX,go-w "$dest"
test -x "$dest/AppRun"
printf 'ORCA_CHANNEL=%s\nORCA_VERSION=%s\nORCA_ASSET=%s\nORCA_SHA256=%s\n' \
    "$channel" "$version" "$asset" "$sha" > "$dest/PRINT_BUDDY_ORCA_PIN"
echo "OrcaSlicer $version ($channel, $arch) installed in $dest"
