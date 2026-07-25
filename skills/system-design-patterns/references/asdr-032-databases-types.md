---
source: https://blog.algomaster.io/p/15-types-of-databases
author: AlgoMaster (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Fifteen Database Families and Their Natural Workloads

## What it teaches

A selection catalog: fifteen database categories, each defined by its data
model, its sweet-spot workloads, and its disqualifiers, closing with the
point that no single engine wins universally — choice follows use case, data
shape, scale needs, and budget. The durable skill it builds is
pattern-matching a workload's dominant access pattern to the storage model
purpose-built for it, and knowing each model's "do not use when" clause.

## Key patterns & decisions

- **Relational (MySQL/PostgreSQL/Oracle)** for structured data with enforced
  integrity, cross-table relationships via keys, rich SQL querying, and ACID
  transactions — the default for enterprise records, commerce orders, and
  finance where consistency is non-negotiable.
- **Key-value (Redis/DynamoDB)** when access is by unique key and the
  priorities are throughput, availability, and horizontal scale — sessions,
  caches, real-time pipelines; wrong when you need complex queries,
  relationships, or strong consistency.
- **Document (MongoDB/Couchbase/CouchDB)** for semi-structured JSON-like
  records under an evolving schema — catalogs with heterogeneous attributes,
  CMS content, IoT payloads; weak for rigidly structured data or
  multi-document transactions.
- **Graph (Neo4j/Neptune)** when relationships are the query — traversals over
  nodes/edges/properties for social graphs, recommendations, knowledge
  graphs.
- **Wide-column (Cassandra/HBase/Bigtable)** for massive distributed write
  throughput with flexible columns and eventual consistency — event streams,
  analytics ingestion; wrong for join-heavy or strict-ACID needs.
- **In-memory (Redis/Memcached)** when latency dominates and the working set
  fits in RAM — gaming state, high-frequency trading; costly and
  capacity-bound.
- **Time-series (InfluxDB/TimescaleDB/Prometheus)** for timestamp-ordered
  streams — metrics, sensors, market ticks — with retention and
  trend-analysis features general engines lack.
- **Object-oriented (ObjectDB/db4o)** to persist application objects directly
  without an object-relational mapping layer.
- **Text-search (Elasticsearch/Solr/Sphinx)** for indexing and querying large
  unstructured text corpora — product search, web search, log analysis.
- **Spatial (PostGIS/Oracle Spatial)** for geometric types with specialized
  indexes (R-tree/quadtree families) powering GIS, location services, and
  routing.
- **Blob stores (S3/Azure Blob/HDFS)** for large unstructured binary media,
  backups, and archives — durability and cost-efficiency over queryability.
- **Ledger (QLDB/Hyperledger)** for append-only, tamper-evident transaction
  history — supply-chain provenance, health records, voting.
- **Hierarchical (IBM IMS, Windows Registry)** — tree-shaped one-parent
  many-children records; largely legacy, superseded by relational/NoSQL
  flexibility, still the natural fit for file-system-like structures.
- **Vector (Faiss/Milvus/Pinecone)** for similarity and nearest-neighbor
  search over high-dimensional embeddings — image retrieval, recommenders,
  anomaly detection in ML/AI systems.
- **Embedded (SQLite/RocksDB/Berkeley DB)** running inside the application
  process rather than as a server — local app data, game saves,
  resource-constrained deployments.

## When to apply / trade-offs

Use this as a triage rubric during system design: identify the dominant
access pattern (key lookup, relationship traversal, time-window scan,
similarity search, full-text query, geometric query, append-only audit) and
shortlist the family built for it, then check the disqualifiers (consistency
strength, join needs, RAM cost, schema rigidity). Polyglot persistence is the
implied norm — one product line often spans categories (Redis appears as both
key-value and in-memory).

## Fidelity check

1. *Claim: wide-column stores are disqualified by join-heavy, strongly
   consistent workloads.* The capture says their column-oriented, eventually
   consistent design suits high write throughput and real-time processing but
   is a poor fit where complex joins, strong consistency, or strict ACID
   transactions are required.
2. *Claim: spatial engines rely on specialized index structures.* The capture
   names R-trees and quadtrees as the indexing techniques spatial databases
   use to make geometric queries efficient.
3. *Claim: embedded databases run in-process.* The capture contrasts them with
   client-server engines, describing them as linked into and running inside
   the application itself, giving fast access, small footprint, and simple
   deployment for constrained environments.

## Notes

Interview-prep newsletter breadth piece — one paragraph per category, no
depth on any single engine; upsell blocks interleaved. Taxonomy overlaps the
standard "polyglot persistence" literature but is a serviceable checklist.
