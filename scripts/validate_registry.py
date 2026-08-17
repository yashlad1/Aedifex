"""Validate the source registry and print a review-status summary.

Run with no infrastructure:

    python -m scripts.validate_registry
    python -m scripts.validate_registry --dir config/sources

Exits non-zero if the registry is invalid, so it can be used as a CI gate and as a
pre-commit check. The summary doubles as the report on outstanding terms-of-use review work.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from aedifex.acquisition.registry import load_registry
from aedifex.acquisition.registry.models import VerificationStatus
from aedifex.errors import SourceRegistryError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dir",
        type=Path,
        default=Path("config/sources"),
        help="Directory of registry YAML files (default: config/sources)",
    )
    arguments = parser.parse_args(argv)

    try:
        registry = load_registry(arguments.dir)
    except SourceRegistryError as error:
        print(f"FAIL  {error}", file=sys.stderr)
        return 1

    by_status: dict[VerificationStatus, list[str]] = {status: [] for status in VerificationStatus}
    for source in registry:
        by_status[source.verification_status].append(source.id)

    print(f"OK  {len(registry)} source(s) in {arguments.dir}\n")
    print(f"{'SOURCE':<28} {'ENABLED':<8} {'REVIEW':<12} {'ACCESS':<22} RATE")
    print("-" * 88)
    for source in registry:
        rate = f"{source.rate_limit.requests_per_minute}/min"
        print(
            f"{source.id:<28} "
            f"{'yes' if source.enabled else 'no':<8} "
            f"{source.verification_status.value:<12} "
            f"{source.data_use.access.value:<22} "
            f"{rate}"
        )

    collectable = registry.collectable()
    print(f"\nCollectable now: {len(collectable)} of {len(registry)}")
    if collectable:
        print("  " + ", ".join(source.id for source in collectable))

    pending = by_status[VerificationStatus.UNVERIFIED]
    if pending:
        print(f"\nAwaiting terms-of-use review ({len(pending)}):")
        for source_id in pending:
            print(f"  - {source_id}")
        print("\nThese cannot be collected from until reviewed. See DATA_SOURCES.md.")

    blocked = by_status[VerificationStatus.BLOCKED]
    if blocked:
        print(f"\nBlocked by review ({len(blocked)}): {', '.join(blocked)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
