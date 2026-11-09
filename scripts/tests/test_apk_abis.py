#!/usr/bin/env python3
"""
Testa o passo "conferir cada APK" do codemagic.yaml com APKs sintéticos.

Por que existe: é o passo que impede um APK com a ABI errada (ou sem o bootstrap, ou sem o
bundle do editor) de chegar no celular. Um `exit 1` dentro de pipe em subshell já fez um check
assim passar batido — os casos inválidos aqui existem para garantir que não aconteça de novo.

Run (da raiz do repo): python3 scripts/tests/test_apk_abis.py
"""
import io, pathlib, subprocess, sys, tempfile, zipfile, yaml

root = pathlib.Path(__file__).resolve().parents[2]
import os
os.chdir(root)
wf = yaml.safe_load(open('codemagic.yaml'))['workflows']['android-apk']
step = [s for s in wf['scripts'] if s['name'].startswith('conferir')][0]['script']
tmp = pathlib.Path(tempfile.mkdtemp())

BOOT = io.BytesIO()  # bootstrap mínimo, com prefixo já reescrito
with zipfile.ZipFile(BOOT, 'w') as z:
    z.writestr("bin/bash", b"\x7fELF\x02\x01\x01" + b"\x00" * 9 + b"/data/data/io.rea.ide/files/usr\x00")
    z.writestr("SYMLINKS.txt", b"/data/data/io.rea.ide/files/usr/bin/dash\xe2\x86\x90bin/sh\n")

def make(name, abis, asset=True, boot=None):
    p = tmp / name
    with zipfile.ZipFile(p, 'w') as z:
        for abi in abis:
            z.writestr(f"lib/{abi}/libtermux-bootstrap.so", boot or BOOT.getvalue())
            z.writestr(f"lib/{abi}/libtermux.so", b"\x7fELF")
        if asset:
            z.writestr("assets/www/index.html", "<html></html>")
    return p

cases = [
    ("arm64 correto", make('app-arm64-v8a.apk', ['arm64-v8a']), True),
    ("arm32 correto", make('app-armeabi-v7a.apk', ['armeabi-v7a']), True),
    ("duas ABIs no mesmo APK", make('mixed.apk', ['arm64-v8a', 'armeabi-v7a']), False),
    ("sem bundle do editor", make('noasset.apk', ['arm64-v8a'], asset=False), False),
    ("bootstrap de outra ABI", make('wrongboot.apk', ['arm64-v8a'],
        boot=b"not a zip"), False),
]

fails = 0
for label, apk, should_pass in cases:
    script = step.replace("APKS=$(find app/build/outputs/apk -name '*.apk')", f"APKS={apk}")
    r = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
    ok = r.returncode == 0
    good = ok == should_pass
    fails += 0 if good else 1
    print(f"  {'ok  ' if good else 'FALHA'} {label:26s} CI {'passa' if ok else 'falha'}")
print(f"\n{len(cases)-fails}/{len(cases)} casos corretos")
sys.exit(1 if fails else 0)
