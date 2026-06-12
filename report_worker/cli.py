from __future__ import annotations

import argparse
import json
import logging

from .config import Settings
from .providers import create_provider
from .worker import ReportWorker


def main() -> None:
    parser = argparse.ArgumentParser(description="Arabic report platform local worker")
    subparsers = parser.add_subparsers(dest="command", required=True)

    test_parser = subparsers.add_parser("test-provider")
    test_parser.add_argument("--provider", choices=["local", "gemini"], required=True)
    test_parser.add_argument("--model")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--once", action="store_true")

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
    )
    settings = Settings()

    if args.command == "test-provider":
        result = create_provider(args.provider, settings, args.model).healthcheck()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result.get("ok") else 1)

    worker = ReportWorker(settings)
    if args.once:
        print(json.dumps({"processed_job": worker.run_once()}, ensure_ascii=False))
    else:
        worker.run_forever()


if __name__ == "__main__":
    main()
