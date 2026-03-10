"""Thin wrapper around the kubectl CLI — read-only operations only."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Optional


class KubectlError(Exception):
    def __init__(self, message: str, returncode: int):
        super().__init__(message)
        self.returncode = returncode


async def _run(args: list[str], timeout: float = 30.0) -> str:
    """Run a kubectl command and return its stdout."""
    proc = await asyncio.create_subprocess_exec(
        "kubectl",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise KubectlError("kubectl command timed out", returncode=-1)

    if proc.returncode != 0:
        raise KubectlError(
            stderr.decode().strip() or "unknown kubectl error",
            returncode=proc.returncode,
        )
    return stdout.decode()


async def get_api_resources() -> list[dict[str, Any]]:
    """Return the list of available API resource types."""
    raw = await _run(["api-resources", "--verbs=list", "-o", "wide", "--no-headers"])
    resources = []
    for line in raw.strip().splitlines():
        parts = line.split()
        if len(parts) >= 5:
            name = parts[0]
            # The "wide" output columns: NAME SHORTNAMES APIVERSION NAMESPACED KIND VERBS
            # But SHORTNAMES can be empty, making column count variable.
            # Parse from the known fixed columns.
            namespaced = "true" in line.lower().split()
            kind = next(
                (p for i, p in enumerate(parts) if p in ("true", "false") and i > 0),
                None,
            )
            namespaced = kind == "true" if kind else False
            resources.append({"name": name, "namespaced": namespaced})
    return resources


async def get_namespaces() -> list[str]:
    """Return the list of namespace names."""
    raw = await _run(["get", "namespaces", "-o", "jsonpath={.items[*].metadata.name}"])
    return raw.strip().split() if raw.strip() else []


async def list_resources(
    resource_type: str,
    namespace: str | None = None,
    label_selector: str | None = None,
    field_selector: str | None = None,
) -> dict[str, Any]:
    """kubectl get <resource_type> -o json, optionally scoped to a namespace."""
    _validate_safe_arg(resource_type)
    args = ["get", resource_type, "-o", "json"]
    if namespace:
        _validate_safe_arg(namespace)
        args.extend(["-n", namespace])
    else:
        args.append("--all-namespaces")
    if label_selector:
        _validate_safe_arg(label_selector)
        args.extend(["-l", label_selector])
    if field_selector:
        _validate_safe_arg(field_selector)
        args.extend(["--field-selector", field_selector])
    raw = await _run(args, timeout=60.0)
    return json.loads(raw)


async def get_resource(
    resource_type: str,
    name: str,
    namespace: str | None = None,
) -> dict[str, Any]:
    """kubectl get <resource_type> <name> -o json."""
    _validate_safe_arg(resource_type)
    _validate_safe_arg(name)
    args = ["get", resource_type, name, "-o", "json"]
    if namespace:
        _validate_safe_arg(namespace)
        args.extend(["-n", namespace])
    raw = await _run(args, timeout=30.0)
    return json.loads(raw)


async def describe_resource(
    resource_type: str,
    name: str,
    namespace: str | None = None,
) -> str:
    """kubectl describe <resource_type> <name>."""
    _validate_safe_arg(resource_type)
    _validate_safe_arg(name)
    args = ["describe", resource_type, name]
    if namespace:
        _validate_safe_arg(namespace)
        args.extend(["-n", namespace])
    return await _run(args, timeout=30.0)


async def get_logs(
    pod_name: str,
    namespace: str | None = None,
    container: str | None = None,
    tail_lines: int = 100,
    previous: bool = False,
) -> str:
    """kubectl logs — read-only log retrieval."""
    _validate_safe_arg(pod_name)
    args = ["logs", pod_name, f"--tail={tail_lines}"]
    if namespace:
        _validate_safe_arg(namespace)
        args.extend(["-n", namespace])
    if container:
        _validate_safe_arg(container)
        args.extend(["-c", container])
    if previous:
        args.append("--previous")
    return await _run(args, timeout=30.0)


async def top_pods(namespace: str | None = None) -> str:
    """kubectl top pods."""
    args = ["top", "pods"]
    if namespace:
        _validate_safe_arg(namespace)
        args.extend(["-n", namespace])
    else:
        args.append("--all-namespaces")
    return await _run(args, timeout=30.0)


async def top_nodes() -> str:
    """kubectl top nodes."""
    return await _run(["top", "nodes"], timeout=30.0)


async def get_contexts() -> list[dict[str, str]]:
    """kubectl config get-contexts — list all available contexts."""
    raw = await _run(["config", "get-contexts", "--no-headers"], timeout=10.0)
    contexts = []
    for line in raw.strip().splitlines():
        # Columns: CURRENT  NAME  CLUSTER  AUTHINFO  NAMESPACE
        # CURRENT is '*' or blank
        current = line.startswith("*")
        parts = line.lstrip("* ").split()
        if parts:
            ctx: dict[str, str] = {"name": parts[0], "current": str(current).lower()}
            if len(parts) >= 2:
                ctx["cluster"] = parts[1]
            if len(parts) >= 3:
                ctx["authinfo"] = parts[2]
            if len(parts) >= 4:
                ctx["namespace"] = parts[3]
            contexts.append(ctx)
    return contexts


async def get_current_context() -> str:
    """kubectl config current-context."""
    raw = await _run(["config", "current-context"], timeout=10.0)
    return raw.strip()


async def use_context(context_name: str) -> str:
    """kubectl config use-context <name>."""
    _validate_safe_arg(context_name)
    raw = await _run(["config", "use-context", context_name], timeout=10.0)
    return raw.strip()


async def get_clusters() -> list[str]:
    """kubectl config get-clusters."""
    raw = await _run(["config", "get-clusters"], timeout=10.0)
    lines = raw.strip().splitlines()
    # First line is the "NAME" header
    return lines[1:] if len(lines) > 1 else []


async def get_events(namespace: str | None = None) -> dict[str, Any]:
    """kubectl get events -o json."""
    args = ["get", "events", "-o", "json", "--sort-by=.lastTimestamp"]
    if namespace:
        _validate_safe_arg(namespace)
        args.extend(["-n", namespace])
    else:
        args.append("--all-namespaces")
    raw = await _run(args, timeout=30.0)
    return json.loads(raw)


def _validate_safe_arg(value: str) -> None:
    """Reject values that could be used for command injection."""
    if not value or any(c in value for c in (";", "|", "&", "`", "$", "(", ")", "\n", "\r")):
        raise KubectlError(f"Invalid argument: {value!r}", returncode=1)
