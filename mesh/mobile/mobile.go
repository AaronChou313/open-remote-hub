// Package mobile exposes a small gomobile-compatible lifecycle. Tokens remain
// inside the application's private storage and are used for loopback API calls.
package mobile

import (
	"context"
	"github.com/AaronChou313/open-remote-hub/mesh/internal/state"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/AaronChou313/open-remote-hub/mesh/internal/agentapp"
)

var mu sync.Mutex
var running *agentapp.App
var version = "development"

func Start(directory, hostname string) error {
	mu.Lock()
	defer mu.Unlock()
	if running != nil {
		return nil
	}
	logs := filepath.Join(directory, "logs")
	if err := os.MkdirAll(logs, 0700); err != nil {
		return err
	}
	if err := os.Setenv("TS_LOGS_DIR", logs); err != nil {
		return err
	}
	path := filepath.Join(directory, "config.json")
	if _, err := os.Stat(path); os.IsNotExist(err) {
		cfg, _, loadErr := state.Load(path)
		if loadErr != nil {
			return loadErr
		}
		cfg.Hostname = hostname
		cfg.Publish = map[int]string{}
		if err = state.Save(path, cfg); err != nil {
			return err
		}
	}
	app, err := agentapp.Start(path, version, "", "", false)
	if err != nil {
		return err
	}
	running = app
	return nil
}
func Stop() error {
	mu.Lock()
	defer mu.Unlock()
	if running == nil {
		return nil
	}
	err := running.Close()
	running = nil
	return err
}
func Token() string {
	mu.Lock()
	defer mu.Unlock()
	if running == nil {
		return ""
	}
	return running.Token
}

// ActiveForwards lets the Android foreground service hold a wake lock only
// while another app is using a mesh connection.
func ActiveForwards() int {
	mu.Lock()
	app := running
	mu.Unlock()
	if app == nil {
		return 0
	}
	count := 0
	for _, entry := range app.API.Forwards.List() {
		count += entry.Connections
	}
	return count
}
func Rebind() error {
	mu.Lock()
	app := running
	mu.Unlock()
	if app == nil {
		return nil
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	return app.Node.Rebind(ctx)
}
