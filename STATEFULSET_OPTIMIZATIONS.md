# StatefulSet Optimization Guide

This document explains three key optimizations for your Open WebUI StatefulSet deployment on OpenShift/Kubernetes.

---

## 1. Health Probes (Liveness & Readiness)

### What They Do

**Liveness Probe**: Checks if the container is still running. If it fails, Kubernetes restarts the pod.

**Readiness Probe**: Checks if the container is ready to accept traffic. If it fails, Kubernetes removes the pod from service endpoints (stops routing traffic to it).

### How They Work

- **Liveness Probe**: 
  - Periodically checks if your app is alive
  - If it fails `failureThreshold` times, Kubernetes kills and restarts the pod
  - Prevents serving requests from dead/hung processes

- **Readiness Probe**:
  - Checks if your app is ready to handle requests
  - If it fails, the pod is removed from the Service's endpoint list
  - Traffic stops being routed to unhealthy pods
  - Pod stays running (not restarted) - allows it to recover

### Implementation

Your application already has a `/health` endpoint at `backend/open_webui/main.py:1487`:

```python
@app.get("/health")
async def healthcheck():
    return {"status": True}
```

Add this to your StatefulSet YAML:

```yaml
spec:
  template:
    spec:
      containers:
      - name: open-webui
        # Liveness Probe - detects and restarts dead pods
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 30    # Wait 30s after container starts
          periodSeconds: 10         # Check every 10 seconds
          timeoutSeconds: 5         # Timeout after 5 seconds
          failureThreshold: 3       # Restart after 3 consecutive failures
        
        # Readiness Probe - controls traffic routing
        readinessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 10   # Wait 10s after container starts
          periodSeconds: 5          # Check every 5 seconds
          timeoutSeconds: 3         # Timeout after 3 seconds
          failureThreshold: 3       # Remove from service after 3 failures
```

### Benefits

1. **Faster Recovery**: Dead pods are automatically restarted (liveness)
2. **Better Traffic Routing**: Only healthy pods receive traffic (readiness)
3. **Prevents Bad User Experience**: Users don't hit pods that are starting up or crashed
4. **Automatic Healing**: System self-heals without manual intervention
5. **Zero-Downtime Deployments**: Readiness probe ensures new pods are fully ready before receiving traffic

### Real-World Impact

- **Before**: If a pod crashes, users might get 500 errors for minutes until you manually notice and restart
- **After**: Pod automatically restarts within ~30 seconds (3 failures × 10s period), and traffic is routed away during recovery

---

## 2. Pod Anti-Affinity

### What It Does

Pod Anti-Affinity ensures that pods are distributed across different nodes (physical/virtual machines) in your cluster.

### How It Works

- **Preferred Anti-Affinity** (soft rule): Kubernetes tries to schedule pods on different nodes, but will allow same-node if necessary
- **Required Anti-Affinity** (hard rule): Kubernetes will NOT schedule pods on the same node (may prevent scheduling if not enough nodes)

### Implementation

Add this to your StatefulSet YAML:

```yaml
spec:
  template:
    spec:
      affinity:
        podAntiAffinity:
          # Use "preferred" to allow flexibility, or "required" for strict distribution
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            podAffinityTerm:
              labelSelector:
                matchExpressions:
                - key: app.kubernetes.io/component
                  operator: In
                  values:
                  - open-webui
              topologyKey: kubernetes.io/hostname  # Distribute across nodes
```

**Important**: Make sure your pods have the label `app.kubernetes.io/component: open-webui`:

```yaml
spec:
  template:
    metadata:
      labels:
        app.kubernetes.io/component: open-webui
        app.kubernetes.io/name: open-webui
```

### Benefits

1. **High Availability**: If one node fails, other pods on different nodes continue serving
2. **Better Resource Distribution**: Spreads load across all available nodes
3. **Improved Resilience**: Single node failure doesn't take down all replicas
4. **Better Performance**: Reduces contention for CPU/memory/network on a single node

### Real-World Impact

**Scenario**: You have 3 replicas and 3 nodes

- **Without Anti-Affinity**: All 3 pods might end up on Node 1
  - If Node 1 crashes → **100% downtime**
  - Node 1 is overloaded → **poor performance**
  
- **With Anti-Affinity**: 1 pod per node (Node 1, Node 2, Node 3)
  - If Node 1 crashes → **33% capacity loss, but service continues**
  - Load is balanced → **better performance**

---

## 3. Environment Variables for Optimization

### ⚠️ NOT RECOMMENDED for Kubernetes/Helm Deployments

**Important**: According to Open WebUI documentation, when deploying in orchestrated environments like Kubernetes or using Helm charts, **keep `UVICORN_WORKERS=1` (default)**.

### Why Not Use Multiple Workers in Kubernetes?

1. **Kubernetes Already Scales**: Container orchestration platforms provide scaling through pod replication
2. **Resource Allocation Issues**: Multiple workers inside containers can cause resource conflicts
3. **Complicates Horizontal Scaling**: HPA (Horizontal Pod Autoscaler) works better with single-worker pods
4. **Better Isolation**: One worker per pod = better fault isolation and resource management

### What This Means for Your Setup

Since you're using:
- ✅ Kubernetes/OpenShift
- ✅ Helm charts
- ✅ HPA (Horizontal Pod Autoscaler)

**You should NOT configure multiple workers**. Instead:

1. **Keep `UVICORN_WORKERS=1`** (or don't set it, as 1 is the default)
2. **Scale horizontally** by increasing pod replicas via HPA
3. **Let Kubernetes handle scaling** rather than scaling within containers

### When Would You Use Multiple Workers?

Multiple workers are beneficial for:
- **Standalone deployments** (not orchestrated)
- **Single-server deployments** (no Kubernetes)
- **Docker Compose** (limited scaling options)

### Your Current Configuration

Your `backend/start.sh` already uses the correct setup:
```bash
uvicorn open_webui.main:app --host "$HOST" --port "$PORT" --forwarded-allow-ips '*'
```

This runs with 1 worker (default), which is perfect for Kubernetes. **No changes needed!**

### Alternative: Scale via HPA

Instead of multiple workers per pod, scale pods:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: open-webui-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: StatefulSet
    name: open-webui
  minReplicas: 3
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

**Benefits of HPA over multiple workers:**
- ✅ Better resource isolation
- ✅ Independent scaling per pod
- ✅ Easier monitoring and debugging
- ✅ Follows Kubernetes best practices

---

## Complete Example StatefulSet

Here's a complete example combining all optimizations:

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: open-webui
spec:
  serviceName: open-webui
  replicas: 3
  selector:
    matchLabels:
      app.kubernetes.io/name: open-webui
  template:
    metadata:
      labels:
        app.kubernetes.io/name: open-webui
        app.kubernetes.io/component: open-webui
    spec:
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            podAffinityTerm:
              labelSelector:
                matchExpressions:
                - key: app.kubernetes.io/component
                  operator: In
                  values:
                  - open-webui
              topologyKey: kubernetes.io/hostname
      containers:
      - name: open-webui
        image: your-image:tag
        ports:
        - containerPort: 8080
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: db-secret
              key: url
        - name: DATABASE_POOL_SIZE
          value: '15'
        - name: DATABASE_POOL_MAX_OVERFLOW
          value: '5'
        # Note: UVICORN_WORKERS should remain 1 (default) for Kubernetes
        # Scale via HPA instead of multiple workers per pod
        # Health Probes
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 3
        readinessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 5
          timeoutSeconds: 3
          failureThreshold: 3
        resources:
          requests:
            memory: "2Gi"
            cpu: "2"
          limits:
            memory: "4Gi"
            cpu: "4"
```

---

## Summary of Benefits

| Optimization | Primary Benefit | Impact Level | Kubernetes/Helm |
|-------------|----------------|--------------|----------------|
| **Health Probes** | Automatic recovery & traffic routing | High - Critical for production | ✅ **Recommended** |
| **Pod Anti-Affinity** | High availability & resilience | Medium - Important for multi-node clusters | ✅ **Recommended** |
| **Worker Configuration** | Better concurrency & throughput | Medium - Depends on workload type | ❌ **NOT Recommended** |

## Recommended Implementation Order

1. **Health Probes** (Do first - critical for production) ✅
2. **Pod Anti-Affinity** (Do if you have 3+ nodes) ✅
3. **Worker Configuration** (Skip - use HPA for scaling instead) ❌

### For Kubernetes/Helm Deployments

**Focus on:**
- ✅ Health Probes (critical)
- ✅ Pod Anti-Affinity (if multi-node)
- ✅ HPA (Horizontal Pod Autoscaler) for scaling

**Skip:**
- ❌ Multiple workers per pod
- ❌ Worker configuration environment variables

---

## Testing

After implementing, test each optimization:

1. **Health Probes**: 
   ```bash
   # Kill a pod process and watch it restart
   kubectl exec <pod> -- kill 1
   kubectl get pods -w  # Watch it restart
   ```

2. **Anti-Affinity**:
   ```bash
   # Check pod distribution
   kubectl get pods -o wide
   # Should see pods on different nodes
   ```

3. **HPA Scaling** (instead of workers):
   ```bash
   # Check HPA status
   kubectl get hpa
   
   # Check current pod count
   kubectl get pods -l app.kubernetes.io/name=open-webui
   
   # Watch HPA scale up/down under load
   kubectl get hpa -w
   ```

