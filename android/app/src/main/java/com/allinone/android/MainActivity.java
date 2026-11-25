package com.allinone.android;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.DownloadManager;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.Settings;
import android.webkit.DownloadListener;
import android.webkit.MimeTypeMap;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.TextView;
import android.widget.Toast;

import androidx.activity.OnBackPressedCallback;
import androidx.activity.ComponentActivity;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.core.content.FileProvider;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.yausername.ffmpeg.FFmpeg;
import com.yausername.youtubedl_android.YoutubeDL;

import java.io.File;
import java.io.ByteArrayOutputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.ServerSocket;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.json.JSONArray;
import org.json.JSONObject;

public final class MainActivity extends ComponentActivity {
    private static final int FALLBACK_PORT = 18765;
    private static final String UPDATE_REPOSITORY = "infobus4668/AllN1Downloader";
    private final ExecutorService startup = Executors.newSingleThreadExecutor();
    private WebView webView;
    private TextView startupText;
    private int port = FALLBACK_PORT;
    private volatile File pendingUpdateApk;
    private ValueCallback<Uri[]> cookieFileCallback;
    private final ActivityResultLauncher<String[]> cookieFilePicker = registerForActivityResult(
            new ActivityResultContracts.OpenDocument(), uri -> {
                ValueCallback<Uri[]> callback = cookieFileCallback;
                cookieFileCallback = null;
                if (callback != null) {
                    callback.onReceiveValue(uri != null && "content".equals(uri.getScheme())
                            ? new Uri[]{uri} : null);
                }
            });

    int getLocalServerPort() {
        return port;
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(0xff080b14);
        getWindow().setNavigationBarColor(0xff080b14);
        startupText = new TextView(this);
        startupText.setText(R.string.startup_text);
        startupText.setTextColor(0xfff2f5fb);
        startupText.setTextSize(18);
        startupText.setPadding(28, 40, 28, 24);
        startupText.setBackgroundColor(0xff080b14);
        setContentView(startupText);
        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override
            public void handleOnBackPressed() {
                if (webView != null && webView.canGoBack()) webView.goBack();
                else {
                    setEnabled(false);
                    getOnBackPressedDispatcher().onBackPressed();
                }
            }
        });
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 20);
        }
        startup.execute(this::startLocalApplication);
        new Thread(this::checkForAppUpdate, "alln1-update-check").start();
    }

    @Override
    protected void onResume() {
        super.onResume();
        File pending = pendingUpdateApk;
        if (pending != null && Build.VERSION.SDK_INT >= 26 && getPackageManager().canRequestPackageInstalls()) {
            pendingUpdateApk = null;
            installUpdateApk(pending);
        }
    }

    private void checkForAppUpdate() {
        File downloadedApk = null;
        try {
            URL releaseUrl = new URL("https://api.github.com/repos/" + UPDATE_REPOSITORY + "/releases/latest");
            HttpURLConnection releaseConnection = (HttpURLConnection) releaseUrl.openConnection();
            releaseConnection.setConnectTimeout(5000);
            releaseConnection.setReadTimeout(7000);
            releaseConnection.setRequestProperty("Accept", "application/vnd.github+json");
            releaseConnection.setRequestProperty("User-Agent", "AllN1Downloader-Android");
            JSONObject release;
            try (InputStream input = releaseConnection.getInputStream();
                 ByteArrayOutputStream output = new ByteArrayOutputStream()) {
                byte[] buffer = new byte[8192];
                int count;
                while ((count = input.read(buffer)) >= 0) {
                    if (output.size() + count > 1024 * 1024) throw new IOException("Release metadata is too large");
                    output.write(buffer, 0, count);
                }
                release = new JSONObject(output.toString(StandardCharsets.UTF_8.name()));
            } finally {
                releaseConnection.disconnect();
            }

            PackageInfo installed = getPackageManager().getPackageInfo(getPackageName(), PackageManager.GET_SIGNING_CERTIFICATES);
            long installedCode = installed.getLongVersionCode();
            String installedName = installed.versionName == null ? "" : installed.versionName;
            String releaseTag = release.optString("tag_name", "");
            if (!releaseTag.matches("v?[0-9]{1,9}(\\.[0-9]{1,9}){1,3}")) return;
            String tag = releaseTag.replaceFirst("^v", "");
            JSONArray assets = release.optJSONArray("assets");
            String apkUrl = null;
            if (assets != null) {
                for (int i = 0; i < assets.length(); i++) {
                    JSONObject asset = assets.optJSONObject(i);
                    if (asset != null && "AllN1Downloader-Android.apk".equals(asset.optString("name"))) {
                        apkUrl = asset.optString("browser_download_url", null);
                        break;
                    }
                }
            }
            String expectedUrl = "https://github.com/" + UPDATE_REPOSITORY + "/releases/download/"
                    + releaseTag + "/AllN1Downloader-Android.apk";
            if (!expectedUrl.equals(apkUrl) || tag.equals(installedName)) return;

            File updateDir = new File(getFilesDir(), "updates");
            if (!updateDir.exists() && !updateDir.mkdirs()) return;
            String safeTag = tag.replaceAll("[^A-Za-z0-9._-]", "_");
            downloadedApk = new File(updateDir, "AllN1Downloader-" + safeTag + ".apk");
            if (!downloadedApk.isFile()) downloadUpdateFile(apkUrl, downloadedApk);

            PackageInfo candidate = getPackageManager().getPackageArchiveInfo(
                    downloadedApk.getAbsolutePath(), PackageManager.GET_SIGNING_CERTIFICATES);
            if (candidate == null || !getPackageName().equals(candidate.packageName)
                    || candidate.getLongVersionCode() <= installedCode
                    || !sameSigningIdentity(installed.signingInfo, candidate.signingInfo)) {
                downloadedApk.delete();
                return;
            }
            File ready = downloadedApk;
            runOnUiThread(() -> offerUpdateInstall(ready, tag));
        } catch (Exception error) {
            if (downloadedApk != null && downloadedApk.length() == 0) downloadedApk.delete();
            android.util.Log.i("AllN1Update", "Update check unavailable: " + error.getMessage());
        }
    }

    private static boolean sameSigningIdentity(android.content.pm.SigningInfo installed,
                                                android.content.pm.SigningInfo candidate) {
        if (installed == null || candidate == null) return false;
        return Arrays.equals(installed.getApkContentsSigners(), candidate.getApkContentsSigners());
    }

    private static void downloadUpdateFile(String address, File destination) throws IOException {
        URL url = new URL(address);
        if (!"https".equalsIgnoreCase(url.getProtocol()) || !"github.com".equalsIgnoreCase(url.getHost())) {
            throw new IOException("Update download is not from a trusted HTTPS GitHub release");
        }
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        connection.setConnectTimeout(10000);
        connection.setReadTimeout(30000);
        connection.setRequestProperty("User-Agent", "AllN1Downloader-Android");
        try (InputStream input = connection.getInputStream(); FileOutputStream output = new FileOutputStream(destination)) {
            byte[] buffer = new byte[64 * 1024];
            int count;
            long total = 0;
            while ((count = input.read(buffer)) >= 0) {
                total += count;
                if (total > 600L * 1024 * 1024) throw new IOException("Update APK is unexpectedly large");
                output.write(buffer, 0, count);
            }
            if (total == 0) throw new IOException("Update APK is empty");
        } catch (Exception error) {
            destination.delete();
            throw error;
        } finally {
            connection.disconnect();
        }
    }

    private void offerUpdateInstall(File apk, String version) {
        new AlertDialog.Builder(this)
                .setTitle("AllN1Downloader update ready")
                .setMessage("Version " + version + " is ready. Android will ask you to confirm the install.")
                .setPositiveButton("Install update", (dialog, which) -> installUpdateApk(apk))
                .setNegativeButton("Later", (dialog, which) -> { })
                .show();
    }

    private void installUpdateApk(File apk) {
        if (Build.VERSION.SDK_INT >= 26 && !getPackageManager().canRequestPackageInstalls()) {
            pendingUpdateApk = apk;
            new AlertDialog.Builder(this)
                    .setTitle("Allow app updates")
                    .setMessage("Allow AllN1Downloader to open the Android installer for signed updates.")
                    .setPositiveButton("Settings", (dialog, which) -> startActivity(
                            new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                                    Uri.parse("package:" + getPackageName()))))
                    .setNegativeButton("Later", (dialog, which) -> pendingUpdateApk = null)
                    .show();
            return;
        }
        try {
            Uri content = FileProvider.getUriForFile(this, getPackageName() + ".files", apk);
            Intent install = new Intent(Intent.ACTION_VIEW)
                    .setDataAndType(content, "application/vnd.android.package-archive")
                    .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(install);
        } catch (Exception error) {
            Toast.makeText(this, "Could not open the Android installer: " + error.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    private void startLocalApplication() {
        try {
            // Keep the predecessor's data folder so rebranded upgrades retain downloads and history.
            File workDir = new File(getFilesDir(), "AllInOne");
            File staticDir = new File(workDir, "static");
            if (!staticDir.exists() && !staticDir.mkdirs()) throw new IOException("Cannot create app storage");
            copyAssets("static", workDir);

            // Extract the Android AAR support libraries, but run the current downloader in Chaquopy.
            YoutubeDL.getInstance().init(getApplicationContext());
            FFmpeg.getInstance().init(getApplicationContext());
            File nativeDir = new File(getApplicationInfo().nativeLibraryDir);
            File ffmpeg = new File(nativeDir, "libffmpeg.so");
            File ffprobe = new File(nativeDir, "libffprobe.so");
            File quickjs = new File(nativeDir, "libqjs.so");
            File pythonLibraries = new File(getNoBackupFilesDir(), "youtubedl-android/packages/python/usr/lib");
            File ffmpegLibraries = new File(getNoBackupFilesDir(), "youtubedl-android/packages/ffmpeg/usr/lib");
            port = choosePort();

            PyObject embeddedServer = Python.getInstance().getModule("android_server");
            embeddedServer.callAttr("start", workDir.getAbsolutePath(), staticDir.getAbsolutePath(),
                    ffmpeg.isFile() ? ffmpeg.getAbsolutePath() : "",
                    ffprobe.isFile() ? ffprobe.getAbsolutePath() : "",
                    quickjs.isFile() ? quickjs.getAbsolutePath() : "",
                    pythonLibraries.getAbsolutePath(), ffmpegLibraries.getAbsolutePath(), port);
            runOnUiThread(this::showWebView);
        } catch (Throwable error) {
            runOnUiThread(() -> {
                startupText.setText(getString(R.string.startup_error, error.getMessage()));
                Toast.makeText(this, R.string.startup_failed_toast, Toast.LENGTH_LONG).show();
            });
        }
    }

    private int choosePort() throws IOException {
        try (ServerSocket socket = new ServerSocket(0)) {
            socket.setReuseAddress(true);
            return socket.getLocalPort();
        }
    }

    private void copyAssets(String assetPath, File destination) throws IOException {
        File currentDestination = assetPath.isEmpty() ? destination : new File(destination, assetPath);
        if (!currentDestination.exists() && !currentDestination.mkdirs()) {
            throw new IOException("Cannot create asset directory: " + currentDestination);
        }
        String[] children = getAssets().list(assetPath);
        if (children == null || children.length == 0) {
            String name = assetPath.isEmpty() ? "" : assetPath.substring(assetPath.lastIndexOf('/') + 1);
            if (name.isEmpty()) return;
            File parent = currentDestination.getParentFile();
            if (parent != null && !parent.exists() && !parent.mkdirs()) {
                throw new IOException("Cannot create asset directory: " + parent);
            }
            copyAssetFile(assetPath, new File(parent == null ? destination : parent, name));
            return;
        }
        for (String child : children) {
            String childPath = assetPath.isEmpty() ? child : assetPath + "/" + child;
            String[] nested = getAssets().list(childPath);
            if (nested != null && nested.length > 0) copyAssets(childPath, destination);
            else copyAssetFile(childPath, new File(currentDestination, child));
        }
    }

    private void copyAssetFile(String assetPath, File target) throws IOException {
        try (InputStream input = getAssets().open(assetPath); FileOutputStream output = new FileOutputStream(target)) {
            byte[] buffer = new byte[16 * 1024];
            int count;
            while ((count = input.read(buffer)) >= 0) output.write(buffer, 0, count);
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    private void showWebView() {
        webView = new WebView(this);
        webView.setId(R.id.appWebView);
        webView.setBackgroundColor(0xff080b14);
        webView.getSettings().setJavaScriptEnabled(true);
        webView.getSettings().setDomStorageEnabled(true);
        webView.getSettings().setAllowFileAccess(false);
        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                String currentUrl = view.getUrl();
                Uri current = currentUrl == null ? Uri.EMPTY : Uri.parse(currentUrl);
                if (!"http".equals(current.getScheme()) || !"127.0.0.1".equals(current.getHost())
                        || current.getPort() != port || params.getMode() != FileChooserParams.MODE_OPEN) {
                    callback.onReceiveValue(null);
                    return true;
                }
                if (cookieFileCallback != null) cookieFileCallback.onReceiveValue(null);
                cookieFileCallback = callback;
                try {
                    // A provider may label a .txt export as text/plain or application/octet-stream.
                    cookieFilePicker.launch(new String[]{"text/plain", "application/octet-stream"});
                } catch (ActivityNotFoundException error) {
                    cookieFileCallback = null;
                    callback.onReceiveValue(null);
                    Toast.makeText(MainActivity.this, "No file picker is available", Toast.LENGTH_SHORT).show();
                }
                return true;
            }
        });
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, android.webkit.WebResourceRequest request) {
                Uri uri = request.getUrl();
                if ("127.0.0.1".equals(uri.getHost())) return false;
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, uri));
                } catch (ActivityNotFoundException ignored) {
                    Toast.makeText(MainActivity.this, "No browser can open this link", Toast.LENGTH_LONG).show();
                }
                return true;
            }
        });
         webView.addJavascriptInterface(new AndroidBridge(), "AllN1DownloaderAndroid");
        webView.setDownloadListener((url, userAgent, contentDisposition, mimeType, contentLength) ->
                downloadToPublicFolder(url, userAgent, contentDisposition, mimeType));
        setContentView(webView);
        webView.loadUrl("http://127.0.0.1:" + port + "/");
    }

    private void downloadToPublicFolder(String url, String userAgent, String contentDisposition, String mimeType) {
        Uri uri = Uri.parse(url);
        if (!"127.0.0.1".equals(uri.getHost())) {
             Toast.makeText(this, "Only local AllN1Downloader downloads are accepted", Toast.LENGTH_LONG).show();
            return;
        }
        try {
            DownloadManager.Request request = new DownloadManager.Request(uri);
            String filename = android.webkit.URLUtil.guessFileName(url, contentDisposition, mimeType);
            request.setTitle(filename);
             request.setDescription("Saved by AllN1Downloader");
            request.setMimeType(mimeType);
            request.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
            if (userAgent != null) request.addRequestHeader("User-Agent", userAgent);
            request.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, filename);
            ((DownloadManager) getSystemService(DOWNLOAD_SERVICE)).enqueue(request);
            Toast.makeText(this, "Saving to Downloads", Toast.LENGTH_SHORT).show();
        } catch (Exception error) {
            Toast.makeText(this, "Could not save file: " + error.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    private final class AndroidBridge {
        @android.webkit.JavascriptInterface
        public void onDownloadQueued() {
            runOnUiThread(() -> {
                Intent intent = new Intent(MainActivity.this, DownloadMonitorService.class)
                        .putExtra(DownloadMonitorService.EXTRA_PORT, port);
                startForegroundService(intent);
            });
        }

        @android.webkit.JavascriptInterface
        public void openDownloads(String ignoredPath) {
            runOnUiThread(() -> {
                try {
                    startActivity(new Intent(DownloadManager.ACTION_VIEW_DOWNLOADS));
                } catch (ActivityNotFoundException error) {
                    Toast.makeText(MainActivity.this, "Use the Files app to open Downloads", Toast.LENGTH_LONG).show();
                }
            });
        }

        @android.webkit.JavascriptInterface
        public void openFolder(String path) {
            runOnUiThread(() -> showFolder(path));
        }

        @android.webkit.JavascriptInterface
        public void openFile(String path) {
            runOnUiThread(() -> viewFile(path));
        }
    }

    private void showFolder(String path) {
        File allowedRoot = new File(getFilesDir(), "AllInOne/downloads").getAbsoluteFile();
        File folder = new File(path).getAbsoluteFile();
        if (!folder.toPath().normalize().startsWith(allowedRoot.toPath().normalize())) {
            Toast.makeText(this, "Invalid download folder", Toast.LENGTH_LONG).show();
            return;
        }
        File[] files = folder.listFiles();
        if (files == null || files.length == 0) {
            Toast.makeText(this, "This download folder is empty", Toast.LENGTH_SHORT).show();
            return;
        }
        String[] names = new String[files.length];
        for (int i = 0; i < files.length; i++) names[i] = files[i].getName();
        new android.app.AlertDialog.Builder(this).setTitle("Download files")
                .setItems(names, (dialog, which) -> {
                    if (files[which].isFile()) viewFile(files[which].getAbsolutePath());
                    else showFolder(files[which].getAbsolutePath());
                }).setNegativeButton("Close", null).show();
    }

    private void viewFile(String path) {
        try {
            File allowedRoot = new File(getFilesDir(), "AllInOne/downloads").getCanonicalFile();
            File file = new File(path).getCanonicalFile();
            if (!file.isFile() || !file.toPath().startsWith(allowedRoot.toPath())) {
                Toast.makeText(this, "File not found", Toast.LENGTH_LONG).show();
                return;
            }
            Uri uri = FileProvider.getUriForFile(this, getPackageName() + ".files", file);
            String extension = MimeTypeMap.getFileExtensionFromUrl(file.getName());
            String mime = MimeTypeMap.getSingleton().getMimeTypeFromExtension(extension);
            Intent intent = new Intent(Intent.ACTION_VIEW).setDataAndType(uri, mime == null ? "*/*" : mime)
                    .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            startActivity(intent);
        } catch (ActivityNotFoundException error) {
            Toast.makeText(this, "No app can open this file", Toast.LENGTH_LONG).show();
        } catch (Exception error) {
            Toast.makeText(this, "Could not open file: " + error.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    @Override
    protected void onDestroy() {
        if (cookieFileCallback != null) {
            cookieFileCallback.onReceiveValue(null);
            cookieFileCallback = null;
        }
        startup.shutdownNow();
        if (webView != null) webView.destroy();
        super.onDestroy();
    }
}
