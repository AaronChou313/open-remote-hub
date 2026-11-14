package mobile

import "tailscale.com/net/netmon"

func updateRoute(name, gateway string) {
	netmon.UpdateLastKnownDefaultRouteInterface(name)
	netmon.UpdateLastKnownDefaultGateway(gateway)
}
