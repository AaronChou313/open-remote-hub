package launcher

import (
	"fmt"
	"net"
	"os/exec"
	"runtime"
	"strconv"
)

func OpenURL(url string) error {
	var cmd *exec.Cmd
	switch runtime.GOOS {
	case "darwin":
		cmd = exec.Command("open", url)
	case "windows":
		cmd = exec.Command("rundll32", "url.dll,FileProtocolHandler", url)
	default:
		cmd = exec.Command("xdg-open", url)
	}
	return cmd.Run()
}
func RustDesk(port int) error {
	address := net.JoinHostPort("127.0.0.1", strconv.Itoa(port))
	var cmd *exec.Cmd
	switch runtime.GOOS {
	case "darwin":
		cmd = exec.Command("/usr/bin/open", "-n", "-a", "/Applications/RustDesk.app", "--args", "--connect", address)
	case "windows":
		path, err := exec.LookPath("rustdesk.exe")
		if err != nil {
			path = `C:\Program Files\RustDesk\rustdesk.exe`
		}
		cmd = exec.Command(path, "--connect", address)
	default:
		cmd = exec.Command("rustdesk", "--connect", address)
	}
	if err := cmd.Start(); err != nil {
		return fmt.Errorf("无法打开 RustDesk，请手动连接 %s", address)
	}
	go cmd.Wait()
	return nil
}
