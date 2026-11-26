# The module's image, from this folder alone: what every module answers comes from t10-modkit, a
# public module go.mod requires by tag (T10_MODKIT in platform/foundation/versions.env).
FROM golang:1.27.4-alpine AS build
WORKDIR /src
ENV CGO_ENABLED=0
# git lets go fetch a tag from its repository when Go's proxy hasn't got it yet, as for a while
# after a release; go.sum still pins every module's hash.
RUN apk add --no-cache git
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY . .
# Go's module and build caches persist between builds, so a rebuild compiles only what changed.
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
	go build -trimpath -ldflags="-s -w" -o /out/__service__ .

# `make test` builds this stage, then runs it beside a throwaway Postgres with TEST_DATABASE_URL
# set (the label says it's to be run). Building it checks gofmt and vet and compiles each
# package's tests, with Go's caches, so a run after a change starts at once; the run prints what
# didn't pass and how many tests skipped.
FROM build AS test
LABEL t10.test=run
RUN test -z "$(gofmt -l .)" || { echo "not gofmt'd:"; gofmt -l .; exit 1; }
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
	go vet ./... && \
	go list -f '{{if or .TestGoFiles .XTestGoFiles}}{{.Dir}}{{end}}' ./... >/tests && \
	while read -r dir; do go test -c -o "$dir/.t10.test" "$dir" || exit 1; done </tests
COPY <<'EOF' /usr/local/bin/t10-test
#!/bin/sh
s=0 skipped=0
while read -r dir; do
	if (cd "$dir" && ./.t10.test -test.v >/tmp/out 2>&1); then r=ok; else r=FAIL; s=1; fi
	grep -vE '^(=== (RUN|PAUSE|CONT)|[[:space:]]*--- PASS|PASS$)' /tmp/out
	skipped=$((skipped + $(grep -cE '^[[:space:]]*--- SKIP' /tmp/out)))
	echo "$r	.${dir#/src}"
done </tests
echo "$skipped skipped"
exit $s
EOF
RUN chmod +x /usr/local/bin/t10-test
CMD ["t10-test"]

FROM alpine:3.21
RUN apk add --no-cache ca-certificates tzdata
COPY --from=build /out/__service__ /usr/local/bin/__service__
# The module pack: how a project plugs this module into the foundation (platform/docs/module.md).
COPY module/ /module/
USER 65534:65534
EXPOSE __port__
ENTRYPOINT ["/usr/local/bin/__service__"]
