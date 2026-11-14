package mesh

import (
	"context"
	"github.com/AaronChou313/open-remote-hub/mesh/internal/state"
	"net"
	"os"
	"testing"
	"time"
)

// This opt-in check intentionally uses Dial without the LocalAPI PeerIP check.
// Run it only against isolated QA nodes to verify control-plane ACL isolation.
func TestCrossAccountDial(t *testing.T) {
	path := os.Getenv("ORN_E2E_CONFIG")
	if path == "" {
		t.Skip("requires an isolated, enrolled QA node")
	}
	cfg, _, err := state.Load(path)
	if err != nil {
		t.Fatal(err)
	}
	node := New(Config{Hostname: cfg.Hostname, ControlURL: cfg.ControlURL, StateDir: cfg.StateDir})
	if err = node.Start(); err != nil {
		t.Fatal(err)
	}
	defer node.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 25*time.Second)
	defer cancel()
	if err = node.Wait(ctx); err != nil {
		t.Fatal(err)
	}
	// Establish the same-account service first, then attempt the known foreign IP.
	connection, err := node.Dial(ctx, "tcp", net.JoinHostPort(os.Getenv("ORN_E2E_ALLOWED"), "19001"))
	if err != nil {
		t.Fatal("same-account dial", err)
	}
	connection.Close()
	blocked, stop := context.WithTimeout(ctx, 5*time.Second)
	defer stop()
	connection, err = node.Dial(blocked, "tcp", net.JoinHostPort(os.Getenv("ORN_E2E_FORBIDDEN"), "19001"))
	if err == nil {
		connection.Close()
		t.Fatal("cross-account dial unexpectedly succeeded")
	}
	t.Log("same-account TCP accepted; raw cross-account TCP rejected", err)
}
