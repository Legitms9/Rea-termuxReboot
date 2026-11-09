#include <dirent.h>
#include <fcntl.h>
#include <jni.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/wait.h>
#include <termios.h>
#include <unistd.h>

#define TERMUX_UNUSED(x) x __attribute__((__unused__))
#ifdef __APPLE__
# define LACKS_PTSNAME_R
#endif

static int throw_runtime_exception(JNIEnv* env, char const* message)
{
    jclass exClass = (*env)->FindClass(env, "java/lang/RuntimeException");
    (*env)->ThrowNew(env, exClass, message);
    return -1;
}

static int create_subprocess(JNIEnv* env,
        char const* cmd,
        char const* cwd,
        char* const argv[],
        char** envp,
        int* pProcessId,
        jint rows,
        jint columns,
        jint cell_width,
        jint cell_height)
{
    int ptm = open("/dev/ptmx", O_RDWR | O_CLOEXEC);
    if (ptm < 0) return throw_runtime_exception(env, "Cannot open /dev/ptmx");

#ifdef LACKS_PTSNAME_R
    char* devname;
#else
    char devname[64];
#endif
    if (grantpt(ptm) || unlockpt(ptm) ||
#ifdef LACKS_PTSNAME_R
            (devname = ptsname(ptm)) == NULL
#else
            ptsname_r(ptm, devname, sizeof(devname))
#endif
       ) {
        return throw_runtime_exception(env, "Cannot grantpt()/unlockpt()/ptsname_r() on /dev/ptmx");
    }

    // Enable UTF-8 mode and disable flow control to prevent Ctrl+S from locking up the display.
    struct termios tios;
    tcgetattr(ptm, &tios);
    tios.c_iflag |= IUTF8;
    tios.c_iflag &= ~(IXON | IXOFF);
    tcsetattr(ptm, TCSANOW, &tios);

    /** Set initial winsize. */
    struct winsize sz = { .ws_row = (unsigned short) rows, .ws_col = (unsigned short) columns, .ws_xpixel = (unsigned short) (columns * cell_width), .ws_ypixel = (unsigned short) (rows * cell_height)};
    ioctl(ptm, TIOCSWINSZ, &sz);

    pid_t pid = fork();
    if (pid < 0) {
        return throw_runtime_exception(env, "Fork failed");
    } else if (pid > 0) {
        *pProcessId = (int) pid;
        return ptm;
    } else {
        // Clear signals which the Android java process may have blocked:
        sigset_t signals_to_unblock;
        sigfillset(&signals_to_unblock);
        sigprocmask(SIG_UNBLOCK, &signals_to_unblock, 0);

        close(ptm);
        setsid();

        int pts = open(devname, O_RDWR);
        if (pts < 0) exit(-1);

        dup2(pts, 0);
        dup2(pts, 1);
        dup2(pts, 2);

        DIR* self_dir = opendir("/proc/self/fd");
        if (self_dir != NULL) {
            int self_dir_fd = dirfd(self_dir);
            struct dirent* entry;
            while ((entry = readdir(self_dir)) != NULL) {
                int fd = atoi(entry->d_name);
                if (fd > 2 && fd != self_dir_fd) close(fd);
            }
            closedir(self_dir);
        }

        clearenv();
        if (envp) for (; *envp; ++envp) putenv(*envp);

        if (chdir(cwd) != 0) {
            char* error_message;
            // No need to free asprintf()-allocated memory since doing execvp() or exit() below.
            if (asprintf(&error_message, "chdir(\"%s\")", cwd) == -1) error_message = "chdir()";
            perror(error_message);
            fflush(stderr);
        }
        execvp(cmd, argv);
        // Show terminal output about failing exec() call:
        char* error_message;
        if (asprintf(&error_message, "exec(\"%s\")", cmd) == -1) error_message = "exec()";
        perror(error_message);
        _exit(1);
    }
}

static jint JNICALL termux_JNI_createSubprocess(
        JNIEnv* env,
        jclass TERMUX_UNUSED(clazz),
        jstring cmd,
        jstring cwd,
        jobjectArray args,
        jobjectArray envVars,
        jintArray processIdArray,
        jint rows,
        jint columns,
        jint cell_width,
        jint cell_height)
{
    jsize size = args ? (*env)->GetArrayLength(env, args) : 0;
    char** argv = NULL;
    if (size > 0) {
        argv = (char**) malloc((size + 1) * sizeof(char*));
        if (!argv) return throw_runtime_exception(env, "Couldn't allocate argv array");
        for (int i = 0; i < size; ++i) {
            jstring arg_java_string = (jstring) (*env)->GetObjectArrayElement(env, args, i);
            char const* arg_utf8 = (*env)->GetStringUTFChars(env, arg_java_string, NULL);
            if (!arg_utf8) return throw_runtime_exception(env, "GetStringUTFChars() failed for argv");
            argv[i] = strdup(arg_utf8);
            (*env)->ReleaseStringUTFChars(env, arg_java_string, arg_utf8);
        }
        argv[size] = NULL;
    }

    size = envVars ? (*env)->GetArrayLength(env, envVars) : 0;
    char** envp = NULL;
    if (size > 0) {
        envp = (char**) malloc((size + 1) * sizeof(char *));
        if (!envp) return throw_runtime_exception(env, "malloc() for envp array failed");
        for (int i = 0; i < size; ++i) {
            jstring env_java_string = (jstring) (*env)->GetObjectArrayElement(env, envVars, i);
            char const* env_utf8 = (*env)->GetStringUTFChars(env, env_java_string, 0);
            if (!env_utf8) return throw_runtime_exception(env, "GetStringUTFChars() failed for env");
            envp[i] = strdup(env_utf8);
            (*env)->ReleaseStringUTFChars(env, env_java_string, env_utf8);
        }
        envp[size] = NULL;
    }

    int procId = 0;
    char const* cmd_cwd = (*env)->GetStringUTFChars(env, cwd, NULL);
    char const* cmd_utf8 = (*env)->GetStringUTFChars(env, cmd, NULL);
    int ptm = create_subprocess(env, cmd_utf8, cmd_cwd, argv, envp, &procId, rows, columns, cell_width, cell_height);
    (*env)->ReleaseStringUTFChars(env, cmd, cmd_utf8);
    (*env)->ReleaseStringUTFChars(env, cmd, cmd_cwd);

    if (argv) {
        for (char** tmp = argv; *tmp; ++tmp) free(*tmp);
        free(argv);
    }
    if (envp) {
        for (char** tmp = envp; *tmp; ++tmp) free(*tmp);
        free(envp);
    }

    int* pProcId = (int*) (*env)->GetPrimitiveArrayCritical(env, processIdArray, NULL);
    if (!pProcId) return throw_runtime_exception(env, "JNI call GetPrimitiveArrayCritical(processIdArray, &isCopy) failed");

    *pProcId = procId;
    (*env)->ReleasePrimitiveArrayCritical(env, processIdArray, pProcId, 0);

    return ptm;
}

static void JNICALL termux_JNI_setPtyWindowSize(JNIEnv* TERMUX_UNUSED(env), jclass TERMUX_UNUSED(clazz), jint fd, jint rows, jint cols, jint cell_width, jint cell_height)
{
    struct winsize sz = { .ws_row = (unsigned short) rows, .ws_col = (unsigned short) cols, .ws_xpixel = (unsigned short) (cols * cell_width), .ws_ypixel = (unsigned short) (rows * cell_height) };
    ioctl(fd, TIOCSWINSZ, &sz);
}

static __attribute__((__unused__)) void JNICALL termux_JNI_setPtyUTF8Mode(JNIEnv* TERMUX_UNUSED(env), jclass TERMUX_UNUSED(clazz), jint fd)
{
    struct termios tios;
    tcgetattr(fd, &tios);
    if ((tios.c_iflag & IUTF8) == 0) {
        tios.c_iflag |= IUTF8;
        tcsetattr(fd, TCSANOW, &tios);
    }
}

static jint JNICALL termux_JNI_waitFor(JNIEnv* TERMUX_UNUSED(env), jclass TERMUX_UNUSED(clazz), jint pid)
{
    int status;
    waitpid(pid, &status, 0);
    if (WIFEXITED(status)) {
        return WEXITSTATUS(status);
    } else if (WIFSIGNALED(status)) {
        return -WTERMSIG(status);
    } else {
        // Should never happen - waitpid(2) says "One of the first three macros will evaluate to a non-zero (true) value".
        return 0;
    }
}

static void JNICALL termux_JNI_close(JNIEnv* TERMUX_UNUSED(env), jclass TERMUX_UNUSED(clazz), jint fileDescriptor)
{
    close(fileDescriptor);
}

/*
 * REA vendor addition.
 *
 * Upstream termux-app exports Java_com_termux_terminal_JNI_* symbols, which hard-codes the Java
 * package name into the shared library. Instead, the JNI class passes *itself* to
 * nativeRegister(JNI.class) right after System.loadLibrary("termux"), and we bind the entry
 * points with RegisterNatives. The emulator core can therefore be repackaged or merged into
 * another app id without editing the JNI glue.
 *
 * The function bodies above are the upstream implementations, unchanged.
 */
/*
 * Extra entry point (REA addition): run a command through the normal exec path but hand back a
 * plain pipe pair instead of a pty, so the IDE can stream a build/test command's output to its
 * console without pretending to be a terminal.
 *
 * Sets {readFd, writeFd, pid} in result; returns 0 on success, -1 on failure.
 */
static jint JNICALL termux_JNI_createPipeProcess(JNIEnv* env, jclass TERMUX_UNUSED(clazz),
        jstring cmd, jstring cwd, jobjectArray args, jobjectArray envVars, jintArray result)
{
    jsize argc = args ? (*env)->GetArrayLength(env, args) : 0;
    char** argv = NULL;
    if (argc > 0) {
        argv = (char**) calloc((size_t) argc + 1, sizeof(char*));
        if (!argv) return throw_runtime_exception(env, "Couldn't allocate argv array");
        for (int i = 0; i < argc; ++i) {
            jstring a = (jstring) (*env)->GetObjectArrayElement(env, args, i);
            char const* u = (*env)->GetStringUTFChars(env, a, NULL);
            if (!u) return throw_runtime_exception(env, "GetStringUTFChars() failed for argv");
            argv[i] = strdup(u);
            (*env)->ReleaseStringUTFChars(env, a, u);
        }
    }

    jsize envc = envVars ? (*env)->GetArrayLength(env, envVars) : 0;
    char** envp = NULL;
    if (envc > 0) {
        envp = (char**) calloc((size_t) envc + 1, sizeof(char*));
        if (!envp) return throw_runtime_exception(env, "malloc() for envp failed");
        for (int i = 0; i < envc; ++i) {
            jstring e = (jstring) (*env)->GetObjectArrayElement(env, envVars, i);
            char const* u = (*env)->GetStringUTFChars(env, e, NULL);
            if (!u) return throw_runtime_exception(env, "GetStringUTFChars() failed for env");
            envp[i] = strdup(u);
            (*env)->ReleaseStringUTFChars(env, e, u);
        }
    }

    int fds[2];
    if (pipe(fds) != 0) return throw_runtime_exception(env, "pipe() failed");

    char const* cmd_utf8 = (*env)->GetStringUTFChars(env, cmd, NULL);
    char const* cwd_utf8 = (*env)->GetStringUTFChars(env, cwd, NULL);

    pid_t pid = fork();
    if (pid < 0) return throw_runtime_exception(env, "fork() failed");

    if (pid == 0) {
        /* Child: stdout+stderr go to the pipe, stdin comes from /dev/null. */
        close(fds[0]);
        int devnull = open("/dev/null", O_RDONLY);
        if (devnull >= 0) { dup2(devnull, STDIN_FILENO); close(devnull); }
        dup2(fds[1], STDOUT_FILENO);
        dup2(fds[1], STDERR_FILENO);
        if (fds[1] > STDERR_FILENO) close(fds[1]);
        setsid();
        if (cwd_utf8 && chdir(cwd_utf8) != 0) { perror("chdir"); _exit(1); }
        execve(cmd_utf8, argv, envp);
        perror("execve");
        _exit(1);
    }

    close(fds[1]);
    (*env)->ReleaseStringUTFChars(env, cmd, cmd_utf8);
    (*env)->ReleaseStringUTFChars(env, cwd, cwd_utf8);
    if (argv) { for (char** t = argv; *t; ++t) free(*t); free(argv); }
    if (envp) { for (char** t = envp; *t; ++t) free(*t); free(envp); }

    jint out[3] = { fds[0], pid };
    jint* p = (jint*) (*env)->GetPrimitiveArrayCritical(env, result, NULL);
    if (!p) return throw_runtime_exception(env, "GetPrimitiveArrayCritical failed");
    p[0] = out[0];
    p[1] = (jint) pid;
    (*env)->ReleasePrimitiveArrayCritical(env, result, p, 0);
    return 0;
}

static void register_pty_natives(JNIEnv* env, jclass target)
{
    JNINativeMethod methods[] = {
        {"createSubprocess", "(Ljava/lang/String;Ljava/lang/String;[Ljava/lang/String;"
                             "[Ljava/lang/String;[IIIII)I",                             (void*) termux_JNI_createSubprocess},
        {"setPtyWindowSize", "(IIIII)V",                                               (void*) termux_JNI_setPtyWindowSize},
        {"waitFor",          "(I)I",                                                   (void*) termux_JNI_waitFor},
        {"close",            "(I)V",                                                   (void*) termux_JNI_close},
        {"createPipeProcess", "(Ljava/lang/String;Ljava/lang/String;[Ljava/lang/String;"
                             "[Ljava/lang/String;[I)I",                                (void*) termux_JNI_createPipeProcess},
    };
    if (target == NULL) {
        jclass exClass = (*env)->FindClass(env, "java/lang/RuntimeException");
        (*env)->ThrowNew(env, exClass, "termux: nativeRegister(null)");
        return;
    }
    if ((*env)->RegisterNatives(env, target, methods, 5) != JNI_OK) {
        jclass exClass = (*env)->FindClass(env, "java/lang/RuntimeException");
        (*env)->ThrowNew(env, exClass, "termux: failed to register pty natives");
    }
}

/* The registrar itself must also be exported, and it is the only symbol whose name matters. */
JNIEXPORT void JNICALL Java_com_termux_terminal_JNI_nativeRegister(JNIEnv* env, jclass TERMUX_UNUSED(clazz), jclass target)
{
    register_pty_natives(env, target);
}
