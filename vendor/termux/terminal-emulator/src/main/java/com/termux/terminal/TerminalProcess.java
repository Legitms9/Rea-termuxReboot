package com.termux.terminal;

import java.io.File;
import java.io.FileDescriptor;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

/**
 * REA addition to the vendored emulator module: run a command without a pty and stream its merged
 * stdout/stderr. The terminal tab uses {@link TerminalSession}; the IDE's build/run console uses
 * this, because a build tool does not need a tty and we want ANSI-stripped, line-oriented output.
 *
 * <p>Lives in this package only so it can reach the package-private {@link JNI} binding; the app
 * never needs reflection.
 */
public final class TerminalProcess {

    public interface LineListener {
        void onLine(String line);
        void onExit(int exitCode);
    }

    private TerminalProcess() {}

    /**
     * @param executable absolute path to the binary (ELF or shebang script)
     * @param args       arguments *including* argv[0]
     */
    public static Thread run(String executable, String cwd, String[] args, String[] env,
                             LineListener listener) {
        int[] result = new int[2];
        int rc = JNI.createPipeProcess(executable, cwd, args, env, result);
        if (rc != 0) {
            listener.onLine("rea: nao foi possivel iniciar " + executable);
            listener.onExit(-1);
            return null;
        }

        final int readFd = result[0];
        final int pid = result[1];

        Thread t = new Thread(() -> {
            StringBuilder line = new StringBuilder();
            try (InputStream in = new FileInputStream(fileDescriptorOf(readFd))) {
                byte[] buf = new byte[8192];
                int n;
                while ((n = in.read(buf)) > 0) {
                    String chunk = new String(buf, 0, n, StandardCharsets.UTF_8);
                    for (int i = 0; i < chunk.length(); i++) {
                        char c = chunk.charAt(i);
                        if (c == '\n') {
                            listener.onLine(line.toString());
                            line.setLength(0);
                        } else if (c != '\r') {
                            line.append(c);
                        }
                        if (line.length() > 8192) { // runaway output guard
                            listener.onLine(line.toString());
                            line.setLength(0);
                        }
                    }
                }
            } catch (IOException ignored) {
                // process ended / fd closed
            }
            if (line.length() > 0) listener.onLine(line.toString());
            int exit = JNI.waitFor(pid);
            JNI.close(readFd);
            listener.onExit(exit);
        }, "rea-proc-" + pid);
        t.setDaemon(true);
        t.start();
        return t;
    }

    /** Wraps a raw fd without taking ownership of the descriptor table slot. */
    private static FileDescriptor fileDescriptorOf(int fd) throws IOException {
        try {
            FileDescriptor d = new FileDescriptor();
            java.lang.reflect.Field f = FileDescriptor.class.getDeclaredField("descriptor");
            f.setAccessible(true);
            f.setInt(d, fd);
            return d;
        } catch (Exception e) {
            throw new IOException("cannot wrap fd " + fd, e);
        }
    }

    /** Convenience: does this happen to be a directory we could chdir into? */
    public static boolean isDirectory(String path) {
        return path != null && new File(path).isDirectory();
    }
}
