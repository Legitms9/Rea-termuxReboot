#!/usr/bin/env python3
"""
Tests for prepare_bootstrap.py against a synthetic bootstrap archive.

The real archive is ~40 MB and needs network, so this builds a miniature one with the same
shape (ELF binaries whose rodata holds the compiled-in prefix, symlinks, asset files) and runs
the exact functions the build uses. It is what catches the class of mistake that would produce
an APK that installs fine and then can't run `bash`.

Run: python3 scripts/test_prepare_bootstrap.py
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("prepare_bootstrap", HERE / "prepare_bootstrap.py")
pb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pb)

FAILS: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok   {name}")
    else:
        FAILS.append(name)
        print(f"  FAIL {name}{('  -> ' + detail) if detail else ''}")


ELF_MAGIC = b"\x7fELF\x02\x01\x01" + b"\x00" * 9


def fake_elf(prefix: bytes) -> bytes:
    """An ELF whose .rodata holds the prefix, like the real binaries."""
    body = b"#!/prefix-not-read" + prefix + b"/bin/sh\x00" + prefix + b"/lib/libc.so\x00"
    return ELF_MAGIC + body + b"\x00" * 32


def make_source_zip(dest: Path, package: str) -> None:
    root = package.encode()
    prefix = b"/data/data/" + root + b"/files/usr"
    with zipfile.ZipFile(dest, "w") as zf:
        zf.writestr("bin/bash", fake_elf(prefix))
        zf.writestr("bin/dash", fake_elf(prefix))
        zf.writestr("lib/libc.so", fake_elf(prefix))
        zf.writestr("lib/python3.12/os.py", f"PREFIX = '{prefix.decode()}'\n".encode())
        zf.writestr("etc/profile",
                    f"export PREFIX={prefix.decode()}\nexport HOME=/data/data/{package}/files/home\n".encode())
        zf.writestr("share/logo.png", b"\x89PNG\r\n\x1a\n" + prefix)  # binary, must not be touched
        zf.writestr("SYMLINKS.txt", f"{prefix.decode()}/bin/dash←bin/sh\n{prefix.decode()}/bin/bash←bin/rbash\n")


def main() -> int:
    print("prepare_bootstrap.py")

    # ---------------------------------------------------------------- invariantes
    try:
        pb.check_length_invariant("io.rea.ide")
        check("applicationId de 10 caracteres é aceito", True)
    except SystemExit:
        check("applicationId de 10 caracteres é aceito", False)

    for bad in ("dev.rea.ide", "rea.ide", "com.example.rea"):
        try:
            pb.check_length_invariant(bad)
            check(f"applicationId inválido rejeitado: {bad}", False)
        except SystemExit:
            check(f"applicationId inválido rejeitado: {bad}", True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        app_id = "io.rea.ide"
        src = tmp / "bootstrap-aarch64.zip"
        make_source_zip(src, "com.termux")

        stage = tmp / "stage"
        stage.mkdir()
        with zipfile.ZipFile(src) as zf:
            zf.extractall(stage)

        # ------------------------------------------------------------------ patch
        files, hits = pb.patch_tree(stage, app_id)
        new_prefix = pb.prefix_for(app_id).encode()
        canonical = pb.CANONICAL_PREFIX.encode()

        check("patch_tree mexeu em arquivos", files >= 5, f"files={files}")
        check("patch_tree contou ocorrências", hits >= 8, f"hits={hits}")

        for rel in ("bin/bash", "lib/libc.so", "etc/profile", "lib/python3.12/os.py"):
            data = (stage / rel).read_bytes()
            check(f"{rel}: prefixo novo presente", new_prefix in data)
            check(f"{rel}: prefixo canônico removido", canonical not in data)
        check("bin/bash continua ELF", (stage / "bin/bash").read_bytes()[:4] == b"\x7fELF")
        check("arquivo de home também reescrito",
              f"/data/data/{app_id}/files/home".encode() in (stage / "etc/profile").read_bytes())
        check("PNG não foi corrompido",
              (stage / "share/logo.png").read_bytes() == b"\x89PNG\r\n\x1a\n" + canonical)

        # ------------------------------------------------------------- manifestos
        pb.write_manifests(stage)
        import json
        manifest = json.loads((stage / "REA-INSTALL-MANIFEST.json").read_text())
        executables = set(manifest["executables"])
        check("manifesto marca bin/bash como executável", "bin/bash" in executables)
        check("manifesto não marca lib/libc.so (é dlopen, não exec)",
              "lib/libc.so" not in executables)
        check("manifesto não marca share/logo.png", "share/logo.png" not in executables)
        check("manifesto não marca python como executável",
              "lib/python3.12/os.py" not in executables)
        check("symlinks do SYMLINKS.txt upstream foram preservados",
              len(manifest["symlinks"]) == 2, str(manifest["symlinks"]))
        check("link bin/sh sobreviveu",
              any(link == "bin/sh" for _, link in manifest["symlinks"]), str(manifest["symlinks"]))
        check("symlinks apontam para o prefixo novo",
              all(new_prefix.decode() in link for link, _ in manifest["symlinks"]))

        symlinks_txt = (stage / "SYMLINKS.txt").read_text()
        check("SYMLINKS.txt em formato upstream (target←link)", "←bin/sh" in symlinks_txt,
              symlinks_txt)
        check("SYMLINKS.txt com prefixo novo", canonical.decode() not in symlinks_txt)

        # symlink que veio como entrada de zip (raro, mas acontece) tem de entrar também
        os.symlink(pb.prefix_for(app_id) + "/bin/bash", stage / "bin" / "rbash")
        pb.write_manifests(stage)
        manifest = json.loads((stage / "REA-INSTALL-MANIFEST.json").read_text())
        links = dict((link, target) for target, link in manifest["symlinks"])
        check("symlink presente na árvore é preservado", links.get("bin/rbash") is not None, str(links))
        check("symlinks são deduplicados por caminho de link", len(links) == len(manifest["symlinks"]))
        os.unlink(stage / "bin" / "rbash")
        pb.write_manifests(stage)

        # ---------------------------------------------------------------- repack
        out = tmp / "out" / "arm64-v8a" / "libtermux-bootstrap.so"
        pb.repack(stage, out)
        check("repack gerou o arquivo", out.exists() and out.stat().st_size > 0)

        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
            check("zip tem bin/bash", "bin/bash" in names)
            check("zip tem SYMLINKS.txt", "SYMLINKS.txt" in names)
            check("zip tem o manifesto", "REA-INSTALL-MANIFEST.json" in names)
            check("zip não guarda symlinks como entradas", "bin/sh" not in names)
            bash = zf.read("bin/bash")
            check("bin/bash no zip mantém o prefixo novo", new_prefix in bash)
            check("bin/bash no zip é executável", (zf.getinfo("bin/bash").external_attr >> 16) & 0o111)
            check("python não é executável no zip",
                  not ((zf.getinfo("lib/python3.12/os.py").external_attr >> 16) & 0o111))

    # ------------------------------------------------- fallback de download (sem rede)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # um destino que já existe e tem o sha correto não deve gerar download nenhum
        good = tmp / "bootstrap-aarch64.zip"
        good.write_bytes(b"x" * 10)
        sha = pb.sha256_file(good)
        try:
            pb.download("https://example.invalid/bootstrap-aarch64.zip", good, sha,
                        "release-x", "bootstrap-aarch64.zip")
            check("cache hit evita download", True)
        except SystemExit:
            check("cache hit evita download", False)

        # rota inválida -> tem de levantar SystemExit (die) e não estourar exceção crua
        missing = tmp / "nope.zip"
        try:
            pb.download("https://example.invalid/nope.zip", missing, "0" * 64,
                        "release-x", "nope.zip")
            check("download impossível falha com die()", False)
        except SystemExit:
            check("download impossível falha com die()", True)
        except Exception as e:  # noqa: BLE001
            check("download impossível falha com die()", False, type(e).__name__)

    print()
    if FAILS:
        print(f"{len(FAILS)} teste(s) falharam")
        return 1
    print("todos os testes passaram")
    return 0


if __name__ == "__main__":
    sys.exit(main())
