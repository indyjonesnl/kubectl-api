# Kubernetes Read-Only API

A FastAPI server that wraps `kubectl` to expose read-only Kubernetes cluster data over HTTP. Designed for LLM agents to query cluster state without risk of mutating resources.

## Prerequisites

- Python 3.10+
- `kubectl` installed and configured with access to your cluster
- A virtual environment (already set up in `.venv/`)

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Start the server

```bash
./run.sh
```

This starts the server on `http://127.0.0.1:8000` with auto-reload enabled.

To use a different port:

```bash
PORT=9000 ./run.sh
```

## Stop the server

Press `Ctrl+C` in the terminal where the server is running.

## API endpoints

All query endpoints are read-only (GET). The only mutation is context switching, which modifies `~/.kube/config` on the developer machine but does not alter any Kubernetes cluster state.

| Endpoint | Description |
|---|---|
| `GET /api-resources` | List all available Kubernetes resource types |
| `GET /namespaces` | List all namespace names |
| `GET /resources/{type}` | List resources (e.g. pods, deployments, services) |
| `GET /resources/{type}/{name}` | Get a single resource as JSON |
| `GET /describe/{type}/{name}` | Human-readable `kubectl describe` output |
| `GET /logs/{pod_name}` | Retrieve pod logs |
| `GET /events` | Cluster events sorted by timestamp |
| `GET /top/pods` | Pod CPU and memory usage |
| `GET /top/nodes` | Node CPU and memory usage                       |
| `GET /contexts` | List all kubeconfig contexts (indicates current)  |
| `GET /current-context` | Get the active kubeconfig context name              |
| `POST /contexts/{name}` | Switch to a different kubeconfig context             |
| `GET /clusters` | List all cluster names in kubeconfig              |

### Common query parameters

| Parameter | Endpoints | Description |
|---|---|---|
| `namespace` | All | Scope the query to a specific namespace |
| `label_selector` | `/resources/{type}` | Kubernetes label selector, e.g. `app=nginx` |
| `field_selector` | `/resources/{type}` | Field selector, e.g. `status.phase=Running` |
| `container` | `/logs/{pod}` | Container name for multi-container pods |
| `tail` | `/logs/{pod}` | Number of log lines (default: 100, max: 5000) |
| `previous` | `/logs/{pod}` | Show logs from the previous container instance |

## Interactive docs

Swagger UI is available at `http://127.0.0.1:8000/docs` when the server is running.

## Examples

```bash
# List all namespaces
curl http://127.0.0.1:8000/namespaces

# List pods in kube-system
curl 'http://127.0.0.1:8000/resources/pods?namespace=kube-system'

# Get a specific deployment
curl 'http://127.0.0.1:8000/resources/deployments/my-app?namespace=production'

# Get logs from a pod
curl 'http://127.0.0.1:8000/logs/my-pod?namespace=default&tail=50'

# List all services with a label selector
curl 'http://127.0.0.1:8000/resources/services?label_selector=app=nginx'

# List all kubeconfig contexts
curl http://127.0.0.1:8000/contexts

# Get the current context
curl http://127.0.0.1:8000/current-context

# Switch to a different context
curl -X POST http://127.0.0.1:8000/contexts/my-other-cluster

# List all clusters in kubeconfig
curl http://127.0.0.1:8000/clusters
```
