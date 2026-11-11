"""Launch a single evaluation application process."""

import argparse
from pathlib import Path

import uvicorn

from .bootstrap import create_app


def main() -> None:
    """Parse explicit storage and bind options before constructing the app."""
    parser = argparse.ArgumentParser(
        description="Run Intelligence Degradation Detection"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--web-dir", type=Path)
    args = parser.parse_args()
    uvicorn.run(
        create_app(args.data_dir, args.web_dir),
        host=args.host,
        port=args.port,
        workers=1,
        access_log=False,
    )


if __name__ == "__main__":
    main()
