#!/usr/bin/env python3
"""
check_codemagic.py — validate codemagic.yaml against the rules the real schema enforces.

Codemagic validates with JSON Schema (`additionalProperties: false`), so a misplaced key does not
warn, it fails before the first script runs. This catches the mistakes that are easy to make and
slow to notice:

  * `cache:` must be a WORKFLOW key, not nested under `environment:`
  * `environment:` accepts groups/vars/java/node/ndk/flutter/xcode/ubuntu/... but NOT `python`
  * `instance_type` must be one of the documented values, and free accounts only get `linux`,
    `mac_mini`, `mac_mini_m2` (the x2/x4/windows runners need billing)
  * `max_build_duration` is 1..120
  * `triggering.events` values are push / pull_request / tag / pull_request_labeled

Run: python3 scripts/check_codemagic.py [path]
Exit: 0 ok, 1 problems found. No network, no dependencies.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import yaml  # PyYAML
except ImportError:  # pragma: no cover - minimal fallback
    yaml = None

WORKFLOW_KEYS = {
    "name", "labels", "instance_type", "max_build_duration", "inputs", "environment",
    "cache", "triggering", "scripts", "artifacts", "publishing", "integrations",
    "environment_variables", "definitions", "artifacts_retention",
}

# From https://codemagic.io/codemagic-schema.json (Environment definition)
ENVIRONMENT_KEYS = {
    "groups", "vars", "flutter", "xcode", "cocoapods", "node", "npm", "ndk", "java",
    "ruby", "ubuntu", "go", "artifacts_retention", "cache",
}
# Keys that exist for some other section and are commonly misplaced into environment.
KNOWN_ELSEWHERE = {"cache", "scripts", "artifacts", "triggering", "publishing", "python", "python3", "pip"}

INSTANCE_TYPES = {
    "mac_mini", "mac_mini_m1", "mac_mini_m2", "mac_mini_m4", "mac_studio_m4_max",
    "mac_pro", "linux", "linux_x2", "linux_x4", "windows_x2",
}
# The free plan is macOS ONLY. Linux/Windows runners (linux, linux_x2, linux_x4, windows_x2)
# require billing and fail instantly with
# "The selected instance type is not available with the current billing plan."
FREE_INSTANCE_TYPES = {"mac_mini", "mac_mini_m2"}
TRIGGER_EVENTS = {"push", "pull_request", "tag", "pull_request_labeled", "pull_request_labelled"}

problems: list[str] = []


def problem(msg: str) -> None:
    problems.append(msg)


def check_workflow(wid: str, wf: dict) -> None:
    for key in wf:
        if key not in WORKFLOW_KEYS:
            problem(f"{wid}: chave desconhecida no workflow: '{key}'")

    it = wf.get("instance_type")
    if it is not None:
        if it not in INSTANCE_TYPES:
            problem(f"{wid}: instance_type '{it}' não existe "
                    f"(válidos: {', '.join(sorted(INSTANCE_TYPES))})")
        elif it not in FREE_INSTANCE_TYPES:
            problem(f"{wid}: instance_type '{it}' exige billing ativo. O plano grátis da "
                    f"Codemagic é só macOS; use um de {', '.join(sorted(FREE_INSTANCE_TYPES))}")

    dur = wf.get("max_build_duration")
    if dur is not None and not (isinstance(dur, int) and 1 <= dur <= 120):
        problem(f"{wid}: max_build_duration deve ser inteiro entre 1 e 120 (recebido: {dur!r})")

    env = wf.get("environment")
    if isinstance(env, dict):
        for key in env:
            if key in ("cache", "scripts", "artifacts", "triggering", "publishing"):
                problem(f"{wid}: '{key}' está dentro de environment; "
                        f"ele pertence ao nível do workflow (2 espaços menos)")
            elif key in KNOWN_ELSEWHERE and key not in ENVIRONMENT_KEYS:
                problem(f"{wid}: environment não aceita '{key}' "
                        f"(o schema usa additionalProperties: false)")
            elif key not in ENVIRONMENT_KEYS:
                problem(f"{wid}: chave desconhecida em environment: '{key}'")

    cache = wf.get("cache")
    if cache is not None:
        if not isinstance(cache, dict) or "cache_paths" not in cache:
            problem(f"{wid}: cache deve ser um mapa com cache_paths")
        elif not isinstance(cache["cache_paths"], list):
            problem(f"{wid}: cache.cache_paths deve ser uma lista")

    trig = wf.get("triggering")
    if isinstance(trig, dict):
        for ev in trig.get("events", []) or []:
            if ev not in TRIGGER_EVENTS:
                problem(f"{wid}: triggering.events tem valor inválido '{ev}'")
        for bp in trig.get("branch_patterns", []) or []:
            if not isinstance(bp, dict) or "pattern" not in bp:
                problem(f"{wid}: cada branch_pattern precisa de 'pattern'")

    scripts = wf.get("scripts")
    if scripts is None:
        problem(f"{wid}: sem 'scripts' — o workflow não faz nada")
    elif not isinstance(scripts, list):
        problem(f"{wid}: scripts deve ser uma lista")

    arts = wf.get("artifacts")
    if arts is not None and not isinstance(arts, list):
        problem(f"{wid}: artifacts deve ser uma lista")


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "codemagic.yaml")
    if not path.exists():
        print(f"arquivo não encontrado: {path}")
        return 1
    if yaml is None:
        print("PyYAML não instalado: pip install pyyaml")
        return 1

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        print(f"YAML inválido em {path}:")
        print(f"  {e}")
        return 1

    if not isinstance(data, dict) or "workflows" not in data:
        print("codemagic.yaml precisa da chave de topo 'workflows'")
        return 1

    for wid, wf in (data["workflows"] or {}).items():
        if not isinstance(wf, dict):
            problem(f"{wid}: workflow precisa ser um mapa")
            continue
        check_workflow(wid, wf)

    print(f"codemagic.yaml: {len(data['workflows'])} workflow(s): {', '.join(data['workflows'])}")
    if problems:
        print("\nproblemas encontrados:")
        for p in problems:
            print(f"  ✗ {p}")
        return 1
    print("  ✓ schema ok (keys, instance_type, cache, triggering)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
