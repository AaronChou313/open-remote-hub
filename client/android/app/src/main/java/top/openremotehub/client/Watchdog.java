package top.openremotehub.client;

import android.app.AlarmManager;
import android.app.PendingIntent;
import android.content.*;
import android.os.SystemClock;

/**
 * Re-arms an OS alarm that restarts the runtime when Android or an OEM power
 * manager stops the foreground service. Alarms survive process death.
 */
public final class Watchdog extends BroadcastReceiver {
    private static final int CODE = 7;
    private static final long ACTIVE = 60_000;
    private static final long IDLE = 10 * 60_000;
    private static final String ACTION = "top.openremotehub.client.WATCHDOG";

    static void schedule(Context context, long delay) {
        AlarmManager alarms = context.getSystemService(AlarmManager.class);
        PendingIntent intent = PendingIntent.getBroadcast(context, CODE,
            new Intent(context, Watchdog.class).setAction(ACTION), PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        try {
            alarms.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, System.currentTimeMillis() + delay, intent);
        } catch (SecurityException error) {
            alarms.set(AlarmManager.RTC_WAKEUP, System.currentTimeMillis() + delay, intent);
        }
    }

    @Override public void onReceive(Context context, Intent intent) {
        boolean active = MeshService.desktopActive(context);
        if (!MeshService.alive()) {
            Diagnostics.log("watchdog", "运行中心已停止，请求重启");
            try {
                context.startForegroundService(new Intent(context, MeshService.class).putExtra("restore", true));
            } catch (RuntimeException error) {
                Diagnostics.log("watchdog", "无法重启服务: " + error);
            }
        } else {
            Diagnostics.log("watchdog", "运行中心正常，心跳 " + (SystemClock.elapsedRealtime() - MeshService.heartbeat) / 1000 + " 秒前");
        }
        schedule(context, active ? ACTIVE : IDLE);
    }
}
