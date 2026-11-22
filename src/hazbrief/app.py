"""MCP server entry point.

Keep this file THIN. It only:
  1. creates the FastMCP instance,
  2. registers tools / prompts / resources / routes from the submodules, and
  3. decides which transport to run (stdio locally vs. HTTP when deployed).

All real logic lives in the submodules:
  - tools/      one file per tool (each exposes `register(mcp)`)
  - prompts/    reusable conversation starters
  - resources/  static/semi-static data the client can read directly
  - routes.py   HTTP-only infrastructure (health check, etc.)
  - config.py   settings loaded from env vars / .env
  - models.py   Pydantic models & enums for tool parameters
  - utils.py    shared helpers (HTTP client, formatting, pagination)
"""

from __future__ import annotations

import os

from fastmcp import FastMCP

from hazbrief.config import settings
from hazbrief.prompts import register_prompts
from hazbrief.resources import register_resources
from hazbrief.routes import register_routes
from hazbrief.tools import register_tools

# The server name is what MCP clients display.
mcp = FastMCP(
    name="HazBrief MCP Server",
    instructions=(
        "Hazmat incident briefing server. Given a transported-hazmat incident "
        "(material, container, location, time), it returns a protective action "
        "footprint traced to the PHMSA Emergency Response Guidebook, sourced "
        "flags, and a draft ICS 201 Incident Briefing as structured data and "
        "GeoJSON. It does not run a dispersion model."
    ),
    # HB-89 (review L3-5): an exception a tool raises reaches the client as a generic
    # "Error calling tool" message, never its text, which can carry a path or an
    # upstream field. A tool's expected failures are returned values (`error` and
    # `hint`, such as the missing CENSUS_API_KEY with its signup URL), not exceptions,
    # so masking hides nothing a caller is meant to read.
    mask_error_details=True,
)

# Wire up everything the server exposes. Each aggregator lives in its submodule.
register_tools(mcp)
register_prompts(mcp)
register_resources(mcp)
register_routes(mcp)


def http_options() -> dict:
    """The bind and the Host/Origin guard every HTTP run uses (HB-89; review L3-1,
    L3-7).

    The host is `MCP_HOST`, 127.0.0.1 unless widened: the route has no authentication
    and no rate limit, and `server.json` publishes no remote, so nothing outside the
    machine is meant to reach it. The guard is fastmcp's strict mode: every request's
    Host must be a loopback name, the bound host, or one listed in `MCP_ALLOWED_HOSTS`
    (fastmcp 4.1.1, `server/http.py` HostOriginGuardMiddleware), and a browser Origin
    must match, so a web page cannot reach a local server by DNS rebinding."""
    return {
        "host": settings.mcp_host,
        "host_origin_protection": True,
        "allowed_hosts": list(settings.mcp_allowed_hosts),
    }


def main() -> None:
    """Start the server, choosing a transport based on the environment.

    Precedence:
      1. A platform-injected port (Databricks `DATABRICKS_APP_PORT` or a generic
         `PORT`) → run HTTP on that port. The container sets PORT.
      2. `MCP_TRANSPORT=streamable-http` in the environment → run HTTP on
         `MCP_PORT` (see config.py / .env).
      3. Otherwise → stdio, which is how local clients (Claude Desktop, Claude
         Code, Zed) launch the server as a subprocess.

    Both HTTP paths bind `MCP_HOST` (127.0.0.1 by default) behind the Host/Origin
    guard (`http_options`).
    """
    platform_port = os.getenv("DATABRICKS_APP_PORT") or os.getenv("PORT")

    if platform_port:
        mcp.run(transport="http", port=int(platform_port), **http_options())
    elif settings.mcp_transport == "streamable-http":
        mcp.run(transport="streamable-http", port=settings.mcp_port, **http_options())
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
