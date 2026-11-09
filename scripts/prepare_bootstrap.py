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
import time
import urllib.error
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

# Set from --source-dir; a module-level default keeps download() callable from tests.
SOURCE_DIR = None

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
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.load(resp)
    except Exception as e:  # noqa: BLE001 - offline/blocked API is not fatal
        log(f"AVISO: nao consegui ler os checksums publicados ({e})")
        log("       a verificacao sha256 sera pulada; use --source-dir com um zip confiavel")
        return {}
    out = {}
    for asset in payload.get("assets", []):
        digest = asset.get("digest") or ""
        if digest.startswith("sha256:"):
            out[asset["name"]] = digest.split(":", 1)[1]
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
        raise RuntimeError(f"gh release download failed for {asset_name}: {proc.stderr.strip()[:400]}")


def local_source(asset_name: str):
    """Archive provided out-of-band (downloaded once elsewhere), if any."""
    for raw in filter(None, [os.environ.get("REA_BOOTSTRAP_SOURCE_DIR"), SOURCE_DIR]):
        candidate = Path(raw) / asset_name
        # Validate it really is a bootstrap archive, not an HTML error page saved as .zip.
        if candidate.is_file() and zipfile.is_zipfile(candidate):
            try:
                with zipfile.ZipFile(candidate) as zf:
                    if "bin/bash" in zf.namelist():
                        return candidate
            except zipfile.BadZipFile:
                pass
    return None


def http_download_once(url: str, dest: Path) -> None:
    """Fetch one attempt, removing any partial file on failure."""
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=900) as resp, open(tmp, "wb") as fh:
            shutil.copyfileobj(resp, fh, length=1 << 20)
        if tmp.stat().st_size < 1 << 20:
            raise RuntimeError(f"suspiciously small file ({tmp.stat().st_size} bytes)")
        tmp.rename(dest)
    finally:
        tmp.unlink(missing_ok=True)


def http_download(url: str, dest: Path) -> None:
    """Retry transient HTTP gateway errors before trying another route."""
    for attempt in range(3):
        try:
            http_download_once(url, dest)
            return
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
            delay = 2 ** (attempt + 1)
            log(f"  HTTP {exc.code}; tentando novamente em {delay}s ({attempt + 2}/3)")
            time.sleep(delay)


def download(url: str, dest: Path, expected_sha256: str, release: str, asset_name: str) -> None:
    """
    Fetch + verify a bootstrap archive, trying every available route.

    Order and rationale:
      1. `gh release download` — authenticated, higher rate limits, follows the bucket 302.
      2. REA_BOOTSTRAP_MIRROR  — your own mirror / artifact store (yours to trust).
      3. REA_BOOTSTRAP_PROXY   — public release proxies, e.g. https://ghproxy.net/https://github.com
      4. the release URL       — plain internet access

    A route that fails never aborts the whole build: we record the error and try the next one.
    The SHA-256 check is the only thing that decides success, so a proxy cannot slip us a
    different archive.
    """
    # A local copy (--source-dir / REA_BOOTSTRAP_SOURCE_DIR) wins over any network route.
    local = local_source(asset_name)
    if local is not None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local, dest)
        log(f"using local copy {local}")

    def matches(path: Path) -> bool:
        return (not expected_sha256) or sha256_file(path) == expected_sha256

    if dest.exists() and matches(dest):
        log(f"cache hit: {dest.name}")
        if not expected_sha256:
            log(f"  AVISO: sem checksum publicado; sha256 local {sha256_file(dest)[:16]}...")
        return
    if dest.exists():
        log(f"cache stale: {dest.name}")
        dest.unlink()

    errors = []

    if shutil.which("gh"):
        try:
            fetch_asset(release, asset_name, dest)
        except Exception as e:  # noqa: BLE001 - any gh failure falls through to HTTP
            errors.append(f"gh: {e}")
            log(f"  gh route failed ({e}), trying HTTP routes")
    else:
        log("gh not available, using HTTP routes")

    if not (dest.exists() and matches(dest)):
        candidates = []
        mirror = os.environ.get("REA_BOOTSTRAP_MIRROR", "").rstrip("/")
        proxy = os.environ.get("REA_BOOTSTRAP_PROXY", "").rstrip("/")
        if mirror:
            candidates.append(f"{mirror}/{asset_name}")
        if proxy:
            candidates.append(f"{proxy}/{url}")
        candidates.append(url)

        for effective in candidates:
            log(f"downloading {effective}")
            try:
                http_download(effective, dest)
                break
            except Exception as e:  # noqa: BLE001 - try the next route
                errors.append(f"{effective.split('?')[0]}: {e}")
                log(f"  failed: {e}")
        else:
            die("could not download {}\n  {}\n\nDicas:\n"
                "  - ja tem o zip? passe --source-dir (ou use REA_BOOTSTRAP_SOURCE_DIR)\n"
                "  - bloqueado? defina REA_BOOTSTRAP_PROXY=https://ghproxy.net/https://github.com\n"
                "  - espelho proprio? defina REA_BOOTSTRAP_MIRROR=https://seu-servidor/bootstraps"
                .format(asset_name, "\n  ".join(errors)))

    got = sha256_file(dest) if dest.exists() else ""
    if not got:
        die(f"{dest.name} nao foi obtido. Rotas tentadas:\n  " + "\n  ".join(errors))
    if expected_sha256 and got != expected_sha256:
        dest.unlink(missing_ok=True)
        die("checksum mismatch for {}\n  expected {}\n  actual   {}\n  routes tentados:\n  {}"
            .format(dest.name, expected_sha256, got or "(arquivo ausente)", "\n  ".join(errors)))
    if expected_sha256:
        log(f"verified sha256:{expected_sha256[:16]}... {dest.name}")
    else:
        log(f"sha256 local (nao verificado): {got[:16]}... {dest.name}")


def is_elf(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(4) == b"\x7fELF"
    except OSError:
        return False


def needs_exec(name: str, path: Path) -> bool:
    """
    Mirrors termux-app's TermuxInstaller: bin/, libexec/, apt's methods and helper, plus the
    bootstrap script. Shared objects under lib/ are dlopen()ed, never executed, and zipfile
    extraction does not restore mode bits, so we cannot (and must not) rely on them.
    """
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


def read_upstream_symlinks(root: Path) -> list:
    """
    Upstream archives do not store symlinks as zip entries: they list them in SYMLINKS.txt as
    "<target>←<link>" (see termux-app's TermuxInstaller). If we rebuilt that file from the
    extracted tree alone we would silently drop every symlink — including bin/sh, bin/awk and
    friends — and leave a prefix where bash exists but nothing else resolves.
    """
    path = root / "SYMLINKS.txt"
    pairs = []
    if not path.exists():
        return pairs
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "←" not in line:
            continue
        target, link = line.split("←", 1)
        target, link = target.strip(), link.strip()
        if target and link:
            pairs.append([target, link])
    return pairs


def write_manifests(root: Path) -> None:
    upstream_symlinks = read_upstream_symlinks(root)
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

    # Merge: symlinks that came as zip entries win over the manifest's, same link path.
    merged = {link: target for target, link in upstream_symlinks}
    for target, link in symlinks:
        merged[link] = target
    symlinks = sorted([[target, link] for link, target in merged.items()], key=lambda p: p[1])

    # Upstream SYMLINKS.txt format is "<target>←<link>", one per line.
    (root / "SYMLINKS.txt").write_text(
        "".join(f"{t}←{l}\n" for t, l in symlinks), encoding="utf-8"
    )
    (root / "REA-INSTALL-MANIFEST.json").write_text(
        json.dumps({
            "version": 1,
            "fileCount": len(entries),
            "executables": sorted(execs),
            "symlinks": symlinks,
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


def build_abi(abi, asset_name, release, expected_sha256, cache, out_dir, app_id, work) -> Path:
    zip_path = cache / asset_name
    url = (f"https://github.com/termux/termux-packages/releases/download/"
           f"{urllib.parse.quote(release)}/{asset_name}")
    download(url, zip_path, expected_sha256, release, asset_name)

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
    ap.add_argument("--source-dir", default=None,
                    help="diretório com os bootstrap-*.zip já baixados (evita a rede)")
    args = ap.parse_args()

    global SOURCE_DIR
    SOURCE_DIR = args.source_dir
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
        if assets and asset not in assets:
            die(f"release {args.release} has no asset {asset}")
        if not assets:
            log(f"AVISO: baixando {asset} sem checksum publicado")
        build_abi(abi, asset, args.release, assets.get(asset, ""), cache, out_dir, args.app_id, work)

    shutil.rmtree(work, ignore_errors=True)
    log("done")


if __name__ == "__main__":
    main()
