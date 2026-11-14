package state

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"tailscale.com/atomicfile"
)

type Cloud struct {
	BaseURL           string  `json:"base_url"`
	DeviceID          string  `json:"device_id"`
	DeviceToken       string  `json:"device_token"`
	UserCode          string  `json:"user_code,omitempty"`
	VerificationURL   string  `json:"verification_url,omitempty"`
	Expires           float64 `json:"expires,omitempty"`
	Bound             bool    `json:"bound"`
	ExternallyManaged bool    `json:"externally_managed,omitempty"`
}
type Config struct {
	ControlURL string         `json:"control_url"`
	Hostname   string         `json:"hostname"`
	StateDir   string         `json:"state_dir"`
	APIAddr    string         `json:"api_addr"`
	Cloud      Cloud          `json:"cloud"`
	Publish    map[int]string `json:"publish"`
}

func DefaultPath() string {
	dir, _ := os.UserConfigDir()
	return filepath.Join(dir, "orn-agent", "config.json")
}
func Load(path string) (Config, string, error) {
	hostname, _ := os.Hostname()
	cfg := Config{ControlURL: "https://hs.openremotehub.top", Hostname: hostname + "-orn", StateDir: filepath.Join(filepath.Dir(path), "state"), APIAddr: "127.0.0.1:4789", Cloud: Cloud{BaseURL: "https://cloud.openremotehub.top"}, Publish: map[int]string{21118: "127.0.0.1:21118"}}
	data, err := os.ReadFile(path)
	if err == nil {
		var saved struct {
			Publish json.RawMessage `json:"publish"`
		}
		err = json.Unmarshal(data, &saved)
		if err == nil {
			// An explicit publication map replaces defaults, including {}.
			if saved.Publish != nil {
				cfg.Publish = nil
			}
			err = json.Unmarshal(data, &cfg)
		}
	} else if os.IsNotExist(err) {
		err = Save(path, cfg)
	}
	if err != nil {
		return cfg, "", err
	}
	host, _, err := net.SplitHostPort(cfg.APIAddr)
	if err != nil || net.ParseIP(host) == nil || !net.ParseIP(host).IsLoopback() {
		return cfg, "", fmt.Errorf("LocalAPI 必须监听 loopback IP")
	}
	if err = os.MkdirAll(cfg.StateDir, 0700); err != nil {
		return cfg, "", err
	}
	tokenPath := filepath.Join(filepath.Dir(path), "api.token")
	token, err := os.ReadFile(tokenPath)
	if os.IsNotExist(err) {
		var secret [32]byte
		if _, err = rand.Read(secret[:]); err != nil {
			return cfg, "", err
		}
		token = []byte(hex.EncodeToString(secret[:]))
		err = privateWrite(tokenPath, token)
	}
	return cfg, string(token), err
}
func privateWrite(path string, data []byte) error {
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	return atomicfile.WriteFile(path, data, 0600)
}
func Save(path string, cfg Config) error {
	data, err := json.MarshalIndent(cfg, "", "  ")
	if err != nil {
		return err
	}
	return privateWrite(path, data)
}
