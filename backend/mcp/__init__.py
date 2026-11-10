"""The MCP server: the protocol layer (`server`) and the tools. Standard library only.

The HTTP side (token check, switch, Origin) is `backend/mcp_api.py`; this package knows JSON-RPC and nothing about HTTP frameworks.
Tool modules import their backend modules inside the functions, so the protocol checks run under a bare python3.
"""
from . import server  # noqa: F401  (first: it holds the registry the tool modules fill)
from . import tools, tools_collections, tools_gallery, tools_graph, tools_library, tools_linkshell, tools_write  # noqa: F401
