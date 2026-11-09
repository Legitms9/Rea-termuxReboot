#!/usr/bin/env python3
"""Testes do scripts/check_android_sources.py.

Cada caso monta um projeto Android falso mínimo num diretório temporário, quebra uma coisa
e confirma que o checador reclama. Isso importa porque o checador já falhou em silêncio
uma vez (um `except Exception: continue` engoliu um NameError e a validação inteira virou
fumaça) — e um validador que não acusa nada é pior do que não ter validador.

Rode: python3 -m unittest discover -s scripts/tests -p 'test_*sources*.py' -v
"""
from __future__ import annotations

import importlib.util
import textwrap
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "check_android_sources.py"
spec = importlib.util.spec_from_file_location("check_android_sources", SCRIPT)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)

MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <application android:label="@string/app_name" android:theme="@style/Theme.X">
        <activity android:name=".MainActivity">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
"""

GRADLE = """plugins { id 'com.android.application' }
android {
    namespace 'io.rea.ide'
    compileSdk 34
    defaultConfig {
        applicationId 'io.rea.ide'
        minSdk 24
        targetSdk 34
    }
}
"""

LAYOUT = """<?xml version="1.0" encoding="utf-8"?>
<LinearLayout xmlns:android="http://schemas.android.com/apk/res/android">
    <TextView android:id="@+id/title" android:text="@string/app_name" />
</LinearLayout>
"""

STRINGS = """<?xml version="1.0" encoding="utf-8"?>
<resources><string name="app_name">REA</string></resources>
"""

THEMES = """<?xml version="1.0" encoding="utf-8"?>
<resources><style name="Theme.X" parent="android:Theme.Material" /></resources>
"""

needs_javalang = unittest.skipIf(
    checker.javalang is None,
    "javalang não instalado: as checagens de Java são puladas (o CLI avisa)",
)

MAIN_ACTIVITY = """package io.rea.ide;

import android.app.Activity;

public class MainActivity extends Activity {
    private Helper helper = new Helper();

    public void onCreate() {
        helper.work();
    }
}
"""

HELPER = """package io.rea.ide;

public class Helper {
    public void work() {}
}
"""


class Project:
    """Projeto Android mínimo em um diretório temporário."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.write("app/src/main/AndroidManifest.xml", MANIFEST)
        self.write("app/build.gradle", GRADLE)
        self.write("app/src/main/res/layout/activity_main.xml", LAYOUT)
        self.write("app/src/main/res/values/strings.xml", STRINGS)
        self.write("app/src/main/res/values/themes.xml", THEMES)
        self.write("app/src/main/java/io/rea/ide/MainActivity.java", MAIN_ACTIVITY)
        self.write("app/src/main/java/io/rea/ide/Helper.java", HELPER)

    def write(self, rel: str, content: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        return path

    def check(self) -> list[str]:
        checker.errors.clear()
        checker.warnings.clear()
        checker.main.__globals__["sys"].argv = ["check", "--repo", str(self.root)]
        try:
            checker.main()
        except SystemExit:
            pass
        return list(checker.errors)


class AndroidSourceChecks(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(__import__("tempfile").TemporaryDirectory()))
        self.project = Project(self.tmp)

    def test_projeto_saudavel_passa(self) -> None:
        self.assertEqual([], self.project.check())

    def test_rid_inexistente(self) -> None:
        self.project.write("app/src/main/java/io/rea/ide/MainActivity.java", """\
            package io.rea.ide;
            import android.app.Activity;
            public class MainActivity extends Activity {
                public void onCreate() { findViewById(R.id.nao_existe); }
            }
        """)
        errors = self.project.check()
        self.assertTrue(any("nao_existe" in e for e in errors), errors)

    def test_string_inexistente_no_layout(self) -> None:
        self.project.write("app/src/main/res/layout/activity_main.xml", """\
            <?xml version="1.0" encoding="utf-8"?>
            <LinearLayout xmlns:android="http://schemas.android.com/apk/res/android">
                <TextView android:text="@string/fantasma" />
            </LinearLayout>
        """)
        errors = self.project.check()
        self.assertTrue(any("@string/fantasma" in e for e in errors), errors)

    @needs_javalang
    def test_metodo_inexistente_em_variavel_local(self) -> None:
        self.project.write("app/src/main/java/io/rea/ide/MainActivity.java", """\
            package io.rea.ide;
            import android.app.Activity;
            public class MainActivity extends Activity {
                public void onCreate() {
                    Helper h = new Helper();
                    h.trabalho();
                }
            }
        """)
        errors = self.project.check()
        self.assertTrue(any("h.trabalho()" in e for e in errors), errors)

    @needs_javalang
    def test_metodo_inexistente_em_campo(self) -> None:
        self.project.write("app/src/main/java/io/rea/ide/MainActivity.java", """\
            package io.rea.ide;
            import android.app.Activity;
            public class MainActivity extends Activity {
                private Helper helper = new Helper();
                public void onCreate() { helper.trabalho(); }
            }
        """)
        errors = self.project.check()
        self.assertTrue(any("helper.trabalho()" in e for e in errors), errors)

    def test_nome_reaproveitado_em_outro_metodo_nao_da_falso_positivo(self) -> None:
        """`e` de um método não pode ser confundido com o `e` de outro."""
        self.project.write("app/src/main/java/io/rea/ide/Helper.java", """\
            package io.rea.ide;
            public class Helper {
                public void work() {}
                public void outro(Helper e) { e.work(); }
            }
        """)
        self.project.write("app/src/main/java/io/rea/ide/MainActivity.java", """\
            package io.rea.ide;
            import android.app.Activity;
            public class MainActivity extends Activity {
                public void onCreate() {
                    Helper helper = new Helper();
                    helper.work();
                }
            }
        """)
        self.assertEqual([], self.project.check())

    @needs_javalang
    def test_interface_incompleta(self) -> None:
        self.project.write("app/src/main/java/io/rea/ide/Listener.java", """\
            package io.rea.ide;
            public interface Listener {
                void aoAbrir(String caminho);
                void aoFechar();
            }
        """)
        self.project.write("app/src/main/java/io/rea/ide/Impl.java", """\
            package io.rea.ide;
            public class Impl implements Listener {
                public void aoAbrir(String caminho) {}
            }
        """)
        errors = self.project.check()
        self.assertTrue(any("aoFechar" in e for e in errors), errors)

    @needs_javalang
    def test_interface_completa_com_heranca(self) -> None:
        self.project.write("app/src/main/java/io/rea/ide/Listener.java", """\
            package io.rea.ide;
            public interface Listener {
                void aoAbrir(String caminho);
                void aoFechar();
                default void opcional() {}
            }
        """)
        self.project.write("app/src/main/java/io/rea/ide/Base.java", """\
            package io.rea.ide;
            public abstract class Base {
                public void aoFechar() {}
            }
        """)
        self.project.write("app/src/main/java/io/rea/ide/Impl.java", """\
            package io.rea.ide;
            public class Impl extends Base implements Listener {
                public void aoAbrir(String caminho) {}
            }
        """)
        self.assertEqual([], self.project.check())

    def test_application_id_com_10_caracteres_e_obrigatorio(self) -> None:
        self.project.write("app/build.gradle", GRADLE.replace("'io.rea.ide'", "'io.rea.idex'"))
        errors = self.project.check()
        self.assertTrue(any("caracteres" in e and "io.rea.idex" in e for e in errors), errors)

    def test_compile_sdk_menor_que_target(self) -> None:
        self.project.write("app/build.gradle", GRADLE.replace("compileSdk 34", "compileSdk 31"))
        errors = self.project.check()
        self.assertTrue(any("compileSdk" in e for e in errors), errors)

    def test_activity_declarada_sem_classe(self) -> None:
        self.project.write("app/src/main/java/io/rea/ide/MainActivity.java", """\
            package io.rea.ide;
            public class OutraActivity {}
        """)
        errors = self.project.check()
        self.assertTrue(any("MainActivity" in e for e in errors), errors)

    def test_sintaxe_java_invalida(self) -> None:
        if checker.javalang is None:
            self.skipTest("javalang não instalado")
        self.project.write("app/src/main/java/io/rea/ide/MainActivity.java", """\
            package io.rea.ide;
            public class MainActivity {
                void f() { int x = ; }
            }
        """)
        errors = self.project.check()
        self.assertTrue(any("sintaxe Java inválida" in e for e in errors), errors)

    @needs_javalang
    def test_analisador_quebrado_nao_passa_em_silencio(self) -> None:
        """Se nada pôde ser analisado, o checador tem que falhar — não imprimir ✓."""
        original = checker._collect_types
        # arquivo real que NÃO tem chamadas internas: a varredura roda, verifica zero e
        # precisa reclamar em vez de dizer "ok"
        checked = self.project.write("app/src/main/java/io/rea/ide/SemChamadas.java", """\
            package io.rea.ide;
            public class SemChamadas {
                void nada() { int x = 1 + 1; }
            }
        """)
        checker._collect_types = lambda root: {"SemChamadas": {
            "file": checked, "methods": {"nada"}, "extends": None, "outer": None}}
        try:
            errors = self.project.check()
        finally:
            checker._collect_types = original
        self.assertTrue(any("nenhuma chamada interna" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
