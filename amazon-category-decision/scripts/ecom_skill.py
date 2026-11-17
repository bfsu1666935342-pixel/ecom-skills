"""CLI entry point for the category-decision skill.

Examples:
  python scripts/ecom_skill.py doctor
  python scripts/ecom_skill.py search "drafting chair"
  python scripts/ecom_skill.py fetch --slug drafting-chair --node 1069142 --category "Drafting Chairs"
  python scripts/ecom_skill.py normalize --slug drafting-chair
  python scripts/ecom_skill.py build --slug drafting-chair
  python scripts/ecom_skill.py verify --slug drafting-chair
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from build_report import build
from fetch import fetch, search
from normalize import normalize
from providers import get_provider, load_dotenv
from verify_report import verify

ROOT = Path(__file__).resolve().parents[1]


def cmd_doctor(args: argparse.Namespace) -> int:
    load_dotenv(ROOT / ".env")
    provider = get_provider(args.provider)
    info = provider.doctor()
    print(json.dumps(info, ensure_ascii=False, indent=2))
    if args.list_tools:
        print("\nTOOLS:")
        for name in info["tools"]:
            print(" ", name)
    return 0 if not info["missing_mapped_tools"] else 1


def cmd_search(args: argparse.Namespace) -> int:
    for item in search(args.provider, args.category, args.site):
        print(f"{item.get('node_id')}\t{item.get('category_name')}")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    fetch(args.provider, args.slug, args.site, args.category, args.node, Path(args.out), args.pulled)
    return 0


def cmd_normalize(args: argparse.Namespace) -> int:
    raw = Path(args.out) / args.slug / "raw"
    out = Path(args.out) / args.slug / "data.json"
    args.input = str(raw)
    args.out_path = str(out)
    # normalize() expects Namespace with input/out; adapter:
    ns = argparse.Namespace(**vars(args))
    ns.input = str(raw)
    normalize(raw, out, ns)
    print(out)
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    print(build(args.slug, Path(args.out), args.report))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    errors = verify(args.slug, Path(args.out))
    if errors:
        print("FAIL")
        for e in errors:
            print(" -", e)
        return 1
    print("PASS")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    fetch(args.provider, args.slug, args.site, args.category, args.node, Path(args.out), args.pulled)
    raw = Path(args.out) / args.slug / "raw"
    out = Path(args.out) / args.slug / "data.json"
    ns = argparse.Namespace(**vars(args))
    ns.input = str(raw)
    normalize(raw, out, ns)
    print(out)
    if (Path(args.out) / args.slug / "narrative.json").exists():
        print(build(args.slug, Path(args.out), args.report))
    else:
        print("Narrative missing. Write data/<slug>/narrative.json before build.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data", help="output root (default: data)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("doctor")
    p.add_argument("--provider", default="sorftime")
    p.add_argument("--list-tools", action="store_true")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("search")
    p.add_argument("--provider", default="sorftime")
    p.add_argument("--site", default="US")
    p.add_argument("--category", required=True)
    p.set_defaults(func=cmd_search)

    common = dict(provider="sorftime", slug="", site="US", category="", node="", out="data", pulled="")
    p = sub.add_parser("fetch")
    for k, v in common.items():
        p.add_argument("--" + k.replace("_", "-"), default=v)
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("normalize")
    p.add_argument("--slug", required=True)
    p.add_argument("--provider", default="sorftime")
    p.add_argument("--site", default="US")
    p.add_argument("--category", default="")
    p.add_argument("--title", default="")
    p.add_argument("--node", default="")
    p.add_argument("--pulled", default=date.today().isoformat())
    p.add_argument("--price", type=float)
    p.add_argument("--landed", type=float)
    p.add_argument("--cpc", type=float)
    p.add_argument("--cvr", type=float)
    p.add_argument("--return-rate", dest="return_rate", type=float)
    p.add_argument("--fba", type=float)
    p.add_argument("--out", default="data")
    p.set_defaults(func=cmd_normalize)

    p = sub.add_parser("build")
    p.add_argument("--slug", required=True)
    p.add_argument("--out", default="data")
    p.add_argument("--report", default="")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("verify")
    p.add_argument("--slug", required=True)
    p.add_argument("--out", default="data")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("run")
    for k, v in common.items():
        p.add_argument("--" + k.replace("_", "-"), default=v)
    p.add_argument("--price", type=float)
    p.add_argument("--landed", type=float)
    p.add_argument("--cpc", type=float)
    p.add_argument("--cvr", type=float)
    p.add_argument("--return-rate", dest="return_rate", type=float)
    p.add_argument("--fba", type=float)
    p.add_argument("--report", default="")
    p.set_defaults(func=cmd_run)

    args = parser.parse_args()
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
