#!/usr/bin/env python3
"""Create a strong bearer key and a digest-only mounted-secret file."""

import argparse
import hashlib
import json
import os
import secrets
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.tenant.strip():
        raise SystemExit("--tenant must not be blank")

    api_key = secrets.token_urlsafe(32)
    digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    payload = json.dumps({digest: args.tenant}, indent=2) + "\n"
    try:
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise SystemExit(f"refusing to overwrite existing secret: {args.output}") from error
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)

    print("Store this bearer key in your client secret manager; it is shown only now:")
    print(api_key)
    print(f"Digest-only server secret written to {args.output} with mode 0600")


if __name__ == "__main__":
    main()
