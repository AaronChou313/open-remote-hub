package api

import (
	"github.com/AaronChou313/open-remote-hub/mesh/internal/state"
	"net/http/httptest"
	"testing"
)

func TestLocalAPIBoundaries(t *testing.T) {
	server := &Server{Token: "private-test-token", Config: state.Config{APIAddr: "127.0.0.1:4789"}, Version: "test"}
	for _, test := range []struct {
		host, origin, token string
		code                int
	}{
		{"127.0.0.1:4789", "", "", 401},
		{"127.0.0.1:4789", "", "private-test-token", 200},
		{"localhost:4789", "http://localhost:4789", "private-test-token", 200},
		{"attacker.example:4789", "", "private-test-token", 400},
		{"192.168.1.2:4789", "", "private-test-token", 400},
		{"127.0.0.1:4789", "https://attacker.example", "private-test-token", 403},
	} {
		request := httptest.NewRequest("GET", "http://"+test.host+"/api/v1/health", nil)
		request.Header.Set("Origin", test.origin)
		if test.token != "" {
			request.Header.Set("Authorization", "Bearer "+test.token)
		}
		response := httptest.NewRecorder()
		server.Handler().ServeHTTP(response, request)
		if response.Code != test.code {
			t.Errorf("host=%s origin=%s got %d", test.host, test.origin, response.Code)
		}
	}
}
