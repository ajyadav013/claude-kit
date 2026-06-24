package main

import (
	"errors"
	"sort"
	"sync"
)

// errNotFound is returned when a task id has no matching task.
var errNotFound = errors.New("task not found")

// Task is a single to-do item.
type Task struct {
	ID    int    `json:"id"`
	Title string `json:"title"`
	Done  bool   `json:"done"`
}

// Store is a concurrency-safe in-memory task collection.
type Store struct {
	mu     sync.Mutex
	tasks  map[int]Task
	nextID int
}

// NewStore returns an empty Store ready for use.
func NewStore() *Store {
	return &Store{tasks: make(map[int]Task), nextID: 1}
}

// Add creates a task with the given title and returns it.
func (s *Store) Add(title string) Task {
	s.mu.Lock()
	defer s.mu.Unlock()
	t := Task{ID: s.nextID, Title: title}
	s.tasks[t.ID] = t
	s.nextID++
	return t
}

// Delete removes the task with the given id, returning errNotFound if it does
// not exist.
func (s *Store) Delete(id int) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.tasks[id]; !ok {
		return errNotFound
	}
	delete(s.tasks, id)
	return nil
}

// List returns all tasks ordered by id.
func (s *Store) List() []Task {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]Task, 0, len(s.tasks))
	for _, t := range s.tasks {
		out = append(out, t)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out
}
