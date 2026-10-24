#!/usr/bin/env python3
"""Create a named, editable IslandOS site configuration without manual JSON edits.

The generated file retains illustrative defaults and is not a representation of
measured site properties. Replace and source each assumption before site-specific use.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from islandos_config import load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-name", required=True, help="human-readable site or study label")
    parser.add_argument("--output", type=Path, default=Path("config/site_parameters.local.json"))
    parser.add_argument("--force", action="store_true", help="replace an existing output file")
    args = parser.parse_args(argv)
    site_name = args.site_name.strip()
    if not site_name:
        parser.error("--site-name must not be blank")
    if args.output.exists() and not args.force:
        parser.error(f"{args.output} already exists; choose another path or pass --force")

    template = ROOT / "config" / "site_parameters.example.json"
    try:
        config = json.loads(template.read_text(encoding="utf-8"))
        config["metadata"]["name"] = site_name
        config["metadata"]["status"] = "illustrative_bootstrap_not_site_data"
        config["metadata"]["notes"] = (
            "Created by tools/init_site_config.py. Equipment/search values are illustrative "
            "starting assumptions, not measured site data or vendor-certified values. "
            "Replace and document relevant parameters before interpreting site-specific results."
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # Run the same validator used by the optimization workflow against the written file.
        load_config(args.output)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        parser.error(f"could not create a valid configuration: {exc}")

    print(f"Created configuration: {args.output}")
    print(f"Site/study label: {site_name}")
    print("Status: illustrative defaults only; not measured site data.")
    print("Next: edit equipment/search values and document source, units, and uncertainty.")
    print(f"Preflight: python tools/validate_site_config.py {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
