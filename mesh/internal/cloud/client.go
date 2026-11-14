package cloud

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"time"
)

func Base(value string) (string, error) {
	u, err := url.Parse(value)
	if err != nil || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || u.Path != "" && u.Path != "/" {
		return "", fmt.Errorf("Cloud 地址无效")
	}
	if u.Scheme != "https" && !(u.Scheme == "http" && (u.Hostname() == "127.0.0.1" || u.Hostname() == "localhost")) {
		return "", fmt.Errorf("公网 Cloud 地址需要 HTTPS")
	}
	return u.Scheme + "://" + u.Host, nil
}

type HTTPError struct {
	Status  int
	Message string
}

func (e *HTTPError) Error() string { return e.Message }

func Call(ctx context.Context, base, path, token string, body, result any) error {
	data, err := json.Marshal(body)
	if err != nil {
		return err
	}
	method := "POST"
	if body == nil {
		method = "GET"
	}
	request, err := http.NewRequestWithContext(ctx, method, base+path, bytes.NewReader(data))
	if err != nil {
		return err
	}
	request.Header.Set("Content-Type", "application/json")
	if token != "" {
		request.Header.Set("Authorization", "Bearer "+token)
	}
	client := &http.Client{Timeout: 12 * time.Second}
	response, err := client.Do(request)
	if err != nil {
		return fmt.Errorf("暂时无法连接 Cloud")
	}
	defer response.Body.Close()
	limited := io.LimitReader(response.Body, 65536)
	if response.StatusCode >= 400 {
		var message struct {
			Detail string `json:"detail"`
		}
		json.NewDecoder(limited).Decode(&message)
		if message.Detail == "" {
			message.Detail = fmt.Sprintf("Cloud 返回 HTTP %d", response.StatusCode)
		}
		return &HTTPError{Status: response.StatusCode, Message: message.Detail}
	}
	return json.NewDecoder(limited).Decode(result)
}
