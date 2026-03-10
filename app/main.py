"""
Kubernetes Read-Only API — a FastAPI server that wraps kubectl for LLM agents.

Only GET (list/read) operations are exposed. No create, update, patch, or delete
endpoints exist, making it safe for autonomous agents to query cluster state.

Kubernetes resource concepts:
- **Pods**: The smallest deployable unit; one or more containers sharing network/storage.
- **Deployments**: Declarative updates for Pods and ReplicaSets (rolling updates, scaling).
- **Services**: Stable network endpoint that routes traffic to a set of Pods.
- **Namespaces**: Virtual clusters that partition resources within a physical cluster.
- **ConfigMaps / Secrets**: Configuration data and sensitive values injected into Pods.
- **Nodes**: The worker machines (VMs or bare-metal) that run your workloads.
- **Events**: Records of state changes and errors — useful for debugging.
- **Ingress**: Rules for routing external HTTP(S) traffic to Services.

See https://kubernetes.io/docs/concepts/ for full documentation.
"""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse

from app.kubectl import (
    KubectlError,
    describe_resource,
    get_api_resources,
    get_clusters,
    get_contexts,
    get_current_context,
    get_events,
    get_logs,
    get_namespaces,
    get_resource,
    list_resources,
    top_nodes,
    top_pods,
    use_context,
)

app = FastAPI(
    title="Kubernetes Read-Only API",
    version="1.0.0",
    description=__doc__,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _handle_kubectl_error(e: KubectlError) -> None:
    status = 502 if e.returncode != 0 else 504
    if "not found" in str(e).lower() or "NotFound" in str(e):
        status = 404
    raise HTTPException(status_code=status, detail=str(e))


# ── Cluster overview ────────────────────────────────────────────────────────

@app.get("/api-resources", summary="List available API resource types")
async def api_resources():
    """Return every resource type the cluster supports (that allows listing)."""
    try:
        return await get_api_resources()
    except KubectlError as e:
        _handle_kubectl_error(e)


@app.get("/namespaces", summary="List all namespaces")
async def namespaces():
    """Return namespace names — useful to scope subsequent queries."""
    try:
        return await get_namespaces()
    except KubectlError as e:
        _handle_kubectl_error(e)


# ── Generic resource endpoints ──────────────────────────────────────────────

@app.get(
    "/resources/{resource_type}",
    summary="List resources of a given type",
)
async def resources_list(
    resource_type: str,
    namespace: str | None = Query(None, description="Scope to a specific namespace"),
    label_selector: str | None = Query(None, description="e.g. app=nginx"),
    field_selector: str | None = Query(None, description="e.g. status.phase=Running"),
):
    """
    List all resources of *resource_type* (e.g. pods, deployments, services).

    Without a namespace the query runs across **all** namespaces.
    Supports Kubernetes label selectors (`-l`) and field selectors (`--field-selector`).
    """
    try:
        return await list_resources(resource_type, namespace, label_selector, field_selector)
    except KubectlError as e:
        _handle_kubectl_error(e)


@app.get(
    "/resources/{resource_type}/{name}",
    summary="Get a single resource by name",
)
async def resource_get(
    resource_type: str,
    name: str,
    namespace: str | None = Query(None, description="Namespace of the resource"),
):
    """Retrieve the full JSON representation of a single resource."""
    try:
        return await get_resource(resource_type, name, namespace)
    except KubectlError as e:
        _handle_kubectl_error(e)


@app.get(
    "/describe/{resource_type}/{name}",
    summary="Describe a resource (human-readable)",
    response_class=PlainTextResponse,
)
async def resource_describe(
    resource_type: str,
    name: str,
    namespace: str | None = Query(None),
):
    """
    Return the human-readable `kubectl describe` output.

    Useful for seeing conditions, events, and status details at a glance.
    """
    try:
        return await describe_resource(resource_type, name, namespace)
    except KubectlError as e:
        _handle_kubectl_error(e)


# ── Pod logs ────────────────────────────────────────────────────────────────

@app.get(
    "/logs/{pod_name}",
    summary="Get pod logs",
    response_class=PlainTextResponse,
)
async def logs(
    pod_name: str,
    namespace: str | None = Query(None),
    container: str | None = Query(None, description="Container name (multi-container pods)"),
    tail: int = Query(100, description="Number of lines from the end", ge=1, le=5000),
    previous: bool = Query(False, description="Show logs from the previous container instance"),
):
    """
    Retrieve the most recent log lines from a pod.

    For multi-container pods, specify the `container` parameter.
    Use `previous=true` to see logs from a crashed container's prior run.
    """
    try:
        return await get_logs(pod_name, namespace, container, tail, previous)
    except KubectlError as e:
        _handle_kubectl_error(e)


# ── Events ──────────────────────────────────────────────────────────────────

@app.get("/events", summary="Get cluster events")
async def events(
    namespace: str | None = Query(None),
):
    """
    Events surface warnings, errors, and state transitions (e.g. image pull
    failures, OOMKilled, scheduling issues). Sorted by last timestamp.
    """
    try:
        return await get_events(namespace)
    except KubectlError as e:
        _handle_kubectl_error(e)


# ── Kubeconfig context management ──────────────────────────────────────────

@app.get("/contexts", summary="List all kubeconfig contexts")
async def contexts():
    """Return all contexts defined in kubeconfig, indicating which is current."""
    try:
        return await get_contexts()
    except KubectlError as e:
        _handle_kubectl_error(e)


@app.get("/current-context", summary="Get the current kubeconfig context")
async def current_context():
    """Return the name of the currently active context."""
    try:
        return {"context": await get_current_context()}
    except KubectlError as e:
        _handle_kubectl_error(e)


@app.post("/contexts/{context_name}", summary="Switch the current kubeconfig context")
async def switch_context(context_name: str):
    """
    Set the active kubectl context. This modifies ~/.kube/config on the
    developer machine but does **not** alter any Kubernetes cluster state.
    """
    try:
        message = await use_context(context_name)
        return {"message": message, "context": context_name}
    except KubectlError as e:
        _handle_kubectl_error(e)


@app.get("/clusters", summary="List all clusters in kubeconfig")
async def clusters():
    """Return cluster names defined in kubeconfig."""
    try:
        return await get_clusters()
    except KubectlError as e:
        _handle_kubectl_error(e)


# ── Resource usage (metrics) ───────────────────────────────────────────────

@app.get(
    "/top/pods",
    summary="Pod CPU and memory usage",
    response_class=PlainTextResponse,
)
async def pods_top(namespace: str | None = Query(None)):
    """Requires the Metrics Server to be installed in the cluster."""
    try:
        return await top_pods(namespace)
    except KubectlError as e:
        _handle_kubectl_error(e)


@app.get(
    "/top/nodes",
    summary="Node CPU and memory usage",
    response_class=PlainTextResponse,
)
async def nodes_top():
    """Requires the Metrics Server to be installed in the cluster."""
    try:
        return await top_nodes()
    except KubectlError as e:
        _handle_kubectl_error(e)
