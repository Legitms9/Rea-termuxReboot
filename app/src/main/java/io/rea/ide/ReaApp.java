package io.rea.ide;

import android.app.Application;
import android.util.Log;

import io.rea.ide.runtime.ReaPaths;

public class ReaApp extends Application {

    @Override
    public void onCreate() {
        super.onCreate();
        ReaPaths.init(getPackageName());
        Log.i("ReaApp", "prefix=" + ReaPaths.prefix() + " pkg=" + getPackageName());
    }
}
