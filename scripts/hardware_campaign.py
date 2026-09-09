#!/usr/bin/env python3
"""Hardware campaign entry point. No subcommand submits implicitly."""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from broadcasting.hardware_campaign import (
    attach_job, campaign_status, collect_campaign, plan_campaign,
    prepare_campaign, read_config, submit_campaign,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("plan", "Offline config validation and ordered budget"),
                            ("prepare", "Look up backend and freeze circuits; do not submit")):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("config", type=Path)
        if name == "plan":
            command.add_argument("--full", action="store_true", help="Include every ordered PUB")
        if name == "prepare":
            command.add_argument("--run-dir", type=Path, required=True)
    for name, help_text in (("status", "Offline receipt and collection status"),
                            ("submit", "Submit never-attempted repeats and save job IDs"),
                            ("collect", "Retrieve known jobs by ID; never submit"),
                            ("attach-job", "Reconcile an ambiguous submission using its tagged job ID")):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("run_dir", type=Path)
        if name == "attach-job":
            command.add_argument("--repeat", type=int, required=True, help="Zero-based repeat index")
            command.add_argument("--job-id", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            result = plan_campaign(read_config(args.config))
            if not args.full:
                result = {key: value for key, value in result.items() if key != "repeats"}
        elif args.command == "prepare":
            prepared = prepare_campaign(read_config(args.config), args.run_dir)
            result = {"bundle": str(args.run_dir / "prepared.json"),
                      "plan": {key: value for key, value in prepared["plan"].items() if key != "repeats"},
                      "review": {key: value for key, value in prepared["review"].items() if key != "mapping_review"}}
        elif args.command == "status":
            result = campaign_status(args.run_dir)
        elif args.command == "submit":
            result = {"submitted_job_ids": submit_campaign(args.run_dir)}
        elif args.command == "collect":
            result = {"saved_results": [str(path) for path in collect_campaign(args.run_dir)]}
        else:
            result = {"receipt": str(attach_job(args.run_dir, args.repeat, args.job_id))}
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f"{args.command}: {exc}\n")


if __name__ == "__main__":
    main()
