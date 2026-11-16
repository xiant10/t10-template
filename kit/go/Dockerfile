# The kit's own tests, with the same toolchain modules build with: make test-template.
FROM golang:1.27.3-alpine
WORKDIR /kit
ENV CGO_ENABLED=0
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY . .
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
	go vet ./... && go test ./...
