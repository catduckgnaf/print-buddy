#!/bin/sh
# Invoked ONLY inside the Docker build stage. No host AppImage installation.
# OrcaSlicer is never built from source: each channel installs the pinned official
# prebuilt Linux release, verified by SHA256 before extraction.
#   orca-prebuilt.sh stable|alpha amd64
set -eu
channel=${1:-}
arch=${2:-}
[ "$arch" = amd64 ] || { echo 'Orca prebuilt supports amd64 only' >&2; exit 2; }
case "$channel" in
    stable)
        version=2.4.2
        revision=8500fcdccaa10b5099ac20d252af3a7c560046f1
        sha256=d12fb8c8eac1aecd2dfb6377acd48f994f8fa439ed5292fa532dd82880f029fd
        asset=OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.4.2.AppImage
        ;;
    alpha)
        version=2.5.0-alpha
        revision=3880f2c58ec392ed2bd5938ab31c9c7c496c0eb2
        sha256=386a5ef38991a4fc32ae2e35ee4261bea43d983683ac675a2c2e2395ab2bc7bb
        asset=OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.5.0-alpha.AppImage
        ;;
    *) echo 'usage: orca-prebuilt.sh stable|alpha amd64' >&2; exit 2 ;;
esac
mkdir -p "/work/orca-prebuilt-$channel" /out/opt /out/usr/local/bin
cd "/work/orca-prebuilt-$channel"
curl --fail --location --retry 3 --output "$asset" \
  "https://github.com/OrcaSlicer/OrcaSlicer/releases/download/v${version}/${asset}"
printf '%s  %s\n' "$sha256" "$asset" | sha256sum --check --strict -
chmod 0755 "$asset"
./"$asset" --appimage-extract
# Keep upstream AppRun, resources, private libraries and environment helper intact.
test -x squashfs-root/AppRun
test -x squashfs-root/bin/orca-slicer
mv "squashfs-root" "/out/opt/orca-$channel"
# The alpha AppImage extracts with directories the runtime user cannot traverse
# (stat on bin/orca-slicer failed with EACCES in hosted validation); normalize the
# extracted tree to world-readable/traversable without changing upstream files.
chmod -R a+rX "/out/opt/orca-$channel"
printf '#!/bin/sh\nexec /opt/orca-%s/AppRun "$@"\n' "$channel" > "/out/usr/local/bin/orca-slicer-$channel"
chmod 0755 "/out/usr/local/bin/orca-slicer-$channel"
if [ "$channel" = stable ]; then
  ln -s orca-slicer-stable /out/usr/local/bin/orca-slicer
fi
printf '%s\n' "$revision" > "/out/orca-$channel-source-revision"
printf 'channel=%s\nsource=prebuilt\nversion=%s\nrevision=%s\narch=amd64\nsha256=%s\n' \
  "$channel" "$version" "$revision" "$sha256" > "/out/orca-$channel-build-info"
rm -f "$asset"
