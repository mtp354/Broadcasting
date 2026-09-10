#!/usr/bin/env python3
"""Inspect and resume self-contained hardware job JSON files in results/."""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from broadcasting.experiments import attach_job, collect_experiment, experiment_status, submit_experiment


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in [("status", "Inspect local state without account access"),
                            ("submit", "Submit prepared jobs; never retry ambiguous attempts"),
                            ("collect", "Collect submitted jobs and finalize their JSON files")]:
        command = commands.add_parser(name, help=help_text)
        command.add_argument("files", nargs="+", type=Path, help="Self-contained job JSON paths")
    command = commands.add_parser("attach-job", help="Link an accepted job after an interrupted submission")
    command.add_argument("file", type=Path)
    command.add_argument("--job-id", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            result = experiment_status(args.files)
        elif args.command == "submit":
            result = {"submitted_job_ids": submit_experiment(args.files)}
        elif args.command == "collect":
            result = {"updated_job_files": [str(path) for path in collect_experiment(args.files)]}
        else:
            result = {"updated_job_file": str(attach_job(args.file, args.job_id))}
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f"{args.command}: {exc}\n")


if __name__ == "__main__":
    main()
