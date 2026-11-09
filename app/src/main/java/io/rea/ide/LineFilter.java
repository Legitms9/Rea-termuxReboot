package io.rea.ide;

/**
 * Strips ANSI/VT escape sequences from command output before it reaches the console TextView.
 *
 * <p>The console is not a terminal: it renders plain text, so colour codes and cursor control
 * would show up as garbage like {@code [0;32m}. This is a small, allocation-light state machine
 * — enough for the CSI/OSC sequences build tools actually emit.
 */
public final class LineFilter {

    private LineFilter() {}

    public static String stripAnsi(String in) {
        if (in == null || in.isEmpty()) return "";
        StringBuilder out = new StringBuilder(in.length());
        int i = 0;
        int n = in.length();
        while (i < n) {
            char c = in.charAt(i);
            if (c != 0x1B) {
                // Drop other C0 control chars except tab.
                if (c < 0x20 && c != '\t') {
                    i++;
                    continue;
                }
                out.append(c);
                i++;
                continue;
            }
            // ESC
            i++;
            if (i >= n) break;
            char kind = in.charAt(i);
            if (kind == '[') {                 // CSI ... final-byte 0x40..0x7E
                i++;
                while (i < n) {
                    char ch = in.charAt(i);
                    i++;
                    if (ch >= 0x40 && ch <= 0x7E) break;
                }
            } else if (kind == ']') {           // OSC ... BEL or ST
                i++;
                while (i < n) {
                    char ch = in.charAt(i);
                    if (ch == 0x07) { i++; break; }
                    if (ch == 0x1B && i + 1 < n && in.charAt(i + 1) == '\\') { i += 2; break; }
                    i++;
                }
            } else if (kind == '(' || kind == ')') {
                i += 2;                          // charset designation
            } else {
                i++;                             // two-char escape
            }
        }
        return out.toString();
    }
}
