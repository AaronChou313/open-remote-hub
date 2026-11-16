package forward

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"net"
	"sort"
	"sync"
	"sync/atomic"
	"time"
)

type Dialer interface {
	Dial(context.Context, string, string) (net.Conn, error)
}
type Entry struct {
	ID          string    `json:"id"`
	PeerIP      string    `json:"peer_ip"`
	RemotePort  int       `json:"remote_port"`
	LocalPort   int       `json:"local_port"`
	Created     time.Time `json:"created"`
	Connections int       `json:"connections"`
	Kind        string    `json:"kind"`
	URL         string    `json:"url,omitempty"`
	DeviceID    string    `json:"device_id,omitempty"`
	GatewayPort int       `json:"gateway_port,omitempty"`
	BytesIn     int64     `json:"bytes_in"`
	BytesOut    int64     `json:"bytes_out"`
	LastActive  time.Time `json:"last_activity"`
	LastError   string    `json:"last_error,omitempty"`
}

// Event is a bounded, in-memory connection history for on-device diagnosis.
// It never contains credentials and is only served on the loopback API.
type Event struct {
	Time    time.Time `json:"time"`
	Kind    string    `json:"kind"`
	Tunnel  string    `json:"tunnel,omitempty"`
	Peer    string    `json:"peer,omitempty"`
	Message string    `json:"message"`
}
type tunnel struct {
	Entry
	listener   net.Listener
	active     map[net.Conn]struct{}
	last       time.Time
	lastActive atomic.Int64
	bytesIn    atomic.Int64
	bytesOut   atomic.Int64
	lastErr    string
	cleanup    func()
	closed     bool
	dial       func(context.Context) (net.Conn, error)
}
type Manager struct {
	Frontend        string
	FrontendGateway string
	mu              sync.Mutex
	dialer          Dialer
	tunnels         map[string]*tunnel
	events          []Event
	eventMu         sync.Mutex
	ctx             context.Context
	cancel          context.CancelFunc
}

const eventLimit = 200

func New(d Dialer) *Manager {
	ctx, cancel := context.WithCancel(context.Background())
	m := &Manager{dialer: d, tunnels: map[string]*tunnel{}, ctx: ctx, cancel: cancel}
	go m.expire()
	return m
}

func (m *Manager) record(kind, tunnelID, peer, message string) {
	m.eventMu.Lock()
	m.events = append(m.events, Event{Time: time.Now(), Kind: kind, Tunnel: tunnelID, Peer: peer, Message: message})
	if len(m.events) > eventLimit {
		m.events = append([]Event{}, m.events[len(m.events)-eventLimit:]...)
	}
	m.eventMu.Unlock()
}

func (m *Manager) Events() []Event {
	m.eventMu.Lock()
	defer m.eventMu.Unlock()
	return append([]Event{}, m.events...)
}
func (m *Manager) allocate(ip string, remote, local int) (*tunnel, error) {
	if net.ParseIP(ip) == nil || remote < 1 || remote > 65535 || local < 0 || local > 65535 {
		return nil, fmt.Errorf("IP 或端口无效")
	}
	listener, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", local))
	if err != nil {
		return nil, fmt.Errorf("本地端口不可用: %w", err)
	}
	var id [12]byte
	rand.Read(id[:])
	t := &tunnel{Entry: Entry{ID: hex.EncodeToString(id[:]), PeerIP: ip, RemotePort: remote, LocalPort: listener.Addr().(*net.TCPAddr).Port, Created: time.Now(), Kind: "tcp"}, listener: listener, last: time.Now(), active: map[net.Conn]struct{}{}}
	t.lastActive.Store(time.Now().UnixNano())
	m.mu.Lock()
	if m.ctx.Err() != nil {
		m.mu.Unlock()
		listener.Close()
		return nil, fmt.Errorf("转发管理器已停止")
	}
	m.tunnels[t.ID] = t
	m.mu.Unlock()
	return t, nil
}
func (m *Manager) Create(ip string, remote, local int) (Entry, error) {
	tunnel, err := m.allocate(ip, remote, local)
	if err != nil {
		return Entry{}, err
	}
	entry := tunnel.Entry
	m.record("forward", entry.ID, entry.PeerIP, fmt.Sprintf("创建转发 127.0.0.1:%d → %s:%d", entry.LocalPort, entry.PeerIP, entry.RemotePort))
	go m.accept(tunnel)
	return entry, nil
}

func (m *Manager) accept(t *tunnel) {
	for {
		local, err := t.listener.Accept()
		if err != nil {
			return
		}
		m.mu.Lock()
		if t.closed {
			m.mu.Unlock()
			local.Close()
			return
		}
		t.active[local] = struct{}{}
		t.Connections++
		t.last = time.Now()
		m.mu.Unlock()
		go m.pipe(t, local)
	}
}
func (m *Manager) pipe(t *tunnel, local net.Conn) {
	started := time.Now()
	defer func() {
		local.Close()
		m.mu.Lock()
		delete(t.active, local)
		t.Connections--
		t.last = time.Now()
		m.mu.Unlock()
		m.record("connection", t.ID, t.PeerIP, fmt.Sprintf("连接结束，持续 %s，下行 %d B，上行 %d B", time.Since(started).Round(time.Second), t.bytesIn.Load(), t.bytesOut.Load()))
	}()
	m.record("connection", t.ID, t.PeerIP, fmt.Sprintf("连接开始，本地端口 %d", t.LocalPort))
	ctx, cancel := context.WithTimeout(m.ctx, 12*time.Second)
	defer cancel()
	dial := t.dial
	if dial == nil {
		dial = func(ctx context.Context) (net.Conn, error) {
			return m.dialer.Dial(ctx, "tcp", net.JoinHostPort(t.PeerIP, fmt.Sprint(t.RemotePort)))
		}
	}
	remote, err := dial(ctx)
	if err != nil {
		m.mu.Lock()
		t.lastErr = fmt.Sprintf("连接 %s:%d 失败: %v", t.PeerIP, t.RemotePort, err)
		m.mu.Unlock()
		m.record("error", t.ID, t.PeerIP, fmt.Sprintf("连接 %s:%d 失败: %v", t.PeerIP, t.RemotePort, err))
		return
	}
	defer remote.Close()
	m.mu.Lock()
	if t.closed {
		m.mu.Unlock()
		return
	}
	t.active[remote] = struct{}{}
	m.mu.Unlock()
	defer func() { m.mu.Lock(); delete(t.active, remote); m.mu.Unlock() }()
	done := make(chan struct{}, 2)
	copySide := func(dst, src net.Conn, counter *atomic.Int64) {
		buffer := make([]byte, 32*1024)
		for {
			src.SetReadDeadline(time.Now().Add(10 * time.Minute))
			n, e := src.Read(buffer)
			if n > 0 {
				counter.Add(int64(n))
				t.lastActive.Store(time.Now().UnixNano())
				dst.SetWriteDeadline(time.Now().Add(30 * time.Second))
				if _, w := dst.Write(buffer[:n]); w != nil {
					m.record("error", t.ID, t.PeerIP, fmt.Sprintf("写往目标失败: %v", w))
					break
				}
			}
			if e != nil {
				if e != io.EOF && !isClosed(e) {
					m.record("error", t.ID, t.PeerIP, fmt.Sprintf("读取中断: %v", e))
				}
				break
			}
		}
		if half, ok := dst.(interface{ CloseWrite() error }); ok {
			half.CloseWrite()
		}
		done <- struct{}{}
	}
	// bytesIn counts data received from the peer, bytesOut data sent to it.
	go copySide(local, remote, &t.bytesIn)
	go copySide(remote, local, &t.bytesOut)
	<-done
	if t.dial != nil {
		local.Close()
		remote.Close()
	}
	<-done
}

func isClosed(err error) bool {
	return errors.Is(err, net.ErrClosed) || errors.Is(err, io.ErrClosedPipe) || errors.Is(err, context.Canceled)
}

func (m *Manager) List() []Entry {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := []Entry{}
	for _, t := range m.tunnels {
		entry := t.Entry
		entry.BytesIn = t.bytesIn.Load()
		entry.BytesOut = t.bytesOut.Load()
		entry.LastActive = time.Unix(0, t.lastActive.Load())
		entry.LastError = t.lastErr
		out = append(out, entry)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Created.Before(out[j].Created) })
	return out
}
func (m *Manager) Delete(id string) error {
	m.mu.Lock()
	tunnel, ok := m.tunnels[id]
	if !ok {
		m.mu.Unlock()
		return fmt.Errorf("转发已关闭")
	}
	tunnel.closed = true
	delete(m.tunnels, id)
	connections := make([]net.Conn, 0, len(tunnel.active))
	for connection := range tunnel.active {
		connections = append(connections, connection)
	}
	cleanup := tunnel.cleanup
	m.mu.Unlock()
	m.record("forward", id, tunnel.PeerIP, fmt.Sprintf("关闭转发 127.0.0.1:%d", tunnel.LocalPort))
	tunnel.listener.Close()
	for _, connection := range connections {
		connection.Close()
	}
	if cleanup != nil {
		cleanup()
	}
	return nil
}

func (m *Manager) expire() {
	ticker := time.NewTicker(time.Minute)
	defer ticker.Stop()
	for {
		select {
		case <-m.ctx.Done():
			return
		case <-ticker.C:
			for _, entry := range m.List() {
				m.mu.Lock()
				t := m.tunnels[entry.ID]
				expired := t != nil && t.Connections == 0 && time.Since(t.last) > 10*time.Minute
				m.mu.Unlock()
				if expired {
					m.Delete(entry.ID)
				}
			}
		}
	}
}
func (m *Manager) Close() {
	m.cancel()
	m.CloseAll()
}

func (m *Manager) CloseAll() {
	for _, t := range m.List() {
		m.Delete(t.ID)
	}
}
