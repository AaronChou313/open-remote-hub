package mobile

import (
	"encoding/json"
	"net"
	"net/netip"
	"sync"
	"tailscale.com/net/netmon"
)

type networkInterface struct {
	Name      string   `json:"name"`
	MTU       int      `json:"mtu"`
	Addresses []string `json:"addresses"`
}
type networkInfo struct {
	Interfaces       []networkInterface `json:"interfaces"`
	DefaultInterface string             `json:"default_interface"`
	Gateway          string             `json:"gateway"`
}

var networkMu sync.RWMutex
var interfaces []netmon.Interface
var registerNetwork sync.Once

// UpdateNetwork supplies real Android LinkProperties. Modern Android denies
// app UIDs Go's NETLINK_ROUTE interface enumeration, so netmon uses this getter.
func UpdateNetwork(value string) error {
	var info networkInfo
	if err := json.Unmarshal([]byte(value), &info); err != nil {
		return err
	}
	result := []netmon.Interface{}
	for index, item := range info.Interfaces {
		addresses := []net.Addr{}
		for _, value := range item.Addresses {
			prefix, err := netip.ParsePrefix(value)
			if err != nil {
				return err
			}
			addresses = append(addresses, &net.IPNet{IP: prefix.Addr().AsSlice(), Mask: net.CIDRMask(prefix.Bits(), prefix.Addr().BitLen())})
		}
		result = append(result, netmon.Interface{Interface: &net.Interface{Index: index + 1, Name: item.Name, MTU: item.MTU, Flags: net.FlagUp | net.FlagRunning}, AltAddrs: addresses})
	}
	networkMu.Lock()
	interfaces = result
	networkMu.Unlock()
	registerNetwork.Do(func() {
		netmon.RegisterInterfaceGetter(func() ([]netmon.Interface, error) {
			networkMu.RLock()
			defer networkMu.RUnlock()
			return append([]netmon.Interface{}, interfaces...), nil
		})
	})
	updateRoute(info.DefaultInterface, info.Gateway)
	return nil
}
