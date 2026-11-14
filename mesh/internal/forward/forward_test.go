package forward

import (
	"context"
	"fmt"
	"io"
	"net"
	"testing"
	"time"
)

type testDialer struct{}

func (testDialer) Dial(ctx context.Context, network, address string) (net.Conn, error) {
	return (&net.Dialer{}).DialContext(ctx, network, address)
}
func TestForwardRoundTripAndClose(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	go func() {
		for {
			conn, err := listener.Accept()
			if err != nil {
				return
			}
			go func() { defer conn.Close(); io.Copy(conn, conn) }()
		}
	}()
	manager := New(testDialer{})
	defer manager.Close()
	entry, err := manager.Create("127.0.0.1", listener.Addr().(*net.TCPAddr).Port, 0)
	if err != nil {
		t.Fatal(err)
	}
	connection, err := net.Dial("tcp", net.JoinHostPort("127.0.0.1", fmt.Sprint(entry.LocalPort)))
	if err != nil {
		t.Fatal(err)
	}
	defer connection.Close()
	connection.SetDeadline(time.Now().Add(3 * time.Second))
	expected := []byte("ORH真实双向转发")
	if _, err = connection.Write(expected); err != nil {
		t.Fatal(err)
	}
	actual := make([]byte, len(expected))
	if _, err = io.ReadFull(connection, actual); err != nil {
		t.Fatal(err)
	}
	if string(actual) != string(expected) {
		t.Fatal("forward corrupted bytes")
	}
	if err = manager.Delete(entry.ID); err != nil {
		t.Fatal(err)
	}
	if len(manager.List()) != 0 {
		t.Fatal("forward retained after delete")
	}
	if _, err = connection.Read(make([]byte, 1)); err == nil {
		t.Fatal("active connection survived deletion")
	}
}

func TestForwardStatsAndEvents(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	go func() {
		for {
			conn, err := listener.Accept()
			if err != nil {
				return
			}
			go func() { defer conn.Close(); io.Copy(conn, conn) }()
		}
	}()
	manager := New(testDialer{})
	defer manager.Close()
	entry, err := manager.Create("127.0.0.1", listener.Addr().(*net.TCPAddr).Port, 0)
	if err != nil {
		t.Fatal(err)
	}
	connection, err := net.Dial("tcp", net.JoinHostPort("127.0.0.1", fmt.Sprint(entry.LocalPort)))
	if err != nil {
		t.Fatal(err)
	}
	payload := []byte("ORH诊断字节计数")
	if _, err = connection.Write(payload); err != nil {
		t.Fatal(err)
	}
	actual := make([]byte, len(payload))
	connection.SetDeadline(time.Now().Add(3 * time.Second))
	if _, err = io.ReadFull(connection, actual); err != nil {
		t.Fatal(err)
	}
	connection.Close()
	deadline := time.Now().Add(3 * time.Second)
	for {
		list := manager.List()
		if len(list) == 1 && list[0].BytesIn == int64(len(payload)) && list[0].BytesOut == int64(len(payload)) && list[0].Connections == 0 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("byte counters not recorded: %+v", list)
		}
		time.Sleep(20 * time.Millisecond)
	}
	events := manager.Events()
	if len(events) < 3 || events[0].Kind != "forward" {
		t.Fatalf("unexpected event history: %+v", events)
	}
	for _, event := range events {
		if event.Kind == "error" {
			t.Fatalf("healthy forward recorded an error: %+v", event)
		}
	}
}

func TestForwardDialFailureIsRecorded(t *testing.T) {
	manager := New(dialFailure{})
	defer manager.Close()
	entry, err := manager.Create("127.0.0.1", 9, 0)
	if err != nil {
		t.Fatal(err)
	}
	connection, err := net.Dial("tcp", net.JoinHostPort("127.0.0.1", fmt.Sprint(entry.LocalPort)))
	if err != nil {
		t.Fatal(err)
	}
	defer connection.Close()
	deadline := time.Now().Add(3 * time.Second)
	for {
		list := manager.List()
		if len(list) == 1 && list[0].LastError != "" {
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("dial failure was not recorded: %+v", list)
		}
		time.Sleep(20 * time.Millisecond)
	}
	recorded := false
	for _, event := range manager.Events() {
		if event.Kind == "error" {
			recorded = true
		}
	}
	if !recorded {
		t.Fatal("dial failure event was not recorded")
	}
}

type dialFailure struct{}

func (dialFailure) Dial(context.Context, string, string) (net.Conn, error) {
	return nil, fmt.Errorf("目标不可达")
}
func TestInvalidPortAndStoppedManager(t *testing.T) {
	manager := New(testDialer{})
	manager.Close()
	for _, port := range []int{-1, 0, 65536} {
		if _, err := manager.Create("127.0.0.1", port, 0); err == nil {
			t.Fatal("invalid port accepted")
		}
	}
	if _, err := manager.Create("127.0.0.1", 80, 0); err == nil {
		t.Fatal("stopped manager accepted a forward")
	}
}
