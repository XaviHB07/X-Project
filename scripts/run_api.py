#!/usr/bin/env python3
"""Levanta la API de producción con uvicorn.

Uso:
    python scripts/run_api.py
    python scripts/run_api.py --port 8080 --reload

Equivalente directo (si se prefiere invocar uvicorn a mano):
    uvicorn src.api.main:app --reload
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="Recarga automática al editar código (desarrollo).")
    return parser.parse_args()


def main() -> None:
    import uvicorn

    args = parse_args()
    uvicorn.run("src.api.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
