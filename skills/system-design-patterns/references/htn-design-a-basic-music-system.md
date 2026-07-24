# Digest: Design a basic Music System

- **Source:** https://x.com/Harry_The_Nerd/status/2056620076246479055
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** LLD (Low-Level Design series #2)
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal engineering reference — no verbatim text.

The article walks through an object-oriented design for a simplified music-playlist system (Java), using five entity classes to illustrate classic LLD relationship types and lifecycle rules. Requirements: songs belong to artists, all songs live in one master library, users own multiple playlists, one song may appear in many playlists, and deleting a playlist must never destroy the songs it referenced.

## Patterns

### Composition (Has-A) for intrinsic dependencies
A Song object holds a reference to its Artist rather than duplicating artist fields inside itself. The author frames the song→artist link as a Has-A/composition relationship: the artist is part of what defines a song (title, artist reference, duration in seconds). Use this when one entity's identity inherently includes another; the trade-off is a pointer indirection in exchange for a single canonical artist record instead of scattered copies. (Note: the same link is later labeled "association" in the concepts recap — the article uses both terms for it.)

### Aggregation with independent lifecycles
The Playlist holds a collection of Song references but does not own them: songs exist before, outside, and after any playlist. Deleting a playlist leaves the songs in the library and in every other playlist that references them. This is the article's central lesson — model container/member relationships as aggregation whenever the member's lifetime must not be coupled to the container's. It makes deletion cheap and safe, at the cost of needing a separate authority (the library) to decide when a song is truly gone.

### Centralized canonical store + reference sharing
A single Library class acts as the master repository of all songs; playlists only point at entries in it. The author's rationale: without a central store, each playlist would carry its own copy of a song, inflating memory and making updates/management painful. This is a deduplicate-by-reference pattern (flyweight-flavored): one instance, many pointers. Use it whenever the same immutable-ish entity can appear in many collections; the trade-off is that the store becomes the lifecycle authority and a coordination point.

### Manager/managed separation (User → Playlist)
The User class creates, stores, and deletes playlists, but playlists are modeled as independent entities rather than inner details of the user. Keeping the manager's responsibilities (create/delete/track) separate from the managed object's own behavior (add/remove/count/duration) keeps both classes small and lets playlists evolve or be shared without touching user logic.

### Single Responsibility Principle as the class-carving rule
Each of the five classes has exactly one job: Artist holds artist data, Song holds song data, Playlist implements playlist operations, User manages a user's playlists, Library stores the song catalog. The article uses SRP as the criterion for where a method belongs; the payoff is that changes to one concern (e.g., playlist math) never ripple into unrelated classes.

### Encapsulation of state
All fields across the classes are private, with access mediated by getters and behavior methods. The stated goal is protecting internal state from arbitrary external mutation — invariants (like a playlist's song list) can only change through the class's own operations.

### Object reuse across collections
Because playlists share references into the library, the identical Song instance can sit in any number of playlists simultaneously. This is the reusability payoff of the aggregation + central-store combination: no per-playlist duplication, and a metadata fix to one song is visible everywhere at once.

### Complexity accounting for collection operations
The article closes the design with a cost table: adding a song to a playlist is O(1), removing a song is O(n), computing total playlist duration is O(n), and creating a playlist is O(1). The implied lesson is to state the big-O of each public operation as part of an LLD answer, since it follows directly from the chosen backing collection (append-friendly list ⇒ linear scan for removal and summation).

## Not absorbed

- **Series/interview framing** ("Low-Level Design series #2", the closing sign-off) — publication packaging, not engineering content.
- **Streaming-app name-dropping intro** (Spotify / Apple Music / YouTube Music comparison) — motivational scene-setting only; no design detail.
- **"UML Diagram" section** — heading present but the diagram itself is an image that did not survive the text-only capture; nothing to summarize.
- **"Full code" pointer** — the actual Java source is referenced but absent from the capture (likely images or an external link); no code to absorb.
- **Engagement metrics / timestamp** (views, likes, 19 May 2026 post date) — platform metadata.

## Fidelity check

- **Post count in capture:** 1 (the entire article is one long-form post; `postCount: 1` in the JSON).
- **Article outline (author's structure):**
  1. Intro — motivation + list of supported capabilities
  2. Problem Statement
  3. Core Classes in the Design (five-class overview)
  4. 1. Artist Class
  5. 2. Song Class
  6. 3. Playlist Class
  7. 4. User Class
  8. 5. Library Class
  9. UML Diagram
  10. Key LLD Concepts Used (Encapsulation, Association, Aggregation, SRP, Reusability)
  11. Time Complexity Analysis
  12. Full code + sign-off
- **Pattern → section mapping:**
  - Composition (Has-A) — section "2. Song Class" (plus "Association" in "Key LLD Concepts Used")
  - Aggregation with independent lifecycles — section "3. Playlist Class" (plus "Aggregation" in "Key LLD Concepts Used" and the Problem Statement's delete rule)
  - Centralized canonical store + reference sharing — section "5. Library Class"
  - Manager/managed separation — section "4. User Class"
  - Single Responsibility Principle — section "1. Artist Class" (first stated) and "Key LLD Concepts Used" item 4
  - Encapsulation of state — "Key LLD Concepts Used" item 1
  - Object reuse across collections — "Key LLD Concepts Used" item 5 (Reusability)
  - Complexity accounting — section "Time Complexity Analysis"
