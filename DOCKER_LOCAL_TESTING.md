# Docker Local Testing Guide

## Error Fixed
✅ Fixed `AttributeError: 'TextClause' object has no attribute 'bindparam'` by replacing `.bindparam()` with `.params()` in SQLAlchemy text queries.

## Building the Docker Image

Build the image the same way you normally do:

```bash
docker build -t test_a3 .
```

## Running with Fresh Database (Default)

If you want to test with a fresh database:

```bash
docker run -it -p 8080:8080 test_a3
```

## Running with Your Existing Database from OpenShift

To use your existing `webui.db` file from the OpenShift cluster, you need to mount it into the container.

### Option 1: Mount the Database File Directly (Recommended)

Place your `webui.db` file in a local directory (e.g., `./local-data/`) and mount it:

```bash
# Create a directory for your local data
mkdir -p ./local-data

# Copy your webui.db file to this directory
# (Assuming you've already copied it from OpenShift)
cp /path/to/your/webui.db ./local-data/webui.db

# Run Docker with the database mounted
docker run -it -p 8080:8080 \
  -v $(pwd)/local-data:/app/backend/data \
  test_a3
```

**Important Notes:**
- The database file must be named `webui.db` (not `ollama.db` or anything else)
- The mount point `/app/backend/data` is where OpenWebUI stores all its data
- Make sure the file has proper permissions (readable/writable)

### Option 2: Mount Only the Database File

If you want to mount just the database file (not the entire data directory):

```bash
# Create a directory for your database
mkdir -p ./local-db

# Copy your webui.db file
cp /path/to/your/webui.db ./local-db/webui.db

# Run Docker with just the database file mounted
docker run -it -p 8080:8080 \
  -v $(pwd)/local-db/webui.db:/app/backend/data/webui.db \
  test_a3
```

### Option 3: Use DATABASE_URL Environment Variable

If your database is in a different location, you can override the database path:

```bash
docker run -it -p 8080:8080 \
  -v $(pwd)/local-db:/mnt/db \
  -e DATABASE_URL="sqlite:///mnt/db/webui.db" \
  test_a3
```

## Using PostgreSQL (Like in OpenShift)

If you want to test with PostgreSQL (matching your OpenShift setup), you can:

### Option A: Use an External PostgreSQL Database

```bash
docker run -it -p 8080:8080 \
  -e DATABASE_URL="postgresql://user:password@host:5432/dbname" \
  test_a3
```

### Option B: Run PostgreSQL in Docker Compose

Create a `docker-compose.local.yml`:

```yaml
version: '3.8'

services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: openwebui
      POSTGRES_PASSWORD: yourpassword
      POSTGRES_DB: openwebui
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  webui:
    build: .
    ports:
      - "8080:8080"
    environment:
      DATABASE_URL: postgresql://openwebui:yourpassword@postgres:5432/openwebui
    depends_on:
      - postgres

volumes:
  postgres_data:
```

Then run:
```bash
docker-compose -f docker-compose.local.yml up
```

## Important Considerations

1. **Database Compatibility**: Make sure the database schema matches. If you're using a database from a different version, you may need to run migrations:
   ```bash
   docker run -it test_a3 alembic upgrade head
   ```

2. **File Permissions**: On Linux/Mac, ensure the mounted files have correct permissions:
   ```bash
   chmod 644 ./local-data/webui.db
   ```

3. **Vector Database**: If you're using Chroma (default), the vector database is stored in `/app/backend/data/vector_db`. You may want to mount that too:
   ```bash
   docker run -it -p 8080:8080 \
     -v $(pwd)/local-data:/app/backend/data \
     test_a3
   ```

4. **Data Persistence**: Any changes made in the container will be persisted to your mounted volume, so be careful not to corrupt your production database copy.

## Testing Performance

Once running with your existing database:

1. Access the UI at `http://localhost:8080`
2. Test tab switching (Models → Knowledge → Prompts → Tools)
3. Monitor the logs for query performance:
   ```bash
   docker logs -f <container_id>
   ```
4. Check the `X-Process-Time` header in responses to see API response times

## Troubleshooting

### Database Locked Error
If you get a "database is locked" error, make sure:
- Only one container is accessing the database file at a time
- The file permissions allow read/write access

### Migration Errors
If you see migration errors, you may need to run migrations manually:
```bash
docker run -it --rm \
  -v $(pwd)/local-data:/app/backend/data \
  test_a3 \
  alembic upgrade head
```

### Permission Denied
On Linux, you might need to adjust file ownership:
```bash
sudo chown -R $USER:$USER ./local-data
```

