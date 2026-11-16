# Go's module and build caches persist between builds, so a rebuild compiles only what changed.
FROM golang:1.27.3-alpine AS build
WORKDIR /src
ENV CGO_ENABLED=0
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY . .
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
	go build -trimpath -ldflags="-s -w" -o /out/__service__ .

# `make test` builds this stage: vet and the tests, with the image's own toolchain.
FROM build AS test
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
	go vet ./... && go test ./...

FROM alpine:3.21
RUN apk add --no-cache ca-certificates tzdata
COPY --from=build /out/__service__ /usr/local/bin/__service__
# The module pack: how a project plugs this module into the foundation (its docs/module.md).
COPY module/ /module/
USER 65534:65534
EXPOSE __port__
ENTRYPOINT ["/usr/local/bin/__service__"]
