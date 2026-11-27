// __service__ is the __id__ module's service. What every module answers (/readyz, /v1/module,
// /v1/access and its tools at /mcp) comes from t10-modkit's module package, at the tag the
// template pins (T10_MODKIT); this module adds its ontology (ontology.go), its own tools (tools.go) and its web app (server.go). Its settings
// come from the project: the standard ones every module gets, and modules/__id__/config/.
// Workbench's bell asks every module for notifications; set Module.Notifier once it has some.
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

	"github.com/xiant10/t10-modkit/module"

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
		ID: moduleID, Service: service, Label: "__Id__", LabelZH: "__Id__", PublicURL: os.Getenv("__ID___PUBLIC_URL"),
		Sections: sections(), Access: access, Ping: pool.Ping, Tools: tools(),
	}}
	// The example notes start with samples only when the module runs alone.
	newOntology(s, newNotes(os.Getenv("T10_STANDALONE") != ""))
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
