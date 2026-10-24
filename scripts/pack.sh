#!/usr/bin/env bash
# Packs the committed plugin without changing tracked files. RELEASE_SUFFIX, for example -dev12, is
# appended to manifest.yaml's version for a staging build; without it, the package is the production
# candidate. Dify versions take one suffix without dots, of at most 16 characters, that Python's version
# rules (PEP 440) also accept, because Dify's API checks them: -dev12, not -staging12. DIFY_CLI is the
# Dify plugin CLI, and the package is written to PACK_DESTINATION.
set -euo pipefail
: "${PACK_DESTINATION:?}" "${DIFY_CLI:?}"

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
git archive HEAD | tar -x -C "$work"
version="$(sed -n 's/^version: //p' "$work/manifest.yaml")${RELEASE_SUFFIX:-}"
perl -pi -e "s/^version: .*/version: $version/ if \$. == 1" "$work/manifest.yaml"

mkdir -p "$PACK_DESTINATION"
package="$PACK_DESTINATION/photon-$version.difypkg"
"$DIFY_CLI" plugin package "$work" -o "$package"

# Check the packed version.
unzip -p "$package" manifest.yaml | grep -qx "version: $version"
echo "Packed $package"
