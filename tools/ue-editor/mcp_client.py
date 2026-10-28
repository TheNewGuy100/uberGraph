"""Tiny Python client for the Unreal MCP plugin (HTTP, loopback), for scripts that chain several calls.

    from mcp_client import Mcp
    mcp = Mcp()
    mcp.call("UMGToolSet.UMGToolSet", "GetWidgets", {"widgetBlueprint": {"refPath": "/Game/Widgets/X.X"}})

Returns the parsed `returnValue` of the tool; raises RuntimeError on tool errors.
"""
import json
import os
import urllib.request

URL = os.environ.get("UE_MCP_URL", "http://127.0.0.1:8000/mcp")
HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


class Mcp:
    def __init__(self, url=URL):
        self.url = url
        self._id = 0
        _, headers = self._post({"jsonrpc": "2.0", "id": self._next(), "method": "initialize", "params": {
            "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "vanillaplus", "version": "1.0"}}})
        self.session = headers.get("Mcp-Session-Id")
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, expect_body=False)

    def _next(self):
        self._id += 1
        return self._id

    def _post(self, payload, expect_body=True):
        headers = dict(HEADERS)
        if getattr(self, "session", None):
            headers["Mcp-Session-Id"] = self.session
        request = urllib.request.Request(self.url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(request, timeout=900) as response:
            body = response.read().decode("utf-8")
            return (json.loads(body) if expect_body and body.strip() else None), dict(response.headers)

    def call(self, toolset, tool, arguments=None):
        payload = {"jsonrpc": "2.0", "id": self._next(), "method": "tools/call", "params": {
            "name": "call_tool", "arguments": {"toolset_name": toolset, "tool_name": tool, "arguments": arguments or {}}}}
        data, _ = self._post(payload)
        result = data.get("result", {})
        text = "".join(c.get("text", "") for c in result.get("content", []))
        if result.get("isError"):
            raise RuntimeError(text)
        try:
            return json.loads(text).get("returnValue")
        except ValueError:
            return text
