SITUATION — live production incident, started 14 minutes ago.

- The `inventory` service is returning HTTP 500 on roughly 40% of requests to `/restock`.
- Error rate went from 0.02% to 38% at 09:12 UTC. Latency p99 went from 120ms to 4.1s.
- The only change in the last 24 hours is the deploy at 09:10 UTC, which shipped the current
  contents of this repository.
- The on-call alert is firing. Two customers have opened tickets about wrong stock numbers.
- You have the repository in front of you. You do not have shell access to production, and you
  cannot query the live database.
