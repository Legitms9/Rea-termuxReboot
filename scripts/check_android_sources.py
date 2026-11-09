#!/usr/bin/env python3
"""Checagens offline que pegam os erros clássicos de "primeiro build Android".

Nada aqui compila Java de verdade (sem JDK/SDK na maior parte das máquinas), mas cobre
as falhas que mais aparecem no primeiro `assembleDebug` de um projeto novo:

  1. sintaxe Java/Kotlin (via javalang, se instalado)
  2. todo R.<tipo>.<nome> usado no código existe nos recursos
  3. todo recurso referenciado em layout (@id/x, @string/x...) existe
  4. todo `findViewById(R.id.x)` de um layout que é inflado existe naquele layout
  5. Manifest: activity declarada, package/namespace batendo, permissões usadas
  6. Gradle: applicationId com 10 caracteres (invariante do prefixo do Termux),
     minSdk/compileSdk coerentes, nenhum `include` de ABI desconhecida

Uso: python3 scripts/check_android_sources.py [--repo RAIZ]
"""
from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

try:  # opcional: sem javalang as checagens de Java são puladas com aviso
    import javalang
    JAVA_PARSE_ERROR = javalang.parser.JavaSyntaxError
except ImportError:  # pragma: no cover
    javalang = None
    JAVA_PARSE_ERROR = SyntaxError

ANDROID_NS = "{http://schemas.android.com/apk/res/android}"
KNOWN_ABIS = {"arm64-v8a", "armeabi-v7a", "armeabi", "x86", "x86_64", "mips", "mips64"}

errors: list[str] = []
warnings: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


# ---------------------------------------------------------------- recursos


def collect_resources(res: Path) -> dict[str, set[str]]:
    """Mapeia tipo -> nomes definidos, lendo nomes de arquivo e conteúdo dos XMLs."""
    res_types: dict[str, set[str]] = {t: set() for t in
        ("id", "string", "layout", "drawable", "mipmap", "color", "style", "xml", "array", "bool", "integer", "dimen")}
    if not res.is_dir():
        return res_types

    for path in res.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(res)
        parts = rel.parts
        folder = parts[0]
        base_type = folder.split("-")[0]

        if path.suffix == ".xml":
            try:
                root = ET.parse(path).getroot()
            except ET.ParseError as exc:
                err(f"{path}: XML inválido: {exc}")
                continue
            if base_type in ("values", "values-night", "values-v21", "values-v26"):
                for child in root:
                    tag = child.tag
                    name = child.get("name")
                    if not name:
                        continue
                    if tag in ("string", "color", "dimen", "bool", "integer", "style", "string-array", "integer-array", "array", "plurals"):
                        res_types[tag if tag != "plurals" else "array"].add(name)
                    elif tag == "item":
                        t = child.get("type")
                        if t:
                            res_types.setdefault(t, set()).add(name)
            # @+id declarado em qualquer XML (layout, menu, navigation...)
            for m in re.finditer(r'@\+id/([A-Za-z0-9_]+)', path.read_text("utf-8", "ignore")):
                res_types["id"].add(m.group(1))
            if base_type in ("layout", "xml", "menu", "navigation", "anim", "drawable", "mipmap"):
                res_types.setdefault(base_type, set()).add(path.stem)
        elif base_type in ("drawable", "mipmap", "raw", "anim"):
            # nome do arquivo sem sufixo de densidade e sem extensão
            res_types.setdefault(base_type, set()).add(path.stem)
    return res_types


def refs_in_file(path: Path) -> list[tuple[str, str]]:
    """Todos os `R.tipo.nome` do arquivo."""
    text = path.read_text("utf-8", "ignore")
    return re.findall(r"\bR\.(id|string|layout|drawable|mipmap|color|style|xml|array|bool|integer|dimen|menu|anim)\.([A-Za-z0-9_]+)", text)


def check_resource_refs(root: Path, res_types: dict[str, set[str]]) -> None:
    java_files = sorted(root.glob("app/src/main/java/**/*.java")) + sorted(root.glob("app/src/main/java/**/*.kt"))
    for path in java_files:
        for kind, name in refs_in_file(path):
            defined = res_types.get(kind, set())
            if name not in defined:
                err(f"{path.relative_to(root)}: R.{kind}.{name} não existe em app/src/main/res")


def check_layout_refs(root: Path) -> None:
    res = root / "app/src/main/res"
    if not res.is_dir():
        return
    # nomes de mipmap/drawable/layout/string/color definidos
    known: dict[str, set[str]] = {t: set(v) for t, v in collect_resources(res).items()}
    for path in res.rglob("*.xml"):
        text = path.read_text("utf-8", "ignore")
        for m in re.finditer(r'="@(?!\+)(?:\+)?(layout|drawable|mipmap|string|color|style|array|xml)/([A-Za-z0-9_.]+)"', text):
            kind, name = m.group(1), m.group(2)
            pool = known.get(kind, set())
            if pool and name not in pool:
                err(f"{path.relative_to(root)}: referência @{kind}/{name} não existe")
        # @android: e ?attr/ são do framework, ignorados de propósito


def check_findviewbyid(root: Path) -> None:
    """findViewById(R.id.x) precisa existir em algum layout do projeto."""
    res = root / "app/src/main/res/layout"
    if not res.is_dir():
        return
    ids = set()
    for path in res.rglob("*.xml"):
        ids |= set(re.findall(r'@\+id/([A-Za-z0-9_]+)', path.read_text("utf-8", "ignore")))
    for path in sorted(root.glob("app/src/main/java/**/*.java")):
        for m in re.finditer(r"findViewById\(\s*R\.id\.([A-Za-z0-9_]+)\s*\)", path.read_text("utf-8", "ignore")):
            if m.group(1) not in ids:
                err(f"{path.relative_to(root)}: findViewById(R.id.{m.group(1)}) — id não está em nenhum layout")


# ---------------------------------------------------------------- manifest


def check_manifest(root: Path) -> None:
    manifest = root / "app/src/main/AndroidManifest.xml"
    if not manifest.exists():
        err("app/src/main/AndroidManifest.xml não existe")
        return
    try:
        tree = ET.parse(manifest)
    except ET.ParseError as exc:
        err(f"AndroidManifest.xml inválido: {exc}")
        return
    mroot = tree.getroot()

    pkg = mroot.get("package")
    gradle = (root / "app/build.gradle").read_text("utf-8", "ignore")
    ns = re.search(r"namespace\s*=?\s*['\"]([^'\"]+)['\"]", gradle)
    appid = re.search(r"applicationId\s*=?\s*['\"]([^'\"]+)['\"]", gradle)
    if pkg and ns and pkg != ns.group(1):
        err(f"manifest package={pkg} mas namespace={ns.group(1)}")
    # AGP 8 não usa mais `package` no manifest: o pacote vem do namespace do Gradle
    pkg = ns.group(1) if ns else pkg
    if pkg and appid and pkg != appid.group(1):
        warn(f"manifest package={pkg} e applicationId={appid.group(1)} diferem (normal com sufixo de debug)")

    activities = []
    for act in mroot.iter("activity"):
        name = act.get(ANDROID_NS + "name") or act.get("name") or ""
        activities.append(name)
        # a classe precisa existir em disco
        rel = name.lstrip(".").replace(".", "/")
        simple = name.rsplit(".", 1)[-1]
        candidates = [root / f"app/src/main/java/{rel}.java", root / f"app/src/main/java/{rel}.kt"]
        if name.startswith(".") and pkg:
            candidates = [
                root / f"app/src/main/java/{pkg.replace('.', '/')}/{simple}.java",
                root / f"app/src/main/java/{pkg.replace('.', '/')}/{simple}.kt",
            ]
        found = [c for c in candidates if c.exists()]
        if not found:
            err(f"manifest declara activity {name} mas o arquivo não existe")
        elif not any(re.search(rf"\bclass\s+{re.escape(simple)}\b", c.read_text("utf-8", "ignore"))
                     for c in found):
            # arquivo com outro nome de classe é o erro clássico ao renomear uma Activity
            err(f"manifest declara activity {name} mas {found[0].relative_to(root)} não "
                f"declara a classe {simple}")

    has_launcher = any(
        i.get(ANDROID_NS + "name") == "android.intent.action.MAIN"
        for i in mroot.iter("action")
    )
    if not has_launcher:
        err("manifest não tem intent-filter MAIN/LAUNCHER — o app instala mas não abre")

    # permissões realmente usadas no código
    code = "\n".join(p.read_text("utf-8", "ignore") for p in root.glob("app/src/main/java/**/*.java"))
    declared = {p.get(ANDROID_NS + "name") for p in mroot.iter("uses-permission")}
    needed = []
    if "getExternalFilesDir" in code or "Environment.getExternalStorage" in code:
        needed.append("android.permission.WRITE_EXTERNAL_STORAGE")
    if re.search(r"\bNotificationManager\b|\bNotificationCompat\b", code):
        needed.append("android.permission.POST_NOTIFICATIONS")
    for perm in needed:
        if perm not in declared:
            warn(f"código usa {perm.split('.')[-1]} mas a permissão não está no manifest")


# ---------------------------------------------------------------- gradle


def check_gradle(root: Path) -> None:
    path = root / "app/build.gradle"
    if not path.exists():
        err("app/build.gradle não existe")
        return
    text = path.read_text("utf-8", "ignore")

    appid = re.search(r"applicationId\s*=?\s*['\"]([^'\"]+)['\"]", text)
    if appid and len(appid.group(1)) != 10:
        err(f"applicationId '{appid.group(1)}' tem {len(appid.group(1))} caracteres — "
            "o prefixo do Termux exige exatamente 10 (io.rea.ide)")

    def num(key: str) -> int | None:
        m = re.search(rf"{key}\s*=?\s*(\d+)", text)
        return int(m.group(1)) if m else None

    minsdk, target = num("minSdk"), num("targetSdk")
    compile_sdk = num("compileSdk")
    if minsdk and target and target < minsdk:
        err(f"targetSdk {target} < minSdk {minsdk}")
    if compile_sdk is None:
        m = re.search(r"compileSdkVersion\s*=?\s*(\d+)", text)
        compile_sdk = int(m.group(1)) if m else None
    if target and compile_sdk and compile_sdk < target:
        err(f"compileSdk {compile_sdk} < targetSdk {target} — o build falha")

    for abi in re.findall(r"['\"](arm64-v8a|armeabi-v7a|armeabi|x86|x86_64|mips|mips64)['\"]", text):
        if abi not in KNOWN_ABIS:
            err(f"build.gradle: ABI desconhecida '{abi}'")

    if "namespace" not in text:
        err("app/build.gradle sem `namespace` (obrigatório no AGP 8)")


# ---------------------------------------------------------------- java


def check_java_syntax(root: Path) -> None:
    if javalang is None:
        warn("javalang não instalado — sintaxe Java não verificada "
             "(pip install --break-system-packages javalang)")
        return
    for path in sorted(root.glob("app/src/**/*.java")):
        try:
            javalang.parse.parse(path.read_text("utf-8", "ignore"))
        except JAVA_PARSE_ERROR as exc:
            err(f"{path.relative_to(root)}: sintaxe Java inválida: {str(exc)[:200]}")
        except RecursionError:
            warn(f"{path.relative_to(root)}: aninhamento profundo demais para o parser")


# --------------------------------------------------- chamadas entre as próprias classes
# Erro de digitação em nome de método ("bootstrapInstaller.install(" quando o método se
# chama "ensure(") só aparece na compilação — ou seja, ~10 min depois de uma fila de 1h.
# Aqui resolvemos as chamadas contra os métodos das classes do próprio projeto.


def _collect_types(root: Path) -> dict[str, dict]:
    """Nome -> métodos próprios, superclasse e arquivo, para cada classe do projeto."""
    if javalang is None:
        return {}
    types: dict[str, dict] = {}
    sources = sorted(root.glob("app/src/main/java/**/*.java")) + \
        sorted(root.glob("vendor/*/*/src/main/java/**/*.java"))
    _OUTER: dict[int, str] = {}
    for path in sources:
        try:
            tree = javalang.parse.parse(path.read_text("utf-8", "ignore"))
        except JAVA_PARSE_ERROR:
            continue
        for _, node in tree.filter(javalang.tree.ClassDeclaration):
            for inner in node.body or ():
                if isinstance(inner, javalang.tree.ClassDeclaration):
                    _OUTER[id(inner)] = node.name
    for path in sources:
        try:
            tree = javalang.parse.parse(path.read_text("utf-8", "ignore"))
        except JAVA_PARSE_ERROR:
            continue  # erro de sintaxe já reportado por check_java_syntax
        for _, node in tree.filter(javalang.tree.ClassDeclaration):
            info = {
                "file": path,
                "methods": {m.name for m in node.methods},
                "extends": node.extends.name if node.extends else None,
                "outer": _OUTER.get(id(node)),
            }
            types[node.name] = info
            # `Workspace.Entry` também precisa resolver
            if info["outer"]:
                types[f"{info['outer']}.{node.name}"] = info
    return types


def _closed_types(types: dict[str, dict]) -> dict[str, dict]:
    """Classes cuja lista de métodos é completa.

    Se a superclasse é do framework (View, Application, AppCompatActivity…), o método
    pode vir dela e não temos como saber — essas classes ficam de fora. O que sobra são
    as classes "fechadas": sem superclasse, ou filhas de outra classe fechada.
    """
    closed: dict[str, dict] = {}

    def resolve(name: str, seen: frozenset[str]) -> bool:
        if name in closed:
            return True
        info = types.get(name)
        if info is None or name in seen:
            return False
        parent = info["extends"]
        if parent and not resolve(parent, seen | {name}):
            return False
        closed[name] = info
        return True

    for name in list(types):
        resolve(name, frozenset())
    return closed


def _signature(method) -> tuple[str, ...]:
    """Tipos dos parâmetros, normalizados: ('MotionEvent,', 'float') -> ('MotionEvent', 'float')."""
    out = []
    for prm in method.parameters:
        base = getattr(prm.type, "name", "") or ""
        sub = getattr(getattr(prm.type, "sub_type", None), "name", None)
        if sub:
            base = f"{base}.{sub}"
        base += "[]" * len(getattr(prm.type, "dimensions", []) or [])
        if getattr(prm, "varargs", False):
            base += "..."
        out.append(base)
    return tuple(out)


def _walk(body):
    """Percorre a árvore de um bloco. `body` pode ser BlockStatement ou lista de nós."""
    stack = [body]
    while stack:
        item = stack.pop()
        if isinstance(item, (list, tuple)):
            stack.extend(item)
            continue
        if not hasattr(item, "children"):
            continue
        yield item
        stack.extend(item.children or ())


def _declared_type(decl) -> str | None:
    """`BootstrapInstaller installer = ...` -> 'BootstrapInstaller'; `Workspace.Entry e` -> 'Workspace.Entry'."""
    base = getattr(decl.type, "name", None)
    if not base:
        return None
    sub = getattr(getattr(decl.type, "sub_type", None), "name", None)
    return f"{base}.{sub}" if sub else base


def check_internal_calls(root: Path) -> None:
    """Erros de digitação em chamadas para as próprias classes.

    Um `installer.instal(...)` só aparece na compilação, ou seja ~10 min depois de uma
    fila de 1h no CI. Aqui resolvemos cada chamada dentro do escopo do próprio método:
    variáveis locais declaradas nele + campos da classe. Nada de escopo global, que é o
    que gera falso positivo quando um nome é reaproveitado em outro método.
    """
    if javalang is None:
        return  # aviso já emitido por check_java_syntax
    types = _collect_types(root)
    closed = _closed_types(types)
    files_total = len(sorted(root.glob("app/src/main/java/**/*.java")) +
                      sorted(root.glob("vendor/*/*/src/main/java/**/*.java")))
    if files_total == 0:
        err("nenhum arquivo Java encontrado em app/src/main/java — o projeto não foi "
            "encontrado no caminho esperado (--repo correto?)")
        return
    if not types:
        err(f"nenhum dos {files_total} arquivo(s) Java pôde ser analisado — o analisador "
            "está quebrado e a validação não estaria acontecendo")
        return

    checked = 0
    parsed_ok = 0
    reported: set[tuple[str, str, str]] = set()

    def visit(nodes_in, scope: dict[str, str], path: Path) -> None:
        nonlocal checked
        if nodes_in is None:
            return
        nodes = []
        for item in nodes_in:
            nodes.extend(_walk(item) if hasattr(item, "children") else [item])
        # locais do próprio corpo (inclui lambdas aninhados)
        for node in nodes:
            if not isinstance(node, javalang.tree.LocalVariableDeclaration):
                continue
            ltype = _declared_type(node)
            if not ltype or ltype not in closed:
                continue
            for decl in node.declarators:
                scope[decl.name] = ltype
        for call in nodes:
            if not isinstance(call, javalang.tree.MethodInvocation):
                continue
            qualifier = call.qualifier or ""
            if not qualifier or "." in qualifier:
                continue  # `this.x()` / `a.b.c()` ficam de fora de propósito
            target = scope.get(qualifier) or qualifier
            target_type = closed.get(target)
            if target_type is None:
                continue
            checked += 1
            if call.member in target_type["methods"]:
                continue
            key = (str(path), qualifier, call.member)
            if key in reported:
                continue
            reported.add(key)
            methods = sorted(target_type["methods"])
            sample = ", ".join(methods[:6]) + ("…" if len(methods) > 6 else "")
            err(f"{path.relative_to(root)}: {qualifier}.{call.member}() — {target} não "
                f"tem esse método (métodos: {sample or 'nenhum'})")

    for name, owner in types.items():
        path = owner["file"]
        try:
            tree = javalang.parse.parse(path.read_text("utf-8", "ignore"))
        except JAVA_PARSE_ERROR:
            continue
        parsed_ok += 1
        for _, cls in tree.filter(javalang.tree.ClassDeclaration):
            fields: dict[str, str] = {}
            for _, fdecl in cls.filter(javalang.tree.FieldDeclaration):
                ftype = _declared_type(fdecl)
                if not ftype or ftype not in types:
                    continue
                for decl in fdecl.declarators:
                    fields[decl.name] = ftype
            for method in list(cls.methods) + list(cls.constructors):
                visit(method.body, dict(fields), path)
            # `private Helper h = new Helper();` roda na inicialização, não num método
            for fdecl in cls.fields:
                for decl in fdecl.declarators:
                    if decl.initializer is not None:
                        visit([decl.initializer], dict(fields), path)

    if files_total and parsed_ok == 0:
        # O analisador já falhou em silêncio uma vez (um except engoliu um NameError e o
        # check inteiro virou fumaça). Se nenhum arquivo foi lido, isso é erro, não "ok".
        err(f"nenhum dos {files_total} arquivo(s) Java pôde ser analisado — o analisador "
            "está quebrado e a validação não estaria acontecendo")


# ------------------------------------------------- interfaces implementadas por completo
# Reusar as interfaces do Termux (TerminalSessionClient tem ~20 métodos) e esquecer um
# deles é o erro de compilação mais comum nesse tipo de fork — e o compilador só reclama
# no fim da fila do CI.


def check_interface_impls(root: Path) -> None:
    """Classe que `implements` uma interface do projeto e esquece um método dela.

    Reusar as interfaces do Termux (TerminalSessionClient tem dezenas de métodos) e
    deixar um de fora é o erro de compilação mais comum num fork assim — e o compilador
    só reclama depois da fila inteira do CI.
    """
    if javalang is None:
        return
    sources = sorted(root.glob("app/src/main/java/**/*.java")) + \
        sorted(root.glob("vendor/*/*/src/main/java/**/*.java"))
    interfaces: dict[str, set[str]] = {}
    types: dict[str, tuple[set[str], str | None]] = {}

    def collect(node, path: Path) -> None:
        for inner in node.body or ():
            if isinstance(inner, javalang.tree.InterfaceDeclaration):
                # métodos sem corpo; `default` e `static` já têm implementação
                interfaces[inner.name] = {
                    (m.name, _signature(m)) for m in inner.methods
                    if not ({"default", "static"} & set(m.modifiers or ()))
                }
                collect(inner, path)
            elif isinstance(inner, javalang.tree.ClassDeclaration):
                types.setdefault(inner.name, (
                    {(m.name, _signature(m)) for m in inner.methods},
                    inner.extends.name if inner.extends else None,
                ))
                collect(inner, path)

    for path in sources:
        try:
            tree = javalang.parse.parse(path.read_text("utf-8", "ignore"))
        except JAVA_PARSE_ERROR:
            continue
        for _, node in tree.filter(javalang.tree.ClassDeclaration):
            types.setdefault(node.name, (
                {(m.name, _signature(m)) for m in node.methods},
                node.extends.name if node.extends else None,
            ))
            collect(node, path)
        for _, node in tree.filter(javalang.tree.InterfaceDeclaration):
            interfaces.setdefault(node.name, {
                (m.name, _signature(m)) for m in node.methods
                if not ({"default", "static"} & set(m.modifiers or ()))
            })
            collect(node, path)

    def inherited_methods(name: str, seen: frozenset[str] = frozenset()) -> set[tuple]:
        if name in seen or name not in types:
            return set()
        methods, parent = types[name]
        return methods | (inherited_methods(parent, seen | {name}) if parent else set())

    for path in sources:
        try:
            tree = javalang.parse.parse(path.read_text("utf-8", "ignore"))
        except JAVA_PARSE_ERROR:
            continue
        for _, node in tree.filter(javalang.tree.ClassDeclaration):
            for iface in node.implements or ():
                required = interfaces.get(iface.name)
                if required is None:
                    continue  # interface do framework/androidx: fonte não está aqui
                have = inherited_methods(node.name)
                missing = sorted(set(required) - have)
                if missing:
                    shown = ", ".join(
                        f"{name}({', '.join(sig)})" for name, sig in missing[:6]
                    )
                    tail = "…" if len(missing) > 6 else ""
                    wrong_name = any(name in {n for n, _ in have} for name, _ in missing)
                    hint = (" — mesmo nome existe, mas o tipo dos parâmetros é diferente"
                            if wrong_name else "")
                    err(f"{path.relative_to(root)}: {node.name} implements {iface.name} "
                        f"mas não implementa {len(missing)} método(s): {shown}{tail}{hint}")


# ----------------------------------------------------- herança implícita de <style>
# No Android, um estilo cujo nome tem ponto herda do "prefixo" quando não declara parent:
#   <style name="Rea.ToolbarButton">  ->  parent implícito "Rea"
# Se "Rea" não existe, o build morre no AAPT2 com
#   "resource style/Rea (aka io.rea.ide:style/Rea) not found" / "failed linking references".
# Isso compila até o fim do build e falha no passo de link — caro de descobrir.


def check_style_parents(root: Path) -> None:
    values = list((root / "app/src/main/res").glob("values*/*.xml"))
    values += list((root / "vendor").glob("*/**/src/main/res/values*/*.xml"))
    if not values:
        return

    styles: dict[str, tuple[Path, str | None]] = {}
    for path in values:
        try:
            tree = ET.parse(path).getroot()
        except ET.ParseError:
            continue  # já reportado em collect_resources
        for node in tree.iter("style"):
            name = node.get("name")
            if name:
                # parent=None -> atributo ausente; parent="" -> explicitamente sem pai
                styles.setdefault(name, (path, node.get("parent")))

    for name, (path, parent) in styles.items():
        if parent is not None:
            continue  # tem parent declarado (inclusive parent="")
        if "." not in name:
            continue  # estilo de nome simples não herda nada
        implicit = name.rsplit(".", 1)[0]
        if implicit in styles:
            continue  # pai definido no projeto: ok
        # o pai pode ser um estilo do framework/AppCompat (Theme.AppCompat.*, Widget.*)
        if "." in implicit and implicit.split(".")[0] in (
            "Theme", "Widget", "TextAppearance", "Platform", "Base"
        ):
            continue
        err(f"{path.relative_to(root)}: <style name=\"{name}\"> sem parent herda de "
            f"\"{implicit}\" (implicito pelo ponto no nome) e \"{implicit}\" nao existe — "
            f"o AAPT2 falha com \"style/{implicit} not found\". "
            f'Adicione parent="" se nao quiser heranca.')


# ------------------------------------------------------- aridade das próprias chamadas
# Chamar `metodo(a, b)` quando ele recebe 3 argumentos é erro de compilação — e, de novo,
# só apareceria no fim da fila. Aqui comparamos a contagem de argumentos com a assinatura
# das classes do próprio projeto (inclui métodos estáticos chamados por Classe.metodo()).


def check_call_arity(root: Path) -> None:
    if javalang is None:
        return
    sources = sorted(root.glob("app/src/main/java/**/*.java")) + \
        sorted(root.glob("vendor/*/*/src/main/java/**/*.java"))
    # nome -> {metodo: [(min_args, max_args)]}
    arity: dict[str, dict[str, list[tuple[int, int | None]]]] = {}
    ctor_arity: dict[str, list[tuple[int, int | None]]] = {}

    def arities(params) -> tuple[int, int | None]:
        total = len(params)
        if total and getattr(params[-1], "varargs", False):
            return total - 1, None  # varargs: mínimo n-1, máximo ilimitado
        return total, total

    parents: dict[str, str | None] = {}
    files: list[tuple[Path, object]] = []
    for path in sources:
        try:
            tree = javalang.parse.parse(path.read_text("utf-8", "ignore"))
        except JAVA_PARSE_ERROR:
            continue
        files.append((path, tree))
        for _, cls in tree.filter(javalang.tree.ClassDeclaration):
            methods = arity.setdefault(cls.name, {})
            for m in cls.methods:
                methods.setdefault(m.name, []).append(arities(m.parameters))
            ctor_arity[cls.name] = [arities(c.parameters) for c in cls.constructors]
            parents[cls.name] = cls.extends.name if cls.extends else None

    def with_inherited(name: str, seen: frozenset[str] = frozenset()) -> dict[str, list]:
        """Métodos próprios + herdados de superclasses do projeto.

        `TerminalSession` extends `TerminalOutput`: sem isso, `session.write("x")` parece
        ter 1 argumento quando a sobrecarga com String está na superclasse.
        """
        if name in seen:
            return {}
        merged: dict[str, list] = {}
        parent = parents.get(name)
        if parent:
            for mname, ranges in with_inherited(parent, seen | {name}).items():
                merged.setdefault(mname, []).extend(ranges)
        for mname, ranges in arity.get(name, {}).items():
            # sobrecargas SOMAM: update() trocaria a lista do pai pela do filho e
            # esconderia a versão herdada (foi o que escondeu TerminalOutput.write)
            merged.setdefault(mname, []).extend(ranges)
        return merged

    arity = {name: with_inherited(name) for name in arity}

    def accepts(ranges, count: int) -> bool:
        for lo, hi in ranges:
            if count >= lo and (hi is None or count <= hi):
                return True
        return False

    reported: set[tuple[str, str, str, int]] = set()
    for path, tree in files:
        for _, cls in tree.filter(javalang.tree.ClassDeclaration):
            fields: dict[str, str] = {}
            for _, fdecl in cls.filter(javalang.tree.FieldDeclaration):
                ftype = _declared_type(fdecl)
                if ftype and ftype in arity:
                    for decl in fdecl.declarators:
                        fields[decl.name] = ftype
            bodies = [(m.body, []) for m in cls.methods] + [(c.body, []) for c in cls.constructors]
            # inicializadores de campo: `private Helper h = new Helper();`
            bodies.append((None, [decl.initializer for fdecl in cls.fields
                                  for decl in fdecl.declarators
                                  if decl.initializer is not None]))
            for body, extra_roots in bodies:
                nodes = list(_walk(body)) if body is not None else []
                for root_node in extra_roots:
                    nodes.extend(_walk(root_node))
                scope = dict(fields)
                for node in nodes:
                    if isinstance(node, javalang.tree.LocalVariableDeclaration):
                        ltype = _declared_type(node)
                        if ltype and ltype in arity:
                            for decl in node.declarators:
                                scope[decl.name] = ltype
                for node in nodes:
                    if not isinstance(node, (javalang.tree.MethodInvocation,
                                             javalang.tree.ClassCreator)):
                        continue
                    qualifier = getattr(node, "qualifier", None) or ""
                    if not isinstance(node, javalang.tree.ClassCreator):
                        if not qualifier or "." in qualifier:
                            continue
                        target = scope.get(qualifier) or qualifier
                        if target not in arity:
                            continue
                        ranges = arity[target].get(node.member)
                        label = f"{target}.{node.member}"
                        if not ranges:
                            continue  # método inexistente: já reportado
                    else:
                        target = getattr(node.type, "name", None)
                        sub = getattr(getattr(node.type, "sub_type", None), "name", None)
                        if sub and not (node.arguments or ()):
                            continue  # `new X.Listener() { ... }`: classe anônima da interface
                        if not target or target not in arity:
                            continue
                        ranges = ctor_arity.get(target) or []
                        label = f"new {target}"
                        if not ranges:
                            continue
                    count = len(node.arguments or ())
                    if accepts(ranges, count):
                        continue
                    key = (str(path), label, str(count), 0)
                    if key in reported:
                        continue
                    reported.add(key)
                    allowed = ", ".join(
                        f"{lo} ou mais" if hi is None else (str(lo) if lo == hi else f"{lo} a {hi}")
                        for lo, hi in ranges)
                    err(f"{path.relative_to(root)}: {label}(...) com {count} argumento(s), "
                        f"mas a assinatura aceita {allowed}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parent.parent))
    args = ap.parse_args()
    root = Path(args.repo).resolve()

    res_dir = root / "app/src/main/res"
    res_types = collect_resources(res_dir)

    def run(label: str, fn) -> None:
        """Um checador que explode é ERRO, não "ok".

        Já aconteceu aqui: um `except Exception: continue` engoliu um NameError e a
        validação inteira deixou de acontecer sem avisar ninguém.
        """
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 — a ideia é justamente não vazar
            err(f"checador '{label}' falhou com {type(exc).__name__}: {exc} — "
                "a validação NÃO foi feita")

    run("recursos", lambda: check_resource_refs(root, res_types))
    run("layouts", lambda: check_layout_refs(root))
    run("findViewById", lambda: check_findviewbyid(root))
    run("manifest", lambda: check_manifest(root))
    run("gradle", lambda: check_gradle(root))
    run("sintaxe java", lambda: check_java_syntax(root))
    run("chamadas internas", lambda: check_internal_calls(root))
    run("interfaces", lambda: check_interface_impls(root))
    run("estilos", lambda: check_style_parents(root))
    run("aridade", lambda: check_call_arity(root))

    for w in warnings:
        print(f"  · aviso: {w}")
    for e in errors:
        print(f"  ✗ {e}")
    if errors:
        print(f"\n{len(errors)} problema(s) encontrado(s).")
        return 1
    counts = ", ".join(f"{k}={len(v)}" for k, v in sorted(res_types.items()) if v)
    print(f"  ✓ fontes Android ok ({counts})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
