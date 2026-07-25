---
source: https://www.canva.dev/blog/engineering/simple-fast-and-scalable-reverse-image-search-using-perceptual-hashes-and-dynamodb/
author: Canva
license-note: ideas absorbed in own words; no text or code reproduced
---

# Reverse image search at 10-billion scale with perceptual hashes and segmented key lookups

## What it teaches

Canva needed to find visually similar images across an enormous user-media library — for
deduplication and for fast content-moderation takedowns — without standing up a dedicated
similarity-search engine. The post shows how far you can get with a plain key-value store:
perceptual hashes plus a multi-index segmentation scheme over DynamoDB deliver
similarity-with-a-threshold search at point-lookup speed. Equally valuable is the postmortem
middle section: the first rollout was unusable, not because the algorithm was wrong, but because
real user data violated two distribution assumptions.

## Key patterns & decisions

- **Cryptographic hashes only match exact bytes.** MD5/SHA-style digests flip completely on a
  one-pixel or metadata change, so they only dedupe perfect copies. Perceptual hashes are
  computed from pixel content, so visually similar images produce hashes that differ in few bit
  positions, and similarity becomes a Hamming-distance comparison (a small watermark cost only a
  distance of 2 in their example).
- **Multi-index hashing to make Hamming search key-addressable.** Split each stored hash into n
  segments and index every segment (prefixed with its position) as a partition key, with the
  image ID as sort key. At query time split the probe hash the same way, run one lookup per
  segment, union the candidates, then filter by true Hamming distance.
- **Pigeonhole guarantee.** With n segments, any stored hash within Hamming distance n−1 of the
  probe must agree exactly on at least one segment — so the segment lookups provably cannot miss
  a match inside the threshold. Recall is guaranteed; precision is handled by the post-filter.
- **Segment count is the precision/recall dial.** More segments tolerate larger distances but
  each segment gets shorter and less selective, exploding the candidate set. Canva's launch
  config returned so many junk candidates that queries took minutes and burned 20x the expected
  read capacity; cutting the segment count 4x (re-testing after each cut to confirm no real
  matches were lost) fixed it.
- **Degenerate inputs create hot keys.** Flat, low-complexity images (solid-color shapes) all
  hash to near-identical values, so single segment values matched hundreds of thousands of rows.
  The fix was to detect and skip hashing such images — they are recognizable because the hash
  collapses to a repeated single character.
- **Real data is more duplicated than you assume.** Users upload the same image repeatedly, so
  the uniqueness distribution was far worse than design estimates; capacity planning for
  similarity systems must use production distributions, not synthetic ones.
- **Results as evidence the simple design holds.** Over 10 billion hashes stored, ~40 ms average
  query latency (p95 ~60 ms), and peaks above 2,000 queries/second (~10k read-capacity units)
  with no degradation.
- **One index, several products.** The same table powers storage deduplication analysis,
  near-duplicate detection, and seconds-scale takedown of known illegal or dangerous media
  across the whole dataset.

## When to apply / trade-offs

- Use this shape when you need near-duplicate detection with a bounded, small distance threshold
  and huge scale on boring infrastructure. It is not semantic similarity — embeddings and vector
  search are the tool once "similar" means "same subject," not "same pixels lightly edited."
- The pigeonhole guarantee only covers distances up to segments−1; raising the threshold means
  more segments, and cost grows through candidate-set inflation. Pick the smallest threshold the
  product tolerates.
- Expect an adversarial-data pass: skewed key popularity (duplicates, degenerate hashes) is the
  practical failure mode of any hash-partitioned similarity index. Guard rails: input filtering,
  candidate caps, and load testing with production data.
- Choice of perceptual hash algorithm matters per media type (photos vs. flat vector art behave
  differently); the algorithm they illustrate with was picked for short hashes, not claimed as
  universally best.

## Fidelity check

1. Claim: the segment scheme guarantees recall within a threshold. Support: the capture explains
   via the pigeonhole principle that with n segments and at most n−1 differing characters, at
   least one segment must match exactly, so a 4-way split guarantees finding everything within
   Hamming distance 3.
2. Claim: the first rollout failed on candidate explosion. Support: the capture reports queries
   taking minutes, roughly 20x the expected read capacity, and result sets in the hundreds of
   thousands driven by duplicate uploads and uniform hashes from simple vector graphics, fixed by
   a 4x segment-count reduction plus skipping low-complexity images.
3. Claim: the production system is fast at very large scale. Support: the capture cites over 10
   billion image hashes in DynamoDB, 40 ms average / 60 ms p95 query times, and 2,000+ queries
   per second at peak without performance degradation.
