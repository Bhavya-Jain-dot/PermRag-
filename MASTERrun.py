"""Start PermRAG with the protected Master Control Center enabled."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.server import serve


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run PermRAG with the Master Control Center")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    arguments = parser.parse_args()
    serve(Path(__file__).resolve().parent, arguments.host, arguments.port, master_enabled=True)
