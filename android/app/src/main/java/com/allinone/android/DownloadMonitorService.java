package com.allinone.android;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.IBinder;

import org.json.JSONArray;

import java.net.HttpURLConnection;
import java.net.URL;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

public final class DownloadMonitorService extends Service {
    public static final String EXTRA_PORT = "port";
    private static final String CHANNEL = "allinone-downloads";
    private static final int NOTIFICATION_ID = 143;
    private final ScheduledExecutorService monitor = Executors.newSingleThreadScheduledExecutor();
    private volatile int port = 8765;
    private volatile int idleChecks = 0;
    private volatile boolean pollScheduled = false;

    @Override
    public void onCreate() {
        super.onCreate();
        createChannel();
        startForegroundCompat(notification("Keeping downloads active"));
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null) port = intent.getIntExtra(EXTRA_PORT, port);
        idleChecks = 0;
        if (!pollScheduled) {
            pollScheduled = true;
            monitor.scheduleWithFixedDelay(this::pollQueue, 0, 2, TimeUnit.SECONDS);
        }
        return START_NOT_STICKY;
    }

    private void pollQueue() {
        int active = getActiveCount();
        if (active < 0) {
            idleChecks++;
            updateNotification("Waiting for the local download queue…");
        } else if (active == 0) {
            idleChecks++;
            updateNotification("Downloads finished");
        } else {
            idleChecks = 0;
            updateNotification("Downloading " + active + (active == 1 ? " item" : " items"));
        }
        if (idleChecks >= 4) {
            stopSelf();
        }
    }

    private int getActiveCount() {
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) new URL("http://127.0.0.1:" + port + "/api/jobs").openConnection();
            connection.setConnectTimeout(1500);
            connection.setReadTimeout(1500);
            connection.setRequestMethod("GET");
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            try (InputStream input = connection.getInputStream()) {
                byte[] buffer = new byte[4096];
                int count;
                while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
            }
            byte[] bytes = output.toByteArray();
            JSONArray jobs = new JSONArray(new String(bytes, StandardCharsets.UTF_8));
            int active = 0;
            for (int i = 0; i < jobs.length(); i++) {
                String status = jobs.getJSONObject(i).optString("status");
                if (status.equals("queued") || status.equals("downloading") || status.equals("processing")) active++;
            }
            return active;
        } catch (Exception ignored) {
            return -1;
        } finally {
            if (connection != null) connection.disconnect();
        }
    }

    private void createChannel() {
        NotificationChannel channel = new NotificationChannel(CHANNEL, "AllN1Downloader downloads", NotificationManager.IMPORTANCE_LOW);
        ((NotificationManager) getSystemService(NOTIFICATION_SERVICE)).createNotificationChannel(channel);
    }

    private Notification notification(String text) {
        return new Notification.Builder(this, CHANNEL).setSmallIcon(android.R.drawable.stat_sys_download)
                .setContentTitle("AllN1Downloader")
                .setContentText(text)
                .setOngoing(true)
                .build();
    }

    private void startForegroundCompat(Notification notification) {
        startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
    }

    private void updateNotification(String text) {
        ((NotificationManager) getSystemService(NOTIFICATION_SERVICE)).notify(NOTIFICATION_ID, notification(text));
    }

    @Override
    public void onDestroy() {
        monitor.shutdownNow();
        stopForeground(STOP_FOREGROUND_REMOVE);
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
