# HB-203 item 4 (HB-198 item 5, ADDENDUM-05): the server image, from the clean clone of main at `ae27a5f7`

## The build with no network

`docker build --network=none -t hazbrief-mcp:hb203-offline -f /private/tmp/hb203_clone/Dockerfile
/private/tmp/hb203_clone`, 2026-11-18 about 16:40 EST. It stops at the dependency layer, where `uv` needs PyPI
(the log is `logs/hb203/image_build.log`, gitignored; these lines are quoted from it):

```
#12 [stage-1  4/12] COPY pyproject.toml uv.lock README.md LICENSE LICENSE-TEMPLATE ./
#13 [stage-1  5/12] RUN uv sync --locked --no-dev --no-install-project
#13 22.60   ├─▶ Failed to fetch:
#13 22.60   ├─▶ dns error
Dockerfile:48
  48 | >>> RUN uv sync --locked --no-dev --no-install-project
ERROR: failed to build: failed to solve: process "/bin/sh -c uv sync --locked --no-dev --no-install-project" did not complete successfully: exit code: 1
```

The package it was fetching was `pygments` 2.21.0 from `files.pythonhosted.org`. So a judge's image build needs PyPI,
as HB-197 item 0d and HB-201 found. No image was made.

## Whether HB-201's image stands for this commit

ADDENDUM-05's test, `git diff --stat 79d46c1e ae27a5f7 --` over the Dockerfile's `COPY` paths:

```
 README.md                            | 2 +-
 src/hazbrief/brief/orchestrator.yaml | 6 +++---
 src/hazbrief/brief/tevv.py           | 2 +-
 3 files changed, 5 insertions(+), 5 deletions(-)
```

The diff is not empty, so `hazbrief-mcp:hb201` (`sha256:d3ea63c83cfd`) does not stand for `ae27a5f7`, and no container
result is recorded for this commit. README's container lines were not run against it.
