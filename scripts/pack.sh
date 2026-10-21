#!/usr/bin/env bash
# Packs the committed plugin for one release channel without changing tracked files.
# RELEASE_CHANNEL is staging or production. RELEASE_SUFFIX, for example -staging12, is appended
# to manifest.yaml's version; Dify versions take one suffix without dots, of at most 16 characters.
# The staging build defaults to Photon's staging API. DIFY_CLI is the Dify plugin CLI, and the
# package is written to PACK_DESTINATION.
set -euo pipefail
: "${RELEASE_CHANNEL:?}" "${PACK_DESTINATION:?}" "${DIFY_CLI:?}"

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
git archive HEAD | tar -x -C "$work"
version="$(sed -n 's/^version: //p' "$work/manifest.yaml")${RELEASE_SUFFIX:-}"
perl -pi -e "s/^version: .*/version: $version/ if \$. == 1" "$work/manifest.yaml"
case "$RELEASE_CHANNEL" in
  staging) perl -pi -e 's#^    default: https://api\.photon\.codes$#    default: https://api.staging.photon.codes#' "$work/provider/photon.yaml" ;;
  production) ;;
  *) echo "RELEASE_CHANNEL must be staging or production" >&2; exit 1 ;;
esac

mkdir -p "$PACK_DESTINATION"
package="$PACK_DESTINATION/photon-$version.difypkg"
"$DIFY_CLI" plugin package "$work" -o "$package"

# Check what was packed: the version, and the default environment of the channel.
origin=$([ "$RELEASE_CHANNEL" = staging ] && echo https://api.staging.photon.codes || echo https://api.photon.codes)
unzip -p "$package" manifest.yaml | grep -qx "version: $version"
unzip -p "$package" provider/photon.yaml | grep -qx "    default: $origin"
echo "Packed $package (default origin $origin)"
