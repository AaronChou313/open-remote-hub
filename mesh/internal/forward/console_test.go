package forward

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
	"time"

	"github.com/coder/websocket"
)

type mappedDialer struct{ target string }

func (d mappedDialer) Dial(ctx context.Context, network, address string) (net.Conn, error) {
	return (&net.Dialer{}).DialContext(ctx, network, d.target)
}

func TestConsoleUsesControllerUIAndTargetAPI(t *testing.T) {
	const id = "f57bc9e0-1f1e-4c96-b4f8-c9e3be1f41c9"
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/.well-known/openremotehub" {
			json.NewEncoder(w).Encode(map[string]string{"service": "openremotehub", "instance_id": id})
			return
		}
		io.WriteString(w, "target:"+r.URL.Path)
	}))
	defer remote.Close()
	frontend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		io.WriteString(w, "controller:"+r.URL.Path)
	}))
	defer frontend.Close()
	remoteURL, _ := url.Parse(remote.URL)
	manager := New(mappedDialer{target: remoteURL.Host})
	manager.Frontend = frontend.URL
	defer manager.Close()
	entry, err := manager.CreateConsole(context.Background(), "100.64.0.20", id)
	if err != nil {
		t.Fatal(err)
	}
	origin, _ := url.Parse(entry.URL)
	transport := &http.Transport{DialContext: func(ctx context.Context, network, address string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, network, net.JoinHostPort("127.0.0.1", origin.Port()))
	}}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport}
	for path, expected := range map[string]string{"/": "controller:/", "/auth/cloud": "controller:/auth/cloud", "/static/app.js": "controller:/static/app.js", "/api/me": "target:/api/me", "/terminal/open/test": "target:/terminal/open/test"} {
		response, err := client.Get(entry.URL + path)
		if err != nil {
			t.Fatal(err)
		}
		body, err := io.ReadAll(response.Body)
		response.Body.Close()
		if err != nil || string(body) != expected {
			t.Fatalf("%s received %q, want %q (%v)", path, body, expected, err)
		}
	}
}

func TestConsoleOriginCookieRedirectAndWebSocket(t *testing.T) {
	const id = "f57bc9e0-1f1e-4c96-b4f8-c9e3be1f41c9"
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Host != "100.64.0.20:8765" && r.Host != "100.64.0.20:8767" {
			t.Errorf("upstream Host %q", r.Host)
		}
		switch r.URL.Path {
		case "/.well-known/openremotehub":
			json.NewEncoder(w).Encode(map[string]string{"service": "openremotehub", "instance_id": id})
		case "/api/dsh/status":
			w.Header().Set("Content-Security-Policy", "frame-src http://100.64.0.20:8767")
			json.NewEncoder(w).Encode(map[string]any{"gateway_port": 8767})
		case "/gateway-health":
			if r.Host != "100.64.0.20:8767" {
				t.Error("gateway Host not translated")
			}
			w.Header().Set("Content-Security-Policy", "frame-ancestors http://100.64.0.20:8765")
			io.WriteString(w, "gateway ready")
		case "/auth/cloud/start":
			data, _ := json.Marshal(map[string]string{"device": id, "address": "http://100.64.0.20:8765", "state": "nonce"})
			location := "https://cloud.example/#" + url.Values{"authorize": {string(data)}}.Encode()
			http.SetCookie(w, &http.Cookie{Name: "orh_cloud_state", Value: "nonce", HttpOnly: true})
			http.Redirect(w, r, location, http.StatusFound)
		case "/echo":
			if r.Header.Get("Origin") != "http://100.64.0.20:8765" {
				t.Error("upstream Origin was not translated")
			}
			if cookie, err := r.Cookie("orh"); err != nil || cookie.Value != "session" {
				t.Error("session cookie lost")
			}
			connection, err := websocket.Accept(w, r, nil)
			if err != nil {
				t.Error(err)
				return
			}
			defer connection.CloseNow()
			kind, data, err := connection.Read(r.Context())
			if err == nil {
				connection.Write(r.Context(), kind, data)
			}
		default:
			io.WriteString(w, "ready")
		}
	}))
	defer upstream.Close()
	target, _ := url.Parse(upstream.URL)
	manager := New(mappedDialer{target: target.Host})
	defer manager.Close()
	entry, err := manager.CreateConsole(context.Background(), "100.64.0.20", id)
	if err != nil {
		t.Fatal(err)
	}
	origin, _ := url.Parse(entry.URL)
	transport := &http.Transport{DialContext: func(ctx context.Context, network, address string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, network, net.JoinHostPort("127.0.0.1", origin.Port()))
	}}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	response, err := client.Get(entry.URL + "/auth/cloud/start")
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	_, browserFragment, _ := strings.Cut(response.Header.Get("Location"), "#")
	fragment, _ := url.ParseQuery(browserFragment)
	var intent map[string]string
	json.Unmarshal([]byte(fragment.Get("authorize")), &intent)
	if intent["address"] != entry.URL || intent["state"] != "nonce" {
		t.Fatal("Cloud authorization callback was not mapped")
	}
	if len(response.Cookies()) != 1 || response.Cookies()[0].Name != "orh_cloud_state" {
		t.Fatal("nonce cookie missing")
	}
	response, err = client.Get(entry.URL + "/api/dsh/status")
	if err != nil {
		t.Fatal(err)
	}
	var dsh map[string]int
	json.NewDecoder(response.Body).Decode(&dsh)
	response.Body.Close()
	if dsh["gateway_port"] != entry.GatewayPort || !strings.Contains(response.Header.Get("Content-Security-Policy"), fmt.Sprint(entry.GatewayPort)) {
		t.Fatal("DSH gateway port or CSP not mapped")
	}
	gatewayURL := "http://" + origin.Hostname() + ":" + fmt.Sprint(entry.GatewayPort) + "/gateway-health"
	gatewayTransport := &http.Transport{DialContext: func(ctx context.Context, network, address string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, network, net.JoinHostPort("127.0.0.1", fmt.Sprint(entry.GatewayPort)))
	}}
	gatewayClient := &http.Client{Transport: gatewayTransport}
	response, err = gatewayClient.Get(gatewayURL)
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	gatewayTransport.CloseIdleConnections()
	if response.StatusCode != 200 || !strings.Contains(response.Header.Get("Content-Security-Policy"), entry.URL) {
		t.Fatal("DSH gateway not mapped")
	}
	request, _ := http.NewRequest("GET", entry.URL+"/", nil)
	request.Host = "attacker.example"
	response, err = client.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	if response.StatusCode != 403 {
		t.Fatal("foreign Host accepted")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	socket, _, err := websocket.Dial(ctx, strings.Replace(entry.URL, "http:", "ws:", 1)+"/echo", &websocket.DialOptions{HTTPClient: client, HTTPHeader: http.Header{"Origin": {entry.URL}, "Cookie": {"orh=session"}}})
	if err != nil {
		t.Fatal(err)
	}
	defer socket.CloseNow()
	if err = socket.Write(ctx, websocket.MessageText, []byte("终端 WebSocket")); err != nil {
		t.Fatal(err)
	}
	_, data, err := socket.Read(ctx)
	if err != nil || string(data) != "终端 WebSocket" {
		t.Fatalf("WebSocket relay failed: %v", err)
	}
	same, err := manager.CreateConsole(context.Background(), "100.64.0.20", id)
	if err != nil || same.ID != entry.ID {
		t.Fatal("console origin was not reused")
	}
	manager.Delete(entry.ID)
}
