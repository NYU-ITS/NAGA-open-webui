# How to Run PilotGenAI on Mac

This guide explains how to set up and run the PilotGenAI project (based on Open WebUI) on macOS.

## Prerequisites

- **Python 3.11** (required - other versions may cause compatibility issues)
- **Node.js** >= 18.13.0 and <= 22.x.x
- **npm** >= 6.0.0

### Check your versions:
```bash
python3 --version  # Should be 3.11.x
node --version     # Should be v18.x - v22.x
npm --version      # Should be 6.x or higher
```

## Setup Instructions

### 1. Backend Setup

Navigate to the backend directory:
```bash
cd backend
```

#### Create a Python virtual environment (if not exists):
```bash
python3.11 -m venv venv
```

#### Activate the virtual environment:
```bash
source venv/bin/activate
```

#### Install dependencies:

Due to complex dependency resolution, install with `--no-deps` first, then install subdependencies:
```bash
pip install --no-deps -r requirements.txt
pip install numpy pillow pyyaml click packaging platformdirs torch scipy scikit-learn
# Additional dependencies will be installed as needed
```

**Note:** The full dependency installation can be complex. If you encounter "resolution-too-deep" errors, try installing packages in smaller batches.

#### Start the backend server:
```bash
# Option 1: Using dev.sh (with hot reload)
./dev.sh

# Option 2: Using uvicorn directly
export CORS_ALLOW_ORIGIN="http://localhost:5173"
uvicorn open_webui.main:app --port 8080 --host 0.0.0.0 --forwarded-allow-ips '*' --reload
```

The backend will be available at: `http://localhost:8080`

### 2. Frontend Setup

Navigate to the project root directory:
```bash
cd /path/to/NAGA-open-webui
```

#### Install npm dependencies:
```bash
npm install
```

#### Start the frontend development server:
```bash
npm run dev
```

The frontend will be available at: `http://localhost:5173`

## Verification

### Check Backend Health:
```bash
curl http://localhost:8080/health
# Expected response: {"status":true}
```

### Access the Application:
Open your browser and navigate to: `http://localhost:5173`

## Running Both Servers Together

You'll need two terminal windows/tabs:

**Terminal 1 (Backend):**
```bash
cd backend
source venv/bin/activate
./dev.sh
```

**Terminal 2 (Frontend):**
```bash
npm run dev
```

## Troubleshooting

### 1. Python Version Issues
If you see import errors or compatibility issues, ensure you're using Python 3.11:
```bash
# On Mac with Homebrew
brew install python@3.11
python3.11 -m venv venv
source venv/bin/activate
```

### 2. Dependency Resolution Errors
If pip fails with "resolution-too-deep" error:
```bash
# Install without dependency resolution first
pip install --no-deps -r requirements.txt

# Then install critical dependencies manually
pip install numpy torch transformers langchain openai anthropic
```

### 3. Port Already in Use
If port 8080 or 5173 is already in use:
```bash
# Find and kill the process
lsof -ti:8080 | xargs kill -9
lsof -ti:5173 | xargs kill -9
```

### 4. Node.js Version Issues
If npm install fails, check your Node version:
```bash
node --version
# If too old or too new, use nvm to switch versions:
nvm install 20
nvm use 20
```

### 5. Missing System Dependencies
Some packages require system libraries. On Mac:
```bash
# For weasyprint (PDF generation)
brew install pango

# For image processing
brew install libmagic
```

### 6. Backend Import Errors
If you see module import errors, the venv might be corrupted:
```bash
cd backend
rm -rf venv
python3.11 -m venv venv
source venv/bin/activate
pip install --no-deps -r requirements.txt
```

## Environment Variables

You can create a `.env` file in the backend directory for configuration:
```bash
# Example .env file
CORS_ALLOW_ORIGIN=http://localhost:5173
PORT=8080
HOST=0.0.0.0
```

## Useful Commands

| Command | Description |
|---------|-------------|
| `npm run dev` | Start frontend dev server |
| `npm run build` | Build frontend for production |
| `./backend/dev.sh` | Start backend with hot reload |
| `./backend/start.sh` | Start backend for production |
| `pip check` | Verify Python dependencies |

## Common Issues and Solutions

| Issue | Solution |
|-------|----------|
| `ModuleNotFoundError` | Run `pip install <module-name>` |
| `CORS error in browser` | Ensure CORS_ALLOW_ORIGIN is set correctly |
| `Database connection error` | Check DATABASE_URL in environment |
| `WebSocket connection failed` | Ensure both backend and frontend are running |
