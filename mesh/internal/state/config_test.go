package state

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

func TestPrivatePersistentConfigAndToken(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.json")
	cfg, first, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	cfg.Hostname = "test-device"
	if err = Save(path, cfg); err != nil {
		t.Fatal(err)
	}
	loaded, second, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if first == "" || first != second || loaded.Hostname != "test-device" {
		t.Fatal("identity was not retained")
	}
	if runtime.GOOS != "windows" {
		info, err := os.Stat(filepath.Join(filepath.Dir(path), "api.token"))
		if err != nil || info.Mode().Perm() != 0600 {
			t.Fatal("token permissions")
		}
	}
	cfg.APIAddr = "0.0.0.0:4789"
	Save(path, cfg)
	if _, _, err = Load(path); err == nil {
		t.Fatal("public LocalAPI listener accepted")
	}
}

func TestPublishConfigurationReplacesDefaults(t *testing.T) {
	for _, test := range []struct {
		name, body string
		expected   int
	}{
		{"empty", `{"publish":{}}`, 0},
		{"custom", `{"publish":{"19001":"127.0.0.1:19001"}}`, 1},
		{"legacy", `{}`, 1},
	} {
		t.Run(test.name, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "config.json")
			if err := os.WriteFile(path, []byte(test.body), 0600); err != nil {
				t.Fatal(err)
			}
			cfg, _, err := Load(path)
			if err != nil || len(cfg.Publish) != test.expected {
				t.Fatal("publication map was merged with defaults", err, cfg.Publish)
			}
			if test.name == "custom" && cfg.Publish[21118] != "" {
				t.Fatal("unexpected default port")
			}
		})
	}
}
