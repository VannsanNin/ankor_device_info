#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
    cat <<'EOF'
Build a Debian package for this project.

Usage:
  ./scripts/build_deb.sh [version]

Version resolution order:
  1) First CLI argument
  2) PACKAGE_VERSION environment variable
  3) version in snap/snapcraft.yaml

Optional environment variables:
  PACKAGE_NAME   (default: ankor-device-info)
  DEB_ARCH       (default: all)
  DEB_MAINTAINER (default: Ankor Maintainers <noreply@example.com>)
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi

require_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "Missing required command: $1" >&2
        exit 1
    fi
}

extract_version_from_snapcraft() {
    local snapcraft_file="$ROOT_DIR/snap/snapcraft.yaml"
    if [[ ! -f "$snapcraft_file" ]]; then
        return 0
    fi

    awk -F': *' '/^version:/ {
        version=$2
        gsub(/["'\'']/, "", version)
        print version
        exit
    }' "$snapcraft_file"
}

escape_sed_replacement() {
    printf '%s' "$1" | sed -e 's/[\/&]/\\&/g'
}

require_cmd dpkg-deb
require_cmd install
require_cmd sed
require_cmd awk

PACKAGE_NAME="${PACKAGE_NAME:-ankor-device-info}"
VERSION="${1:-${PACKAGE_VERSION:-}}"
if [[ -z "$VERSION" ]]; then
    VERSION="$(extract_version_from_snapcraft)"
fi
if [[ -z "$VERSION" ]]; then
    echo "Version is required. Pass it as argument or set PACKAGE_VERSION." >&2
    exit 1
fi

ARCH="${DEB_ARCH:-all}"
MAINTAINER="${DEB_MAINTAINER:-Ankor Maintainers <noreply@example.com>}"

BUILD_ROOT="$ROOT_DIR/build/deb"
STAGE_DIR="$BUILD_ROOT/${PACKAGE_NAME}_${VERSION}"
DIST_DIR="$ROOT_DIR/dist"
OUTPUT_DEB="$DIST_DIR/${PACKAGE_NAME}_${VERSION}_${ARCH}.deb"

rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR/DEBIAN"
mkdir -p "$STAGE_DIR/usr/bin"
mkdir -p "$STAGE_DIR/usr/share/$PACKAGE_NAME"
mkdir -p "$STAGE_DIR/usr/share/applications"
mkdir -p "$STAGE_DIR/usr/share/icons/hicolor/scalable/apps"
mkdir -p "$STAGE_DIR/usr/share/doc/$PACKAGE_NAME"
mkdir -p "$DIST_DIR"

install -m 644 "$ROOT_DIR/main.py" "$STAGE_DIR/usr/share/$PACKAGE_NAME/main.py"
install -m 755 "$ROOT_DIR/packaging/deb/launcher.sh" "$STAGE_DIR/usr/bin/$PACKAGE_NAME"
install -m 644 "$ROOT_DIR/packaging/deb/ankor-device-info.desktop" \
    "$STAGE_DIR/usr/share/applications/$PACKAGE_NAME.desktop"
install -m 644 "$ROOT_DIR/snap/gui/ankor-device-info.svg" \
    "$STAGE_DIR/usr/share/icons/hicolor/scalable/apps/ankor-device-info.svg"
install -m 644 "$ROOT_DIR/README.md" "$STAGE_DIR/usr/share/doc/$PACKAGE_NAME/README.md"

INSTALLED_SIZE="$(du -ks "$STAGE_DIR/usr" | awk '{print $1}')"

sed \
    -e "s/@PACKAGE_NAME@/$(escape_sed_replacement "$PACKAGE_NAME")/g" \
    -e "s/@VERSION@/$(escape_sed_replacement "$VERSION")/g" \
    -e "s/@ARCH@/$(escape_sed_replacement "$ARCH")/g" \
    -e "s/@MAINTAINER@/$(escape_sed_replacement "$MAINTAINER")/g" \
    -e "s/@INSTALLED_SIZE@/$(escape_sed_replacement "$INSTALLED_SIZE")/g" \
    "$ROOT_DIR/packaging/deb/control.template" > "$STAGE_DIR/DEBIAN/control"

dpkg-deb --build --root-owner-group "$STAGE_DIR" "$OUTPUT_DEB"
echo "Built package: $OUTPUT_DEB"
