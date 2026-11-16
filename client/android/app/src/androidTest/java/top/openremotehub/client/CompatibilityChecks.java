package top.openremotehub.client;

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
import top.openremotehub.client.core.mobile.Mobile;

/** Runs against Android's actual Uri implementation, without an external test framework. */
public final class CompatibilityChecks extends Instrumentation {
    private String peer="";
    private boolean consoleTest;
    @Override public void onCreate(Bundle arguments) {
        super.onCreate(arguments);
        if (arguments!=null) {peer=arguments.getString("peer","");consoleTest="1".equals(arguments.getString("console",""));}
        start();
    }
    @Override public void onStart() {
        Bundle result=new Bundle();
        try {
            if(consoleTest) {
                checkConsoleEntry();
                result.putString("stream","Console entry opened the authenticated shared Agent workspace.\n");
                finish(Activity.RESULT_OK,result);return;
            }
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

    /** Optional end-to-end check, with credentials in an app-private fixture. */
    private void checkConsoleEntry() throws Exception {
        java.io.File fixture=new java.io.File(getTargetContext().getFilesDir(),"console-qa.json");
        String text=new String(java.nio.file.Files.readAllBytes(fixture.toPath()),StandardCharsets.UTF_8);
        fixture.delete();
        org.json.JSONObject input=new org.json.JSONObject(text);
        MainActivity home=(MainActivity)startActivitySync(new Intent(getTargetContext(),MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK|Intent.FLAG_ACTIVITY_CLEAR_TASK));
        org.json.JSONObject login=null;
        long until=SystemClock.elapsedRealtime()+60000;
        while(input.has("password")&&login==null) {
            try {login=(org.json.JSONObject)LocalApi.call("/cloud/login",new org.json.JSONObject()
                .put("cloud_url",input.getString("cloud_url")).put("username",input.getString("username")).put("password",input.getString("password")),"POST");}
            catch(Exception unavailable){if(SystemClock.elapsedRealtime()>until)throw unavailable;Thread.sleep(1000);}
        }
        if(login!=null)getTargetContext().getSharedPreferences("cloud",0).edit().putString("token",login.getString("account_token"))
            .putString("url",input.getString("cloud_url")).commit();
        until=SystemClock.elapsedRealtime()+180000;
        while(true) {
            org.json.JSONObject status=(org.json.JSONObject)LocalApi.call("/status",null,"GET");
            if("Running".equals(status.optString("backend_state")))break;
            if(SystemClock.elapsedRealtime()>until)throw new AssertionError("Mesh did not connect");
            Thread.sleep(1000);
        }
        ConsoleActivity console=(ConsoleActivity)startActivitySync(new Intent(getTargetContext(),ConsoleActivity.class)
            .putExtra("device_id",input.getString("device_id")).putExtra("peer_ip",input.getString("peer_ip"))
            .putExtra("name","ORH console QA").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        final android.webkit.WebView[] web={null};
        runOnMainSync(() -> web[0]=findWeb(console.getWindow().getDecorView()));
        if(web[0]==null)throw new AssertionError("Console screen did not open immediately");
        until=SystemClock.elapsedRealtime()+60000;
        while(true) {
            java.util.concurrent.CountDownLatch done=new java.util.concurrent.CountDownLatch(1);
            final String[] ready={""};
            runOnMainSync(() -> web[0].evaluateJavascript("JSON.stringify({authenticated:Boolean(document.querySelector('#shell') && !document.querySelector('#shell').hidden),path:location.pathname,body:document.body?document.body.innerText.slice(0,2000):''})",value -> {ready[0]=value;done.countDown();}));
            done.await(3,java.util.concurrent.TimeUnit.SECONDS);
            if(ready[0].contains("authenticated\\\":true"))break;
            if(SystemClock.elapsedRealtime()>until)throw new AssertionError("Agent workspace did not authenticate. "+ready[0]+" "+Diagnostics.tail(2000));
            Thread.sleep(500);
        }
        runOnMainSync(console::finish);
        runOnMainSync(home::finish);
    }

    private android.webkit.WebView findWeb(android.view.View view) {
        if(view instanceof android.webkit.WebView)return (android.webkit.WebView)view;
        if(view instanceof android.view.ViewGroup) {
            android.view.ViewGroup group=(android.view.ViewGroup)view;
            for(int index=0;index<group.getChildCount();index++) {
                android.webkit.WebView found=findWeb(group.getChildAt(index));
                if(found!=null)return found;
            }
        }
        return null;
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
        getTargetContext().startForegroundService(new Intent(getTargetContext(),MeshService.class).putExtra("desktop",true));
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
        Mobile.start(new java.io.File(getTargetContext().getFilesDir(),"mesh").getAbsolutePath(),"ORN background QA");
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
