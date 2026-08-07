// Package fixture is a stdlib-only Go fixture for the evaluation harness. It has no module
// dependencies so `go test` proves the Go toolchain works inside Docker without network access.
package fixture

import "errors"

// ErrEmpty is returned when a statistic is undefined for an empty sample.
var ErrEmpty = errors.New("empty sample")

// Mean returns the arithmetic mean of xs.
func Mean(xs []float64) (float64, error) {
	if len(xs) == 0 {
		return 0, ErrEmpty
	}
	total := 0.0
	for _, x := range xs {
		total += x
	}
	return total / float64(len(xs)), nil
}
