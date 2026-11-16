// __service__ is the __id__ module's service. It answers what a project expects of every
// module (docs/module.md in the project): /readyz, /v1/module, /v1/access and its tools at
// /mcp. Its settings come from the project: modules/__id__/config/ and compose/base.yml.
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

	"__service__/verifier"

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

	issuer, secret := os.Getenv("AUTH_ISSUER"), os.Getenv("AUTH_CLIENT_SECRET")
	authURL := cmp.Or(os.Getenv("AUTH_URL"), issuer)
	client := &http.Client{Timeout: 5 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	v, err := verifier.New(verifier.Config{Issuer: issuer, URL: authURL, Service: service, ClientSecret: secret, HTTPClient: client})
	if err != nil {
		log.Fatal(err)
	}

	s := &Server{
		Access:    &Auth{URL: authURL, Secret: secret, HTTP: client, Verifier: v},
		Ping:      pool.Ping,
		PublicURL: os.Getenv("__ID___PUBLIC_URL"),
	}
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
