package com.allinone.android;

import static org.junit.Assert.assertTrue;
import static org.junit.Assert.assertEquals;

import android.util.Log;
import android.webkit.WebView;

import androidx.test.core.app.ActivityScenario;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.rule.GrantPermissionRule;
import androidx.test.platform.app.InstrumentationRegistry;

import org.junit.Test;
import org.junit.Rule;
import org.junit.runner.RunWith;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.URL;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

@RunWith(AndroidJUnit4.class)
public final class AndroidStartupSmokeTest {
    @Rule
    public final GrantPermissionRule notifications = GrantPermissionRule.grant("android.permission.POST_NOTIFICATIONS");

    @Test
    public void embeddedPythonServerAndLocalUiStart() throws Exception {
        try (ActivityScenario<MainActivity> scenario = ActivityScenario.launch(MainActivity.class)) {
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(90);
            boolean ready = false;
            while (System.nanoTime() < deadline && !ready) {
                CountDownLatch evaluated = new CountDownLatch(1);
                AtomicReference<String> result = new AtomicReference<>("false");
                scenario.onActivity(activity -> {
                    WebView webView = activity.findViewById(R.id.appWebView);
                    if (webView == null) {
                        evaluated.countDown();
                        return;
                    }
                    webView.evaluateJavascript(
                             "document.querySelector('#versionInfo')?.textContent === 'AllN1Downloader v" + BuildConfig.VERSION_NAME + "' " +
                                     "&& document.querySelector('#cookiesControl')?.classList.contains('hidden') " +
                                    "&& document.querySelector('#notifyLabel')?.classList.contains('hidden') " +
                                     "&& typeof window.AllN1DownloaderAndroid?.onDownloadQueued === 'function'",
                            value -> {
                                result.set(value);
                                evaluated.countDown();
                            }
                    );
                });
                evaluated.await(2, TimeUnit.SECONDS);
                ready = "true".equals(result.get());
                if (!ready) Thread.sleep(500);
            }
            assertTrue("Embedded backend and local WebView did not become ready", ready);

            AtomicInteger apiPort = new AtomicInteger();
            scenario.onActivity(activity -> apiPort.set(activity.getLocalServerPort()));
            JSONObject apiHealth = getJson("http://127.0.0.1:" + apiPort.get() + "/api/health");
            String ffmpegProbe = runBinary(apiHealth.getString("ffmpeg_path"));
            String ffprobeProbe = runBinary(apiHealth.getString("ffprobe_path"));
            try (FixtureSource source = new FixtureSource(wavFixture())) {
                JSONObject created = postJson("http://127.0.0.1:" + apiPort.get() + "/api/download", new JSONObject()
                        .put("url", source.getUrl())
                        .put("mode", "audio")
                        .put("container", "mp3")
                        .put("audio_quality", "320")
                        .put("title", "Android local smoke"));
                CountDownLatch monitorStarted = new CountDownLatch(1);
                scenario.onActivity(activity -> {
                    WebView webView = activity.findViewById(R.id.appWebView);
                    webView.evaluateJavascript("window.AllN1DownloaderAndroid.onDownloadQueued()", value -> monitorStarted.countDown());
                });
                assertTrue("Foreground download monitor did not start", monitorStarted.await(5, TimeUnit.SECONDS));
                String jobUrl = "http://127.0.0.1:" + apiPort.get() + "/api/jobs/" + created.getString("id");
                JSONObject job = null;
                for (int i = 0; i < 300; i++) {
                    job = getJson(jobUrl);
                    String status = job.getString("status");
                    if (status.equals("completed") || status.equals("error") || status.equals("cancelled")) break;
                    Thread.sleep(200);
                }
                if (job == null || !"completed".equals(job.optString("status"))) {
                    JSONObject logs = getJson(jobUrl + "/logs");
                    throw new AssertionError("Android fixture download failed: "
                            + (job == null ? "missing job" : job.optString("error", job.optString("status")))
                            + " health=" + apiHealth + " binaryChecks=" + ffmpegProbe + "; " + ffprobeProbe
                            + " logs=" + logs.optJSONArray("logs"));
                }
                assertEquals("mp3", job.getJSONObject("media").getJSONObject("audio").getString("codec"));
                assertZipHasMp3(jobUrl + "/zip");
            }
        }
    }

    private static byte[] wavFixture() {
        int sampleRate = 16000;
        int dataSize = sampleRate * 2 * 2;
        ByteBuffer wav = ByteBuffer.allocate(44 + dataSize).order(ByteOrder.LITTLE_ENDIAN);
        wav.put("RIFF".getBytes(StandardCharsets.US_ASCII)).putInt(36 + dataSize);
        wav.put("WAVEfmt ".getBytes(StandardCharsets.US_ASCII)).putInt(16);
        wav.putShort((short) 1).putShort((short) 1).putInt(sampleRate).putInt(sampleRate * 2);
        wav.putShort((short) 2).putShort((short) 16);
        wav.put("data".getBytes(StandardCharsets.US_ASCII)).putInt(dataSize);
        while (wav.hasRemaining()) wav.put((byte) 0);
        return wav.array();
    }

    private static JSONObject postJson(String address, JSONObject body) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(address).openConnection();
        connection.setConnectTimeout(5000);
        connection.setReadTimeout(10000);
        connection.setRequestMethod("POST");
        connection.setDoOutput(true);
        connection.setRequestProperty("Content-Type", "application/json");
        try (OutputStream output = connection.getOutputStream()) {
            output.write(body.toString().getBytes(StandardCharsets.UTF_8));
        }
        try (InputStream input = connection.getInputStream()) {
            return new JSONObject(readAll(input));
        } finally {
            connection.disconnect();
        }
    }

    private static JSONObject getJson(String address) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(address).openConnection();
        connection.setConnectTimeout(5000);
        connection.setReadTimeout(10000);
        try (InputStream input = connection.getInputStream()) {
            return new JSONObject(readAll(input));
        } finally {
            connection.disconnect();
        }
    }

    private static String readAll(InputStream input) throws Exception {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[4096];
        int count;
        while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
        return output.toString(StandardCharsets.UTF_8.name());
    }

    private static String runBinary(String binary) {
        try {
            ProcessBuilder builder = new ProcessBuilder(binary, "-version").redirectErrorStream(true);
            android.content.Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
            File libraries = new File(context.getNoBackupFilesDir(), "youtubedl-android/packages/ffmpeg/usr/lib");
            File pythonLibraries = new File(context.getNoBackupFilesDir(), "youtubedl-android/packages/python/usr/lib");
            builder.environment().put("LD_LIBRARY_PATH", context.getApplicationInfo().nativeLibraryDir
                    + ":" + pythonLibraries.getAbsolutePath() + ":" + libraries.getAbsolutePath());
            Process process = builder.start();
            String output;
            try (InputStream stream = process.getInputStream()) {
                output = readAll(stream);
            }
            int exit = process.waitFor();
            return "exit=" + exit + " output=" + output.substring(0, Math.min(180, output.length()));
        } catch (Throwable error) {
            return "launch error=" + error;
        }
    }

    private static void assertZipHasMp3(String address) throws Exception {
        try (InputStream response = new URL(address).openStream(); ZipInputStream zip = new ZipInputStream(response)) {
            ZipEntry entry;
            byte[] buffer = new byte[2048];
            while ((entry = zip.getNextEntry()) != null) {
                if (entry.getName().toLowerCase().endsWith(".mp3")) {
                    while (zip.read(buffer) != -1) { /* drain to validate archive stream */ }
                    return;
                }
            }
        }
        throw new AssertionError("ZIP export did not include the converted MP3");
    }

    private static final class FixtureSource implements AutoCloseable {
        private final ServerSocket server;
        private final byte[] wav;
        private volatile boolean closed;
        private final Thread thread;

        FixtureSource(byte[] wav) throws Exception {
            this.wav = wav;
            server = new ServerSocket(0, 8, java.net.InetAddress.getByName("127.0.0.1"));
            thread = new Thread(this::serve, "android-wav-fixture");
            thread.setDaemon(true);
            thread.start();
        }

        String getUrl() {
            return "http://127.0.0.1:" + server.getLocalPort() + "/tone.wav";
        }

        private void serve() {
            while (!closed) {
                try (Socket socket = server.accept()) {
                    socket.setSoTimeout(5000);
                    BufferedReader reader = new BufferedReader(new InputStreamReader(socket.getInputStream(), StandardCharsets.US_ASCII));
                    String request = reader.readLine();
                    String line;
                    while ((line = reader.readLine()) != null && !line.isEmpty()) { /* skip headers */ }
                    boolean head = request != null && request.startsWith("HEAD ");
                    OutputStream output = socket.getOutputStream();
                    String headers = "HTTP/1.1 200 OK\r\nContent-Type: audio/wav\r\nContent-Length: " + wav.length
                            + "\r\nConnection: close\r\n\r\n";
                    output.write(headers.getBytes(StandardCharsets.US_ASCII));
                    if (!head) output.write(wav);
                    output.flush();
                } catch (Exception error) {
                    if (!closed) Log.w("AllN1DownloaderSmoke", "Local fixture request ended", error);
                }
            }
        }

        @Override
        public void close() throws Exception {
            closed = true;
            server.close();
            thread.join(2000);
        }
    }
}
