// Package mesh owns the userspace node. It does not launch platform programs.
package mesh

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/netip"
	"sort"
	"sync"
	"time"

	"tailscale.com/envknob"
	"tailscale.com/ipn"
	"tailscale.com/ipn/ipnstate"
	"tailscale.com/net/netcheck"
	"tailscale.com/net/netns"
	"tailscale.com/tailcfg"
	"tailscale.com/tsnet"
)

type Config struct {
	Hostname, ControlURL, StateDir, AuthKey string
	Debug                                   bool
	Logf                                    func(string, ...any)
}
type Peer struct {
	ID         string   `json:"id"`
	NodeKey    string   `json:"node_key,omitempty"`
	Hostname   string   `json:"hostname"`
	DNSName    string   `json:"dns_name"`
	IPs        []string `json:"ips"`
	OS         string   `json:"os"`
	Online     bool     `json:"online"`
	Path       string   `json:"path"`
	DirectAddr string   `json:"direct_addr"`
	Relay      string   `json:"relay"`
	RX         int64    `json:"rx"`
	TX         int64    `json:"tx"`
}
type Status struct {
	BackendState string   `json:"backend_state"`
	Version      string   `json:"version"`
	Device       Peer     `json:"device"`
	Peers        []Peer   `json:"peers"`
	Health       []string `json:"health"`
	AuthURL      string   `json:"auth_url,omitempty"`
	Network      string   `json:"network"`
	MagicDNS     bool     `json:"magic_dns"`
}
type Node struct {
	server    *tsnet.Server
	mu        sync.Mutex
	published []net.Listener
	ports     map[int]bool
}

func New(cfg Config) *Node {
	// A userspace node creates no system routes. Respect the host route table,
	// including a local proxy that owns fake DNS addresses.
	netns.SetEnabled(false)
	envknob.SetNoLogsNoSupport()
	logf := cfg.Logf
	if logf == nil {
		logf = func(string, ...any) {}
	}
	s := &tsnet.Server{Hostname: cfg.Hostname, ControlURL: cfg.ControlURL, Dir: cfg.StateDir, AuthKey: cfg.AuthKey, UserLogf: logf}
	if cfg.Debug {
		s.Logf = logf
	} else {
		s.Logf = func(string, ...any) {}
	}
	return &Node{server: s, ports: map[int]bool{}}
}
func (n *Node) Start() error { return n.server.Start() }
func (n *Node) Wait(ctx context.Context) error {
	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()
	for {
		status, err := n.Status(ctx)
		if err == nil && status.BackendState == "Running" {
			return nil
		}
		select {
		case <-ctx.Done():
			return fmt.Errorf("等待组网就绪: %w", ctx.Err())
		case <-ticker.C:
		}
	}
}
func peer(p *ipnstate.PeerStatus) Peer {
	out := Peer{IPs: []string{}, Path: "idle"}
	if p == nil {
		return out
	}
	out.NodeKey = p.PublicKey.String()
	out.ID = string(p.ID)
	out.Hostname = p.HostName
	out.DNSName = p.DNSName
	out.OS = p.OS
	out.Online = p.Online
	out.DirectAddr = p.CurAddr
	out.Relay = p.Relay
	out.RX = p.RxBytes
	out.TX = p.TxBytes
	if p.CurAddr != "" {
		out.Path = "direct"
	} else if p.Active && p.Relay != "" {
		out.Path = "relay"
	}
	for _, ip := range p.TailscaleIPs {
		out.IPs = append(out.IPs, ip.String())
	}
	return out
}
func (n *Node) Status(ctx context.Context) (Status, error) {
	lc, err := n.server.LocalClient()
	if err != nil {
		return Status{}, err
	}
	raw, err := lc.Status(ctx)
	if err != nil {
		return Status{}, err
	}
	out := Status{BackendState: raw.BackendState, Version: raw.Version, Device: peer(raw.Self), Peers: []Peer{}, Health: raw.Health, AuthURL: raw.AuthURL}
	if raw.CurrentTailnet != nil {
		out.Network = raw.CurrentTailnet.MagicDNSSuffix
		out.MagicDNS = raw.CurrentTailnet.MagicDNSEnabled
	}
	for _, p := range raw.Peer {
		out.Peers = append(out.Peers, peer(p))
	}
	sort.Slice(out.Peers, func(i, j int) bool { return out.Peers[i].Hostname < out.Peers[j].Hostname })
	return out, nil
}
func (n *Node) StatusJSON() (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
	defer cancel()
	s, e := n.Status(ctx)
	if e != nil {
		return "", e
	}
	b, e := json.Marshal(s)
	return string(b), e
}
func (n *Node) Dial(ctx context.Context, network, address string) (net.Conn, error) {
	if err := n.Wait(ctx); err != nil {
		return nil, err
	}
	return n.server.Dial(ctx, network, address)
}
func (n *Node) PeerIP(ctx context.Context, value string) (netip.Addr, error) {
	ip, err := netip.ParseAddr(value)
	if err != nil {
		return ip, fmt.Errorf("请选择设备的组网 IP")
	}
	status, err := n.Status(ctx)
	if err != nil {
		return ip, err
	}
	for _, p := range status.Peers {
		for _, candidate := range p.IPs {
			if candidate == ip.String() {
				return ip, nil
			}
		}
	}
	return ip, fmt.Errorf("目标不在当前账号的设备列表中")
}
func (n *Node) Ping(ctx context.Context, value string) (*ipnstate.PingResult, error) {
	ip, err := n.PeerIP(ctx, value)
	if err != nil {
		return nil, err
	}
	lc, err := n.server.LocalClient()
	if err != nil {
		return nil, err
	}
	return lc.Ping(ctx, ip, tailcfg.PingDisco)
}
func (n *Node) SetRunning(ctx context.Context, running bool) error {
	lc, err := n.server.LocalClient()
	if err != nil {
		return err
	}
	_, err = lc.EditPrefs(ctx, &ipn.MaskedPrefs{Prefs: ipn.Prefs{WantRunning: running}, WantRunningSet: true})
	return err
}
func (n *Node) Logout(ctx context.Context) error {
	lc, err := n.server.LocalClient()
	if err != nil {
		return err
	}
	if err = lc.Logout(ctx); err == nil {
		return nil
	}
	// A revoked headscale node may already have lost its control-client key.
	// Remove its local profile even when the server logout cannot complete.
	current, _, profileErr := lc.ProfileStatus(ctx)
	if profileErr != nil {
		return err
	}
	if current.ID != "" {
		return lc.DeleteProfile(ctx, current.ID)
	}
	return lc.SwitchToEmptyProfile(ctx)
}

// Publish exposes only an explicitly configured local service to this node's ACL peers.
func (n *Node) Publish(port int, target string) error {
	host, _, err := net.SplitHostPort(target)
	if err != nil || net.ParseIP(host) == nil || !net.ParseIP(host).IsLoopback() {
		return fmt.Errorf("发布目标必须是 loopback 服务")
	}
	n.mu.Lock()
	defer n.mu.Unlock()
	if n.ports[port] {
		return nil
	}
	listener, err := n.server.Listen("tcp", fmt.Sprintf(":%d", port))
	if err != nil {
		return err
	}
	n.published = append(n.published, listener)
	n.ports[port] = true
	go func() {
		for {
			incoming, err := listener.Accept()
			if err != nil {
				return
			}
			go func() {
				defer incoming.Close()
				outgoing, err := net.DialTimeout("tcp", target, 8*time.Second)
				if err != nil {
					return
				}
				defer outgoing.Close()
				Relay(incoming, outgoing)
			}()
		}
	}()
	return nil
}
func Relay(a, b net.Conn) {
	done := make(chan struct{}, 2)
	transfer := func(dst, src net.Conn) {
		io.Copy(dst, src)
		if tcp, ok := dst.(interface{ CloseWrite() error }); ok {
			tcp.CloseWrite()
		}
		done <- struct{}{}
	}
	go transfer(a, b)
	go transfer(b, a)
	<-done
	// Preserve half-close, but bound a peer that never finishes the other direction.
	timer := time.NewTimer(10 * time.Minute)
	defer timer.Stop()
	select {
	case <-done:
	case <-timer.C:
	}
	a.Close()
	b.Close()
}
func (n *Node) Close() error {
	n.mu.Lock()
	for _, l := range n.published {
		l.Close()
	}
	n.published = nil
	n.mu.Unlock()
	return n.server.Close()
}

func (n *Node) Rebind(ctx context.Context) error {
	n.server.Sys().NetMon.Get().InjectEvent()
	lc, err := n.server.LocalClient()
	if err != nil {
		return err
	}
	return lc.DebugAction(ctx, "rebind")
}
func (n *Node) Netcheck(ctx context.Context) (*netcheck.Report, error) {
	lc, err := n.server.LocalClient()
	if err != nil {
		return nil, err
	}
	regions, err := lc.CurrentDERPMap(ctx)
	if err != nil {
		return nil, err
	}
	client := &netcheck.Client{NetMon: n.server.Sys().NetMon.Get(), Logf: func(string, ...any) {}}
	return client.GetReport(ctx, regions, nil)
}
func (n *Node) Login(ctx context.Context, key string) error {
	lc, err := n.server.LocalClient()
	if err != nil {
		return err
	}
	prefs := ipn.NewPrefs()
	prefs.Hostname = n.server.Hostname
	prefs.ControlURL = n.server.ControlURL
	prefs.WantRunning = true
	if err = lc.Start(ctx, ipn.Options{AuthKey: key, UpdatePrefs: prefs}); err != nil {
		return err
	}
	return lc.StartLoginInteractive(ctx)
}
