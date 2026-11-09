package io.rea.ide.runtime;

import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.util.Log;
import android.view.KeyEvent;

import com.termux.terminal.TerminalSession;
import com.termux.terminal.TerminalSessionClient;

import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

/**
 * Owns the shell sessions. Adapted from termux-app's TermuxTerminalSessionClient.
 */
public final class TerminalManager implements TerminalSessionClient {

    private static final String TAG = "TerminalManager";

    public static final class Descriptor {
        public final String id = UUID.randomUUID().toString();
        public String name;
        public String cwd;
        public TerminalSession session;
        /** Running command shown in the tab title, e.g. "vim src/main.rs". */
        public String runningCommand;
        public boolean finished;
    }

    public interface Listener {
        void onSessionTextChanged(TerminalSession session);
        void onSessionTitleChanged(TerminalSession session);
        void onSessionFinished(TerminalSession session);
        void onSessionListChanged();
        void onBell(TerminalSession session);
    }

    private final Context context;
    private final List<Descriptor> sessions = new ArrayList<>();
    private Listener listener;

    public TerminalManager(Context context) {
        this.context = context.getApplicationContext();
    }

    public void setListener(Listener listener) {
        this.listener = listener;
    }

    public List<Descriptor> sessions() {
        return sessions;
    }

    public Descriptor createSession(String cwd, String shell, String[] args) {
        if (cwd == null || cwd.isEmpty()) cwd = ReaPaths.home();
        String shellPath = shell;
        if (shellPath == null) {
            // Same choice termux-app makes: $PREFIX/bin/login gives you the full Termux login
            // environment (it re-execs the user's shell after sourcing the profile).
            // bash/sh are fallbacks for a partially installed prefix.
            for (String candidate : new String[] {"/login", "/bash", "/sh"}) {
                if (new java.io.File(ReaPaths.binPrefix() + candidate).exists()) {
                    shellPath = ReaPaths.binPrefix() + candidate;
                    break;
                }
            }
        }
        if (shellPath == null) shellPath = ReaPaths.binPrefix() + "/sh";

        String[] argv;
        if (args == null) {
            // `login` takes no flags; `bash` needs -l to source the profile and export $PREFIX.
            boolean isLogin = shellPath.endsWith("/login");
            argv = isLogin ? new String[] {shellPath} : new String[] {shellPath, "-l"};
        } else {
            argv = new String[args.length + 1];
            argv[0] = shellPath;
            System.arraycopy(args, 0, argv, 1, args.length);
        }

        TerminalSession session = new TerminalSession(
                shellPath, cwd, argv, ShellEnv.build(cwd, false), 5000, this);

        Descriptor d = new Descriptor();
        d.session = session;
        d.cwd = cwd;
        d.name = shortName(cwd);
        synchronized (sessions) {
            sessions.add(d);
        }
        if (listener != null) listener.onSessionListChanged();
        return d;
    }

    public void closeSession(Descriptor d) {
        if (d == null) return;
        d.session.finishIfRunning();
        synchronized (sessions) {
            sessions.remove(d);
        }
        if (listener != null) listener.onSessionListChanged();
    }

    public Descriptor find(TerminalSession s) {
        synchronized (sessions) {
            for (Descriptor d : sessions) if (d.session == s) return d;
        }
        return null;
    }

    /** Send a full command line and press enter. */
    public void runCommand(TerminalSession session, String command) {
        if (session == null) return;
        session.write(command + "\r");
    }

    public void sendKey(TerminalSession session, String sequence) {
        if (session == null) return;
        session.write(sequence);
    }

    private static String shortName(String cwd) {
        if (cwd == null) return "shell";
        int i = cwd.lastIndexOf('/');
        return i >= 0 ? cwd.substring(i + 1) : cwd;
    }

    // ------------------------------------------------------------ TerminalSessionClient

    @Override public void onTextChanged(TerminalSession s) {
        if (listener != null) listener.onSessionTextChanged(s);
    }

    @Override public void onTitleChanged(TerminalSession s) {
        if (listener != null) listener.onSessionTitleChanged(s);
    }

    @Override public void onSessionFinished(TerminalSession s) {
        Descriptor d = find(s);
        if (d != null) d.finished = true;
        if (listener != null) listener.onSessionFinished(s);
    }

    @Override public void onCopyTextToClipboard(TerminalSession s, String text) {
        ClipboardManager cm = (ClipboardManager) context.getSystemService(Context.CLIPBOARD_SERVICE);
        if (cm != null) cm.setPrimaryClip(ClipData.newPlainText("terminal", text));
    }

    @Override public void onPasteTextFromClipboard(TerminalSession s) {
        ClipboardManager cm = (ClipboardManager) context.getSystemService(Context.CLIPBOARD_SERVICE);
        if (cm == null || !cm.hasPrimaryClip()) return;
        CharSequence text = cm.getPrimaryClip().getItemAt(0).coerceToText(context);
        if (text != null) s.write(text.toString());
    }

    @Override public void onBell(TerminalSession s) {
        if (listener != null) listener.onBell(s);
    }

    @Override public void onColorsChanged(TerminalSession s) { }

    @Override public void onTerminalCursorStateChange(boolean state) { }

    @Override public Integer getTerminalCursorStyle() {
        return com.termux.terminal.TerminalEmulator.TERMINAL_CURSOR_STYLE_BLOCK;
    }

    @Override public void logError(String tag, String message) { Log.e(tag, message); }
    @Override public void logWarn(String tag, String message) { Log.w(tag, message); }
    @Override public void logInfo(String tag, String message) { Log.i(tag, message); }
    @Override public void logDebug(String tag, String message) { Log.d(tag, message); }
    @Override public void logVerbose(String tag, String message) { Log.v(tag, message); }
    @Override public void logStackTraceWithMessage(String tag, String message, Exception e) { Log.e(tag, message, e); }
    @Override public void logStackTrace(String tag, Exception e) { Log.e(tag, "stack trace", e); }
}
