package forward

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"
)

var devicePattern = regexp.MustCompile(`^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$`)

type consoleConn struct {
	connection net.Conn
	hijacked   bool
}
type connectionKey struct{}

// CreateConsole provides a distinct browser origin per ORH device. Requests
// still require the remote ORH login. The controller forwards HTTP and WebSocket
// through the encrypted mesh, with no public listener or Cloud data relay.
func (m *Manager) CreateConsole(ctx context.Context, ip, expectedDevice string) (Entry, error) {
	target := &url.URL{Scheme: "http", Host: net.JoinHostPort(ip, "8765")}
	transport := &http.Transport{DialContext: m.dialer.Dial, ResponseHeaderTimeout: 12 * time.Second, IdleConnTimeout: 60 * time.Second}
	client := &http.Client{Transport: transport, Timeout: 12 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	request, err := http.NewRequestWithContext(ctx, "GET", target.String()+"/.well-known/openremotehub", nil)
	if err != nil {
		return Entry{}, err
	}
	response, err := client.Do(request)
	if err != nil {
		transport.CloseIdleConnections()
		return Entry{}, fmt.Errorf("目标设备未提供 ORH 控制台（可能是旧组网节点或 ORH 未运行）")
	}
	var identity struct {
		Service    string `json:"service"`
		InstanceID string `json:"instance_id"`
	}
	err = json.NewDecoder(io.LimitReader(response.Body, 16384)).Decode(&identity)
	response.Body.Close()
	if err != nil || response.StatusCode != 200 || identity.Service != "openremotehub" || !devicePattern.MatchString(identity.InstanceID) || expectedDevice != "" && expectedDevice != identity.InstanceID {
		transport.CloseIdleConnections()
		return Entry{}, fmt.Errorf("目标控制台身份不匹配（可能是旧组网节点；请确认目标设备只保留 ORN 节点且 ORH 已绑定）")
	}
	// Reuse an existing browser origin for this device while this process lives.
	m.mu.Lock()
	for _, tunnel := range m.tunnels {
		if tunnel.Kind == "console" && tunnel.DeviceID == identity.InstanceID && tunnel.PeerIP == ip {
			entry := tunnel.Entry
			m.mu.Unlock()
			transport.CloseIdleConnections()
			return entry, nil
		}
	}
	m.mu.Unlock()
	tunnel, err := m.allocate(ip, 8765, 0)
	if err != nil {
		transport.CloseIdleConnections()
		return Entry{}, err
	}
	origin := &url.URL{Scheme: "http", Host: "orh-" + identity.InstanceID + ".localhost:" + strconv.Itoa(tunnel.LocalPort)}
	gatewayListener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		m.Delete(tunnel.ID)
		transport.CloseIdleConnections()
		return Entry{}, err
	}
	gatewayPort := gatewayListener.Addr().(*net.TCPAddr).Port
	gatewayOrigin := &url.URL{Scheme: "http", Host: origin.Hostname() + ":" + strconv.Itoa(gatewayPort)}
	gatewayTarget := &url.URL{Scheme: "http", Host: net.JoinHostPort(ip, "8767")}
	mainTarget, mainOrigin := target, origin
	makeServer := func(target, origin *url.URL) *http.Server {
		proxy := &httputil.ReverseProxy{
			Transport: transport,
			Rewrite: func(request *httputil.ProxyRequest) {
				request.SetURL(target)
				request.Out.Host = target.Host
				if request.In.Header.Get("Origin") != "" {
					request.Out.Header.Set("Origin", target.String())
				}
				request.Out.Header.Del("Forwarded")
				request.Out.Header.Set("Accept-Encoding", "identity")
			},
			ModifyResponse: func(response *http.Response) error {
				response.Header.Set("Content-Security-Policy", strings.NewReplacer(mainTarget.String(), mainOrigin.String(), gatewayTarget.String(), gatewayOrigin.String()).Replace(response.Header.Get("Content-Security-Policy")))
				if response.Request.URL.Path == "/api/dsh/status" && response.StatusCode == 200 {
					var value map[string]any
					err := json.NewDecoder(io.LimitReader(response.Body, 65536)).Decode(&value)
					response.Body.Close()
					if err != nil {
						return err
					}
					value["gateway_port"] = gatewayPort
					data, err := json.Marshal(value)
					if err != nil {
						return err
					}
					response.Body = io.NopCloser(bytes.NewReader(data))
					response.ContentLength = int64(len(data))
					response.Header.Set("Content-Length", strconv.Itoa(len(data)))
				}
				location := response.Header.Get("Location")
				if location == "" {
					return nil
				}
				redirect, err := url.Parse(location)
				if err != nil {
					return err
				}
				if redirect.Host == mainTarget.Host {
					redirect.Host = mainOrigin.Host
					redirect.Scheme = mainOrigin.Scheme
				}
				if redirect.Host == gatewayTarget.Host {
					redirect.Host = gatewayOrigin.Host
					redirect.Scheme = gatewayOrigin.Scheme
				}
				fragment, err := url.ParseQuery(redirect.Fragment)
				if err == nil && fragment.Has("authorize") {
					var intent map[string]any
					if json.Unmarshal([]byte(fragment.Get("authorize")), &intent) == nil && intent["device"] == identity.InstanceID {
						intent["address"] = mainOrigin.String()
						data, err := json.Marshal(intent)
						if err != nil {
							return err
						}
						fragment.Set("authorize", string(data))
						encoded := fragment.Encode()
						redirect.Fragment, _ = url.PathUnescape(encoded)
						redirect.RawFragment = encoded
					}
				}
				response.Header.Set("Location", redirect.String())
				return nil
			},
			ErrorHandler: func(w http.ResponseWriter, r *http.Request, err error) {
				http.Error(w, "控制台连接中断，请返回 ORN 重新连接", http.StatusBadGateway)
			},
		}
		server := &http.Server{ReadHeaderTimeout: 5 * time.Second, IdleTimeout: 60 * time.Second}
		server.ConnContext = func(ctx context.Context, connection net.Conn) context.Context {
			return context.WithValue(ctx, connectionKey{}, &consoleConn{connection: connection})
		}
		server.ConnState = func(connection net.Conn, status http.ConnState) {
			m.mu.Lock()
			defer m.mu.Unlock()
			switch status {
			case http.StateNew:
				if tunnel.closed {
					connection.Close()
					return
				}
				tunnel.active[connection] = struct{}{}
				tunnel.Connections++
				tunnel.last = time.Now()
			case http.StateClosed:
				if _, ok := tunnel.active[connection]; ok {
					delete(tunnel.active, connection)
					tunnel.Connections--
				}
				tunnel.last = time.Now()
			}
		}
		server.Handler = http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.Host != origin.Host || r.Header.Get("Origin") != "" && r.Header.Get("Origin") != origin.String() {
				http.Error(w, "控制台请求来源无效", http.StatusForbidden)
				return
			}
			link := r.Context().Value(connectionKey{}).(*consoleConn)
			// ReverseProxy serves a hijacked WebSocket until its bidirectional relay ends.
			websocket := strings.EqualFold(r.Header.Get("Upgrade"), "websocket")
			if websocket {
				defer func() { link.connection.Close(); server.ConnState(link.connection, http.StateClosed) }()
			}
			proxy.ServeHTTP(w, r)
		})
		return server
	}
	server := makeServer(mainTarget, mainOrigin)
	gatewayServer := makeServer(gatewayTarget, gatewayOrigin)
	m.mu.Lock()
	tunnel.Kind = "console"
	tunnel.DeviceID = identity.InstanceID
	tunnel.URL = origin.String()
	tunnel.GatewayPort = gatewayPort
	tunnel.cleanup = func() { server.Close(); gatewayServer.Close(); transport.CloseIdleConnections() }
	entry := tunnel.Entry
	m.mu.Unlock()
	go server.Serve(tunnel.listener)
	go gatewayServer.Serve(gatewayListener)
	return entry, nil
}
