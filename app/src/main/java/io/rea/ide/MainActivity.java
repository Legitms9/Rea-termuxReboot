package io.rea.ide;

import android.annotation.SuppressLint;
import android.app.AlertDialog;
import android.content.Intent;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.util.Log;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.drawerlayout.widget.DrawerLayout;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import com.termux.terminal.TerminalProcess;
import com.termux.terminal.TerminalSession;
import com.termux.view.TerminalView;
import com.termux.view.TerminalViewClient;


import java.io.File;

import io.rea.ide.runtime.BootstrapInstaller;
import io.rea.ide.runtime.ReaPaths;
import io.rea.ide.runtime.ShellEnv;
import io.rea.ide.runtime.TerminalManager;

/**
 * The IDE shell: an editor page (CodeMirror in a WebView) and a terminal page
 * (vendored termux terminal-view) sharing one activity bar, one explorer drawer and one
 * status bar.
 */
public class MainActivity extends AppCompatActivity
        implements TerminalManager.Listener, TerminalViewClient, FileAdapter.Listener {

    private static final String TAG = "ReaMain";
    private static final int PAGE_EDITOR = 0;
    private static final int PAGE_TERMINAL = 1;

    // ------------------------------------------------------------------ state
    private DrawerLayout drawer;
    private FrameLayout editorHost, terminalHost;
    private WebView editor;
    private TerminalView terminalView;
    private LinearLayout sessionTabs;
    private LinearLayout extraKeysRow;
    private ScrollView consoleScroll;
    private TextView consoleText;
    private final StringBuilder consoleBuffer = new StringBuilder();
    private RecyclerView fileList;
    private FileAdapter fileAdapter;
    private TextView bottomPath, bottomStatus, drawerPath, tabFiles, tabEditor, tabTerminal;
    private View extraKeys;

    private TerminalManager terminals;
    private TerminalManager.Descriptor activeSession;
    private int activePage = PAGE_EDITOR;

    private boolean bootstrapReady = false;
    private String cwd;
    private final Handler main = new Handler(Looper.getMainLooper());
    private boolean editorPageReady = false;
    private String pendingOpenPath;

    // --------------------------------------------------------------- lifecycle

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        ReaPaths.init(getPackageName());
        setContentView(R.layout.activity_main);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        bindViews();
        buildPager();
        buildTerminal();
        buildExplorer();
        wireActivityBar();

        cwd = Workspace.projects().getAbsolutePath();
        openProject(cwd);
        handleViewIntent(getIntent());

        new Thread(this::installBootstrapIfNeeded, "rea-bootstrap").start();
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleViewIntent(intent);
    }

    /** Opens a file passed by a file manager (file:// or content://). */
    private void handleViewIntent(Intent intent) {
        if (intent == null || !Intent.ACTION_VIEW.equals(intent.getAction())) return;
        android.net.Uri uri = intent.getData();
        if (uri == null) return;
        if ("file".equals(uri.getScheme()) && uri.getPath() != null) {
            openInEditor(uri.getPath());
            return;
        }
        // content://: copy into the workspace so the editor owns a real path.
        try (java.io.InputStream in = getContentResolver().openInputStream(uri)) {
            if (in == null) return;
            String name = "shared-" + System.currentTimeMillis() + ".txt";
            String dest = ReaPaths.home() + "/shared/" + name;
            Workspace.createDir(ReaPaths.home() + "/shared");
            Workspace.write(dest, Workspace.readAll(in));
            openInEditor(dest);
        } catch (Exception e) {
            toast("Não foi possível abrir o arquivo compartilhado");
        }
    }

    @Override
    protected void onPause() {
        super.onPause();
        // The web layer buffers edits for 220 ms; force a flush before backgrounding.
        if (editor != null) editor.evaluateJavascript("window.ReaIde && window.ReaIde.flush && ReaIde.flush()", null);
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        if (editor != null) editor.destroy();
    }

    private void bindViews() {
        drawer = findViewById(R.id.drawer_layout);
        bottomPath = findViewById(R.id.bottom_path);
        bottomStatus = findViewById(R.id.bottom_status);
        drawerPath = findViewById(R.id.drawer_path);
        tabFiles = findViewById(R.id.tab_files);
        tabEditor = findViewById(R.id.tab_editor);
        tabTerminal = findViewById(R.id.tab_terminal);
        extraKeys = findViewById(R.id.extra_keys_container);
    }

    // ------------------------------------------------------------------- pages

    /**
     */
    /**
     * Two pages, no carousel: the editor (WebView) and the terminal live in sibling FrameLayouts and
     * we just toggle visibility. A ViewPager here would fight the terminal's own horizontal
     * gestures, which is exactly why IDEs don't page-swipe between editor and shell.
     */
    private void buildPager() {
        editorHost = findViewById(R.id.editor_host);
        extraKeysRow = findViewById(R.id.extra_keys_row);
        terminalHost = findViewById(R.id.terminal_host);

        View editorPage = getLayoutInflater().inflate(R.layout.page_editor, editorHost, false);
        editor = editorPage.findViewById(R.id.editor_webview);
        setupWebView(editor);
        editorHost.addView(editorPage);

        View terminalPage = getLayoutInflater().inflate(R.layout.page_terminal, terminalHost, false);
        terminalView = terminalPage.findViewById(R.id.terminal_view);
        terminalView.setTerminalViewClient(this);
        terminalView.setTextSize(mTerminalFontSize);
        sessionTabs = terminalPage.findViewById(R.id.session_tabs);
        consoleScroll = terminalPage.findViewById(R.id.console_scroll);
        consoleText = terminalPage.findViewById(R.id.console_text);
        wireTerminalKeys(terminalPage);
        buildExtraKeys();
        terminalHost.addView(terminalPage);

        showPage(PAGE_EDITOR);
    }

    private void showPage(int page) {
        activePage = page;
        editorHost.setVisibility(page == PAGE_EDITOR ? View.VISIBLE : View.GONE);
        terminalHost.setVisibility(page == PAGE_TERMINAL ? View.VISIBLE : View.GONE);
        updateChrome();
        if (page == PAGE_TERMINAL) {
            if (activeSession != null) terminalView.attachSession(activeSession.session);
            terminalView.requestFocus();
        }
    }

    private void wireActivityBar() {
        tabFiles.setOnClickListener(v -> drawer.openDrawer(Gravity.START));
        tabEditor.setOnClickListener(v -> showPage(PAGE_EDITOR));
        tabTerminal.setOnClickListener(v -> {
            showPage(PAGE_TERMINAL);
            ensureSession();
        });
        findViewById(R.id.btn_run).setOnClickListener(v -> showRunDialog());
        findViewById(R.id.btn_more).setOnClickListener(v -> showMoreMenu());
    }

    private void updateChrome() {
        highlightTab(tabFiles, false);
        highlightTab(tabEditor, activePage == PAGE_EDITOR);
        highlightTab(tabTerminal, activePage == PAGE_TERMINAL);
        extraKeys.setVisibility(View.VISIBLE);
        buildExtraKeys();
        updateBottomBar();
    }

    private void highlightTab(TextView v, boolean on) {
        v.setTextColor(on ? getColor(R.color.rea_accent) : getColor(R.color.rea_text_dim));
        v.setBackgroundResource(on ? R.drawable.bg_toolbar_button : 0);
    }

    private void updateBottomBar() {
        bottomPath.setText(ShellEnv.prettyPath(cwd));
        String status;
        if (!bootstrapReady) status = "instalando ambiente…";
        else if (activePage == PAGE_TERMINAL && activeSession != null) status = "shell · " + activeSession.name;
        else status = "editor";
        bottomStatus.setText(status);
    }

    // ---------------------------------------------------------------- webview

    @SuppressLint("SetJavaScriptEnabled")
    private void setupWebView(WebView wv) {
        WebSettings s = wv.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(true);
        s.setAllowContentAccess(false);
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        s.setTextZoom(100);
        s.setMediaPlaybackRequiresUserGesture(true);
        s.setCacheMode(WebSettings.LOAD_NO_CACHE);
        wv.setBackgroundColor(Color.parseColor("#0B0E14"));
        wv.setWebViewClient(new WebViewClient() {
            @Override public void onPageFinished(WebView view, String url) {
                editorPageReady = true;
                if (pendingOpenPath != null) {
                    openInEditor(pendingOpenPath);
                    pendingOpenPath = null;
                }
            }
        });
        wv.setWebChromeClient(new WebChromeClient());
        wv.addJavascriptInterface(new EditorBridge(), "ReaIdeBridge");
        wv.loadUrl("file:///android_asset/www/index.html");
    }

    /** Called by the web layer. Runs on the WebView's JS thread — always hop to UI. */
    private final class EditorBridge {
        @JavascriptInterface
        public void onReady() {
            main.post(() -> {
                editorPageReady = true;
                if (pendingOpenPath != null) {
                    openInEditor(pendingOpenPath);
                    pendingOpenPath = null;
                }
            });
        }

        @JavascriptInterface
        public void onContentChanged(String path, String content) {
            saveFile(path, content);
        }

        @JavascriptInterface
        public void onCommand(String action) {
            main.post(() -> handleEditorCommand(action));
        }
    }

    private void js(String code) {
        if (editor == null) return;
        editor.evaluateJavascript(code, null);
    }

    private static String jsStr(String s) {
        if (s == null) return "null";
        StringBuilder b = new StringBuilder("\"");
        for (char c : s.toCharArray()) {
            switch (c) {
                case '"': b.append("\\\""); break;
                case '\\': b.append("\\\\"); break;
                case '\n': b.append("\\n"); break;
                case '\r': b.append("\\r"); break;
                case '\t': b.append("\\t"); break;
                default:
                    if (c < 0x20) b.append(String.format("\\u%04x", (int) c));
                    else b.append(c);
            }
        }
        return b.append('"').toString();
    }

    // ------------------------------------------------------------------ editor

    private void openInEditor(final String path) {
        if (editor == null || !editorPageReady) {
            pendingOpenPath = path;
            return;
        }
        new Thread(() -> {
            try {
                final Workspace.FileText ft = Workspace.read(path);
                main.post(() -> {
                    if (ft.binary) {
                        toast("Arquivo binário: " + new File(path).getName());
                        return;
                    }
                    js("ReaIde.openFile(" + jsStr(path) + "," + jsStr(ft.text) + ",null)");
                    showPage(PAGE_EDITOR);
                    updateBottomBar();
                });
            } catch (Exception e) {
                main.post(() -> toast("Não foi possível abrir: " + e.getMessage()));
            }
        }, "rea-open").start();
    }

    private void saveFile(String path, String content) {
        new Thread(() -> {
            try {
                Workspace.write(path, content);
                main.post(() -> bottomStatus.setText("salvo " + new java.text.SimpleDateFormat("HH:mm:ss",
                        java.util.Locale.US).format(new java.util.Date())));
            } catch (Exception e) {
                Log.e(TAG, "save failed", e);
                main.post(() -> toast("Falha ao salvar: " + e.getMessage()));
            }
        }, "rea-save").start();
    }

    private void handleEditorCommand(String action) {
        if (action == null) return;
        switch (action) {
            case "open-file": showFilePicker(); break;
            case "new-file": promptNewFile(); break;
            case "open-terminal":
                showPage(PAGE_TERMINAL);
                ensureSession();
                break;
            default: toast("ação desconhecida: " + action);
        }
    }

    // ---------------------------------------------------------------- explorer

    private void buildExplorer() {
        fileList = findViewById(R.id.file_list);
        fileAdapter = new FileAdapter(this);
        fileList.setLayoutManager(new LinearLayoutManager(this));
        fileList.setAdapter(fileAdapter);
        drawerPath.setOnClickListener(v -> promptGoto());
        findViewById(R.id.drawer_actions).setOnClickListener(v -> showExplorerActions());
    }

    private void openProject(String dir) {
        cwd = dir;
        drawerPath.setText(ShellEnv.prettyPath(dir));
        new Thread(() -> {
            final java.util.List<Workspace.Entry> entries = Workspace.list(dir);
            main.post(() -> fileAdapter.submit(entries));
        }, "rea-list").start();
        updateBottomBar();
    }

    private void refreshExplorer() {
        openProject(cwd);
    }

    @Override
    public void onOpen(Workspace.Entry entry) {
        if (entry.directory) {
            openProject(entry.path);
        } else {
            drawer.closeDrawers();
            openInEditor(entry.path);
        }
    }

    @Override
    public void onLongPress(Workspace.Entry entry) {
        String[] items = entry.directory
                ? new String[] {"Abrir", "Novo arquivo aqui", "Renomear", "Excluir"}
                : new String[] {"Abrir", "Renomear", "Excluir"};
        new AlertDialog.Builder(this)
                .setTitle(entry.name)
                .setItems(items, (d, which) -> {
                    String choice = items[which];
                    if (choice.equals("Abrir")) onOpen(entry);
                    else if (choice.equals("Novo arquivo aqui")) promptNewFileIn(entry.path);
                    else if (choice.equals("Renomear")) promptRename(entry);
                    else if (choice.equals("Excluir")) confirmDelete(entry);
                })
                .show();
    }

    private void promptNewFile() {
        promptNewFileIn(cwd);
    }

    private void promptNewFileIn(String dir) {
        EditText input = new EditText(this);
        input.setHint("ex: src/main.js");
        input.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        new AlertDialog.Builder(this)
                .setTitle("Novo arquivo em " + ShellEnv.prettyPath(dir))
                .setView(input)
                .setPositiveButton("Criar", (d, w) -> {
                    String name = input.getText().toString().trim();
                    if (name.isEmpty()) return;
                    String path = dir + "/" + name;
                    if (Workspace.createFile(path)) {
                        refreshExplorer();
                        openInEditor(path);
                    } else {
                        toast("Não foi possível criar o arquivo");
                    }
                })
                .setNegativeButton("Cancelar", null)
                .show();
    }

    private void promptRename(Workspace.Entry entry) {
        EditText input = new EditText(this);
        input.setText(entry.name);
        new AlertDialog.Builder(this)
                .setTitle("Renomear")
                .setView(input)
                .setPositiveButton("Renomear", (d, w) -> {
                    String name = input.getText().toString().trim();
                    if (name.isEmpty()) return;
                    File parent = new File(entry.path).getParentFile();
                    if (Workspace.rename(entry.path, parent + "/" + name)) refreshExplorer();
                    else toast("Falha ao renomear");
                })
                .setNegativeButton("Cancelar", null)
                .show();
    }

    private void confirmDelete(Workspace.Entry entry) {
        new AlertDialog.Builder(this)
                .setTitle("Excluir")
                .setMessage("Excluir " + entry.name + "? Isso não pode ser desfeito.")
                .setPositiveButton("Excluir", (d, w) -> {
                    if (Workspace.delete(entry.path)) refreshExplorer();
                })
                .setNegativeButton("Cancelar", null)
                .show();
    }

    private void showExplorerActions() {
        String[] items = {"Novo arquivo", "Nova pasta", "Ir para caminho…", "Subir um nível", "Recarregar"};
        new AlertDialog.Builder(this)
                .setItems(items, (d, w) -> {
                    switch (w) {
                        case 0: promptNewFile(); break;
                        case 1: promptNewDir(); break;
                        case 2: promptGoto(); break;
                        case 3: {
                            File p = new File(cwd).getParentFile();
                            if (p != null) openProject(p.getAbsolutePath());
                            break;
                        }
                        case 4: refreshExplorer(); break;
                    }
                }).show();
    }

    private void promptNewDir() {
        EditText input = new EditText(this);
        input.setHint("nome-da-pasta");
        new AlertDialog.Builder(this)
                .setTitle("Nova pasta")
                .setView(input)
                .setPositiveButton("Criar", (d, w) -> {
                    String name = input.getText().toString().trim();
                    if (name.isEmpty()) return;
                    Workspace.createDir(cwd + "/" + name);
                    refreshExplorer();
                })
                .setNegativeButton("Cancelar", null)
                .show();
    }

    private void promptGoto() {
        EditText input = new EditText(this);
        input.setText(cwd);
        input.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        new AlertDialog.Builder(this)
                .setTitle("Caminho")
                .setView(input)
                .setPositiveButton("Ir", (d, w) -> {
                    String path = input.getText().toString().trim();
                    if (path.startsWith("~")) path = ReaPaths.home() + path.substring(1);
                    File f = new File(path);
                    if (f.isDirectory()) openProject(f.getAbsolutePath());
                    else if (f.isFile()) openInEditor(f.getAbsolutePath());
                    else toast("Caminho não existe");
                })
                .setNegativeButton("Cancelar", null)
                .show();
    }

    private void showFilePicker() {
        drawer.openDrawer(Gravity.START);
    }

    // -------------------------------------------------------------- extra keys

    /** Context-sensitive key row: symbols for the editor, control keys for the terminal. */
    private void buildExtraKeys() {
        if (extraKeysRow == null) return;
        extraKeysRow.removeAllViews();
        // The row scrolls horizontally: 14 keys x 40dp does not fit a phone in portrait.
        String[] keys = activePage == PAGE_TERMINAL
                ? new String[] {"⏎", "⇥", "←", "↑", "↓", "→", "^C", "^D", "|", "/", "-", "~", "$", "&"}
                : new String[] {"⇥", "←", "↑", "↓", "→", "{", "}", "(", ")", "\"", "'", ";", ":", "/", "*"};
        for (String k : keys) {
            TextView tv = new TextView(this);
            tv.setText(k);
            tv.setTextSize(12);
            tv.setGravity(Gravity.CENTER);
            tv.setTextColor(getColor(R.color.rea_text));
            tv.setBackgroundResource(R.drawable.bg_key);
            int w = (int) (getResources().getDisplayMetrics().density * 40);
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(w,
                    (int) (getResources().getDisplayMetrics().density * 34));
            lp.setMargins(2, 2, 2, 2);
            tv.setLayoutParams(lp);
            tv.setOnClickListener(v -> onExtraKey(k));
            extraKeysRow.addView(tv);
        }
    }

    private void onExtraKey(String key) {
        if (activePage == PAGE_TERMINAL) {
            switch (key) {
                case "⏎": sendSeq("\r"); break;
                case "⇥": sendSeq("\t"); break;
                case "←": sendSeq("\u001b[D"); break;
                case "↑": sendSeq("\u001b[A"); break;
                case "↓": sendSeq("\u001b[B"); break;
                case "→": sendSeq("\u001b[C"); break;
                case "^C": sendSeq("\u0003"); break;
                case "^D": sendSeq("\u0004"); break;
                case "|": sendSeq("|"); break;
                default: sendSeq(key);
            }
        } else {
            String insert = "⇥".equals(key) ? "  " : key;
            js("ReaIde.insertText(" + jsStr(insert) + ")");
        }
    }

    // ---------------------------------------------------------------- console

    /** Runs a command without a pty and streams it into the build console. */
    private void runInConsole(String command) {
        if (!bootstrapReady) {
            toast("Ambiente ainda instalando…");
            return;
        }
        showPage(PAGE_TERMINAL);
        consoleScroll.setVisibility(View.VISIBLE);
        terminalView.setVisibility(View.GONE);
        appendConsole("$ " + command + "\n");

        String shell = ReaPaths.binPrefix() + "/bash";
        if (!new File(shell).exists()) shell = ReaPaths.binPrefix() + "/sh";
        String[] argv = {shell, "-lc", command};
        TerminalProcess.run(shell, cwd, argv, ShellEnv.build(cwd, false),
                new TerminalProcess.LineListener() {
                    @Override public void onLine(String line) {
                        main.post(() -> appendConsole(LineFilter.stripAnsi(line) + "\n"));
                    }
                    @Override public void onExit(int exitCode) {
                        main.post(() -> appendConsole("\n[processo finalizado com código " + exitCode + "]\n"));
                    }
                });
    }

    private void appendConsole(String text) {
        consoleBuffer.append(text);
        if (consoleBuffer.length() > 200_000) consoleBuffer.delete(0, 100_000);
        consoleText.setText(consoleBuffer);
        consoleScroll.post(() -> consoleScroll.fullScroll(View.FOCUS_DOWN));
    }

    private void clearConsole() {
        consoleBuffer.setLength(0);
        consoleText.setText("");
    }

    // ---------------------------------------------------------------- terminal

    private void buildTerminal() {
        terminals = new TerminalManager(this);
        terminals.setListener(this);
    }

    private void wireTerminalKeys(ViewGroup terminalPage) {
        terminalPage.findViewById(R.id.term_btn_new).setOnClickListener(v -> {
            TerminalManager.Descriptor d = terminals.createSession(cwd, null, null);
            setActiveSession(d);
        });
        terminalPage.findViewById(R.id.term_btn_keyboard).setOnClickListener(v -> {
            if (terminalView != null) terminalView.requestFocus();
        });
        terminalPage.findViewById(R.id.term_btn_esc).setOnClickListener(v -> sendSeq("\u001b"));
        terminalPage.findViewById(R.id.term_btn_tab).setOnClickListener(v -> sendSeq("\t"));
        terminalPage.findViewById(R.id.term_btn_up).setOnClickListener(v -> sendSeq("\u001b[A"));
        terminalPage.findViewById(R.id.term_btn_down).setOnClickListener(v -> sendSeq("\u001b[B"));
        terminalPage.findViewById(R.id.term_btn_ctrl).setOnClickListener(v -> toggleModifier('c'));
        terminalPage.findViewById(R.id.term_btn_alt).setOnClickListener(v -> toggleModifier('a'));
        terminalPage.findViewById(R.id.term_btn_console).setOnClickListener(v -> {
            boolean showConsole = consoleScroll.getVisibility() != View.VISIBLE;
            consoleScroll.setVisibility(showConsole ? View.VISIBLE : View.GONE);
            terminalView.setVisibility(showConsole ? View.GONE : View.VISIBLE);
        });
    }

    private boolean ctrlDown = false, altDown = false;

    private void toggleModifier(char which) {
        if (which == 'c') {
            ctrlDown = !ctrlDown;
            findViewById(R.id.term_btn_ctrl).setBackgroundResource(
                    ctrlDown ? R.drawable.bg_key_active : R.drawable.bg_key);
        } else if (which == 'a') {
            altDown = !altDown;
            findViewById(R.id.term_btn_alt).setBackgroundResource(
                    altDown ? R.drawable.bg_key_active : R.drawable.bg_key);
        }
    }

    private void sendSeq(String seq) {
        if (activeSession != null) activeSession.session.write(seq);
    }

    private void ensureSession() {
        if (activeSession == null) {
            if (!bootstrapReady) {
                toast("Ambiente ainda instalando…");
                return;
            }
            TerminalManager.Descriptor d = terminals.createSession(cwd, null, null);
            setActiveSession(d);
        }
    }

    private void setActiveSession(TerminalManager.Descriptor d) {
        activeSession = d;
        if (terminalView != null) {
            terminalView.attachSession(d.session);
            terminalView.requestFocus();
        }
        renderSessionTabs();
        updateBottomBar();
    }

    private void renderSessionTabs() {
        sessionTabs.removeAllViews();
        for (TerminalManager.Descriptor d : terminals.sessions()) {
            TextView tv = new TextView(this);
            tv.setText(d.name + (d.finished ? " ×" : ""));
            tv.setTextSize(11);
            tv.setPadding(18, 8, 18, 8);
            tv.setTextColor(d == activeSession ? getColor(R.color.rea_accent) : getColor(R.color.rea_text_dim));
            tv.setOnClickListener(v -> {
                setActiveSession(d);
                showPage(PAGE_TERMINAL);
            });
            tv.setOnLongClickListener(v -> {
                terminals.closeSession(d);
                if (d == activeSession) {
                    activeSession = terminals.sessions().isEmpty() ? null : terminals.sessions().get(0);
                    if (activeSession != null && terminalView != null) terminalView.attachSession(activeSession.session);
                }
                renderSessionTabs();
                return true;
            });
            sessionTabs.addView(tv);
        }
    }

    // ------------------------------------------------ TerminalManager.Listener

    @Override public void onSessionTextChanged(TerminalSession session) {
        if (terminalView != null && session == attached()) terminalView.onScreenUpdated();
    }

    private TerminalSession attached() {
        return activeSession == null ? null : activeSession.session;
    }

    @Override public void onSessionTitleChanged(TerminalSession session) {
        TerminalManager.Descriptor d = terminals.find(session);
        if (d != null) {
            String t = session.getTitle();
            if (t != null && !t.isEmpty()) d.name = t;
            renderSessionTabs();
        }
    }

    @Override public void onSessionFinished(TerminalSession session) {
        renderSessionTabs();
        toast("Shell encerrado (" + session.getExitStatus() + ")");
    }

    @Override public void onSessionListChanged() {
        main.post(this::renderSessionTabs);
    }

    @Override public void onBell(TerminalSession session) {
        if (terminalView != null) terminalView.performHapticFeedback(
                android.view.HapticFeedbackConstants.VIRTUAL_KEY);
    }

    // --------------------------------------------------- TerminalViewClient

    @Override public float onScale(float scale) {
        if (terminalView == null) return 1f;
        mTerminalFontSize = Math.max(6, Math.min(30, Math.round(mTerminalFontSize * scale)));
        terminalView.setTextSize(mTerminalFontSize);
        return scale;
    }

    private int mTerminalFontSize = 12;

    @Override public void onSingleTapUp(MotionEvent e) {
        if (terminalView != null) terminalView.requestFocus();
    }

    @Override public boolean shouldBackButtonBeMappedToEscape() { return true; }

    @Override public boolean shouldEnforceCharBasedInput() { return true; }

    @Override public boolean shouldUseCtrlSpaceWorkaround() { return false; }

    @Override public boolean isTerminalViewSelected() { return activePage == PAGE_TERMINAL; }

    @Override public void copyModeChanged(boolean copyMode) { }

    @Override public boolean onKeyDown(int keyCode, KeyEvent e, TerminalSession session) {
        if (keyCode == KeyEvent.KEYCODE_BACK && e.isCtrlPressed()) {
            // reserved: ctrl+back returns to the editor
            showPage(PAGE_EDITOR);
            return true;
        }
        return false;
    }

    @Override public boolean onKeyUp(int keyCode, KeyEvent e) { return false; }

    @Override public boolean onLongPress(MotionEvent event) { return false; }

    @Override public boolean readControlKey() { return ctrlDown; }

    @Override public boolean readAltKey() { return altDown; }

    @Override public boolean readShiftKey() { return false; }

    @Override public boolean readFnKey() { return false; }

    @Override public boolean onCodePoint(int codePoint, boolean ctrlDownFromEvent, TerminalSession session) {
        return false; // default: TerminalView encodes the code point itself
    }

    @Override public void onEmulatorSet() { }

    @Override public void logError(String tag, String msg) { Log.e(tag, msg); }
    @Override public void logWarn(String tag, String msg) { Log.w(tag, msg); }
    @Override public void logInfo(String tag, String msg) { Log.i(tag, msg); }
    @Override public void logDebug(String tag, String msg) { Log.d(tag, msg); }
    @Override public void logVerbose(String tag, String msg) { Log.v(tag, msg); }
    @Override public void logStackTraceWithMessage(String tag, String msg, Exception e) { Log.e(tag, msg, e); }
    @Override public void logStackTrace(String tag, Exception e) { Log.e(tag, "trace", e); }

    // ------------------------------------------------------------- bootstrap

    private void installBootstrapIfNeeded() {
        final BootstrapInstaller installer = new BootstrapInstaller(this);
        if (installer.isInstalled()) {
            main.post(() -> onBootstrapReady(true));
            return;
        }
        try {
            installer.install((message, extracted, total) ->
                    main.post(() -> bottomStatus.setText(message)));
            main.post(() -> onBootstrapReady(true));
        } catch (final Exception e) {
            Log.e(TAG, "bootstrap failed", e);
            main.post(() -> {
                bottomStatus.setText("falha na instalação");
                new AlertDialog.Builder(MainActivity.this)
                        .setTitle("Falha ao instalar o ambiente Linux")
                        .setMessage(String.valueOf(e.getMessage()))
                        .setPositiveButton("OK", null)
                        .show();
            });
        }
    }

    private void onBootstrapReady(boolean ok) {
        bootstrapReady = ok;
        updateBottomBar();
        if (ok) {
            ensureDefaultProject();
            ensureSession();
        }
    }

    /** Seeds ~/projects/hello-web so the first launch has something real to run. */
    private void ensureDefaultProject() {
        File proj = new File(Workspace.projects(), "hello-web");
        File index = new File(proj, "index.html");
        if (index.exists()) return;
        proj.mkdirs();
        try {
            Workspace.write(index.getAbsolutePath(),
                    "<!doctype html>\n<html lang=\"pt-BR\">\n<head>\n"
                    + "  <meta charset=\"utf-8\" />\n"
                    + "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />\n"
                    + "  <title>Hello REA</title>\n"
                    + "  <link rel=\"stylesheet\" href=\"style.css\" />\n"
                    + "</head>\n<body>\n"
                    + "  <h1>Hello, REA IDE</h1>\n"
                    + "  <p>Editado no Android, rodado no Termux.</p>\n"
                    + "  <button id=\"go\">Contar cliques</button>\n"
                    + "  <script src=\"app.js\"></script>\n"
                    + "</body>\n</html>\n");
            Workspace.write(new File(proj, "style.css").getAbsolutePath(),
                    ":root { color-scheme: dark; }\n"
                    + "body { font-family: system-ui, sans-serif; background: #0b0e14; color: #d7dae0;\n"
                    + "       display: grid; place-content: center; min-height: 100vh; margin: 0; gap: 12px; }\n"
                    + "button { background: #7c5cff; color: white; border: 0; padding: 10px 16px;\n"
                    + "         border-radius: 8px; font-size: 15px; }\n");
            Workspace.write(new File(proj, "app.js").getAbsolutePath(),
                    "let count = 0;\n"
                    + "const btn = document.getElementById('go');\n"
                    + "btn.addEventListener('click', () => {\n"
                    + "  count += 1;\n"
                    + "  btn.textContent = `Cliques: ${count}`;\n"
                    + "});\n");
            Workspace.write(new File(proj, "README.md").getAbsolutePath(),
                    "# hello-web\n\nProjeto de exemplo criado pelo REA IDE.\n\n"
                    + "```sh\ncd ~/projects/hello-web\npython -m http.server 8080\n```\n");
        } catch (Exception e) {
            Log.w(TAG, "could not seed demo project", e);
        }
    }

    // ------------------------------------------------------------- run / menu

    private void showRunDialog() {
        if (!bootstrapReady) {
            toast("Ambiente ainda instalando…");
            return;
        }
        String[] items = {
                "Abrir shell em " + ShellEnv.prettyPath(cwd),
                "python -m http.server 8080",
                "node .",
                "bash run.sh",
                "Comando personalizado…",
                "Console: npm test",
                "Console: comando personalizado…",
                "Limpar console",
        };
        new AlertDialog.Builder(this)
                .setTitle("Executar")
                .setItems(items, (d, w) -> {
                    showPage(PAGE_TERMINAL);
                    ensureSession();
                    switch (w) {
                        case 0: sendSeq("cd " + cwd + "\r"); break;
                        case 1: sendSeq("cd " + cwd + " && python -m http.server 8080\r"); break;
                        case 2: sendSeq("cd " + cwd + " && node .\r"); break;
                        case 3: sendSeq("cd " + cwd + " && bash run.sh\r"); break;
                        case 4: promptCustomCommand(); break;
                        case 5: runInConsole("npm test"); break;
                        case 6: promptConsoleCommand(); break;
                        case 7: clearConsole(); break;
                    }
                })
                .show();
    }

    private void promptConsoleCommand() {
        EditText input = new EditText(this);
        input.setHint("./gradlew test");
        new AlertDialog.Builder(this)
                .setTitle("Console em " + ShellEnv.prettyPath(cwd))
                .setView(input)
                .setPositiveButton("Executar", (d, w) -> {
                    String cmd = input.getText().toString().trim();
                    if (!cmd.isEmpty()) runInConsole(cmd);
                })
                .setNegativeButton("Cancelar", null)
                .show();
    }

    private void promptCustomCommand() {
        EditText input = new EditText(this);
        input.setHint("npm test");
        input.setInputType(InputType.TYPE_CLASS_TEXT);
        new AlertDialog.Builder(this)
                .setTitle("Comando em " + ShellEnv.prettyPath(cwd))
                .setView(input)
                .setPositiveButton("Executar", (d, w) -> {
                    String cmd = input.getText().toString().trim();
                    if (!cmd.isEmpty()) {
                        showPage(PAGE_TERMINAL);
                        ensureSession();
                        sendSeq("cd " + cwd + " && " + cmd + "\r");
                    }
                })
                .setNegativeButton("Cancelar", null)
                .show();
    }

    private void showMoreMenu() {
        String[] items = {
                "Nova aba de editor (arquivo)",
                "Novo shell",
                "Fechar shell atual",
                "Recarregar interface do editor",
                "Tamanho da fonte do editor",
                "Sobre o REA IDE",
        };
        new AlertDialog.Builder(this)
                .setItems(items, (d, w) -> {
                    switch (w) {
                        case 0: showFilePicker(); break;
                        case 1: {
                            showPage(PAGE_TERMINAL);
                            TerminalManager.Descriptor ds = terminals.createSession(cwd, null, null);
                            setActiveSession(ds);
                            break;
                        }
                        case 2:
                            if (activeSession != null) {
                                terminals.closeSession(activeSession);
                                activeSession = null;
                                renderSessionTabs();
                            }
                            break;
                        case 3:
                            if (editor != null) {
                                editorPageReady = false;
                                editor.reload();
                            }
                            break;
                        case 4: promptEditorFontSize(); break;
                        default: showAbout(); break;
                    }
                }).show();
    }

    private int editorFontPx = 13;

    private void promptEditorFontSize() {
        EditText input = new EditText(this);
        input.setText(String.valueOf(editorFontPx));
        input.setInputType(InputType.TYPE_CLASS_NUMBER);
        new AlertDialog.Builder(this)
                .setTitle("Fonte do editor (9–22)")
                .setView(input)
                .setPositiveButton("Aplicar", (d, w) -> {
                    try {
                        editorFontPx = Math.max(9, Math.min(22, Integer.parseInt(input.getText().toString().trim())));
                    } catch (NumberFormatException ignored) { }
                    js("ReaIde.setFontSize(" + editorFontPx + ")");
                })
                .setNegativeButton("Cancelar", null)
                .show();
    }

    private void showAbout() {
        String abi = android.os.Build.SUPPORTED_ABIS[0];
        new AlertDialog.Builder(this)
                .setTitle("REA IDE")
                .setMessage("Editor de código + Termux Linux para Android\n\n"
                        + "versão: " + BuildConfig.VERSION_NAME + "\n"
                        + "abi: " + abi + "\n"
                        + "prefix: " + ReaPaths.prefix() + "\n"
                        + "bootstrap: " + (bootstrapReady ? "instalado" : "pendente") + "\n\n"
                        + "Terminal: termux-app (Apache-2.0)\n"
                        + "Editor: CodeMirror 6 (MIT)")
                .setPositiveButton("OK", null)
                .show();
    }

    private void toast(String msg) {
        Toast.makeText(this, msg, Toast.LENGTH_SHORT).show();
    }

    // ------------------------------------------------------------------ back

    @Override
    public void onBackPressed() {
        if (drawer.isDrawerOpen(Gravity.START)) {
            drawer.closeDrawers();
        } else if (activePage == PAGE_TERMINAL) {
            showPage(PAGE_EDITOR);
        } else if (new File(cwd).getParentFile() != null
                && cwd.startsWith(ReaPaths.projects())
                && !cwd.equals(ReaPaths.projects())) {
            openProject(new File(cwd).getParentFile().getAbsolutePath());
        } else {
            super.onBackPressed();
        }
    }
}
