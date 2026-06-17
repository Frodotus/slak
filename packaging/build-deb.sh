#!/usr/bin/env bash
# Build a self-contained .deb for slak.
#
# The package bundles slak and all its Python dependencies into a private venv
# under /usr/lib/slak, with a /usr/bin/slak launcher. It depends only on the
# matching system CPython (python3.X) — no apt Python-library packages, so it is
# not affected by Debian/Ubuntu shipping older Textual etc.
#
# The bundle is tied to the build host's Python minor version and architecture
# (Pillow ships a compiled extension). Build it on / for the target's Ubuntu
# release. Usage:  packaging/build-deb.sh
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

version="$(python3 - <<'PY'
import tomllib
print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])
PY
)"
pyver="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"  # e.g. 3.14
pyfull="$(python3 -c 'import platform; print(platform.python_version())')"
arch="$(dpkg --print-architecture)"

pkg="slak"
stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
root="$stage/$pkg"
prefix="$root/usr/lib/slak"      # the bundled venv lives here

echo ">> building venv (python $pyfull, $arch)"
python3 -m venv "$prefix"
"$prefix/bin/pip" install --quiet --upgrade pip
"$prefix/bin/pip" install --quiet .

echo ">> trimming build-only cruft"
"$prefix/bin/pip" uninstall --quiet --yes pip setuptools wheel 2>/dev/null || true
rm -f "$prefix"/bin/pip* "$prefix"/bin/activate* "$prefix"/bin/slak "$prefix"/bin/Activate.ps1
find "$prefix" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true

echo ">> launcher /usr/bin/slak"
mkdir -p "$root/usr/bin"
cat > "$root/usr/bin/slak" <<EOF
#!/bin/sh
exec /usr/lib/slak/bin/python3 -m slak "\$@"
EOF
chmod 0755 "$root/usr/bin/slak"

installed_kb="$(du -sk "$root/usr" | cut -f1)"

echo ">> control metadata"
mkdir -p "$root/DEBIAN"
cat > "$root/DEBIAN/control" <<EOF
Package: $pkg
Version: $version
Architecture: $arch
Maintainer: Toni Leino <toni@leino.net>
Installed-Size: $installed_kb
Depends: python$pyver
Section: net
Priority: optional
Homepage: https://github.com/Frodotus/slak
Description: A terminal Slack client built on Textual
 slak is a keyboard-first terminal client for Slack: channels, threads,
 reactions, search, inline images and emoji on capable terminals.
 .
 This package bundles slak and its Python dependencies in a private
 environment under /usr/lib/slak; it requires only python$pyver.
EOF

mkdir -p dist
out="dist/${pkg}_${version}_${arch}.deb"
dpkg-deb --root-owner-group --build "$root" "$out"
echo ">> built $out"
