#!/bin/sh
# Build the models image (HB-111, HB-167; deploy/models/Dockerfile). Optional: the server never needs it.
# Usage, from the repository root:  sh deploy/models/build.sh [DIR_HOLDING_epa-slab-code.zip] [TAG] [SCICHEM_SOURCE_DIR]
#   DIR defaults to corpus/raw (resolved, so a worktree's symlinked corpus/raw works);
#   TAG defaults to hazbrief-models (src/hazbrief/brief/orchestrator.yaml dense_gas.image);
#   SCICHEM_SOURCE_DIR defaults to $HAZBRIEF_SCICHEM_SRC, else ~/.cache/hazbrief/scichem-<commit>, and is filled
#   first by deploy/models/scichem/fetch_source.sh when it is not there (git and curl, network; HB-167).
# Extra arguments to `docker build` go in DOCKER_BUILD_ARGS (for example --build-arg ...).
set -eu
ZIPDIR=$(cd "${1:-corpus/raw}" && pwd -P)
TAG="${2:-hazbrief-models}"
if [ ! -f "$ZIPDIR/epa-slab-code.zip" ]; then
  echo "no epa-slab-code.zip in $ZIPDIR (fetch it per corpus/sources.yaml, id epa-slab-code)" >&2
  exit 2
fi
# shellcheck disable=SC1091
. deploy/models/scichem/pins.env
SCIDIR="${3:-${HAZBRIEF_SCICHEM_SRC:-$HOME/.cache/hazbrief/scichem-$SCICHEM_COMMIT}}"
if [ ! -f "$SCIDIR/TREE.sha256" ]; then
  bash deploy/models/scichem/fetch_source.sh "$SCIDIR"
fi
# shellcheck disable=SC2086
exec docker build -f deploy/models/Dockerfile --build-context "slabzip=$ZIPDIR" \
  --build-context "scichemsrc=$SCIDIR" ${DOCKER_BUILD_ARGS:-} -t "$TAG" .
