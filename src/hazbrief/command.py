"""The `hazbrief` console script: `hazbrief brief ...` writes a brief (HB-41, DN-011
D5); anything else runs the MCP server as before (`hazbrief.app:main`). The container
starts the server with `python -m hazbrief.app`, so it does not pass through here.

The brief's package is imported only for `brief`, so the server never loads the
application (DN-010 D2, D7).
"""

from __future__ import annotations

import sys


def main() -> None:
    if sys.argv[1:2] == ["brief"]:
        from hazbrief.brief.cli import main as brief_main

        sys.exit(brief_main(sys.argv[2:]))
    from hazbrief.app import main as server_main

    server_main()
