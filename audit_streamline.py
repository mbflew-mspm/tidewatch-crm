#!/usr/bin/env python3
"""
Standalone CLI for the read-only Streamline capability audit.

The client + probes live in streamline.py (shared with the always-on worker).
This is just a convenient local runner. Strictly read-only.

  cp .env.example .env          # paste tokens
  set -a; source .env; set +a
  python3 audit_streamline.py            # human-readable
  python3 audit_streamline.py --json     # machine-readable
"""

import json
import os
import sys

from streamline import StreamlineClient, TokenStore, run_audit, print_report


def main():
    as_json = "--json" in sys.argv
    if not os.environ.get("STREAMLINE_TOKEN_KEY") or not os.environ.get("STREAMLINE_TOKEN_SECRET"):
        sys.exit("Missing STREAMLINE_TOKEN_KEY / STREAMLINE_TOKEN_SECRET. See .env.example.")
    store = TokenStore(
        os.environ.get("TOKEN_STORE_PATH", "tokens.json"),
        os.environ["STREAMLINE_TOKEN_KEY"],
        os.environ["STREAMLINE_TOKEN_SECRET"],
    )
    result = run_audit(StreamlineClient(store))
    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print_report(result)


if __name__ == "__main__":
    main()
