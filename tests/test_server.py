"""Smoke tests for the hazbrief MCP server.

These verify the server imports and every submodule registers without error.
Add functional tests for your own tools as you build them.
"""

from __future__ import annotations

from fastmcp import FastMCP

from hazbrief.app import mcp
from hazbrief.config import settings


def test_server_is_importable():
    assert mcp is not None


def test_server_has_name():
    assert mcp.name == "HazBrief MCP Server"


def test_default_transport_is_stdio():
    """Guard against accidentally shipping with a non-stdio default."""
    assert settings.mcp_transport == "stdio"


def test_tools_register_without_error():
    from hazbrief.tools import register_tools

    register_tools(FastMCP("test"))  # must not raise


def test_prompts_register_without_error():
    from hazbrief.prompts import register_prompts

    register_prompts(FastMCP("test"))  # must not raise


def test_resources_register_without_error():
    from hazbrief.resources import register_resources

    register_resources(FastMCP("test"))  # must not raise


def test_routes_register_without_error():
    from hazbrief.routes import register_routes

    register_routes(FastMCP("test"))  # must not raise


def test_health_route_reports_service():
    from starlette.testclient import TestClient

    from hazbrief import __version__

    with TestClient(mcp.http_app()) as client:
        health = client.get("/health")
        version = client.get("/version")

    assert health.status_code == 200
    assert health.json() == {"status": "healthy", "service": "hazbrief-mcp"}
    assert version.json() == {"version": __version__}
