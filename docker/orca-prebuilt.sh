#!/bin/sh
# Invoked ONLY inside the Docker build stage. No host AppImage installation.
# OrcaSlicer is never built from source: each channel installs the pinned official
# prebuilt Linux release for the target architecture, verified by SHA256 before
# extraction. Upstream publishes both x86_64 and aarch64 AppImages; Docker's
# TARGETARCH spells them amd64 and arm64, so arm64 selects the aarch64 asset.
# Any other architecture (for example arm/v7, for which upstream ships no Linux
# build) fails closed.
#   orca-prebuilt.sh stable|alpha amd64|arm64
set -eu
channel=${1:-}
arch=${2:-}
case "$arch" in
    amd64|arm64) ;;
    *) echo "Orca prebuilt supports amd64 and arm64 only (got '${arch}')" >&2; exit 2 ;;
esac
case "$channel" in
    stable)
        # Print Buddy ships OrcaSlicer v2.5.0-alpha (#356): it is the first release whose
        # BBL vendor profiles cover the H2C and A2L, and the profiles pipeline reads its
        # packed preset caches (profiles/<Vendor>.opc) directly. There is no newer
        # upstream release, so the alpha channel below currently pins the same build;
        # the channels diverge again when upstream publishes a newer alpha.
        version=2.5.0-alpha
        revision=3880f2c58ec392ed2bd5938ab31c9c7c496c0eb2
        sha256_amd64=386a5ef38991a4fc32ae2e35ee4261bea43d983683ac675a2c2e2395ab2bc7bb
        sha256_arm64=b64c705537a80ca0f4a5d0b51fa21d1f789191141f54b7f3599d2f2b9bfad0be
        asset_amd64=OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.5.0-alpha.AppImage
        asset_arm64=OrcaSlicer_Linux_AppImage_Ubuntu2404_aarch64_V2.5.0-alpha.AppImage
        ;;
    alpha)
        version=2.5.0-alpha
        revision=3880f2c58ec392ed2bd5938ab31c9c7c496c0eb2
        sha256_amd64=386a5ef38991a4fc32ae2e35ee4261bea43d983683ac675a2c2e2395ab2bc7bb
        sha256_arm64=b64c705537a80ca0f4a5d0b51fa21d1f789191141f54b7f3599d2f2b9bfad0be
        asset_amd64=OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.5.0-alpha.AppImage
        asset_arm64=OrcaSlicer_Linux_AppImage_Ubuntu2404_aarch64_V2.5.0-alpha.AppImage
        ;;
    *) echo 'usage: orca-prebuilt.sh stable|alpha amd64|arm64' >&2; exit 2 ;;
esac
# The source revision is per channel, shared by both architectures; the asset
# name and SHA256 are per architecture.
case "$arch" in
    amd64) sha256=$sha256_amd64; asset=$asset_amd64 ;;
    arm64) sha256=$sha256_arm64; asset=$asset_arm64 ;;
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
printf 'channel=%s\nsource=prebuilt\nversion=%s\nrevision=%s\narch=%s\nsha256=%s\n' \
  "$channel" "$version" "$revision" "$arch" "$sha256" > "/out/orca-$channel-build-info"
rm -f "$asset"
