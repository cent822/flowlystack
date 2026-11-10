"""The tools. Each is a small function over the same modules the HTTP routes use; results are plain dicts."""
from __future__ import annotations

from .server import SERVER_INFO, SUPPORTED, tool, visible


@tool("flowlystack_about",
      "Describe this FlowlyStack server: what the connected token may do and which tools exist. Call this first. "
      "FlowlyStack holds the user's own prompts (Library and Studio), document collections, Linkshell project plans, Gallery patterns and the Lattice graph of how it all connects.",
      title="About FlowlyStack")
def about(args: dict, ctx: dict) -> dict:
    return {"app": SERVER_INFO["name"], "version": SERVER_INFO["version"],
            "token": {"name": ctx.get("name", ""), "scope": ctx.get("scope", "read")},
            "protocol_versions": list(SUPPORTED),
            "tools": [{"name": t["name"], "scope": t["scope"]} for t in visible(ctx.get("scope", "read"))]}
