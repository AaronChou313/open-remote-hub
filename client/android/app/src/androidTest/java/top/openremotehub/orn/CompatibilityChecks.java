package top.openremotehub.orn;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.os.SystemClock;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.io.DataInputStream;
import java.io.OutputStream;
import top.openremotehub.orn.core.mobile.Mobile;

/** Runs against Android's actual Uri implementation, without an external test framework. */
public final class CompatibilityChecks extends Instrumentation {
    private String peer="";
    @Override public void onCreate(Bundle arguments) {
        super.onCreate(arguments);
        if (arguments!=null) peer=arguments.getString("peer","");
        start();
    }
    @Override public void onStart() {
        Bundle result=new Bundle();
        try {
            String address="127.0.0.1:54321";
            Uri link=MainActivity.rustDeskURI(address);
            if (!link.toString().equals("rustdesk://connection/new/"+address)
                || !link.getEncodedPath().equals("/new/"+address)) {
                throw new AssertionError("RustDesk received an encoded connection address");
            }
            Uri previous=new Uri.Builder().scheme("rustdesk").authority("connection").appendPath("new").appendPath(address).build();
            if (!previous.getEncodedPath().contains("%3A")) throw new AssertionError("Regression fixture no longer reproduces colon encoding");
            if (!peer.isEmpty()) checkBackgroundForward();
            result.putString("stream","RustDesk URI preserves the literal port colon. Previous URI reproduces %3A.\n");
            finish(Activity.RESULT_OK,result);
        } catch (Throwable error) {
            android.util.Log.e("ORN-COMPAT","Compatibility check failed",error);
            result.putString("stream",error.toString());
            finish(Activity.RESULT_CANCELED,result);
        }
    }

    /** Optional real-network test. The isolated peer must publish an echo server on 21118. */
    private void checkBackgroundForward() throws Exception {
        MainActivity activity=(MainActivity)startActivitySync(new Intent(getTargetContext(),MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK|Intent.FLAG_ACTIVITY_CLEAR_TASK));
        long readyUntil=SystemClock.elapsedRealtime()+180000;
        String address;
        while (true) {
            try { address=activity.desktopAddress(peer); break; }
            catch (Exception error) {
                if (SystemClock.elapsedRealtime()>readyUntil) throw error;
                Thread.sleep(1000);
            }
        }
        if (!address.equals(activity.desktopAddress(peer))) throw new AssertionError("Repeated entry changed the desktop port");
        getTargetContext().startForegroundService(new Intent(getTargetContext(),OrnService.class).putExtra("desktop",true));
        int port=Integer.parseInt(address.substring(address.lastIndexOf(':')+1));
        try (Socket socket=new Socket("127.0.0.1",port)) {
            socket.setSoTimeout(12000);
            DataInputStream input=new DataInputStream(socket.getInputStream());
            OutputStream output=socket.getOutputStream();
            runOnMainSync(() -> activity.moveTaskToBack(true));
            android.util.Log.i("ORN-COMPAT","BACKGROUND_READY port="+port);
            long until=SystemClock.elapsedRealtime()+150000;
            int count=0;
            do {
                byte[] payload=("ORN background roundtrip "+count).getBytes(StandardCharsets.UTF_8);
                output.write(payload);
                byte[] received=new byte[payload.length];
                input.readFully(received);
                if (!java.util.Arrays.equals(payload,received)) throw new AssertionError("Background TCP bytes changed");
                count++;
                Thread.sleep(2000);
            } while (SystemClock.elapsedRealtime()<until);
            if (Mobile.activeForwards()<1) throw new AssertionError("Active forward disappeared");
            android.util.Log.i("ORN-COMPAT","BACKGROUND_PASSED roundtrips="+count);
        }
        Thread.sleep(20000);
        if (Mobile.activeForwards()!=0) throw new AssertionError("Closed connection retained activity");
        // A restarted core must reuse the saved local port and existing binding.
        Mobile.stop();
        Mobile.start(new java.io.File(getTargetContext().getFilesDir(),"orn").getAbsolutePath(),"ORN background QA");
        String restored;
        readyUntil=SystemClock.elapsedRealtime()+60000;
        while (true) {
            try { restored=activity.desktopAddress(peer); break; }
            catch (Exception error) {
                if (SystemClock.elapsedRealtime()>readyUntil) throw error;
                Thread.sleep(1000);
            }
        }
        if (!address.equals(restored)) throw new AssertionError("Core restart changed the saved desktop port");
    }
}
