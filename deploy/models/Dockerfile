# syntax=docker/dockerfile:1
# The models image, `hazbrief-models` (DN-020 section 2 item 5 and section 3.2; HB-111 Part A).
#
# SLAB (D. L. Ermak, LLNL, 1990), compiled from the held archive `corpus/raw/epa-slab-code.zip`
# (`epa-slab-code`, as EPA SCRAM serves it), checked by its four distributed test cases at build,
# run by a standard-library driver that reads an input deck and writes SLAB's output. It is a
# second image beside the server, never part of it: the server image (`Dockerfile` at the root)
# holds none of this (`.dockerignore`; test_container_image.py (a test held privately)), and SLAB's code never enters
# the repository's MIT tree. It opens no port: the application runs it per deck with
# `docker run --rm -i --network none hazbrief-models < deck > predict` (src/hazbrief/brief/dense_gas.py).
#
# Why the Fortran image and not the Python port: HB-111 Part 0 ran slabx 1.0.7 on the same four
# cases, and its concentrations differ from SLAB's by more than DN-020 ADDENDUM-00 item 2's
# 5 percent (to 24 percent within 46 m on PR4, the chlorine jet); the HB-111 evidence (held privately).
#
# Build (from the repository root; deploy/models/build.sh does this):
#   docker build -f deploy/models/Dockerfile \
#     --build-context slabzip=<directory holding epa-slab-code.zip> -t hazbrief-models .
# The archive comes in by that named context, not the root context: in a git worktree `corpus/raw`
# is a symlink, which COPY copies as a link. `deploy/models/Dockerfile.dockerignore` limits the
# root context to the three files this build reads.
#
# The build fails, before anything is unpacked, when the archive's sha256 is not
# SLAB_ZIP_SHA256: the manifest's `raw_sha256` for epa-slab-code
# (docs/sources/manifest.tsv; test_models_image.py (a test held privately) holds the two equal).
# It fails again, after compiling, when any of SLAB's four test cases differs from its
# distributed output by more than one unit in the third printed significant figure: HB-102's
# measured tolerance (docs/evidence/hb102/inventory.md section 5), signed zeros and SLAB.RME's
# documented x = 0 residue excepted (deploy/models/check_cases.py).
#
# SCICHEM 3.4 (EPRI; SCIPUFF inside), the engine for a dense release (HB-167, DN-028), is built in
# its own stage from EPRI's repository at a pinned commit with HB-165's eleven patches and flags
# (deploy/models/scichem/). Its source arrives by a second named context, `scichemsrc`, which
# deploy/models/scichem/fetch_source.sh fills (the CMake root by git at the commit, the land-use
# table from Git LFS by sha256); the build checks that directory's tree hash before anything is
# compiled, and checks the built engine against EPRI's Intel build at build
# (deploy/models/scichem/check/check_engine.py). deploy/models/build.sh passes both contexts.
#   docker build -f deploy/models/Dockerfile --build-context slabzip=<dir> \
#     --build-context scichemsrc=<dir from fetch_source.sh> -t hazbrief-models .

ARG SLAB_ZIP_SHA256=0d19cf8e91b8ecfd958463bbe0da3fa94917b7d6a594dc4ed0f25353d4f41df4
# deploy/models/scichem/pins.env and fetch_source.sh's tree hash (test_hb167_scichem_image.py (a test held privately)).
ARG SCICHEM_COMMIT=156625eff47923d232dbe4f6d055707ea3bf6ff1
ARG SCICHEM_TREE_SHA256=f76ec5e34c85a69d675e8efcd80340317f1f898aac20ea47cae9486c01c57f0a

# GCC 14.2.0: the gfortran version HB-102 built and checked SLAB with (Homebrew GCC 14.2.0_1). The
# official image's index digest as pulled on 2026-11-07. A tag can move; the digest cannot.
FROM gcc:14.2.0@sha256:b99b86a28812b1e6453a231a947dc43d76fe192788a12f344a9b568bf9f5d24c AS build
ARG SLAB_ZIP_SHA256
WORKDIR /build
COPY --from=slabzip epa-slab-code.zip ./
RUN echo "${SLAB_ZIP_SHA256}  epa-slab-code.zip" | sha256sum -c - \
 && unzip -q epa-slab-code.zip \
 && test -f SLAB/SLAB.FOR
# As HB-102 compiled it (`gfortran -std=legacy -O0`, no Fortran warnings), linked statically so the
# runtime stage needs no gfortran, no libgfortran and no compiler at all.
RUN gfortran -std=legacy -O0 -static -o slab SLAB/SLAB.FOR \
 && mkdir -p /out/cases /out/licenses \
 && cp SLAB/INPR1 SLAB/INPR2 SLAB/INPR3 SLAB/INPR4 \
       SLAB/OUTPR1 SLAB/OUTPR2 SLAB/OUTPR3 SLAB/OUTPR4 /out/cases/ \
 && sed -n '1,20p' SLAB/SLAB.FOR > /out/licenses/SLAB

# SCICHEM's build stage: the server image's own base (the runtime below), so the engine links the
# same Debian libraries it runs with, with gfortran 14.2, cmake, ninja and NetCDF/HDF5 from Debian, as
# HB-165's toolchain (docs/evidence/hb165/probe/Dockerfile.toolchain). NetCDF and HDF5 are required:
# CMakeLists.txt lines 131 and 132 `find_package(HDF5 REQUIRED)` and `find_package(netCDF REQUIRED)`,
# and SWIM links netCDF::netcdf (HB-167 Part B item 9 tried the build without them).
FROM python:3.11-slim@sha256:b7a9e5f6a93d6d4a31f129bbd4bdee69efccb6ded0fb230d78aafaf37af98377 AS scichem
ARG SCICHEM_COMMIT
ARG SCICHEM_TREE_SHA256
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      gfortran gcc g++ cmake ninja-build make patch \
      libnetcdf-dev libhdf5-dev libaec-dev zlib1g-dev pkg-config \
 && rm -rf /var/lib/apt/lists/*
COPY --from=scichemsrc . /src/scichem
# The fetched directory's tree hash, before anything is compiled (fetch_source.sh's recipe).
RUN cd /src/scichem \
 && rm -f TREE.sha256 \
 && got=$(find . -type f | LC_ALL=C sort | while IFS= read -r f; do sha256sum "$f"; done | sha256sum | cut -d' ' -f1) \
 && echo "SCICHEM tree sha256 $got" \
 && test "$got" = "${SCICHEM_TREE_SHA256}"
COPY patches/ (held privately) /src/patches/
COPY deploy/models/scichem/build_engine.sh /src/build_engine.sh
RUN SCICHEM_COMMIT=${SCICHEM_COMMIT} bash /src/build_engine.sh /src/scichem /src/patches /opt/scichem \
 && mkdir -p /opt/scichem/sciData \
 && cp /src/scichem/sciData/landuse_scichem.dat /opt/scichem/sciData/

# Python 3.11 on Debian slim, the same digest as the server image (Dockerfile at the root; HB-34,
# HB-35): already in the local cache, and the driver and the check need only its standard library.
FROM python:3.11-slim@sha256:b7a9e5f6a93d6d4a31f129bbd4bdee69efccb6ded0fb230d78aafaf37af98377

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV SLAB_BIN=/opt/slab/bin/slab
# A run of SLAB's longest test case takes well under a second; this bounds a pathological deck.
ENV SLAB_TIMEOUT_S=300

COPY --from=build /build/slab /opt/slab/bin/slab
COPY --from=build /out/cases /opt/slab/cases
# SLAB.FOR lines 1 to 20, verbatim: the University of California's copyright and the two
# conditions under which the program may be copied and distributed (no fee; no commercial
# product). docs/SECURITY.md quotes them.
COPY --from=build /out/licenses/SLAB /licenses/SLAB

COPY src/hazbrief/brief/slab_driver.py /opt/slab/slab_driver.py
COPY docs/evidence/hb102/compare_outputs.py /opt/slab/check/compare_outputs.py
COPY deploy/models/check_cases.py /opt/slab/check/check_cases.py

# The four test cases, run through the driver and the binary this image ships, before anything
# else: the build stops here when any value is outside the tolerance.
RUN cp /opt/slab/slab_driver.py /opt/slab/check/slab_driver.py \
 && python -I /opt/slab/check/check_cases.py /opt/slab/cases /opt/slab/check/runs

# SCICHEM (HB-167): the engine's runtime libraries from Debian (gfortran's and OpenMP's runtimes and
# NetCDF with its closure; no compiler), the two executables and seven libraries the build stage made,
# the land-use table, the notice (/licenses/SCICHEM) and the driver, run as
#   docker run --rm -i --network none --entrypoint python hazbrief-models -I /opt/scichem/scichem_driver.py
# (src/hazbrief/brief/scichem.yaml `entry`).
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgfortran5 libgomp1 libnetcdf22 \
 && rm -rf /var/lib/apt/lists/*
ENV SCICHEM_HOME=/opt/scichem
# An 8-hour run with 300 sensors and its 300 contour extractions takes about 10 s; this bounds a
# pathological request (each runsci or scipp call).
ENV SCICHEM_TIMEOUT_S=600
COPY --from=scichem /opt/scichem /opt/scichem
COPY deploy/models/scichem/NOTICE /licenses/SCICHEM
COPY src/hazbrief/brief/scichem_driver.py /opt/scichem/scichem_driver.py
COPY deploy/models/scichem/check/check_engine.py /opt/scichem/check/check_engine.py
COPY deploy/models/scichem/check/intel_reference_csxday_base.smp.gz /opt/scichem/check/intel_reference_csxday_base.smp.gz
COPY case/ (held privately) /opt/scichem/check/case/
# The engine's gate, before the user and the entry: normal termination of a single-material namelist
# project (patch 11), sensors above zero inside the cloud (-fno-frontend-optimize), and every value
# within 1 percent of EPRI's Intel build on the same inputs (HB-165's measured agreement).
RUN python -I /opt/scichem/check/check_engine.py /opt/scichem/check /opt/scichem

# A non-root user, as the server image. The driver writes only to its own temporary directory.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin slab
USER slab

ENTRYPOINT ["python", "-I", "/opt/slab/slab_driver.py"]
