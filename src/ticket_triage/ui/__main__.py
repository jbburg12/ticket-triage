"""`uv run python -m ticket_triage.ui [--port 8000]` starts the UI on localhost."""

import argparse

import truststore
import uvicorn
from dotenv import load_dotenv

from ticket_triage.ui.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the ticket-triage web UI.")
    parser.add_argument("--host", default="127.0.0.1", help="Default: localhost only.")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    # Same setup as the CLI: OS certificate store for HTTPS, API keys from .env.
    truststore.inject_into_ssl()
    load_dotenv()
    print(f"ticket-triage UI: http://{args.host}:{args.port}")
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
