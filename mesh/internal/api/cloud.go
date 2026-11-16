package api

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"net/http"
	"regexp"
	"runtime"
	"sort"
	"strings"
	"time"

	cloudclient "github.com/AaronChou313/open-remote-hub/mesh/internal/cloud"
	"github.com/AaronChou313/open-remote-hub/mesh/internal/state"
)

func (s *Server) publicCloud() map[string]any {
	s.cloudMu.RLock()
	defer s.cloudMu.RUnlock()
	value := s.Config.Cloud
	result := map[string]any{"bound": value.Bound, "device_id": value.DeviceID, "shared_with_orh": value.ExternallyManaged, "base_url": value.BaseURL, "error": s.cloudError}
	if !value.Bound && value.UserCode != "" && value.Expires > float64(time.Now().Unix()) {
		result["pending"] = map[string]any{"user_code": value.UserCode, "verification_url": value.VerificationURL, "expires": value.Expires}
	}
	return result
}
func (s *Server) cloudStatus(w http.ResponseWriter, r *http.Request) { reply(w, s.publicCloud()) }
func (s *Server) metadata() map[string]any {
	s.cloudMu.RLock()
	cfg := s.Config
	s.cloudMu.RUnlock()
	kind := "mesh"
	if runtime.GOOS == "android" {
		kind = "controller-only"
	}
	return map[string]any{"instance_id": cfg.Cloud.DeviceID, "name": cfg.Hostname, "os": runtime.GOOS, "addresses": []string{}, "port": 4789, "kind": kind}
}
func (s *Server) cloudBind(w http.ResponseWriter, r *http.Request) {
	s.syncMu.Lock()
	defer s.syncMu.Unlock()
	var input struct {
		CloudURL string `json:"cloud_url"`
	}
	if err := body(w, r, &input); err != nil {
		fail(w, 400, err)
		return
	}
	base, err := cloudclient.Base(input.CloudURL)
	if err != nil {
		fail(w, 400, err)
		return
	}
	s.cloudMu.Lock()
	if s.Config.Cloud.Bound {
		s.cloudMu.Unlock()
		fail(w, 409, http.ErrUseLastResponse)
		return
	}
	if s.Config.Cloud.BaseURL == base && s.Config.Cloud.UserCode != "" && s.Config.Cloud.Expires > float64(time.Now().Unix()) {
		s.cloudMu.Unlock()
		reply(w, s.publicCloud())
		return
	}
	if s.Config.Cloud.DeviceID == "" {
		var id [16]byte
		rand.Read(id[:])
		id[6] = (id[6] & 15) | 64
		id[8] = (id[8] & 63) | 128
		value := hex.EncodeToString(id[:])
		s.Config.Cloud.DeviceID = value[:8] + "-" + value[8:12] + "-" + value[12:16] + "-" + value[16:20] + "-" + value[20:]
	}
	s.cloudMu.Unlock()
	var result struct {
		DeviceCode      string `json:"device_code"`
		UserCode        string `json:"user_code"`
		VerificationURL string `json:"verification_url"`
		ExpiresIn       int    `json:"expires_in"`
	}
	if err = cloudclient.Call(r.Context(), base, "/agent/bindings/start", "", s.metadata(), &result); err != nil {
		fail(w, 503, err)
		return
	}
	s.cloudMu.Lock()
	s.Config.Cloud.BaseURL = base
	s.Config.Cloud.DeviceToken = result.DeviceCode
	s.Config.Cloud.UserCode = result.UserCode
	s.Config.Cloud.VerificationURL = result.VerificationURL
	s.Config.Cloud.Expires = float64(time.Now().Unix() + int64(result.ExpiresIn))
	err = state.Save(s.ConfigPath, s.Config)
	s.cloudMu.Unlock()
	if err != nil {
		fail(w, 500, err)
		return
	}
	reply(w, s.publicCloud())
}
func (s *Server) syncCloud(ctx context.Context) error {
	s.cloudMu.RLock()
	cfg := s.Config
	s.cloudMu.RUnlock()
	if cfg.Cloud.DeviceToken == "" {
		return nil
	}
	if !cfg.Cloud.Bound {
		if cfg.Cloud.Expires <= float64(time.Now().Unix()) {
			return fmt.Errorf("绑定码已过期，请重新绑定")
		}
		var result struct {
			Status string `json:"status"`
		}
		if err := cloudclient.Call(ctx, cfg.Cloud.BaseURL, "/agent/bindings/poll", "", map[string]string{"device_code": cfg.Cloud.DeviceToken}, &result); err != nil {
			return err
		}
		if result.Status != "approved" {
			return nil
		}
		s.cloudMu.Lock()
		s.Config.Cloud.Bound = true
		cfg = s.Config
		err := state.Save(s.ConfigPath, s.Config)
		s.cloudMu.Unlock()
		if err != nil {
			return err
		}
	}
	status, err := s.Node.Status(ctx)
	if err != nil {
		return err
	}
	if status.BackendState == "NeedsLogin" || status.BackendState == "NoState" {
		var enrollment struct {
			Key        string `json:"key"`
			ControlURL string `json:"control_url"`
		}
		if err = cloudclient.Call(ctx, cfg.Cloud.BaseURL, "/agent/preauth", cfg.Cloud.DeviceToken, map[string]any{}, &enrollment); err != nil {
			return err
		}
		if enrollment.ControlURL != cfg.ControlURL {
			return fmt.Errorf("组网服务地址与本机配置不一致，请修改 control_url 后重启")
		}
		if err = s.Node.Login(ctx, enrollment.Key); err != nil {
			return err
		}
	}
	var heartbeat map[string]any
	if cfg.Cloud.ExternallyManaged {
		var directory []map[string]any
		err = cloudclient.Call(ctx, cfg.Cloud.BaseURL, "/agent/directory", cfg.Cloud.DeviceToken, nil, &directory)
	} else {
		err = cloudclient.Call(ctx, cfg.Cloud.BaseURL, "/agent/heartbeat", cfg.Cloud.DeviceToken, s.metadata(), &heartbeat)
	}
	if err != nil {
		return err
	}
	if status.BackendState == "Running" && status.Device.NodeKey != "" {
		for port, target := range cfg.Publish {
			if err = s.Node.Publish(port, target); err != nil {
				return err
			}
		}
		ports := []int{}
		for port := range cfg.Publish {
			ports = append(ports, port)
		}
		sort.Ints(ports)
		paths := []string{}
		seen := map[string]bool{}
		for _, peer := range status.Peers {
			if (peer.Path == "direct" || peer.Path == "relay") && !seen[peer.Path] {
				paths = append(paths, peer.Path)
				seen[peer.Path] = true
			}
		}
		return cloudclient.Call(ctx, cfg.Cloud.BaseURL, "/agent/reconcile", cfg.Cloud.DeviceToken, map[string]any{"node_key": status.Device.NodeKey, "services": ports, "paths": paths}, &heartbeat)
	}
	return nil
}
func (s *Server) CloudLoop(ctx context.Context) {
	timer := time.NewTicker(3 * time.Second)
	defer timer.Stop()
	next := time.Time{}
	for {
		select {
		case <-ctx.Done():
			return
		case <-timer.C:
			s.cloudMu.RLock()
			bound := s.Config.Cloud.Bound
			s.cloudMu.RUnlock()
			if bound && time.Now().Before(next) {
				continue
			}
			s.syncMu.Lock()
			err := s.syncCloud(ctx)
			var httpError *cloudclient.HTTPError
			if errors.As(err, &httpError) && httpError.Status == 401 {
				if revokeErr := s.clearBinding(ctx); revokeErr != nil {
					err = revokeErr
				}
			}
			s.syncMu.Unlock()
			s.cloudMu.Lock()
			if err != nil {
				s.cloudError = err.Error()
			} else {
				s.cloudError = ""
			}
			s.cloudMu.Unlock()
			next = time.Now().Add(30 * time.Second)
		}
	}
}

// clearBinding revokes local access after Cloud unbinding. It preserves the
// stable device UUID and allows a fresh bind without restarting the process.
func (s *Server) clearBinding(ctx context.Context) error {
	if err := s.Node.Logout(ctx); err != nil {
		return err
	}
	s.Forwards.CloseAll()
	s.cloudMu.Lock()
	defer s.cloudMu.Unlock()
	s.Config.Cloud = state.Cloud{BaseURL: s.Config.Cloud.BaseURL, DeviceID: s.Config.Cloud.DeviceID}
	return state.Save(s.ConfigPath, s.Config)
}
func (s *Server) unbind(ctx context.Context) error {
	s.cloudMu.RLock()
	cloud := s.Config.Cloud
	s.cloudMu.RUnlock()
	if cloud.Bound {
		var result map[string]any
		err := cloudclient.Call(ctx, cloud.BaseURL, "/agent/unbind", cloud.DeviceToken, map[string]any{}, &result)
		var httpError *cloudclient.HTTPError
		if err != nil && !(errors.As(err, &httpError) && httpError.Status == 401) {
			return err
		}
	}
	return s.clearBinding(ctx)
}
func (s *Server) directory(w http.ResponseWriter, r *http.Request) {
	s.cloudMu.RLock()
	cfg := s.Config.Cloud
	s.cloudMu.RUnlock()
	if !cfg.Bound {
		fail(w, 409, fmt.Errorf("请先将此设备绑定 Cloud 账号"))
		return
	}
	var result []map[string]any
	if err := cloudclient.Call(r.Context(), cfg.BaseURL, "/agent/directory", cfg.DeviceToken, nil, &result); err != nil {
		fail(w, 503, err)
		return
	}
	reply(w, result)
}

// cloudAdopt lets the co-located ORH reuse its existing Cloud device identity.
// A validated device credential is persisted privately, never returned to UI.
func (s *Server) cloudAdopt(w http.ResponseWriter, r *http.Request) {
	s.syncMu.Lock()
	defer s.syncMu.Unlock()
	var input struct {
		BaseURL        string `json:"base_url"`
		DeviceID       string `json:"device_id"`
		DeviceToken    string `json:"device_token"`
		ConsolePort    int    `json:"console_port"`
		GatewayPort    int    `json:"gateway_port"`
		DesktopEnabled *bool  `json:"desktop_enabled,omitempty"`
	}
	if err := body(w, r, &input); err != nil {
		fail(w, 400, err)
		return
	}
	base, err := cloudclient.Base(input.BaseURL)
	if err != nil {
		fail(w, 400, err)
		return
	}
	s.cloudMu.RLock()
	current := s.Config.Cloud
	s.cloudMu.RUnlock()
	if current.Bound {
		if current.BaseURL != base || current.DeviceID != input.DeviceID || current.DeviceToken != input.DeviceToken {
			fail(w, 409, fmt.Errorf("组网已绑定其他设备身份，请先解绑"))
			return
		}
	}
	var devices []struct {
		ID   string `json:"instance_id"`
		Self bool   `json:"self"`
	}
	if !current.Bound {
		if err = cloudclient.Call(r.Context(), base, "/agent/directory", input.DeviceToken, nil, &devices); err != nil {
			fail(w, 403, err)
			return
		}
		found := false
		for _, device := range devices {
			if device.ID == input.DeviceID && device.Self {
				found = true
			}
		}
		if !found {
			fail(w, 403, fmt.Errorf("设备凭据与 ORH 身份不匹配"))
			return
		}
	}
	for _, port := range []int{input.ConsolePort, input.GatewayPort} {
		if port < 0 || port > 65535 {
			fail(w, 400, fmt.Errorf("服务端口无效"))
			return
		}
	}
	s.cloudMu.Lock()
	s.Config.Cloud = state.Cloud{BaseURL: base, DeviceID: input.DeviceID, DeviceToken: input.DeviceToken, Bound: true, ExternallyManaged: true}
	publish := map[int]string{}
	for port, target := range s.Config.Publish {
		publish[port] = target
	}
	if input.ConsolePort > 0 {
		publish[8765] = fmt.Sprintf("127.0.0.1:%d", input.ConsolePort)
	}
	if input.GatewayPort > 0 {
		publish[8767] = fmt.Sprintf("127.0.0.1:%d", input.GatewayPort)
	}
	if input.DesktopEnabled != nil {
		if *input.DesktopEnabled {
			publish[21118] = "127.0.0.1:21118"
		} else {
			delete(publish, 21118)
		}
	}
	s.Config.Publish = publish
	err = state.Save(s.ConfigPath, s.Config)
	s.cloudMu.Unlock()
	if err != nil {
		fail(w, 500, err)
		return
	}
	reply(w, s.publicCloud())
}

type cloudLoginInput struct {
	CloudURL string `json:"cloud_url"`
	Username string `json:"username"`
	Password string `json:"password"`
}

// cloudLogin registers this node with an account session: one login, no code.
func (s *Server) cloudLogin(w http.ResponseWriter, r *http.Request) {
	var input cloudLoginInput
	if err := body(w, r, &input); err != nil {
		fail(w, 400, fmt.Errorf("请输入 Cloud 账号与密码"))
		return
	}
	base, err := cloudclient.Base(input.CloudURL)
	if err != nil {
		fail(w, 400, err)
		return
	}
	if strings.TrimSpace(input.Username) == "" || input.Password == "" {
		fail(w, 400, fmt.Errorf("请输入 Cloud 账号与密码"))
		return
	}
	s.syncMu.Lock()
	defer s.syncMu.Unlock()
	s.cloudMu.RLock()
	bound, deviceID, hostname := s.Config.Cloud.Bound, s.Config.Cloud.DeviceID, s.Config.Hostname
	s.cloudMu.RUnlock()
	var login struct {
		Token string `json:"token"`
		User  struct {
			ID       string `json:"id"`
			Username string `json:"username"`
		} `json:"user"`
	}
	if err = cloudclient.Call(r.Context(), base, "/api/login", "", map[string]string{"username": input.Username, "password": input.Password}, &login); err != nil {
		fail(w, 503, err)
		return
	}
	if login.Token == "" {
		fail(w, 502, fmt.Errorf("Cloud 登录响应无效"))
		return
	}
	if bound {
		s.cloudMu.RLock()
		currentBase := s.Config.Cloud.BaseURL
		s.cloudMu.RUnlock()
		var directory []map[string]any
		if currentBase != base {
			fail(w, 409, fmt.Errorf("请使用已绑定的 Cloud 服务登录"))
			return
		}
		if err = cloudclient.Call(r.Context(), base, "/api/devices", login.Token, nil, &directory); err != nil {
			fail(w, 503, err)
			return
		}
		owned := false
		for _, device := range directory {
			if device["instance_id"] == deviceID {
				owned = true
			}
		}
		if !owned {
			fail(w, 403, fmt.Errorf("请使用此设备所属的账号登录"))
			return
		}
		reply(w, map[string]any{"ok": true, "instance_id": deviceID, "username": login.User.Username, "cloud_url": base, "account_token": login.Token})
		return
	}
	if deviceID == "" {
		var id [16]byte
		rand.Read(id[:])
		id[6] = (id[6] & 15) | 64
		id[8] = (id[8] & 63) | 128
		value := hex.EncodeToString(id[:])
		deviceID = value[:8] + "-" + value[8:12] + "-" + value[12:16] + "-" + value[16:20] + "-" + value[20:]
	}
	metadata := map[string]any{"kind": "mesh", "instance_id": deviceID, "name": hostname, "os": runtime.GOOS, "addresses": []string{}, "port": 4789}
	if runtime.GOOS == "android" {
		metadata["kind"] = "controller-only"
	}
	var enrolled struct {
		DeviceToken string `json:"device_token"`
	}
	if err = cloudclient.Call(r.Context(), base, "/api/devices/enroll", login.Token, metadata, &enrolled); err != nil {
		fail(w, 503, err)
		return
	}
	s.cloudMu.Lock()
	s.Config.Cloud = state.Cloud{BaseURL: base, DeviceID: deviceID, DeviceToken: enrolled.DeviceToken, Bound: true}
	err = state.Save(s.ConfigPath, s.Config)
	s.cloudMu.Unlock()
	if err != nil {
		fail(w, 500, err)
		return
	}
	reply(w, map[string]any{"ok": true, "instance_id": deviceID, "username": login.User.Username, "cloud_url": base, "account_token": login.Token})
}

// cloudTicket shares the existing Go Cloud transport with Android account login.
// The account token is supplied by the Client and remains in request memory.
func (s *Server) cloudTicket(w http.ResponseWriter, r *http.Request) {
	var input struct {
		DeviceID     string `json:"device_id"`
		Address      string `json:"address"`
		AccountToken string `json:"account_token"`
	}
	if err := body(w, r, &input); err != nil {
		fail(w, 400, err)
		return
	}
	valid, _ := regexp.MatchString(`^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$`, input.DeviceID)
	if !valid || input.Address == "" || input.AccountToken == "" {
		fail(w, 400, fmt.Errorf("请选择目标设备并登录 ORH 账号"))
		return
	}
	s.cloudMu.RLock()
	config := s.Config.Cloud
	s.cloudMu.RUnlock()
	if !config.Bound {
		fail(w, 409, fmt.Errorf("请先登录 ORH 账号"))
		return
	}
	var result struct {
		URL string `json:"url"`
	}
	err := cloudclient.Call(r.Context(), config.BaseURL, "/api/devices/"+input.DeviceID+"/ticket", input.AccountToken,
		map[string]string{"address": input.Address, "state": ""}, &result)
	if err != nil {
		status := 503
		var response *cloudclient.HTTPError
		if errors.As(err, &response) {
			status = response.Status
		}
		fail(w, status, err)
		return
	}
	if result.URL == "" {
		fail(w, 502, fmt.Errorf("Cloud 未返回设备授权"))
		return
	}
	reply(w, result)
}
