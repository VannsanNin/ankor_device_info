#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
    cat <<'EOF'
Generate a static APT repository from local .deb files.

Usage:
  ./scripts/publish_apt_repo.sh [deb_dir] [repo_dir]

Arguments:
  deb_dir   Directory containing .deb files (default: ./dist)
  repo_dir  Output repository directory (default: ./apt-repo)

Optional environment variables:
  DIST_NAME      (default: stable)
  COMPONENT      (default: main)
  ARCHITECTURES  (default: "amd64 all")
  ORIGIN         (default: Ankor)
  LABEL          (default: Ankor Device Info)
  DESCRIPTION    (default: APT repository for Ankor Device Info)
  GPG_KEY_ID     (if set, generates Release.gpg and InRelease)
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

require_cmd dpkg-scanpackages
require_cmd apt-ftparchive
require_cmd gzip
require_cmd xz

DEB_DIR="${1:-$ROOT_DIR/dist}"
REPO_DIR="${2:-$ROOT_DIR/apt-repo}"
DIST_NAME="${DIST_NAME:-stable}"
COMPONENT="${COMPONENT:-main}"
ARCHITECTURES="${ARCHITECTURES:-amd64 all}"
ORIGIN="${ORIGIN:-Ankor}"
LABEL="${LABEL:-Ankor Device Info}"
DESCRIPTION="${DESCRIPTION:-APT repository for Ankor Device Info}"
GPG_KEY_ID="${GPG_KEY_ID:-}"

if [[ ! -d "$DEB_DIR" ]]; then
    echo "Input deb_dir does not exist: $DEB_DIR" >&2
    exit 1
fi

shopt -s nullglob
debs=("$DEB_DIR"/*.deb)
shopt -u nullglob
if [[ "${#debs[@]}" -eq 0 ]]; then
    echo "No .deb files found in $DEB_DIR" >&2
    exit 1
fi

POOL_DIR="$REPO_DIR/pool/$COMPONENT"
DIST_DIR="$REPO_DIR/dists/$DIST_NAME"

rm -rf "$POOL_DIR" "$DIST_DIR"
mkdir -p "$POOL_DIR"
mkdir -p "$DIST_DIR/$COMPONENT"

cp "${debs[@]}" "$POOL_DIR/"

TMP_PACKAGES_FILE="$(mktemp)"
trap 'rm -f "$TMP_PACKAGES_FILE"' EXIT
(
    cd "$REPO_DIR"
    dpkg-scanpackages --multiversion "pool/$COMPONENT" /dev/null > "$TMP_PACKAGES_FILE"
)

for arch in $ARCHITECTURES; do
    BINARY_DIR="$DIST_DIR/$COMPONENT/binary-$arch"
    mkdir -p "$BINARY_DIR"
    cp "$TMP_PACKAGES_FILE" "$BINARY_DIR/Packages"
    gzip -9c "$TMP_PACKAGES_FILE" > "$BINARY_DIR/Packages.gz"
    xz -9c "$TMP_PACKAGES_FILE" > "$BINARY_DIR/Packages.xz"
done

(
    cd "$REPO_DIR"
    apt-ftparchive \
        -o "APT::FTPArchive::Release::Origin=$ORIGIN" \
        -o "APT::FTPArchive::Release::Label=$LABEL" \
        -o "APT::FTPArchive::Release::Suite=$DIST_NAME" \
        -o "APT::FTPArchive::Release::Codename=$DIST_NAME" \
        -o "APT::FTPArchive::Release::Architectures=$ARCHITECTURES" \
        -o "APT::FTPArchive::Release::Components=$COMPONENT" \
        -o "APT::FTPArchive::Release::Description=$DESCRIPTION" \
        release "dists/$DIST_NAME" > "dists/$DIST_NAME/Release"
)

if [[ -n "$GPG_KEY_ID" ]]; then
    require_cmd gpg
    gpg --batch --yes --local-user "$GPG_KEY_ID" --detach-sign \
        --output "$DIST_DIR/Release.gpg" "$DIST_DIR/Release"
    gpg --batch --yes --local-user "$GPG_KEY_ID" --clearsign \
        --output "$DIST_DIR/InRelease" "$DIST_DIR/Release"
fi

echo "APT repository generated in: $REPO_DIR"
echo "Distribution: $DIST_NAME"
echo "Component:    $COMPONENT"
echo "Architectures: $ARCHITECTURES"
if [[ -n "$GPG_KEY_ID" ]]; then
    echo "Signed with key: $GPG_KEY_ID"
else
    echo "Unsigned repository (use [trusted=yes] on clients, or set GPG_KEY_ID)."
fi
