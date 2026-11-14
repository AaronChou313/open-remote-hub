package api

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"fmt"
	"io/fs"
	"net"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/AaronChou313/open-remote-hub/mesh/internal/forward"
	"github.com/AaronChou313/open-remote-hub/mesh/internal/launcher"
	"github.com/AaronChou313/open-remote-hub/mesh/internal/mesh"
	"github.com/AaronChou313/open-remote-hub/mesh/internal/state"
	"github.com/AaronChou313/open-remote-hub/mesh/web"
)

type Server struct {
	Node       *mesh.Node
	Forwards   *forward.Manager
	Token      string
	Config     state.Config
	ConfigPath string
	Version    string
	Started    time.Time
	Platform   string
	cloudMu    sync.RWMutex
	syncMu     sync.Mutex
	cloudError string
}

func reply(w http.ResponseWriter, value any) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(value)
}
func fail(w http.ResponseWriter, status int, err error) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(map[string]string{"detail": err.Error()})
}
func body(w http.ResponseWriter, r *http.Request, value any) error {
	decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 16*1024))
	decoder.DisallowUnknownFields()
	return decoder.Decode(value)
}
func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /api/v1/health", func(w http.ResponseWriter, r *http.Request) {
		reply(w, map[string]any{"ok": true, "version": s.Version})
	})
	mux.HandleFunc("GET /api/v1/status", s.status)
	mux.HandleFunc("GET /api/v1/peers", func(w http.ResponseWriter, r *http.Request) {
		value, err := s.Node.Status(r.Context())
		if err != nil {
			fail(w, 503, err)
			return
		}
		reply(w, value.Peers)
	})
	mux.HandleFunc("GET /api/v1/forwards", func(w http.ResponseWriter, r *http.Request) { reply(w, s.Forwards.List()) })
	mux.HandleFunc("POST /api/v1/forwards", s.createForward)
	mux.HandleFunc("POST /api/v1/connect", s.createForward)
	mux.HandleFunc("POST /api/v1/console", s.console)
	mux.HandleFunc("DELETE /api/v1/forwards/{id}", func(w http.ResponseWriter, r *http.Request) {
		if err := s.Forwards.Delete(r.PathValue("id")); err != nil {
			fail(w, 404, err)
			return
		}
		reply(w, map[string]bool{"ok": true})
	})
	mux.HandleFunc("POST /api/v1/ping", s.ping)
	mux.HandleFunc("POST /api/v1/control", s.control)
	mux.HandleFunc("POST /api/v1/leave", s.leave)
	mux.HandleFunc("POST /api/v1/netcheck", func(w http.ResponseWriter, r *http.Request) {
		value, err := s.Node.Netcheck(r.Context())
		if err != nil {
			fail(w, 503, err)
			return
		}
		reply(w, value)
	})
	mux.HandleFunc("GET /api/v1/directory", s.directory)
	mux.HandleFunc("GET /api/v1/diagnostics", s.diagnostics)
	mux.HandleFunc("GET /api/v1/cloud", s.cloudStatus)
	mux.HandleFunc("POST /api/v1/cloud/bind", s.cloudBind)
	mux.HandleFunc("POST /api/v1/cloud/adopt", s.cloudAdopt)
	assets, _ := fs.Sub(web.Files, ".")
	mux.Handle("/", http.FileServer(http.FS(assets)))
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		host, port, err := net.SplitHostPort(r.Host)
		_, expectedPort, _ := net.SplitHostPort(s.Config.APIAddr)
		ip := net.ParseIP(host)
		if err != nil || port != expectedPort || (host != "localhost" && (ip == nil || !ip.IsLoopback())) {
			fail(w, 400, fmt.Errorf("无效的 LocalAPI 地址"))
			return
		}
		if origin := r.Header.Get("Origin"); origin != "" {
			parsed, e := url.Parse(origin)
			if e != nil || parsed.Scheme != "http" || parsed.Host != r.Host {
				fail(w, 403, fmt.Errorf("请求来源无效"))
				return
			}
		}
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("Referrer-Policy", "no-referrer")
		w.Header().Set("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
		if strings.HasPrefix(r.URL.Path, "/api/") {
			given := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
			if subtle.ConstantTimeCompare([]byte(given), []byte(s.Token)) != 1 {
				fail(w, 401, fmt.Errorf("请通过 ORH 启动入口打开本地页面"))
				return
			}
		}
		ctx, cancel := context.WithTimeout(r.Context(), 15*time.Second)
		defer cancel()
		mux.ServeHTTP(w, r.WithContext(ctx))
	})
}
func (s *Server) status(w http.ResponseWriter, r *http.Request) {
	value, err := s.Node.Status(r.Context())
	if err != nil {
		fail(w, 503, err)
		return
	}
	s.cloudMu.RLock()
	publish := s.Config.Publish
	s.cloudMu.RUnlock()
	uptime := int64(0)
	if !s.Started.IsZero() {
		uptime = int64(time.Since(s.Started).Seconds())
	}
	reply(w, map[string]any{"backend_state": value.BackendState, "version": s.Version, "engine_version": value.Version, "device": value.Device, "health": value.Health, "auth_url": value.AuthURL, "network": value.Network, "magic_dns": value.MagicDNS, "publish": publish, "cloud": s.publicCloud(), "uptime_seconds": uptime})
}
func (s *Server) createForward(w http.ResponseWriter, r *http.Request) {
	var input struct {
		PeerIP     string `json:"peer_ip"`
		RemotePort int    `json:"remote_port"`
		LocalPort  int    `json:"local_port"`
	}
	if err := body(w, r, &input); err != nil {
		fail(w, 400, fmt.Errorf("请输入 IP 和端口"))
		return
	}
	if _, err := s.Node.PeerIP(r.Context(), input.PeerIP); err != nil {
		fail(w, 400, err)
		return
	}
	if input.RemotePort < 1 || input.RemotePort > 65535 || input.LocalPort < 0 || input.LocalPort > 65535 {
		fail(w, 400, fmt.Errorf("端口范围为 1–65535，本地自动端口可填 0"))
		return
	}
	// Test the destination before returning a seemingly usable local endpoint.
	target, err := s.Node.Dial(r.Context(), "tcp", net.JoinHostPort(input.PeerIP, fmt.Sprint(input.RemotePort)))
	if err != nil {
		fail(w, 502, fmt.Errorf("目标端口无法连接，请确认远端服务已启动"))
		return
	}
	target.Close()
	entry, err := s.Forwards.Create(input.PeerIP, input.RemotePort, input.LocalPort)
	if err != nil {
		fail(w, 409, err)
		return
	}
	result := map[string]any{"forward": entry, "address": net.JoinHostPort("127.0.0.1", fmt.Sprint(entry.LocalPort))}
	if r.URL.Path == "/api/v1/connect" {
		if err = launcher.RustDesk(entry.LocalPort); err != nil {
			result["launch_error"] = err.Error()
		}
	}
	reply(w, result)
}
func (s *Server) ping(w http.ResponseWriter, r *http.Request) {
	var input struct {
		PeerIP string `json:"peer_ip"`
	}
	if err := body(w, r, &input); err != nil {
		fail(w, 400, err)
		return
	}
	result, err := s.Node.Ping(r.Context(), input.PeerIP)
	if err != nil {
		fail(w, 502, fmt.Errorf("设备检测未完成: %v", err))
		return
	}
	reply(w, result)
}
func (s *Server) control(w http.ResponseWriter, r *http.Request) {
	var input struct {
		Action string `json:"action"`
	}
	if err := body(w, r, &input); err != nil {
		fail(w, 400, err)
		return
	}
	var err error
	switch input.Action {
	case "connect":
		err = s.Node.SetRunning(r.Context(), true)
	case "disconnect":
		err = s.Node.SetRunning(r.Context(), false)
	case "reconnect":
		err = s.Node.SetRunning(r.Context(), true)
		if err == nil {
			err = s.Node.Rebind(r.Context())
		}
	default:
		fail(w, 400, fmt.Errorf("不支持的网络操作"))
		return
	}
	if err != nil {
		fail(w, 503, err)
		return
	}
	reply(w, map[string]bool{"ok": true})
}
func (s *Server) leave(w http.ResponseWriter, r *http.Request) {
	var input struct {
		Confirm bool `json:"confirm"`
	}
	if err := body(w, r, &input); err != nil || !input.Confirm {
		fail(w, 400, fmt.Errorf("请确认退出当前网络并移除本机网络身份"))
		return
	}
	s.syncMu.Lock()
	defer s.syncMu.Unlock()
	if err := s.unbind(r.Context()); err != nil {
		fail(w, 503, err)
		return
	}
	reply(w, map[string]bool{"ok": true})
}

func (s *Server) console(w http.ResponseWriter, r *http.Request) {
	var input struct {
		PeerIP   string `json:"peer_ip"`
		DeviceID string `json:"device_id"`
	}
	if err := body(w, r, &input); err != nil {
		fail(w, 400, err)
		return
	}
	s.cloudMu.RLock()
	ownID, localConsole := s.Config.Cloud.DeviceID, s.Config.Publish[8765]
	s.cloudMu.RUnlock()
	if input.DeviceID != "" && input.DeviceID == ownID && localConsole != "" {
		reply(w, map[string]any{"url": "http://" + localConsole + "/auth/cloud/enter"})
		return
	}
	if _, err := s.Node.PeerIP(r.Context(), input.PeerIP); err != nil {
		fail(w, 400, err)
		return
	}
	entry, err := s.Forwards.CreateConsole(r.Context(), input.PeerIP, input.DeviceID)
	if err != nil {
		fail(w, 502, err)
		return
	}
	reply(w, map[string]any{"forward": entry, "url": entry.URL + "/auth/cloud/enter"})
}
