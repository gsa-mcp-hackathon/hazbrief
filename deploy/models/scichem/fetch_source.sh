#!/bin/sh
# Fetch what the SCICHEM build needs, and nothing else (HB-167 Part B item 7), into one directory the models image's
# build reads as its `scichemsrc` context:
#   <DIR>/source/                      the CMake root at the pinned commit (git: a blob-less partial clone, sparse)
#   <DIR>/README.md                    the repository's README at that commit
#   <DIR>/sciData/landuse_scichem.dat  the land-use table, from Git LFS, checked by sha256
#   <DIR>/TREE.sha256                  the sha256 the Dockerfile checks (SCICHEM_TREE_SHA256), see below
# Not the 1 GB sciData, the examples, the Windows or Linux binaries, or the documents.
#
# Usage, from the repository root:  bash deploy/models/scichem/fetch_source.sh [DIR]
#   DIR defaults to $HAZBRIEF_SCICHEM_SRC, else ~/.cache/hazbrief/scichem-<commit>.
# Needs git and curl. Re-running it on a complete directory checks it and fetches nothing.
#
# The tree hash: the sha256 of the sorted list "sha256  ./path" of every file under the directory except TREE.sha256,
# as `find . -type f | LC_ALL=C sort | xargs sha256sum | sha256sum` prints it (shasum -a 256 on macOS). The Dockerfile
# recomputes it before building, so the build stops on any other bytes.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck disable=SC1091
. "$HERE/pins.env"
DIR="${1:-${HAZBRIEF_SCICHEM_SRC:-$HOME/.cache/hazbrief/scichem-$SCICHEM_COMMIT}}"
if command -v sha256sum >/dev/null 2>&1; then SHA="sha256sum"; else SHA="shasum -a 256"; fi
mkdir -p "$DIR"
if [ ! -f "$DIR/source/CMakeLists.txt" ]; then
  TMP=$(mktemp -d)
  git -C "$TMP" init -q
  git -C "$TMP" remote add origin "$SCICHEM_REPO"
  git -C "$TMP" fetch -q --depth 1 --filter=blob:none origin "$SCICHEM_COMMIT"
  git -C "$TMP" sparse-checkout set --no-cone '/source/' '/README.md'
  git -C "$TMP" -c advice.detachedHead=false checkout -q FETCH_HEAD
  got=$(git -C "$TMP" rev-parse HEAD)
  if [ "$got" != "$SCICHEM_COMMIT" ]; then
    echo "fetched commit $got, not $SCICHEM_COMMIT" >&2
    exit 2
  fi
  rm -rf "$DIR/source"
  cp -R "$TMP/source" "$DIR/source"
  cp "$TMP/README.md" "$DIR/README.md"
  rm -rf "$TMP"
fi
mkdir -p "$DIR/sciData"
LU="$DIR/sciData/landuse_scichem.dat"
if [ ! -f "$LU" ]; then
  curl -fsSL -o "$LU.part" "$SCICHEM_LANDUSE_URL"
  mv "$LU.part" "$LU"
fi
got=$($SHA "$LU" | cut -d' ' -f1)
if [ "$got" != "$SCICHEM_LANDUSE_SHA256" ]; then
  echo "landuse_scichem.dat sha256 $got, not $SCICHEM_LANDUSE_SHA256" >&2
  exit 2
fi
rm -f "$DIR/TREE.sha256"
# The hash is written outside the directory first: a file created inside it while find runs would be hashed too.
HASHTMP=$(mktemp)
( cd "$DIR" && find . -type f | LC_ALL=C sort | while IFS= read -r f; do $SHA "$f"; done | $SHA | cut -d' ' -f1 ) > "$HASHTMP"
mv "$HASHTMP" "$DIR/TREE.sha256"
echo "SCICHEM source at $DIR: commit $SCICHEM_COMMIT, tree sha256 $(cat "$DIR/TREE.sha256")"
