#!/usr/bin/env python3
"""
prepare_bootstrap.py — package the Termux bootstrap for a differently-named app.

WHY THIS EXISTS
---------------
The Termux bootstrap is a ~40 MB archive of prebuilt Debian-ish packages (bash,
apt, coreutils, python, node, clang, ...). Every one of those ELF files has the
*absolute* path

        /data/data/com.termux/files/usr

compiled into its read-only data (`.rodata`, `DT_RPATH`, script shebangs, config
files, python `sysconfig` paths...). Rebuilding 400+ packages per fork is not
something CI should do.

The trick is:

  1. choose an applicationId whose `/data/data/<id>` string is the **same byte
     length** as `/data/data/com.termux`; our id is `io.rea.ide` (10 chars,
     identical to `com.termux`).
  2. rewrite the prefix bytes in place inside every file that contains them.
     Same length => same offsets => ELF program/section headers and script
     offsets stay valid, nothing needs relinking.

Mapping is a byte-for-byte substitution:

        /data/data/com.termux/files/usr   (31 bytes)
        /data/data/io.rea.ide/files/usr  (31 bytes)

Steps:
  * download (and cache) the bootstrap zip for the requested ABIs,
  * verify it against the SHA-256 published in the GitHub release,
  * extract to a scratch dir,
  * rewrite every hit of the compiled-in prefix (also the shorter
    `/data/data/com.termux/files` form used by $ROOTFS references),
  * emit SYMLINKS.txt (upstream format) + REA-INSTALL-MANIFEST.json (modes),
  * repack and store as `libtermux-bootstrap.so` in app/src/main/jniLibs/<abi>/
    so AGP packages one archive per ABI and `extractNativeLibs=true` leaves it
    as a plain readable file on device.

At runtime `io.rea.ide.bootstrap.BootstrapInstaller` unzips that library into
`$FILES/usr-staging`, applies the manifest, then renames it to `$FILES/usr`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

CANONICAL_PACKAGE = "com.termux"
CANONICAL_PREFIX = f"/data/data/{CANONICAL_PACKAGE}/files/usr"
CANONICAL_ROOTFS = f"/data/data/{CANONICAL_PACKAGE}/files"

SKIP_SUFFIXES = {
    ".zip", ".jar", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
    ".woff", ".woff2", ".ttf", ".otf", ".mo", ".gz", ".xz", ".bz2",
}

EXEC_PREFIXES = ("bin/", "libexec/", "lib/apt/methods/", "lib/apt/apt-helper")
EXEC_FILES = ("etc/termux/bootstrap/termux-bootstrap-second-stage.sh",)

ABI_TO_ASSET = {
    "arm64-v8a": "aarch64",
    "armeabi-v7a": "arm",
    "x86_64": "x86_64",
    "x86": "i686",
}


def log(msg: str) -> None:
    print(f"[prepare-bootstrap] {msg}", flush=True)


def die(msg: str) -> None:
    print(f"[prepare-bootstrap] ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def prefix_for(app_id: str) -> str:
    return f"/data/data/{app_id}/files/usr"


def check_length_invariant(app_id: str) -> None:
    new = prefix_for(app_id)
    if len(new) != len(CANONICAL_PREFIX):
        die(
            f"applicationId '{app_id}' yields prefix '{new}' ({len(new)} bytes) but the "
            f"bootstrap was compiled with '{CANONICAL_PREFIX}' ({len(CANONICAL_PREFIX)} bytes). "
            f"Equal length is required for in-place substitution.\n"
            f"        => applicationId must be exactly {len(CANONICAL_PACKAGE)} characters."
        )


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def release_assets(release_tag: str) -> dict:
    url = (f"https://api.github.com/repos/termux/termux-packages/releases/tags/"
           f"{urllib.parse.quote(release_tag)}")
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "rea-termux-ide-ci",
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.load(resp)
    out = {}
    for asset in payload.get("assets", []):
        digest = asset.get("digest") or ""
        if digest.startswith("sha256:"):
            out[asset["name"]] = digest.split(":", 1)[1]
    if not out:
        die(f"no checksummed assets in release {release_tag}")
    return out


def fetch_asset(release: str, asset_name: str, dest: Path) -> None:
    """
    Download a release asset with the GitHub CLI.

    We go through `gh` on purpose: it authenticates with GH_TOKEN in CI (higher rate limits,
    works on private mirrors) and it follows GitHub's 302 to its asset CDN for us, which plain
    urllib cannot reach from egress-restricted networks.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    log(f"fetching {asset_name} from {release} via gh")
    proc = subprocess.run(
        ["gh", "release", "download", release, "--repo", "termux/termux-packages",
         "--pattern", asset_name, "--dir", str(dest.parent), "--clobber"],
        capture_output=True, text=True)
    if proc.returncode != 0:
        die(f"gh release download failed for {asset_name}:\n{proc.stdout}\n{proc.stderr}")


def download(url: str, dest: Path, expected_sha256: str, release: str, asset_name: str) -> None:
    if dest.exists() and sha256_file(dest) == expected_sha256:
        log(f"cache hit: {dest.name}")
        return
    if dest.exists():
        log(f"cache stale: {dest.name}")
        dest.unlink()

    if shutil.which("gh"):
        fetch_asset(release, asset_name, dest)
    else:
        mirror = os.environ.get("REA_BOOTSTRAP_MIRROR", "").rstrip("/")
        effective = f"{mirror}/{asset_name}" if mirror else url
        log(f"downloading {effective}")
        tmp = dest.with_suffix(dest.suffix + ".part")
        with urllib.request.urlopen(effective, timeout=900) as resp, open(tmp, "wb") as fh:
            shutil.copyfileobj(resp, fh, length=1 << 20)
        tmp.rename(dest)

    got = sha256_file(dest)
    if got != expected_sha256:
        dest.unlink(missing_ok=True)
        die(f"checksum mismatch for {dest.name}\n  expected {expected_sha256}\n  actual   {got}")
    log(f"verified sha256:{expected_sha256[:16]}… {dest.name}")


def is_elf(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(4) == b"\x7fELF"
    except OSError:
        return False


def needs_exec(name: str, path: Path) -> bool:
    if name in EXEC_FILES or any(name.startswith(p) for p in EXEC_PREFIXES):
        return True
    return is_elf(path) and (os.stat(path).st_mode & 0o111) != 0


def substitute(path: Path, old: bytes, new: bytes) -> int:
    data = path.read_bytes()
    n = data.count(old)
    if n:
        path.write_bytes(data.replace(old, new))
    return n


def patch_tree(root: Path, app_id: str) -> tuple:
    pairs = [
        (CANONICAL_PREFIX.encode(), prefix_for(app_id).encode()),
        (CANONICAL_ROOTFS.encode(), f"/data/data/{app_id}/files".encode()),
    ]
    files = hits = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            p = Path(dirpath) / filename
            if p.suffix.lower() in SKIP_SUFFIXES:
                continue
            if p.is_symlink():
                target = os.readlink(p)
                if CANONICAL_ROOTFS in target:
                    p.unlink()
                    p.symlink_to(target.replace(CANONICAL_ROOTFS, f"/data/data/{app_id}/files"))
                continue
            local = 0
            for old, new in pairs:
                local += substitute(p, old, new)
            if local:
                files += 1
                hits += local
    return files, hits


def write_manifests(root: Path) -> None:
    entries, symlinks, execs = [], [], []
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            p = Path(dirpath) / filename
            rel = p.relative_to(root).as_posix()
            if rel in ("SYMLINKS.txt", "REA-INSTALL-MANIFEST.json"):
                continue
            if p.is_symlink():
                symlinks.append([os.readlink(p), rel])
                continue
            if needs_exec(rel, p):
                execs.append(rel)
            entries.append(rel)

    # Upstream SYMLINKS.txt format is "<target>←<link>", one per line.
    (root / "SYMLINKS.txt").write_text(
        "".join(f"{t}←{l}\n" for t, l in sorted(symlinks)), encoding="utf-8"
    )
    (root / "REA-INSTALL-MANIFEST.json").write_text(
        json.dumps({
            "version": 1,
            "fileCount": len(entries),
            "executables": sorted(execs),
            "symlinks": sorted(symlinks),
        }, separators=(",", ":")),
        encoding="utf-8",
    )


def repack(root: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for dirpath, _dirnames, filenames in os.walk(root):
            for filename in filenames:
                p = Path(dirpath) / filename
                if p.is_symlink():
                    continue  # replayed from SYMLINKS.txt
                rel = p.relative_to(root).as_posix()
                info = zipfile.ZipInfo(rel, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (0o755 if needs_exec(rel, p) else 0o644) << 16
                with open(p, "rb") as src, zf.open(info, "w") as out:
                    shutil.copyfileobj(src, out, length=1 << 20)
    tmp.rename(dest)


def build_abi(abi, asset_name, release, assets, cache, out_dir, app_id, work) -> Path:
    zip_path = cache / asset_name
    url = (f"https://github.com/termux/termux-packages/releases/download/"
           f"{urllib.parse.quote(release)}/{asset_name}")
    download(url, zip_path, assets[asset_name], release, asset_name)

    stage = work / abi
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True, exist_ok=True)
    log(f"extracting {asset_name}")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(stage)

    files, hits = patch_tree(stage, app_id)
    log(f"{abi}: prefix rewritten in {files} files ({hits} occurrences)")
    write_manifests(stage)

    dest = out_dir / abi / "libtermux-bootstrap.so"
    repack(stage, dest)
    log(f"{abi}: wrote {dest.name} ({dest.stat().st_size / 1e6:.1f} MB) -> jniLibs/{abi}/")
    shutil.rmtree(stage, ignore_errors=True)
    return dest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--release", required=True)
    ap.add_argument("--app-id", required=True)
    ap.add_argument("--abis", default="arm64-v8a,armeabi-v7a,x86_64,x86")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--cache-dir", required=True)
    ap.add_argument("--skip", action="store_true", help="exit early when every ABI output exists")
    args = ap.parse_args()

    check_length_invariant(args.app_id)

    abis = [a.strip() for a in args.abis.split(",") if a.strip()]
    bad = [a for a in abis if a not in ABI_TO_ASSET]
    if bad:
        die(f"unknown ABI(s) {bad}; known: {sorted(ABI_TO_ASSET)}")

    out_dir = Path(args.out_dir)
    targets = [out_dir / abi / "libtermux-bootstrap.so" for abi in abis]
    if args.skip and all(t.exists() for t in targets):
        log("all per-ABI bootstrap libraries present; skipping")
        return

    cache = Path(args.cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    work = cache / "work"
    work.mkdir(parents=True, exist_ok=True)

    assets = release_assets(args.release)
    for abi in abis:
        asset = f"bootstrap-{ABI_TO_ASSET[abi]}.zip"
        if asset not in assets:
            die(f"release {args.release} has no asset {asset}")
        build_abi(abi, asset, args.release, assets, cache, out_dir, args.app_id, work)

    shutil.rmtree(work, ignore_errors=True)
    log("done")


if __name__ == "__main__":
    main()
