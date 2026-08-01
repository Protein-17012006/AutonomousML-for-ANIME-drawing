"""Admin-only cleanup for box-local active workspaces.

Dry-run by default. This never touches DynamoDB or S3 durable history.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Support `python scripts/purge_active_workspaces.py` from the repository root.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from service.active_workspace.service import ActiveWorkspaceService


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="list workspaces without deleting (the default)")
    parser.add_argument("--expired", action="store_true", help="remove expired non-running workspaces")
    parser.add_argument("--all", action="store_true", help="remove all temporary workspaces")
    parser.add_argument("--include-running", action="store_true", help="permit removal of running manifests")
    parser.add_argument("--confirm", action="store_true", help="perform deletion instead of dry-run")
    args = parser.parse_args()
    if args.expired and args.all:
        parser.error("choose at most one of --expired or --all")
    if args.list and (args.expired or args.all or args.confirm):
        parser.error("--list cannot be combined with deletion options")
    if args.confirm and not (args.expired or args.all):
        parser.error("--confirm requires --expired or --all")
    store = ActiveWorkspaceService()
    candidates = [manifest for _, manifest in store.list_manifests()]
    print(f"active workspace root: {store.settings.root}")
    for manifest in candidates:
        print(f"{manifest.workspace_id}\t{manifest.state}\texpires={manifest.expires_at}\towner={manifest.owner_hash[:12]}")
    if not (args.expired or args.all):
        print("Listed only. Use --expired or --all with --confirm to delete workspaces.")
        return 0
    if not args.confirm:
        print("Dry-run only. Re-run with --confirm to delete eligible workspaces.")
        return 0
    removed = store.purge(expired_only=args.expired, include_running=args.include_running)
    print(f"removed {len(removed)} workspace(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
