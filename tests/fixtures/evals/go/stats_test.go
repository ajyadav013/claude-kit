package fixture

import (
	"errors"
	"testing"
)

func TestMean(t *testing.T) {
	got, err := Mean([]float64{2, 4, 6})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != 4 {
		t.Fatalf("Mean = %v, want 4", got)
	}
}

func TestMeanEmpty(t *testing.T) {
	if _, err := Mean(nil); !errors.Is(err, ErrEmpty) {
		t.Fatalf("err = %v, want ErrEmpty", err)
	}
}
