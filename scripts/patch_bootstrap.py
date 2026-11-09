#!/usr/bin/env python3
"""
patch_bootstrap.py — in-place prefix rewrite for a *single* file or tree.

Same invariant as prepare_bootstrap.py: the replacement string must have exactly the
same byte length as the original, so ELF offsets, script shebangs and config values
stay valid.

CLI
---
  patch_bootstrap.py --check            # verify the length invariant only
  patch_bootstrap.py PATH...            # patch files/dirs in place (default app id)
  patch_bootstrap.py --app-id X PATH... # patch for another (same-length) app id
  patch_bootstrap.py --scan PATH        # report hits without touching anything

Exit code 1 when --check fails; 0 otherwise.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

CANONICAL = b"/data/data/com.termux/files/usr"
CANONICAL_ROOTFS = b"/data/data/com.termux/files"

SKIP_SUFFIXES = {
    ".zip", ".jar", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
    ".woff", ".woff2", ".ttf", ".otf", ".mo", ".gz", ".xz", ".bz2",
}


def prefix_for(app_id: str) -> bytes:
    return f"/data/data/{app_id}/files/usr".encode()


def check(app_id: str) -> bool:
    old, new = CANONICAL, prefix_for(app_id)
    ok = len(old) == len(new)
    print(f"canonical : {old.decode()} ({len(old)} bytes)")
    print(f"replacement: {new.decode()} ({len(new)} bytes)")
    print("OK" if ok else "MISMATCH — the app id must be exactly %d characters" % len("com.termux"))
    return ok


def iter_files(paths):
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for dirpath, _dirnames, filenames in os.walk(p):
                for name in filenames:
                    yield Path(dirpath) / name
        elif p.is_file():
            yield p


def patch_file(path: Path, old: bytes, new: bytes, scan_only: bool) -> int:
    if path.suffix.lower() in SKIP_SUFFIXES or path.is_symlink():
        return 0
    try:
        data = path.read_bytes()
    except OSError as e:
        print(f"  ! {path}: {e}", file=sys.stderr)
        return 0
    n = data.count(old)
    if not n:
        return 0
    if scan_only:
        print(f"  {path}: {n} hit(s)")
    else:
        path.write_bytes(data.replace(old, new))
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--app-id", default="io.rea.ide")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--scan", action="store_true")
    args = ap.parse_args()

    if not check(args.app_id):
        return 1
    if args.check:
        return 0

    if not args.paths:
        print("nothing to do; pass paths (or --check)", file=sys.stderr)
        return 1

    old, new = CANONICAL, prefix_for(args.app_id)
    old_root, new_root = CANONICAL_ROOTFS, f"/data/data/{args.app_id}/files".encode()

    files = hits = 0
    for path in iter_files(args.paths):
        local = patch_file(path, old, new, args.scan)
        local += patch_file(path, old_root, new_root, args.scan)
        if local:
            files += 1
            hits += local

    verb = "found" if args.scan else "rewrote"
    print(f"{verb} {hits} occurrence(s) in {files} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
