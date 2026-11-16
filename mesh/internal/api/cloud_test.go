package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/AaronChou313/open-remote-hub/mesh/internal/state"
)

func cloudRequest(s *Server, path string, value any) *httptest.ResponseRecorder {
	data, _ := json.Marshal(value)
	request := httptest.NewRequest("POST", "http://127.0.0.1:4789/api/v1"+path, strings.NewReader(string(data)))
	request.Header.Set("Authorization", "Bearer test-api-token")
	response := httptest.NewRecorder()
	s.Handler().ServeHTTP(response, request)
	return response
}
func TestAdoptExistingORHIdentity(t *testing.T) {
	const device = "4de38c98-befa-4dc4-9241-b5b5154a003c"
	const credential = "private-device-credential-test"
	var calls atomic.Int32
	cloud := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		if r.Method != "GET" || r.URL.Path != "/agent/directory" || r.Header.Get("Authorization") != "Bearer "+credential {
			t.Error("unexpected Cloud request")
		}
		json.NewEncoder(w).Encode([]map[string]any{{"instance_id": device, "self": true}})
	}))
	defer cloud.Close()
	s := &Server{Token: "test-api-token", Config: state.Config{APIAddr: "127.0.0.1:4789", StateDir: filepath.Join(t.TempDir(), "state"), Publish: map[int]string{21118: "127.0.0.1:21118"}}, ConfigPath: filepath.Join(t.TempDir(), "config.json")}
	input := map[string]any{"base_url": cloud.URL, "device_id": device, "device_token": credential, "console_port": 8765, "gateway_port": 8767}
	response := cloudRequest(s, "/cloud/adopt", input)
	if response.Code != 200 || strings.Contains(response.Body.String(), credential) {
		t.Fatalf("adopt status %d", response.Code)
	}
	cfg, _, err := state.Load(s.ConfigPath)
	if err != nil || !cfg.Cloud.Bound || !cfg.Cloud.ExternallyManaged || cfg.Cloud.DeviceID != device || cfg.Publish[8765] != "127.0.0.1:8765" {
		t.Fatal("adopted config was not persisted")
	}
	response = cloudRequest(s, "/cloud/adopt", input)
	if response.Code != 200 || calls.Load() != 1 {
		t.Fatal("idempotent adoption should not repeat Cloud validation")
	}
	input["device_id"] = "another-device"
	if response = cloudRequest(s, "/cloud/adopt", input); response.Code != 409 {
		t.Fatal("existing identity was overwritten")
	}
}
func TestConcurrentBindReusesPendingCodeAndHidesExpired(t *testing.T) {
	var calls atomic.Int32
	cloud := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		json.NewEncoder(w).Encode(map[string]any{"device_code": "private-code", "user_code": "ABCD-1234", "verification_url": "https://cloud.example/#bind=ABCD1234", "expires_in": 600})
	}))
	defer cloud.Close()
	s := &Server{Token: "test-api-token", Config: state.Config{APIAddr: "127.0.0.1:4789"}, ConfigPath: filepath.Join(t.TempDir(), "config.json")}
	var group sync.WaitGroup
	for range 2 {
		group.Add(1)
		go func() {
			defer group.Done()
			if cloudRequest(s, "/cloud/bind", map[string]string{"cloud_url": cloud.URL}).Code != 200 {
				t.Error("bind failed")
			}
		}()
	}
	group.Wait()
	if calls.Load() != 1 {
		t.Fatal("duplicate binding codes were issued")
	}
	s.Config.Cloud.Expires = float64(time.Now().Add(-time.Minute).Unix())
	if s.publicCloud()["pending"] != nil {
		t.Fatal("expired binding code shown")
	}
}

func TestAdoptRejectsAnotherDeviceInTheSameAccount(t *testing.T) {
	cloud := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode([]map[string]any{{"instance_id": "device-a", "self": true}, {"instance_id": "device-b", "self": false}})
	}))
	defer cloud.Close()
	s := &Server{Token: "test-api-token", Config: state.Config{APIAddr: "127.0.0.1:4789"}}
	response := cloudRequest(s, "/cloud/adopt", map[string]any{"base_url": cloud.URL, "device_id": "device-b", "device_token": "device-a-private-credential"})
	if response.Code != 403 || s.Config.Cloud.Bound {
		t.Fatal("another device credential was accepted")
	}
}

func TestClientTicketUsesBoundCloudAndPreservesAccountErrors(t *testing.T) {
	const device = "4de38c98-befa-4dc4-9241-b5b5154a003c"
	const token = "private-account-ticket-token"
	status := 200
	cloud := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/devices/"+device+"/ticket" || r.Header.Get("Authorization") != "Bearer "+token {
			t.Error("ticket used another endpoint or credential")
		}
		if status != 200 {
			w.WriteHeader(status)
			json.NewEncoder(w).Encode(map[string]string{"detail": "account expired"})
			return
		}
		json.NewEncoder(w).Encode(map[string]string{"url": "http://orh-device.localhost:12345/auth/cloud#ticket=fixture"})
	}))
	defer cloud.Close()
	server := &Server{Token: "test-api-token", Config: state.Config{APIAddr: "127.0.0.1:4789", Cloud: state.Cloud{BaseURL: cloud.URL, Bound: true}}}
	input := map[string]string{"device_id": device, "address": "http://orh-device.localhost:12345", "account_token": token}
	response := cloudRequest(server, "/cloud/ticket", input)
	if response.Code != 200 || !strings.Contains(response.Body.String(), "ticket=fixture") || strings.Contains(response.Body.String(), token) {
		t.Fatal("ticket response failed")
	}
	status = 401
	if response = cloudRequest(server, "/cloud/ticket", input); response.Code != 401 {
		t.Fatal("account rejection became an offline fallback")
	}
	input["device_id"] = "../other-endpoint"
	if cloudRequest(server, "/cloud/ticket", input).Code != 400 {
		t.Fatal("invalid device path was accepted")
	}
}
