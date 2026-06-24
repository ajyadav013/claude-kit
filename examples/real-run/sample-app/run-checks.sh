#!/usr/bin/env bash
# The exact gate-check commands whose output backs this run's build-green and test-coverage verdicts.
# Dependency-free: Go standard library only, so it reproduces anywhere Go is installed.
set -euo pipefail
cd "$(dirname "$0")"

echo "== build =="; go build ./...
echo "== vet ==";   go vet ./...
echo "== gofmt =="; test -z "$(gofmt -l .)" && echo "all files formatted"
echo "== test ==";  go test ./... -v -cover -count=1
