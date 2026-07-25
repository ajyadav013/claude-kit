---
source: https://github.com/ashishps1/awesome-low-level-design/blob/main/problems/music-streaming-service.md
author: ashishps1
license-note: ideas absorbed in own words; no text or code reproduced
---

# Object model for a music streaming service (Spotify-style)

## What it teaches

A component-per-concern decomposition of a media platform: instead of one
god service, the design splits the domain into a catalog store, a user/auth
manager, a playback engine, and a recommendation engine, each a separate
class, with a thin top-level service wiring them together. It is less about
clever data structures and more about drawing subsystem boundaries that
match independent axes of change.

## Key patterns & decisions

- **Three-level catalog hierarchy** — Song, Album, and Artist are linked
  entities (a track knows its album and artist), so browse and search can
  pivot on any of the three without duplicate data.
- **Playlist as user-owned composition** — playlists are ordered
  collections of songs hanging off the user, keeping curation state
  separate from the shared catalog it references.
- **Subsystem-per-concern managers** — a MusicLibrary (catalog CRUD and
  lookup), a UserManager (registration/login), a MusicPlayer (transport
  controls: play, pause, skip, seek), and a MusicRecommender
  (history-driven suggestions) each encapsulate one concern; the
  MusicStreamingService entry point composes them and routes user requests.
- **Singleton per shared component** — the library, user manager, and
  recommender are each single-instance, treating them as process-wide
  shared services rather than per-request objects.
- **Recommendations as a pluggable consumer of listening history** — the
  recommender reads preferences and play history but is otherwise isolated,
  so its algorithm can evolve (or be replaced) without touching playback or
  catalog code.
- **Extensibility as a stated requirement** — the spec explicitly reserves
  room for future capabilities like social sharing and offline listening,
  a nudge to keep the component seams loose rather than fusing playback
  into the catalog.

## When to apply / trade-offs

This shape fits any content platform (video, podcasts, courses): shared
read-mostly catalog, per-user mutable state, a stateful playback session,
and an advisory engine on the side. The manager-object split is the main
reusable idea — it maps cleanly onto real service boundaries if the system
later distributes. Costs: a proliferation of singletons is global state in
disguise, hostile to testing and to the multi-session reality of streaming
(a per-user player session object would model concurrent listeners better
than one shared MusicPlayer). The capture also stays silent on the hard
streaming problems — buffering, licensing, offline sync — so treat this as
the control-plane object model, not a streaming architecture. Auth is
named as a requirement but only surfaces as password fields plus a login
manager; real designs would isolate credentials from the user entity.

## Fidelity check

1. **Claim:** the design splits catalog, users, playback, and
   recommendations into separate manager classes composed by one entry
   point. **Support:** the capture lists MusicLibrary, UserManager,
   MusicPlayer, and MusicRecommender as distinct classes, with a
   MusicStreamingService initializing the components and handling requests.
2. **Claim:** recommendations are driven by user preference and listening
   history. **Support:** both the requirements and the recommender's class
   description state suggestions are generated from user preferences and
   past listening.
3. **Claim:** the spec plans for growth into sharing and offline modes.
   **Support:** the requirements include an extensibility clause naming
   social sharing and offline playback as anticipated future features.
