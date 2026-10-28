#!/bin/bash
# Minimal client for the Unreal MCP plugin (HTTP, loopback). Usage:
#   mcp_call.sh init                          -> prints a session id
#   mcp_call.sh <session> list                -> list_toolsets
#   mcp_call.sh <session> describe <toolset>  -> describe_toolset
#   mcp_call.sh <session> call '<json>'       -> call_tool with the given arguments object
# Toolset names are full, e.g. UMGToolSet.UMGToolSet or editor_toolset.toolsets.object.ObjectTools.
URL="${UE_MCP_URL:-http://127.0.0.1:8000/mcp}"
H=(-H "Content-Type: application/json" -H "Accept: application/json, text/event-stream")
if [ "$1" = "init" ]; then
  R=$(curl -s -i -m 15 -X POST "$URL" "${H[@]}" -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"vanillaplus","version":"1.0"}}}')
  S=$(echo "$R" | grep -i '^Mcp-Session-Id' | tr -d '\r' | awk '{print $2}')
  curl -s -m 10 -X POST "$URL" "${H[@]}" -H "Mcp-Session-Id: $S" -d '{"jsonrpc":"2.0","method":"notifications/initialized"}' -o /dev/null
  echo "$S"; exit 0
fi
S="$1"; ACTION="$2"
case "$ACTION" in
  list) BODY='{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"list_toolsets","arguments":{}}}' ;;
  describe) BODY="{\"jsonrpc\":\"2.0\",\"id\":4,\"method\":\"tools/call\",\"params\":{\"name\":\"describe_toolset\",\"arguments\":{\"toolset_name\":\"$3\"}}}" ;;
  call) BODY="{\"jsonrpc\":\"2.0\",\"id\":9,\"method\":\"tools/call\",\"params\":{\"name\":\"call_tool\",\"arguments\":$3}}" ;;
  *) echo "unknown action"; exit 1 ;;
esac
curl -s -m 120 -X POST "$URL" "${H[@]}" -H "Mcp-Session-Id: $S" -d "$BODY" | python -c "
import sys, json
d = json.load(sys.stdin)
r = d.get('result', d)
for c in r.get('content', []):
    print(c.get('text', ''))
if r.get('isError'): print('ISERROR')
if 'error' in d: print(json.dumps(d['error'])[:800])
"
