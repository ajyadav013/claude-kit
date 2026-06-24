package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func newTestServer(t *testing.T) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(newMux(NewStore()))
	t.Cleanup(srv.Close)
	return srv
}

func TestHealth(t *testing.T) {
	srv := newTestServer(t)
	resp, err := http.Get(srv.URL + "/health")
	if err != nil {
		t.Fatalf("GET /health: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
}

func TestCreateAndListTask(t *testing.T) {
	srv := newTestServer(t)
	body := bytes.NewBufferString(`{"title":"ship it"}`)
	resp, err := http.Post(srv.URL+"/tasks", "application/json", body)
	if err != nil {
		t.Fatalf("POST /tasks: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusCreated {
		t.Fatalf("status = %d, want 201", resp.StatusCode)
	}
	var created Task
	if err := json.NewDecoder(resp.Body).Decode(&created); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if created.ID != 1 || created.Title != "ship it" {
		t.Fatalf("created = %+v, want id=1 title=ship it", created)
	}
}

func TestCreateRejectsEmptyTitle(t *testing.T) {
	srv := newTestServer(t)
	resp, err := http.Post(srv.URL+"/tasks", "application/json", bytes.NewBufferString(`{"title":"  "}`))
	if err != nil {
		t.Fatalf("POST /tasks: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", resp.StatusCode)
	}
}

// do issues a request with no body and returns the status code.
func do(t *testing.T, method, url string) int {
	t.Helper()
	req, err := http.NewRequest(method, url, nil)
	if err != nil {
		t.Fatalf("new request: %v", err)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("%s %s: %v", method, url, err)
	}
	defer resp.Body.Close()
	return resp.StatusCode
}

func TestDeleteTask(t *testing.T) {
	srv := newTestServer(t)
	if _, err := http.Post(srv.URL+"/tasks", "application/json", bytes.NewBufferString(`{"title":"a"}`)); err != nil {
		t.Fatalf("seed POST: %v", err)
	}
	if code := do(t, http.MethodDelete, srv.URL+"/tasks/1"); code != http.StatusNoContent {
		t.Fatalf("DELETE status = %d, want 204", code)
	}
	// The list is empty after the only task is deleted.
	resp, err := http.Get(srv.URL + "/tasks")
	if err != nil {
		t.Fatalf("GET /tasks: %v", err)
	}
	defer resp.Body.Close()
	var payload struct {
		Tasks []Task `json:"tasks"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&payload); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(payload.Tasks) != 0 {
		t.Fatalf("tasks after delete = %d, want 0", len(payload.Tasks))
	}
}

func TestDeleteMissingReturns404(t *testing.T) {
	srv := newTestServer(t)
	if code := do(t, http.MethodDelete, srv.URL+"/tasks/999"); code != http.StatusNotFound {
		t.Fatalf("DELETE missing status = %d, want 404", code)
	}
}

func TestDeleteNonIntegerReturns400(t *testing.T) {
	srv := newTestServer(t)
	if code := do(t, http.MethodDelete, srv.URL+"/tasks/abc"); code != http.StatusBadRequest {
		t.Fatalf("DELETE non-int status = %d, want 400", code)
	}
}

// TestDeleteRejectsNonCanonicalID drives the mux directly (httptest.NewRecorder), because the Go
// http.Client normalizes request paths and would hide non-canonical ids. Regression for the id-
// aliasing defect the devils-advocate found: "01"/"+1"/"-1"/"0" must 400, not delete task 1.
func TestDeleteRejectsNonCanonicalID(t *testing.T) {
	for _, id := range []string{"01", "+1", "%2B1", "00000000001", "-1", "0"} {
		store := NewStore()
		store.Add("keep me")
		rec := httptest.NewRecorder()
		req := httptest.NewRequest(http.MethodDelete, "/tasks/"+id, nil)
		newMux(store).ServeHTTP(rec, req)
		if rec.Code != http.StatusBadRequest {
			t.Errorf("DELETE /tasks/%s = %d, want 400", id, rec.Code)
		}
		if _, err := storeGet(store, 1); err != nil {
			t.Errorf("DELETE /tasks/%s deleted canonical task 1 (alias bug)", id)
		}
	}
}

// storeGet reports whether task id is still present (test-only helper).
func storeGet(s *Store, id int) (Task, error) {
	for _, tk := range s.List() {
		if tk.ID == id {
			return tk, nil
		}
	}
	return Task{}, errNotFound
}
