package forward

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strconv"

	"github.com/coder/websocket"
)

// openService runs on the viewing device, beside its per-device console gateway.
func (m *Manager) openService(w http.ResponseWriter, r *http.Request, ip, device string, target *url.URL, client *http.Client) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	fail := func(code int, message string) {
		w.WriteHeader(code)
		json.NewEncoder(w).Encode(map[string]string{"detail": message})
	}
	if r.Method != "POST" || r.Header.Get("X-ORH-Request") != "1" {
		fail(403, "请从设备工作区打开服务")
		return
	}
	request, _ := http.NewRequestWithContext(r.Context(), "GET", target.String()+"/api/me", nil)
	request.Header.Set("Cookie", r.Header.Get("Cookie"))
	response, err := client.Do(request)
	if err != nil {
		fail(502, "目标控制台无法连接")
		return
	}
	var session struct {
		Role     string `json:"role"`
		DeviceID string `json:"device_id"`
	}
	json.NewDecoder(io.LimitReader(response.Body, 65536)).Decode(&session)
	response.Body.Close()
	if response.StatusCode != 200 || session.Role == "" || session.DeviceID != device {
		fail(401, "请重新登录目标控制台")
		return
	}
	var input struct {
		Kind string `json:"kind"`
		ID   string `json:"id"`
	}
	if json.NewDecoder(http.MaxBytesReader(w, r.Body, 4096)).Decode(&input) != nil {
		fail(400, "打开请求无效")
		return
	}
	if input.Kind == "desktop" {
		if session.Role != "admin" {
			fail(403, "请使用管理员账户连接远程桌面")
			return
		}
		connection, err := m.dialer.Dial(r.Context(), "tcp", net.JoinHostPort(ip, "21118"))
		if err != nil {
			fail(502, "目标 RustDesk 直连接入未启动，请在远程桌面模块启用 IP 直连")
			return
		}
		connection.Close()
		entry, err := m.Create(ip, 21118, 0)
		if err != nil {
			fail(502, err.Error())
			return
		}
		json.NewEncoder(w).Encode(map[string]string{"url": "rustdesk://connection/new/" + net.JoinHostPort("127.0.0.1", strconv.Itoa(entry.LocalPort))})
		return
	}
	if input.Kind != "application" {
		fail(400, "请选择应用或远程桌面")
		return
	}
	request, _ = http.NewRequestWithContext(r.Context(), "GET", target.String()+"/api/applications", nil)
	request.Header.Set("Cookie", r.Header.Get("Cookie"))
	response, err = client.Do(request)
	if err != nil {
		fail(502, "无法读取目标应用")
		return
	}
	var listing struct {
		Applications []struct {
			ID     string `json:"id"`
			Mode   string `json:"mode"`
			Scheme string `json:"scheme"`
			Port   int    `json:"port"`
			Path   string `json:"path"`
		} `json:"applications"`
	}
	err = json.NewDecoder(io.LimitReader(response.Body, 4<<20)).Decode(&listing)
	response.Body.Close()
	if err != nil || response.StatusCode != 200 {
		fail(502, "无法读取目标应用")
		return
	}
	for _, app := range listing.Applications {
		if app.ID != input.ID || app.Mode != "host" {
			continue
		}
		endpoint := *target
		endpoint.Scheme = "ws"
		endpoint.Path = "/api/applications/" + url.PathEscape(app.ID) + "/tunnel"
		socketClient := *client
		socketClient.Timeout = 0
		headers := http.Header{"Cookie": {r.Header.Get("Cookie")}, "Origin": {target.String()}}
		dial := func(ctx context.Context) (net.Conn, error) {
			connection, _, err := websocket.Dial(ctx, endpoint.String(), &websocket.DialOptions{HTTPClient: &socketClient, HTTPHeader: headers})
			if err != nil {
				return nil, err
			}
			connection.SetReadLimit(128 * 1024)
			return websocket.NetConn(m.ctx, connection, websocket.MessageBinary), nil
		}
		probe, err := dial(r.Context())
		if err != nil {
			fail(502, "无法连接目标应用，请确认该服务正在运行并监听 127.0.0.1 或全部网卡")
			return
		}
		probe.Close()
		tunnel, err := m.allocate(ip, app.Port, 0)
		if err != nil {
			fail(502, err.Error())
			return
		}
		m.mu.Lock()
		tunnel.dial = dial
		tunnel.Kind = "application"
		tunnel.DeviceID = device
		tunnel.URL = fmt.Sprintf("%s://app-%s-%s.localhost:%d%s", app.Scheme, device, app.ID, tunnel.LocalPort, app.Path)
		entry := tunnel.Entry
		m.mu.Unlock()
		go m.accept(tunnel)
		json.NewEncoder(w).Encode(map[string]string{"url": entry.URL})
		return
	}
	fail(404, "应用入口已移除或使用自定义网址，请刷新应用列表")
}
