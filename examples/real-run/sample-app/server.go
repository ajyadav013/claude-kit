package main

import (
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"strings"
)

// newMux wires the task API routes over the given store. Uses the Go 1.22+
// method-and-pattern routing in the standard-library ServeMux.
func newMux(store *Store) *http.ServeMux {
	mux := http.NewServeMux()

	mux.HandleFunc("GET /health", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	})

	mux.HandleFunc("GET /tasks", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{"tasks": store.List()})
	})

	mux.HandleFunc("DELETE /tasks/{id}", func(w http.ResponseWriter, r *http.Request) {
		raw := r.PathValue("id")
		id, err := strconv.Atoi(raw)
		// The path id must be the task's canonical positive integer. strconv.Atoi alone accepts
		// leading zeros and a leading '+' ("01", "+1", "%2B1"), which would alias and delete task 1;
		// re-encoding and comparing rejects every non-canonical form. (Defect found by devils-advocate.)
		if err != nil || id <= 0 || strconv.Itoa(id) != raw {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "id must be a positive integer"})
			return
		}
		if err := store.Delete(id); errors.Is(err, errNotFound) {
			writeJSON(w, http.StatusNotFound, map[string]string{"error": "task not found"})
			return
		}
		w.WriteHeader(http.StatusNoContent)
	})

	mux.HandleFunc("POST /tasks", func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Title string `json:"title"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid JSON body"})
			return
		}
		if strings.TrimSpace(body.Title) == "" {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "title is required"})
			return
		}
		writeJSON(w, http.StatusCreated, store.Add(strings.TrimSpace(body.Title)))
	})

	return mux
}

// writeJSON serialises v as a JSON response with the given status code.
func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}
