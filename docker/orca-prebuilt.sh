#!/bin/sh
# Invoked ONLY inside the Docker build stage. No host AppImage installation.
set -eu
[ "$1" = amd64 ] || { echo 'Orca prebuilt supports amd64 only; use ORCA_SOURCE=source' >&2; exit 2; }
version=2.4.2
revision=8500fcdccaa10b5099ac20d252af3a7c560046f1
sha256=d12fb8c8eac1aecd2dfb6377acd48f994f8fa439ed5292fa532dd82880f029fd
asset=OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.4.2.AppImage
mkdir -p /work/orca-prebuilt /out/opt /out/usr/local/bin
cd /work/orca-prebuilt
curl --fail --location --retry 3 --output "$asset" \
  "https://github.com/OrcaSlicer/OrcaSlicer/releases/download/v${version}/${asset}"
printf '%s  %s\n' "$sha256" "$asset" | sha256sum --check --strict -
chmod 0755 "$asset"
./"$asset" --appimage-extract
# Keep upstream AppRun, resources, private libraries and environment helper intact.
test -x squashfs-root/AppRun
test -x squashfs-root/bin/orca-slicer
mv squashfs-root /out/opt/orca-stable
printf '#!/bin/sh\nexec /opt/orca-stable/AppRun "$@"\n' > /out/usr/local/bin/orca-slicer-stable
chmod 0755 /out/usr/local/bin/orca-slicer-stable
ln -s orca-slicer-stable /out/usr/local/bin/orca-slicer
printf '%s\n' "$revision" > /out/orca-stable-source-revision
printf 'channel=stable\nsource=prebuilt\nversion=%s\nrevision=%s\narch=amd64\nsha256=%s\n' \
  "$version" "$revision" "$sha256" > /out/orca-stable-build-info
rm -f "$asset"
