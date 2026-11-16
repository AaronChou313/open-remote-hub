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

func TestConsoleOpensSavedServicesOnController(t *testing.T) {
	const device = "f57bc9e0-1f1e-4c96-b4f8-c9e3be1f41c9"
	const app = "abcdef0123456789"
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/.well-known/openremotehub":
			json.NewEncoder(w).Encode(map[string]string{"service": "openremotehub", "instance_id": device})
		case "/api/me":
			if r.Header.Get("Cookie") != "orh=session" {
				w.WriteHeader(401)
				return
			}
			json.NewEncoder(w).Encode(map[string]string{"role": "admin", "device_id": device})
		case "/api/applications":
			json.NewEncoder(w).Encode(map[string]any{"applications": []map[string]any{{"id": app, "mode": "host", "port": 17861, "scheme": "http", "path": "/signin?q=1"}}})
		case "/api/applications/" + app + "/tunnel":
			if r.Header.Get("Cookie") != "orh=session" {
				w.WriteHeader(401)
				return
			}
			connection, err := websocket.Accept(w, r, nil)
			if err != nil {
				t.Error(err)
				return
			}
			defer connection.CloseNow()
			connection.SetReadLimit(128 * 1024)
			stream := websocket.NetConn(r.Context(), connection, websocket.MessageBinary)
			io.Copy(stream, stream)
		default:
			t.Errorf("unexpected target %s", r.URL.Path)
		}
	}))
	defer upstream.Close()
	target, _ := url.Parse(upstream.URL)
	manager := New(mappedDialer{target: target.Host})
	defer manager.Close()
	entry, err := manager.CreateConsole(context.Background(), "100.64.0.20", device)
	if err != nil {
		t.Fatal(err)
	}
	transport := &http.Transport{DialContext: func(ctx context.Context, network, address string) (net.Conn, error) {
		_, port, _ := net.SplitHostPort(address)
		return (&net.Dialer{}).DialContext(ctx, network, "127.0.0.1:"+port)
	}}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport}
	open := func(cookie, kind, id string) *http.Response {
		request, _ := http.NewRequest("POST", entry.URL+"/__remotehub__/open", strings.NewReader(fmt.Sprintf(`{"kind":%q,"id":%q}`, kind, id)))
		request.Header.Set("Cookie", cookie)
		request.Header.Set("X-ORH-Request", "1")
		response, err := client.Do(request)
		if err != nil {
			t.Fatal(err)
		}
		return response
	}
	denied := open("", "application", app)
	denied.Body.Close()
	if denied.StatusCode != 401 {
		t.Fatal("unauthenticated service creation accepted")
	}
	response := open("orh=session", "application", app)
	var result map[string]string
	json.NewDecoder(response.Body).Decode(&result)
	response.Body.Close()
	if response.StatusCode != 200 {
		t.Fatalf("open failed: %+v", result)
	}
	destination, err := url.Parse(result["url"])
	if err != nil || !strings.HasPrefix(destination.Hostname(), "app-"+device) || destination.Path != "/signin" || destination.RawQuery != "q=1" {
		t.Fatalf("wrong service URL %+v", result)
	}
	connection, err := net.Dial("tcp", "127.0.0.1:"+destination.Port())
	if err != nil {
		t.Fatal(err)
	}
	defer connection.Close()
	connection.SetDeadline(time.Now().Add(5 * time.Second))
	payload := strings.Repeat("http-and-websocket-bytes", 5000)
	go io.WriteString(connection, payload)
	echoed := make([]byte, len(payload))
	if _, err = io.ReadFull(connection, echoed); err != nil || string(echoed) != payload {
		t.Fatalf("service stream lost bytes: %v", err)
	}
	missing := open("orh=session", "application", "missing")
	missing.Body.Close()
	if missing.StatusCode != 404 {
		t.Fatal("unsaved service accepted")
	}
	desktop := open("orh=session", "desktop", "")
	json.NewDecoder(desktop.Body).Decode(&result)
	desktop.Body.Close()
	if !strings.HasPrefix(result["url"], "rustdesk://connection/new/127.0.0.1") {
		t.Fatalf("desktop did not use controller forward: %+v", result)
	}
}
