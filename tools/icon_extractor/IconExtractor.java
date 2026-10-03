package com.droidmgr;

import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ActivityInfo;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.res.Resources;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.drawable.Drawable;
import android.os.Looper;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;
import java.io.PrintStream;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;

public class IconExtractor {
    public static void main(String[] args) {
        if (args.length == 0) {
            System.err.println("Usage: IconExtractor [--labels] [--out=<dir>] [--size=<px>] [pkg1 pkg2 ...]");
            System.exit(1);
        }

        try {
            Looper.prepareMainLooper();
        } catch (Throwable ignored) {}

        PrintStream origErr = System.err;
        try {
            System.setErr(new PrintStream(new OutputStream() {
                public void write(int b) {}
                public void write(byte[] b, int off, int len) {}
            }));
        } catch (Throwable ignored) {}

        Context context;
        PackageManager pm;
        try {
            Class<?> atClass = Class.forName("android.app.ActivityThread");
            Method systemMain = atClass.getMethod("systemMain");
            Object at = systemMain.invoke(null);
            Method getSystemContext = atClass.getMethod("getSystemContext");
            context = (Context) getSystemContext.invoke(at);
            pm = context.getPackageManager();
        } catch (Throwable t) {
            System.setErr(origErr);
            System.err.println("Failed to initialize Android Context: " + t);
            System.exit(2);
            return;
        } finally {
            try {
                System.setErr(origErr);
            } catch (Throwable ignored) {}
        }

        String outDirPath = null;
        int size = 192;
        boolean labelsOnly = false;
        List<String> targetPkgs = new ArrayList<String>();

        for (int i = 0; i < args.length; i++) {
            if (args[i].equals("--labels")) {
                labelsOnly = true;
            } else if (args[i].startsWith("--out=")) {
                outDirPath = args[i].substring(6);
            } else if (args[i].startsWith("--size=")) {
                try {
                    size = Integer.parseInt(args[i].substring(7));
                } catch (Exception ignored) {}
            } else if (!args[i].startsWith("--")) {
                targetPkgs.add(args[i]);
            }
        }

        // If --labels mode without specific packages, list ALL installed packages
        if (labelsOnly && targetPkgs.isEmpty() && outDirPath == null) {
            try {
                List<PackageInfo> installed = pm.getInstalledPackages(0);
                for (PackageInfo pi : installed) {
                    String label = getLabel(pm, pi.packageName, pi.applicationInfo);
                    System.out.println("LABEL:" + pi.packageName + "\t" + label);
                }
                return;
            } catch (Throwable t) {
                System.err.println("Failed to list installed packages: " + t);
                System.exit(3);
                return;
            }
        }

        // If labels-only with specific packages
        if (labelsOnly && outDirPath == null) {
            for (String pkg : targetPkgs) {
                String label = getLabel(pm, pkg, null);
                System.out.println("LABEL:" + pkg + "\t" + label);
            }
            return;
        }

        // Single package stdout mode: IconExtractor <package> (no --out flag, 1 pkg)
        if (outDirPath == null && targetPkgs.size() == 1) {
            String pkg = targetPkgs.get(0);
            boolean ok = extractSingleToStream(pm, pkg, size, System.out);
            System.exit(ok ? 0 : 3);
            return;
        }

        File outDir = new File(outDirPath != null ? outDirPath : "/data/local/tmp/droidmgr_icons");
        if (!outDir.exists()) {
            outDir.mkdirs();
        }

        for (String pkg : targetPkgs) {
            try {
                String label = getLabel(pm, pkg, null);
                System.out.println("LABEL:" + pkg + "\t" + label);

                Drawable icon = getIcon(pm, pkg);
                if (icon != null) {
                    Bitmap bmp = renderDrawable(icon, size);
                    File outFile = new File(outDir, pkg + ".png");
                    FileOutputStream fos = new FileOutputStream(outFile);
                    bmp.compress(Bitmap.CompressFormat.PNG, 100, fos);
                    fos.flush();
                    fos.close();
                    System.out.println("OK:" + pkg);
                } else {
                    System.out.println("FAIL:" + pkg + ":null");
                }
            } catch (Throwable t) {
                System.out.println("FAIL:" + pkg + ":" + t.getMessage());
            }
        }
    }

    private static String getLabel(PackageManager pm, String pkg, ApplicationInfo appInfo) {
        if (appInfo == null) {
            try {
                appInfo = pm.getApplicationInfo(pkg, 0);
            } catch (Throwable ignored) {}
        }

        // 1. Try launcher activity label first
        try {
            Intent intent = pm.getLaunchIntentForPackage(pkg);
            if (intent != null && intent.getComponent() != null) {
                ActivityInfo aInfo = pm.getActivityInfo(intent.getComponent(), 0);
                if (aInfo != null) {
                    CharSequence label = aInfo.loadLabel(pm);
                    if (label != null && label.length() > 0) {
                        return label.toString().trim();
                    }
                }
            }
        } catch (Throwable ignored) {}

        // 2. Try application label
        if (appInfo != null) {
            try {
                CharSequence label = pm.getApplicationLabel(appInfo);
                if (label != null && label.length() > 0) {
                    return label.toString().trim();
                }
            } catch (Throwable ignored) {}

            try {
                CharSequence label = appInfo.loadLabel(pm);
                if (label != null && label.length() > 0) {
                    return label.toString().trim();
                }
            } catch (Throwable ignored) {}

            try {
                if (appInfo.labelRes != 0) {
                    Resources res = pm.getResourcesForApplication(appInfo);
                    CharSequence label = res.getText(appInfo.labelRes);
                    if (label != null && label.length() > 0) {
                        return label.toString().trim();
                    }
                }
            } catch (Throwable ignored) {}

            if (appInfo.nonLocalizedLabel != null && appInfo.nonLocalizedLabel.length() > 0) {
                return appInfo.nonLocalizedLabel.toString().trim();
            }
        }

        return pkg;
    }

    private static Drawable getIcon(PackageManager pm, String pkg) {
        // 1. Try launcher activity icon first
        try {
            Intent intent = pm.getLaunchIntentForPackage(pkg);
            if (intent != null && intent.getComponent() != null) {
                ActivityInfo aInfo = pm.getActivityInfo(intent.getComponent(), 0);
                if (aInfo != null && aInfo.icon != 0) {
                    Resources res = pm.getResourcesForApplication(aInfo.applicationInfo);
                    Drawable d = res.getDrawable(aInfo.icon, null);
                    if (d != null) return d;
                }
            }
        } catch (Throwable ignored) {}

        // 2. Try application icon
        try {
            ApplicationInfo appInfo = pm.getApplicationInfo(pkg, 0);
            if (appInfo != null && appInfo.icon != 0) {
                Resources res = pm.getResourcesForApplication(appInfo);
                Drawable d = res.getDrawable(appInfo.icon, null);
                if (d != null) return d;
            }
        } catch (Throwable ignored) {}

        // 3. Fallback to default system icon
        try {
            return Resources.getSystem().getDrawable(17301651, null); // android.R.drawable.sym_def_app_icon
        } catch (Throwable ignored) {}

        return null;
    }

    private static Bitmap renderDrawable(Drawable drawable, int size) {
        int width = size;
        int height = size;
        int intrinsicWidth = drawable.getIntrinsicWidth();
        int intrinsicHeight = drawable.getIntrinsicHeight();

        if (intrinsicWidth > 0 && intrinsicHeight > 0) {
            if (intrinsicWidth > intrinsicHeight) {
                height = Math.max(1, (size * intrinsicHeight) / intrinsicWidth);
            } else if (intrinsicHeight > intrinsicWidth) {
                width = Math.max(1, (size * intrinsicWidth) / intrinsicHeight);
            }
        }

        Bitmap bitmap = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888);
        Canvas canvas = new Canvas(bitmap);
        int left = (size - width) / 2;
        int top = (size - height) / 2;
        drawable.setBounds(left, top, left + width, top + height);
        drawable.draw(canvas);
        return bitmap;
    }

    private static boolean extractSingleToStream(PackageManager pm, String pkg, int size, OutputStream out) {
        try {
            Drawable icon = getIcon(pm, pkg);
            if (icon == null) return false;
            Bitmap bmp = renderDrawable(icon, size);
            bmp.compress(Bitmap.CompressFormat.PNG, 100, out);
            out.flush();
            return true;
        } catch (Throwable t) {
            return false;
        }
    }
}
