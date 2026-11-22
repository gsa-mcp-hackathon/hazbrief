#!/bin/bash
# Build SCICHEM 3.4 with gfortran inside the models image's `scichem` stage (HB-167 Part B item 7), exactly as HB-165
# built and measured it (docs/evidence/hb165/probe/build.sh and build_final.sh; why.tsv gives each patch's reason):
#   1. copy the pinned CMake root and apply the eleven patches in numbered order;
#   2. configure as scichem-compile-instructions.docx's SCICHEM step (cmake -DCMAKE_BUILD_TYPE=Release
#      -Dbuild_client=epri), with gfortran for ifort and HB-165's flags:
#        -ffixed-line-length-132   ifort's -extend-source 132 (fixed-form AQAER, PRIME, AERMET)
#        -fdec-format-defaults     `I` with no width in FORMATs (ifort default widths)
#        -fno-frontend-optimize    without it gfortran short-circuits `refine .OR. find_cell_samp(...)` in sampler.f90
#                                  line 813 and every point sensor reads zero (HB-165 build_log.txt, attempt 8)
#        -U<20 client options>     ifort's -Qoption,fpp,-macro=no (only CHEM, EPA, FINI_OPT and LINUX are tested)
#        -Dclient_use_openmp=OFF   EPRI's own switch, working after patch 01; one thread
#        -lgomp                    SCIPtool calls omp_get_max_threads/omp_set_num_threads outside any sentinel
#   3. build and install to $3, then keep only what a run uses: runsci, scipp, the seven shared libraries.
# Usage: build_engine.sh <source dir (holds source/)> <patch dir> <install prefix>
set -euo pipefail
SRC=$1
PATCHES=$2
PREFIX=$3
WORK=/build/scichem
rm -rf "$WORK"
mkdir -p "$WORK"
cp -R "$SRC/source" "$WORK/tree"
for p in "$PATCHES"/[0-9]*.patch; do
  echo "applying $(basename "$p")"
  patch -d "$WORK/tree" -p1 --forward --quiet < "$p"
done
FFLAGS="-ffixed-line-length-132 -fdec-format-defaults -fno-frontend-optimize"
for m in AEROSOL DENSE EPRI INTEL LIQUID MULT OPVIEW SAMPAVG SCM SKEW METPLOT PROCESS REVERSE VALIDATION WRF OMP OMP_SWIM OMP_SPLIT OMP_PLIST OMP_CHEM; do
  FFLAGS="$FFLAGS -U$m"
done
mkdir -p "$WORK/build"
cd "$WORK/build"
cmake "$WORK/tree" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$WORK/install" \
  -DCMAKE_Fortran_COMPILER=gfortran \
  -DCMAKE_C_COMPILER=gcc -DCMAKE_CXX_COMPILER=g++ \
  -DCMAKE_Fortran_FLAGS="$FFLAGS" \
  -Dbuild_client=epri \
  -Dclient_use_openmp=OFF -DCMAKE_Fortran_STANDARD_LIBRARIES=-lgomp
cmake --build . -- -j "${JOBS:-6}"
cmake --install .
mkdir -p "$PREFIX/bin" "$PREFIX/lib"
cp "$WORK/install/bin/runsci" "$WORK/install/bin/scipp" "$PREFIX/bin/"
cp "$WORK/install/lib/"*.so "$PREFIX/lib/"
{
  echo "SCICHEM 3.4, epri-dev/SCICHEM commit ${SCICHEM_COMMIT:-unknown}, built by deploy/models/scichem/build_engine.sh"
  echo "patches: $(cd "$PATCHES" && ls [0-9]*.patch | tr '\n' ' ')"
  echo "Fortran flags: $FFLAGS"
  echo "cmake: -DCMAKE_BUILD_TYPE=Release -Dbuild_client=epri -Dclient_use_openmp=OFF -DCMAKE_Fortran_STANDARD_LIBRARIES=-lgomp"
  gfortran --version | head -1
  cmake --version | head -1
  dpkg-query -W -f '${Package} ${Version}\n' libnetcdf-dev libhdf5-dev gfortran
} > "$PREFIX/BUILD_INFO"
cat "$PREFIX/BUILD_INFO"
