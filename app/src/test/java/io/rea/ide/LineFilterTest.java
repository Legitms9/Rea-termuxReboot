package io.rea.ide;

import org.junit.Test;

import static org.junit.Assert.assertEquals;

public class LineFilterTest {

    @Test public void stripsSgrColour() {
        assertEquals("ok", LineFilter.stripAnsi("\u001b[0;32mok\u001b[0m"));
    }

    @Test public void stripsCursorAndErase() {
        assertEquals("ab", LineFilter.stripAnsi("a\u001b[K\u001b[1;1Hb"));
    }

    @Test public void stripsOscTitle() {
        assertEquals("x", LineFilter.stripAnsi("\u001b]0;title\u0007x"));
        assertEquals("x", LineFilter.stripAnsi("\u001b]0;title\u001b\\x"));
    }

    @Test public void keepsTabsAndDropsCR() {
        assertEquals("a\tb", LineFilter.stripAnsi("a\tb\r"));
    }

    @Test public void handlesTruncatedSequence() {
        assertEquals("done", LineFilter.stripAnsi("done\u001b["));
        assertEquals("done", LineFilter.stripAnsi("done\u001b"));
    }

    @Test public void plainTextUntouched() {
        assertEquals("npm test 1/2 passed", LineFilter.stripAnsi("npm test 1/2 passed"));
    }
}
