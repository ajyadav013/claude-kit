// Command taskapi is a tiny standard-library HTTP task API used as the sample
// application for a captured claude-kit /sdlc run.
package main

import (
	"log"
	"net/http"
)

func main() {
	store := NewStore()
	addr := "127.0.0.1:8080"
	log.Printf("taskapi listening on %s", addr)
	if err := http.ListenAndServe(addr, newMux(store)); err != nil {
		log.Fatal(err)
	}
}
