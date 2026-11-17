// __service__ is the __id__ module's service. What every module answers (/readyz, /v1/module,
// /v1/access and its tools at /mcp) comes from the template's kit (t10kit/module, kit/go/ in
// the project); this module adds its tools (tools.go) and its web app (server.go). Its settings
// come from the project: the standard ones every module gets, and modules/__id__/config/.
package main

import (
	"cmp"
	"context"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"t10kit/module"

	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	moduleID = "__id__"
	service  = "__service__"
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	// Connects lazily: /readyz reports whether the database answers.
	pool, err := pgxpool.New(ctx, os.Getenv("DATABASE_URL"))
	if err != nil {
		log.Fatal(err)
	}
	defer pool.Close()

	access, err := module.NewAccess(moduleID, service)
	if err != nil {
		log.Fatal(err)
	}
	s := &Server{Module: module.Module{
		ID: moduleID, Service: service, Label: "__Id__", PublicURL: os.Getenv("__ID___PUBLIC_URL"),
		Access: access, Ping: pool.Ping, Tools: tools(),
	}}
	srv := &http.Server{Addr: cmp.Or(os.Getenv("LISTEN_ADDR"), ":__port__"), Handler: s.Handler(), ReadHeaderTimeout: 10 * time.Second}
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		_ = srv.Shutdown(shutdown)
	}()
	log.Printf("%s listening on %s", service, srv.Addr)
	if err := srv.ListenAndServe(); err != http.ErrServerClosed {
		log.Fatal(err)
	}
}
