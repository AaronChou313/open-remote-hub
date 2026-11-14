package mobile

import (
	"tailscale.com/net/netmon"
	"testing"
)

func TestAndroidNetworkInventory(t *testing.T) {
	if err := UpdateNetwork(`{"interfaces":[{"name":"wlan0","mtu":1500,"addresses":["192.168.1.20/24","2001:db8::20/64"]}],"default_interface":"wlan0"}`); err != nil {
		t.Fatal(err)
	}
	list, err := netmon.GetInterfaceList()
	if err != nil || len(list) != 1 || list[0].Name != "wlan0" || !list[0].IsUp() {
		t.Fatal("network inventory was lost")
	}
	addresses, err := list[0].Addrs()
	if err != nil || len(addresses) != 2 || addresses[0].String() != "192.168.1.20/24" {
		t.Fatal("network prefixes were lost")
	}
	if err = UpdateNetwork(`{"interfaces":[{"name":"cellular","addresses":["invalid"]}]}`); err == nil {
		t.Fatal("invalid prefix accepted")
	}
	list, _ = netmon.GetInterfaceList()
	if list[0].Name != "wlan0" {
		t.Fatal("failed update replaced the last valid inventory")
	}
	if err = UpdateNetwork(`{"interfaces":[]}`); err != nil {
		t.Fatal(err)
	}
	list, _ = netmon.GetInterfaceList()
	if len(list) != 0 {
		t.Fatal("disconnected state kept stale interfaces")
	}
}
