#!/usr/bin/env bash
# An MCP client inside the k3s cluster, as a kagent agent would be: a pod in another
# namespace (default "kagent") calls the release's Service at
# http://<service>.<namespace>.svc.cluster.local/mcp (not a base URL: /mcp is exempt from
# the app's Host check) with the official MCP Python SDK from the app image. The key
# reaches the pod the way kagent's RemoteMCPServer reads it: a Secret whose value is the
# whole header, "Bearer sdg_...". scripts/mcp-smoke.sh calls this (MCP_CLIENT_HOOK)
# from scripts/k3s-smoke.sh with MCP=1.
#
#   MCP_KEY=sdg_... MCP_EXPECT=ok scripts/k3s-mcp-client.sh
#
#   MCP_KEY            the API key (read from the environment, never from arguments)
#   MCP_EXPECT         ok: initialize (the handshake kagent's Go SDK uses), the nine
#                      tools, search_ideas (MCP_QUERY, if set, must find MCP_EXPECT_KEY);
#                      unauthorized: POST /mcp answers 401 (a revoked key);
#                      blocked: the NetworkPolicy drops the connection (DNS still works)
#   MCP_CLIENT_NAMESPACE  namespace of the client pod (default kagent; created if missing)
#   RELEASE / NAMESPACE   the Soundings release (defaults soundings / soundings)
# Needs jq. Removes its pod and Secret afterwards, and the namespace if it created it.
set -euo pipefail
# shellcheck source-path=SCRIPTDIR source=lib/k3s-env.sh
source "$(dirname "$0")/lib/k3s-env.sh"

RELEASE="${RELEASE:-soundings}"
NAMESPACE="${NAMESPACE:-soundings}"
CLIENT_NS="${MCP_CLIENT_NAMESPACE:-kagent}"
EXPECT="${MCP_EXPECT:-ok}"
: "${MCP_KEY:?MCP_KEY (the API key) is required}"
case "$EXPECT" in ok | unauthorized | blocked) ;; *) die "MCP_EXPECT must be ok, unauthorized or blocked" ;; esac
command -v jq >/dev/null || die "jq is required"
require_k3s

deployment="$(kubectl -n "$NAMESPACE" get deploy -o name \
  -l "app.kubernetes.io/instance=$RELEASE,app.kubernetes.io/component=api" | head -n 1)"
[ -n "$deployment" ] || die "no api Deployment for release $RELEASE in namespace $NAMESPACE"
image="$(kubectl -n "$NAMESPACE" get "$deployment" -o jsonpath='{.spec.template.spec.containers[0].image}')"
pull="$(kubectl -n "$NAMESPACE" get "$deployment" -o jsonpath='{.spec.template.spec.containers[0].imagePullPolicy}')"
# The chart's Service is the one named after the release's fullname with port "http".
service="$(kubectl -n "$NAMESPACE" get svc -l "app.kubernetes.io/instance=$RELEASE" \
  -o jsonpath='{range .items[*]}{.metadata.name} {.spec.ports[?(@.name=="http")].port}{"\n"}{end}' |
  awk 'NF == 2 { print; exit }')"
[ -n "$service" ] || die "no Service with an http port for release $RELEASE"
url="http://${service% *}.$NAMESPACE.svc.cluster.local:${service#* }/mcp"

pod="mcp-client-$(date +%s)-$RANDOM"
secret="$pod"
created_ns=0
# A namespace this script removed a moment ago may still be terminating.
for _ in $(seq 1 60); do
  [ "$(kubectl get namespace "$CLIENT_NS" -o jsonpath='{.status.phase}' 2>/dev/null)" = "Terminating" ] || break
  sleep 2
done
if ! kubectl get namespace "$CLIENT_NS" >/dev/null 2>&1; then
  kubectl create namespace "$CLIENT_NS" >/dev/null
  created_ns=1
fi
cleanup() {
  if [ "$created_ns" = 1 ]; then
    kubectl delete namespace "$CLIENT_NS" --wait=false >/dev/null 2>&1 || true
  else
    kubectl -n "$CLIENT_NS" delete pod "$pod" --ignore-not-found --wait=false >/dev/null 2>&1 || true
    kubectl -n "$CLIENT_NS" delete secret "$secret" --ignore-not-found >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

# The Secret travels on stdin, so the key never shows up in a process list.
jq -n --arg name "$secret" --arg value "Bearer $MCP_KEY" \
  '{apiVersion: "v1", kind: "Secret", metadata: {name: $name}, type: "Opaque",
    stringData: {authorization: $value}}' | kubectl -n "$CLIENT_NS" apply -f - >/dev/null

read -r -d '' client_py <<'PY' || true
import asyncio, json, os, socket, sys, time
from urllib.parse import urlsplit

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

URL, EXPECT = os.environ["MCP_URL"], os.environ["MCP_EXPECT"]
HEADERS = {"Authorization": os.environ["MCP_AUTHORIZATION"]}
QUERY, WANT_KEY = os.environ.get("MCP_QUERY", ""), os.environ.get("MCP_EXPECT_KEY", "")
TOOLS = {"list_projects", "search_ideas", "get_idea", "create_idea", "add_comment",
         "submit_evaluation", "get_rubric", "get_proposal", "propose_proposal_section"}
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
    "protocolVersion": "2025-06-18", "capabilities": {},
    "clientInfo": {"name": "k3s-mcp-client", "version": "1"}}}

def reachable(timeout: float) -> bool:
    parts = urlsplit(URL)
    socket.getaddrinfo(parts.hostname, parts.port)  # DNS must work either way
    try:
        socket.create_connection((parts.hostname, parts.port), timeout=timeout).close()
        return True
    except OSError:
        return False

def wait_reachable() -> None:
    # A NetworkPolicy controller may admit a new pod's address a moment after it starts.
    for _ in range(30):
        if reachable(2):
            return
        time.sleep(1)
    sys.exit(f"FAIL {URL} is not reachable from this namespace")

async def main() -> None:
    if EXPECT == "blocked":
        if any(reachable(3) for _ in range(5)):
            sys.exit(f"FAIL {URL} is reachable, want blocked by the NetworkPolicy")
        print(f"ok  {URL}: name resolves, connections are dropped (NetworkPolicy)")
        return
    wait_reachable()
    if EXPECT == "unauthorized":
        async with httpx2.AsyncClient(headers=HEADERS, timeout=10) as http:
            response = await http.post(URL, json=INIT, headers={
                "Accept": "application/json, text/event-stream"})
        challenge = response.headers.get("www-authenticate", "")
        if response.status_code != 401 or not challenge.startswith("Bearer"):
            sys.exit(f"FAIL with the revoked key: {response.status_code} {challenge!r}, want 401")
        print(f"ok  revoked key from the cluster: 401 ({challenge})")
        return
    async with httpx2.AsyncClient(headers=HEADERS, timeout=30) as http:
        # "legacy": the initialize handshake, which kagent's Go SDK client uses.
        async with Client(streamable_http_client(URL, http_client=http), mode="legacy") as client:
            info = client.server_info
            tools = {tool.name for tool in (await client.list_tools()).tools}
            if tools != TOOLS:
                sys.exit(f"FAIL tools/list: {sorted(tools)}")
            print(f"ok  initialize: {info.name if info else None} {client.protocol_version}; tools/list: {len(tools)} tools")
            result = await client.call_tool("search_ideas", {"query": QUERY} if QUERY else {})
            if result.is_error:
                sys.exit(f"FAIL search_ideas: {result.content}")
            keys = [item["key"] for item in result.structured_content["items"]]
            if WANT_KEY and WANT_KEY not in keys:
                sys.exit(f"FAIL search_ideas {QUERY!r}: {keys}, want {WANT_KEY}")
            print(f"ok  search_ideas {QUERY!r}: {json.dumps(keys)}")

asyncio.run(main())
PY

restricted='{"allowPrivilegeEscalation": false, "readOnlyRootFilesystem": true,
  "capabilities": {"drop": ["ALL"]}}'
jq -n --arg name "$pod" --arg image "$image" --arg pull "$pull" --arg secret "$secret" \
  --arg url "$url" --arg expect "$EXPECT" --arg query "${MCP_QUERY:-}" \
  --arg want "${MCP_EXPECT_KEY:-}" --arg script "$client_py" --argjson sc "$restricted" '
  {apiVersion: "v1", kind: "Pod",
   metadata: {name: $name, labels: {"app.kubernetes.io/name": "mcp-smoke-client"}},
   spec: {restartPolicy: "Never", automountServiceAccountToken: false, enableServiceLinks: false,
     securityContext: {runAsNonRoot: true, runAsUser: 10001, runAsGroup: 10001,
       seccompProfile: {type: "RuntimeDefault"}},
     containers: [{name: "client", image: $image, imagePullPolicy: $pull,
       command: ["python", "-c", $script],
       env: [{name: "MCP_URL", value: $url}, {name: "MCP_EXPECT", value: $expect},
             {name: "MCP_QUERY", value: $query}, {name: "MCP_EXPECT_KEY", value: $want},
             {name: "MCP_AUTHORIZATION",
              valueFrom: {secretKeyRef: {name: $secret, key: "authorization"}}}],
       resources: {requests: {cpu: "10m", memory: "64Mi"}, limits: {memory: "256Mi"}},
       securityContext: $sc,
       volumeMounts: [{name: "tmp", mountPath: "/tmp"}]}],
     volumes: [{name: "tmp", emptyDir: {sizeLimit: "16Mi"}}]}}' |
  kubectl -n "$CLIENT_NS" apply -f - >/dev/null

phase=""
for _ in $(seq 1 90); do
  phase="$(kubectl -n "$CLIENT_NS" get pod "$pod" -o jsonpath='{.status.phase}' 2>/dev/null || true)"
  case "$phase" in Succeeded | Failed) break ;; esac
  sleep 2
done
kubectl -n "$CLIENT_NS" logs "$pod" 2>/dev/null | sed "s/^/  [$CLIENT_NS] /" || true
[ "$phase" = "Succeeded" ] || die "in-cluster MCP client ($CLIENT_NS, expect $EXPECT): pod $phase"
