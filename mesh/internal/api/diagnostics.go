package api

import (
	"net/http"
	"runtime"
	"time"
)

// diagnostics is loopback-only evidence for a dropped remote-desktop session:
// process uptime, the current mesh path, per-forward byte counters and the
// bounded event history. It never returns credentials or peer contents.
func (s *Server) diagnostics(w http.ResponseWriter, r *http.Request) {
	var memory runtime.MemStats
	runtime.ReadMemStats(&memory)
	value := map[string]any{
		"version":        s.Version,
		"platform":       s.Platform,
		"go":             runtime.Version(),
		"started":        s.Started,
		"uptime_seconds": int64(time.Since(s.Started).Seconds()),
		"goroutines":     runtime.NumGoroutine(),
		"heap_bytes":     memory.HeapInuse,
		"forwards":       s.Forwards.List(),
		"events":         s.Forwards.Events(),
	}
	status, err := s.Node.Status(r.Context())
	if err != nil {
		value["mesh_error"] = err.Error()
	} else {
		value["backend_state"] = status.BackendState
		value["health"] = status.Health
		value["device"] = status.Device
		value["peers"] = status.Peers
	}
	s.cloudMu.RLock()
	value["cloud"] = map[string]any{"bound": s.Config.Cloud.Bound, "device_id": s.Config.Cloud.DeviceID, "error": s.cloudError}
	s.cloudMu.RUnlock()
	reply(w, value)
}
