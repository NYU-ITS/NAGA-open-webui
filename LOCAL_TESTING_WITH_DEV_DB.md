# Testing Locally with Dev Cluster Database

This guide shows how to copy the `webui.db` file from your dev cluster and mount it locally for testing before pushing changes.

---

## Step 1: Find the Database Location

The database file is stored at:
- **Container path**: `/app/backend/data/webui.db`
- **Default location** when `DATABASE_URL` is not set (SQLite mode)

---

## Step 2: Copy Database from Dev Cluster Pod

### Option A: Using kubectl (Kubernetes/OpenShift)

```bash
# 1. Find your pod name
kubectl get pods -l app.kubernetes.io/name=open-webui

# 2. Copy the database file from the pod
kubectl cp <namespace>/<pod-name>:/app/backend/data/webui.db ./webui.db

# Example:
kubectl cp my-namespace/open-webui-0:/app/backend/data/webui.db ./webui.db
```

### Option B: Using oc (OpenShift)

```bash
# 1. Find your pod name
oc get pods -l app.kubernetes.io/name=open-webui

# 2. Copy the database file from the pod
oc cp <namespace>/<pod-name>:/app/backend/data/webui.db ./webui.db

# Example:
oc cp my-namespace/open-webui-0:/app/backend/data/webui.db ./webui.db
```

### Option C: Using kubectl exec + tar (if cp doesn't work)

```bash
# 1. Create a tar archive in the pod
kubectl exec <pod-name> -n <namespace> -- tar czf - /app/backend/data/webui.db > webui.db.tar.gz

# 2. Extract locally
tar xzf webui.db.tar.gz
mv app/backend/data/webui.db ./webui.db
rm -rf app webui.db.tar.gz
```

---

## Step 3: Create Local Data Directory

```bash
# Create the data directory structure locally
mkdir -p ./local-data
mv ./webui.db ./local-data/webui.db
```

---

## Step 4: Run Docker with Mounted Database

### Option A: Using docker run

```bash
# Build your image first (if needed)
docker build -t open-webui-local .

# Run with mounted database
docker run -it \
  -p 8080:8080 \
  -v $(pwd)/local-data:/app/backend/data \
  -e DATABASE_URL="" \
  --name open-webui-test \
  open-webui-local
```

### Option B: Using docker-compose

Create a `docker-compose.local.yml`:

```yaml
version: '3.8'

services:
  open-webui:
    build: .
    ports:
      - "8080:8080"
    volumes:
      # Mount the local database
      - ./local-data:/app/backend/data
    environment:
      # Use SQLite (empty DATABASE_URL means use default SQLite)
      - DATABASE_URL=
      # Or explicitly set SQLite path
      # - DATABASE_URL=sqlite:///app/backend/data/webui.db
    container_name: open-webui-test
```

Then run:
```bash
docker-compose -f docker-compose.local.yml up
```

### Option C: Using docker run with specific database path

```bash
docker run -it \
  -p 8080:8080 \
  -v $(pwd)/local-data:/app/backend/data \
  -e DATABASE_URL=sqlite:///app/backend/data/webui.db \
  --name open-webui-test \
  open-webui-local
```

---

## Step 5: Verify Database is Mounted

Once the container is running:

```bash
# Check if database file exists in container
docker exec open-webui-test ls -lh /app/backend/data/webui.db

# Check database size
docker exec open-webui-test stat /app/backend/data/webui.db
```

---

## Important Notes

### ⚠️ Database Locking (SQLite)

SQLite uses file locking. If you're testing while the dev cluster is still running:
- **Option 1**: Stop the dev cluster pod temporarily while copying
- **Option 2**: Copy the database, but be aware changes won't sync back
- **Option 3**: Use a read-only mount (see below)

### Read-Only Mount (Recommended for Testing)

To prevent accidental writes to your dev database copy:

```bash
docker run -it \
  -p 8080:8080 \
  -v $(pwd)/local-data:/app/backend/data:ro \
  -e DATABASE_URL=sqlite:///app/backend/data/webui.db \
  --name open-webui-test \
  open-webui-local
```

**Note**: Read-only mount means you can't test write operations. For full testing, use read-write.

### Backup Before Testing

Always backup before testing:

```bash
# Backup the copied database
cp ./local-data/webui.db ./local-data/webui.db.backup
```

---

## Quick Script: Copy and Run

Save this as `test-with-dev-db.sh`:

```bash
#!/bin/bash

# Configuration
NAMESPACE="your-namespace"
POD_NAME="open-webui-0"  # Adjust based on your pod name
LOCAL_DATA_DIR="./local-data"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Step 1: Copying database from dev cluster...${NC}"
kubectl cp ${NAMESPACE}/${POD_NAME}:/app/backend/data/webui.db ${LOCAL_DATA_DIR}/webui.db

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Database copied successfully${NC}"
else
    echo "✗ Failed to copy database"
    exit 1
fi

echo -e "${YELLOW}Step 2: Creating backup...${NC}"
cp ${LOCAL_DATA_DIR}/webui.db ${LOCAL_DATA_DIR}/webui.db.backup
echo -e "${GREEN}✓ Backup created${NC}"

echo -e "${YELLOW}Step 3: Starting Docker container...${NC}"
docker run -it \
  -p 8080:8080 \
  -v $(pwd)/${LOCAL_DATA_DIR}:/app/backend/data \
  -e DATABASE_URL= \
  --name open-webui-test \
  --rm \
  open-webui-local

echo -e "${GREEN}✓ Container stopped${NC}"
```

Make it executable:
```bash
chmod +x test-with-dev-db.sh
```

Run it:
```bash
./test-with-dev-db.sh
```

---

## Troubleshooting

### Issue: "database is locked"

**Solution**: The database might be in use. Try:
1. Copy the database when the pod is stopped/restarting
2. Use `kubectl exec` to check if the database is being accessed:
   ```bash
   kubectl exec <pod-name> -- fuser /app/backend/data/webui.db
   ```

### Issue: "No such file or directory"

**Solution**: The database might be in a different location:
1. Check where the database actually is:
   ```bash
   kubectl exec <pod-name> -- find /app -name "webui.db" 2>/dev/null
   ```
2. Or check if using PostgreSQL (DATABASE_URL set):
   ```bash
   kubectl exec <pod-name> -- env | grep DATABASE_URL
   ```

### Issue: Permission denied

**Solution**: The database file might have wrong permissions:
```bash
# Fix permissions locally
chmod 644 ./local-data/webui.db

# Or in container
docker exec open-webui-test chmod 644 /app/backend/data/webui.db
```

### Issue: Database schema mismatch

**Solution**: Your local code might have different migrations:
1. Check migration status:
   ```bash
   docker exec open-webui-test python -c "from open_webui.internal.db import engine; print(engine)"
   ```
2. Run migrations if needed (be careful - this modifies the database)

---

## Alternative: Using PostgreSQL Dump (If Using PostgreSQL)

If your dev cluster uses PostgreSQL instead of SQLite:

```bash
# 1. Get database credentials from pod
kubectl exec <pod-name> -- env | grep DATABASE_URL

# 2. Dump the database
kubectl exec <pod-name> -- pg_dump $DATABASE_URL > dev-db-dump.sql

# 3. Import locally
# Set up local PostgreSQL and import
psql -U postgres -d open_webui < dev-db-dump.sql

# 4. Run Docker with PostgreSQL
docker run -it \
  -p 8080:8080 \
  -e DATABASE_URL=postgresql://user:pass@host.docker.internal:5432/open_webui \
  --name open-webui-test \
  open-webui-local
```

---

## Best Practices

1. **Always backup** before testing
2. **Use read-only mount** if you only need to test reads
3. **Stop dev cluster pod** before copying to avoid locking issues
4. **Test in isolated environment** - don't test against production data
5. **Clean up** after testing:
   ```bash
   docker stop open-webui-test
   docker rm open-webui-test
   ```

---

## Summary

```bash
# Quick commands:
# 1. Copy database
kubectl cp <namespace>/<pod>:/app/backend/data/webui.db ./local-data/webui.db

# 2. Run locally
docker run -it -p 8080:8080 -v $(pwd)/local-data:/app/backend/data -e DATABASE_URL= --name open-webui-test open-webui-local

# 3. Access at http://localhost:8080
```

