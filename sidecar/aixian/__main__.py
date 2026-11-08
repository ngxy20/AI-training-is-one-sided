"""Run the sidecar: python -m aixian [--port 8756]."""
from __future__ import annotations

import argparse
import os

import uvicorn

from . import config


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Training Studio local sidecar")
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument("--host", default=config.HOST)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    config.bootstrap()
    os.environ["AIXIAN_PORT"] = str(args.port)
    print(f"AI Training Studio sidecar http://{args.host}:{args.port}{config.API_PREFIX}")
    uvicorn.run("aixian.app:app", host=args.host, port=args.port,
                log_level="info", reload=args.reload)


if __name__ == "__main__":
    main()
