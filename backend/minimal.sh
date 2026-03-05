#!/bin/bash
# minimal.sh - Run backend for local macOS dev only.
#
# WHY THIS FILE EXISTS:
#   dev.sh, start.sh, and use_local_model.sh all fail on macOS because the backend
#   imports two packages at startup that require system-level libraries not available
#   on macOS. This script works around both without touching any source code.
#
# WHAT IS BROKEN AND WHY:
#
#   1. weasyprint (PDF export)
#      - Imported unconditionally in: routers/chats.py -> utils/pdf_generator.py
#      - Needs libgobject-2.0 (part of GTK/GLib), a Linux system library.
#      - Fix: we create a fake weasyprint package in ./minimal_stubs/weasyprint/
#        that stubs out the HTML class. By prepending ./minimal_stubs to PYTHONPATH,
#        Python finds our stub before the real (broken) weasyprint in the venv.
#        PYTHONPATH is only set for this script's process, so dev.sh/start.sh
#        are completely unaffected.
#        Side effect: PDF export silently returns empty bytes locally (acceptable).
#
#   2. rq / Redis Queue (distributed job processing)
#      - Imported unconditionally in: routers/retrieval.py -> utils/job_queue.py
#      - Needs Redis running + the rq package installed.
#      - The app has an ENABLE_JOB_QUEUE flag, but the import happens before
#        any flag is checked, so it crashes regardless.
#      - Fix part A: set ENABLE_JOB_QUEUE=False so the job queue logic is skipped
#        at runtime. This env var is process-scoped and does not affect other scripts.
#      - Fix part B: install rq into the venv if missing, so the import itself
#        doesn't crash. rq is a pure Python package with no native dependencies,
#        so this is safe. Installing it also helps dev.sh/start.sh if someone
#        tries them later (they would have crashed on rq too).
#
# ISOLATION — does this affect dev.sh / start.sh / use_local_model.sh?
#   - PYTHONPATH: NO  — set only for this process, not inherited by other shells.
#   - ENABLE_JOB_QUEUE: NO  — same, process-scoped.
#   - rq install: rq is installed into the venv permanently, but this only helps
#     the other scripts; they would have failed on the missing rq import anyway.
#   - minimal_stubs/ directory: NO — it's just a folder, inert unless PYTHONPATH
#     points to it.

PORT="${PORT:-8080}"
export CORS_ALLOW_ORIGIN="http://localhost:5173"
export ENABLE_JOB_QUEUE="False"

# Prepend stubs dir so our fake weasyprint shadows the real broken one in the venv
export PYTHONPATH="$(pwd)/minimal_stubs:$PYTHONPATH"

# Install rq if missing — it's a pure Python package, safe to add to the venv
if ! python -c "import rq" 2>/dev/null; then
    echo "Installing missing 'rq' package into venv..."
    pip install rq --quiet
fi

uvicorn open_webui.main:app \
    --port $PORT \
    --host 0.0.0.0 \
    --forwarded-allow-ips '*' \
    --reload
