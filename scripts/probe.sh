#!/usr/bin/env bash
# Send raw JSON-RPC to an MCP server and print each exchange (M0).
# Usage: scripts/probe.sh [url]   (default: http://localhost:9001/mcp)
set -u

URL="${1:-http://localhost:9001/mcp}"
MODERN="2026-07-28"
LEGACY="2025-11-25"
META="\"_meta\":{\"io.modelcontextprotocol/protocolVersion\":\"$MODERN\",\"io.modelcontextprotocol/clientCapabilities\":{},\"io.modelcontextprotocol/clientInfo\":{\"name\":\"probe\",\"version\":\"0\"}}"
BASE_HEADERS=(-H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream')

# post <title> <body> [extra curl args...]
post() {
  local title="$1" body="$2"
  shift 2
  echo "### $title"
  echo ">>> $body"
  curl -s -i "$URL" "${BASE_HEADERS[@]}" "$@" -d "$body" \
    | grep -iE '^(HTTP/|mcp-session-id:)|^\{' | sed 's/^/<<< /'
  echo
}

# post_modern <title> <method> <params-without-meta> [name]
post_modern() {
  local title="$1" method="$2" params="$3" name="${4:-}"
  local headers=(-H "MCP-Protocol-Version: $MODERN" -H "Mcp-Method: $method")
  [[ -n "$name" ]] && headers+=(-H "Mcp-Name: $name")
  local sep=""
  [[ -n "$params" ]] && sep=","
  post "$title" "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"$method\",\"params\":{$params$sep$META}}" "${headers[@]}"
}

echo "======== $MODERN (stateless) ========"
post_modern "server/discover" "server/discover" ""
post_modern "tools/list" "tools/list" ""
post_modern "tools/call add(2,3)" "tools/call" '"name":"add","arguments":{"a":2,"b":3}' add

echo "======== $MODERN error cases ========"
post "Mcp-Name header != body name" \
  "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"add\",\"arguments\":{\"a\":1,\"b\":1},$META}}" \
  -H "MCP-Protocol-Version: $MODERN" -H 'Mcp-Method: tools/call' -H 'Mcp-Name: multiply'
post "missing Mcp-Method header" \
  "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\",\"params\":{$META}}" \
  -H "MCP-Protocol-Version: $MODERN"
post "unsupported protocol version" \
  '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2099-01-01","io.modelcontextprotocol/clientCapabilities":{}}}}' \
  -H 'MCP-Protocol-Version: 2099-01-01' -H 'Mcp-Method: tools/list'
post_modern "unknown tool" "tools/call" '"name":"nope","arguments":{}' nope
post_modern "invalid arguments" "tools/call" '"name":"add","arguments":{"a":"x"}' add
post_modern "unknown method" "foo/bar" ""

echo "======== $LEGACY (session) ========"
init=$(curl -s -i "$URL" "${BASE_HEADERS[@]}" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"$LEGACY\",\"capabilities\":{},\"clientInfo\":{\"name\":\"probe\",\"version\":\"0\"}}}")
echo "### initialize"
echo "$init" | grep -iE '^(HTTP/|mcp-session-id:)|^\{' | sed 's/^/<<< /'
echo
SID=$(echo "$init" | grep -i '^mcp-session-id:' | awk '{print $2}' | tr -d '\r')
post "notifications/initialized" '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
  -H "Mcp-Session-Id: $SID" -H "MCP-Protocol-Version: $LEGACY"
post "tools/call add(2,3) with session" '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"add","arguments":{"a":2,"b":3}}}' \
  -H "Mcp-Session-Id: $SID" -H "MCP-Protocol-Version: $LEGACY"
post "tools/list without session" '{"jsonrpc":"2.0","id":3,"method":"tools/list"}' \
  -H "MCP-Protocol-Version: $LEGACY"
