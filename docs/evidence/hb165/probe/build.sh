#!/bin/bash
# HB-165 Part A: configure and build SCICHEM 3.4 with gfortran, inside hb165-toolchain.
# Mounts: /scichem = the checkout's CMake root (read-only), /work = scratch (build tree, install).
# Follows scichem-compile-instructions.docx's SCICHEM step (cmake .. -G <generator>
# -DCMAKE_BUILD_TYPE=Release -Dbuild_client=epri), with gfortran in place of ifort.
# Extra flags, if any, come in by EXTRA_FFLAGS so each attempt is a recorded command line.
set -uo pipefail
BUILD=/work/build${BUILD_SUFFIX:-}
INSTALL=/work/install${INSTALL_SUFFIX:-}
mkdir -p "$BUILD" "$INSTALL"
cd "$BUILD"
echo "== configure $(date -u +%FT%TZ) EXTRA_FFLAGS='${EXTRA_FFLAGS:-}'"
cmake /scichem -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$INSTALL" \
  -DCMAKE_Fortran_COMPILER=gfortran \
  -DCMAKE_C_COMPILER=gcc -DCMAKE_CXX_COMPILER=g++ \
  -DCMAKE_Fortran_FLAGS="${EXTRA_FFLAGS:-}" \
  -Dbuild_client=epri ${EXTRA_CMAKE:-}
rc=$?
echo "== configure rc=$rc"
[ $rc -eq 0 ] || exit $rc
echo "== build $(date -u +%FT%TZ)"
cmake --build . -- -k 0 -j "${JOBS:-6}"
rc=$?
echo "== build rc=$rc $(date -u +%FT%TZ)"
[ $rc -eq 0 ] || exit $rc
cmake --install .
rc=$?
echo "== install rc=$rc"
exit $rc
