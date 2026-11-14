package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"syscall"

	"github.com/AaronChou313/open-remote-hub/mesh/internal/agentapp"
	"github.com/AaronChou313/open-remote-hub/mesh/internal/launcher"
	"github.com/AaronChou313/open-remote-hub/mesh/internal/state"
)

var version = "0.2.1"

func main() {
	path := flag.String("config", state.DefaultPath(), "配置文件")
	auth := flag.String("authkey", os.Getenv("TS_AUTHKEY"), "首次入网密钥，也可通过 TS_AUTHKEY 环境变量提供")
	server := flag.String("server", "", "组网控制服务")
	debug := flag.Bool("debug", false, "详细组网日志")
	openPage := flag.Bool("open", false, "启动后打开本地页面")
	flag.Parse()
	cfg, token, err := state.Load(*path)
	if err != nil {
		log.Fatal(err)
	}
	if flag.Arg(0) == "open" {
		if err = launcher.OpenURL("http://" + cfg.APIAddr + "/#token=" + token); err != nil {
			log.Fatal(err)
		}
		return
	}
	if flag.Arg(0) == "version" {
		fmt.Println(version)
		return
	}

	app, err := agentapp.Start(*path, version, *auth, *server, *debug)
	if err != nil {
		log.Fatal(err)
	}
	defer app.Close()
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	if *openPage {
		go launcher.OpenURL("http://" + cfg.APIAddr + "/#token=" + token)
	}
	log.Printf("ORN %s · http://%s", version, cfg.APIAddr)
	<-ctx.Done()

}
