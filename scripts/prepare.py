"""Prepare an isolated environment and print arguments for Kaze's mcp_add."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import venv


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path, help="Kaze's actual workspace directory")
    parser.add_argument("--skip-install", action="store_true", help="Use an already installed plugin environment")
    parser.add_argument("--skip-skill", action="store_true", help="Keep an existing workspace skill")
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        parser.error("Python 3.12 or newer is required")
    root = Path(__file__).resolve().parents[1]
    workspace = args.workspace.expanduser().resolve()
    if not workspace.is_dir():
        parser.error("Workspace must already exist; use Kaze's real workspace")
    python = root / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if args.skip_install and not python.is_file():
        parser.error("--skip-install requires a prepared .venv")
    if not args.skip_install:
        if not python.is_file():
            venv.EnvBuilder(with_pip=True).create(root / ".venv")
        subprocess.run(
            [str(python), "-m", "pip", "install", "."], cwd=root, check=True,
            stdout=sys.stderr,
        )
    if not args.skip_skill:
        source = root / "skills" / "feed-manage" / "SKILL.md"
        destination = workspace / "skills" / "feed-manage" / "SKILL.md"
        if destination.exists() and destination.read_bytes() != source.read_bytes():
            parser.error("An existing feed-manage skill differs; preserve it with --skip-skill")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    data = workspace / "mcp-data" / "kaze-feed"
    print(json.dumps({
        "name": "feed",
        "command": [str(python), str(root / "run_mcp.py")],
        "env": {"KAZE_FEED_DATA_DIR": str(data)},
    }, ensure_ascii=False, indent=2))
    print("Pass this JSON to Kaze's mcp_add, then verify with mcp_list and feed_status.", file=sys.stderr)


if __name__ == "__main__":
    main()
