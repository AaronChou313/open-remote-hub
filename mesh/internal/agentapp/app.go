// Package agentapp runs the same networking, LocalAPI and Cloud lifecycle on
// desktop and Android. Platform launchers own only the surrounding UI/service.
package agentapp

import (
	"context"
	"log"
	"net"
	"net/http"
	"runtime"
	"sync"
	"time"

	"github.com/AaronChou313/open-remote-hub/mesh/internal/api"
	"github.com/AaronChou313/open-remote-hub/mesh/internal/forward"
	"github.com/AaronChou313/open-remote-hub/mesh/internal/mesh"
	"github.com/AaronChou313/open-remote-hub/mesh/internal/state"
)

type App struct {
	Node   *mesh.Node
	API    *api.Server
	Config state.Config
	Token  string
	http   *http.Server
	cancel context.CancelFunc
	done   chan struct{}
}

func Start(path, version, auth, controlURL string, debug bool) (*App, error) {
	cfg, token, err := state.Load(path)
	if err != nil {
		return nil, err
	}
	if controlURL != "" {
		cfg.ControlURL = controlURL
	}
	listener, err := net.Listen("tcp", cfg.APIAddr)
	if err != nil {
		return nil, err
	}
	node := mesh.New(mesh.Config{Hostname: cfg.Hostname, ControlURL: cfg.ControlURL, StateDir: cfg.StateDir, AuthKey: auth, Debug: debug, Logf: log.Printf})
	if err = node.Start(); err != nil {
		listener.Close()
		return nil, err
	}
	forwards := forward.New(node)
	if address := cfg.Publish[8765]; address != "" {
		forwards.Frontend = "http://" + address
	}
	if address := cfg.Publish[8767]; address != "" {
		forwards.FrontendGateway = "http://" + address
	}
	handler := &api.Server{Node: node, Forwards: forwards, Token: token, Config: cfg, ConfigPath: path, Version: version, Started: time.Now(), Platform: runtime.GOOS}
	ctx, cancel := context.WithCancel(context.Background())
	a := &App{Node: node, API: handler, Config: cfg, Token: token, cancel: cancel, done: make(chan struct{})}
	a.http = &http.Server{Handler: handler.Handler(), ReadHeaderTimeout: 5 * time.Second, IdleTimeout: 60 * time.Second}
	var tasks sync.WaitGroup
	tasks.Add(2)
	go func() { defer tasks.Done(); handler.CloudLoop(ctx) }()
	go func() {
		defer tasks.Done()
		if err := node.Wait(ctx); err != nil {
			return
		}
		for port, target := range cfg.Publish {
			if err := node.Publish(port, target); err != nil {
				log.Printf("发布端口 %d 失败: %v", port, err)
			}
		}
	}()
	go func() { tasks.Wait(); close(a.done) }()
	go func() {
		if err := a.http.Serve(listener); err != nil && err != http.ErrServerClosed {
			log.Printf("LocalAPI: %v", err)
		}
	}()
	return a, nil
}
func (a *App) Close() error {
	a.cancel()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	a.http.Shutdown(ctx)
	a.http.Close()
	a.API.Forwards.Close()
	<-a.done
	return a.Node.Close()
}
