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
    def test_interface_com_tipo_de_parametro_errado(self) -> None:
        """Mesmo nome, tipo diferente: o compilador acusa 'does not override'."""
        self.project.write("app/src/main/java/io/rea/ide/Listener.java", """\
            package io.rea.ide;
            public interface Listener {
                void aoAbrir(String caminho);
            }
        """)
        self.project.write("app/src/main/java/io/rea/ide/Impl.java", """\
            package io.rea.ide;
            public class Impl implements Listener {
                public void aoAbrir(int caminho) {}
            }
        """)
        errors = self.project.check()
        self.assertTrue(any("aoAbrir" in e and "tipo" in e for e in errors), errors)

    @needs_javalang
    def test_interface_com_heranca(self) -> None:
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

    def test_estilo_sem_parent_herda_pai_inexistente(self) -> None:
        """O erro real do CI: <style name="Rea.X"> sem parent herda de "Rea"."""
        self.project.write("app/src/main/res/values/themes.xml", """\
            <?xml version="1.0" encoding="utf-8"?>
            <resources>
                <style name="Theme.X" parent="android:Theme.Material" />
                <style name="Rea.ToolbarButton">
                    <item name="android:textSize">12sp</item>
                </style>
            </resources>
        """)
        errors = self.project.check()
        self.assertTrue(any('style/Rea not found' in e for e in errors), errors)

    def test_estilo_com_parent_vazio_passa(self) -> None:
        """parent="" desliga a herança implícita: é a correção usada no projeto."""
        self.project.write("app/src/main/res/values/themes.xml", """\
            <?xml version="1.0" encoding="utf-8"?>
            <resources>
                <style name="Theme.X" parent="android:Theme.Material" />
                <style name="Rea.ToolbarButton" parent="">
                    <item name="android:textSize">12sp</item>
                </style>
            </resources>
        """)
        self.assertEqual([], self.project.check())

    def test_estilo_filho_de_estilo_existente_passa(self) -> None:
        self.project.write("app/src/main/res/values/themes.xml", """\
            <?xml version="1.0" encoding="utf-8"?>
            <resources>
                <style name="Theme.X" parent="android:Theme.Material" />
                <style name="Rea.Text" parent="">
                    <item name="android:textSize">13sp</item>
                </style>
                <style name="Rea.Text.Dim">
                    <item name="android:textSize">11sp</item>
                </style>
            </resources>
        """)
        self.assertEqual([], self.project.check())

    def test_estilo_apontando_para_style_inexistente_no_layout(self) -> None:
        self.project.write("app/src/main/res/layout/activity_main.xml", """\
            <?xml version="1.0" encoding="utf-8"?>
            <LinearLayout xmlns:android="http://schemas.android.com/apk/res/android">
                <TextView style="@style/Rea.Fantasma" />
            </LinearLayout>
        """)
        errors = self.project.check()
        self.assertTrue(any("@style/Rea.Fantasma" in e for e in errors), errors)

    @needs_javalang
    def test_aridade_errada_em_chamada(self) -> None:
        self.project.write("app/src/main/java/io/rea/ide/Helper.java", """\
            package io.rea.ide;
            public class Helper {
                public void work(String a, int b) {}
            }
        """)
        self.project.write("app/src/main/java/io/rea/ide/MainActivity.java", """\
            package io.rea.ide;
            public class MainActivity {
                public void onCreate() {
                    Helper h = new Helper();
                    h.work("so um");
                }
            }
        """)
        errors = self.project.check()
        self.assertTrue(any("Helper.work" in e and "1 argumento" in e for e in errors), errors)

    @needs_javalang
    def test_sobrecarga_herdada_da_superclasse_nao_e_falso_positivo(self) -> None:
        """TerminalSession extends TerminalOutput: write(String) vem do pai."""
        self.project.write("app/src/main/java/io/rea/ide/Base.java", """\
            package io.rea.ide;
            public abstract class Base {
                public final void write(String data) {}
                public abstract void write(byte[] data, int offset, int count);
            }
        """)
        self.project.write("app/src/main/java/io/rea/ide/Impl.java", """\
            package io.rea.ide;
            public class Impl extends Base {
                public void write(byte[] data, int offset, int count) {}
                public void usar() { write("texto com 1 argumento"); }
            }
        """)
        self.assertEqual([], self.project.check())

    @needs_javalang
    def test_classe_anonima_de_interface_nao_e_construtor(self) -> None:
        """`new Helper.Listener() { ... }` não é `new Helper()`."""
        self.project.write("app/src/main/java/io/rea/ide/Helper.java", """\
            package io.rea.ide;
            public class Helper {
                public interface Listener { void aoAbrir(); }
                public Helper(String a, int b) {}
            }
        """)
        self.project.write("app/src/main/java/io/rea/ide/MainActivity.java", """\
            package io.rea.ide;
            public class MainActivity {
                private Object o = new Helper.Listener() {
                    @Override public void aoAbrir() {}
                };
            }
        """)
        self.assertEqual([], self.project.check())

    @needs_javalang
    def test_construtor_com_numero_errado_de_argumentos(self) -> None:
        self.project.write("app/src/main/java/io/rea/ide/Helper.java", """\
            package io.rea.ide;
            public class Helper { public Helper(String a) {} }
        """)
        self.project.write("app/src/main/java/io/rea/ide/MainActivity.java", """\
            package io.rea.ide;
            public class MainActivity {
                private Helper h = new Helper();
            }
        """)
        errors = self.project.check()
        self.assertTrue(any("new Helper" in e for e in errors), errors)

    @needs_javalang
    def test_varargs_aceita_qualquer_quantidade(self) -> None:
        self.project.write("app/src/main/java/io/rea/ide/Helper.java", """\
            package io.rea.ide;
            public class Helper {
                public void run(String cmd, String... args) {}
            }
        """)
        self.project.write("app/src/main/java/io/rea/ide/MainActivity.java", """\
            package io.rea.ide;
            public class MainActivity {
                public void onCreate() {
                    Helper h = new Helper();
                    h.run("ls");
                    h.run("ls", "-l", "-a");
                }
            }
        """)
        self.assertEqual([], self.project.check())

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
    def test_checador_que_explode_vira_erro(self) -> None:
        """Um checador que levanta exceção não pode virar "✓ ok"."""
        original = checker.check_style_parents

        def boom(root):
            raise NameError("name 'javalang' is not defined")

        checker.check_style_parents = boom
        try:
            errors = self.project.check()
        finally:
            checker.check_style_parents = original
        self.assertTrue(any("estilos" in e and "NameError" in e for e in errors), errors)

    def test_projeto_vazio_de_java_nao_imprime_ok_sem_analisar(self) -> None:
        import shutil
        shutil.rmtree(self.project.root / "app/src/main/java")
        errors = self.project.check()
        self.assertTrue(any("nenhum" in e and "Java" in e for e in errors), errors)

if __name__ == "__main__":
    unittest.main(verbosity=2)
