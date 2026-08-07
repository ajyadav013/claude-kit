"""Keep scenario fixtures, sealed holdouts and reference solutions out of the repository's own run.

`fixtures/`, `holdouts/` and `solutions/` are DATA, not tests of claude-kit. They are pytest files on
purpose — they get copied into a scenario workspace and executed there against that workspace's
source — so collecting them here is wrong twice over: their imports (`calc`, `inventory`, `billing`)
do not resolve in this repo, and `pybug` deliberately ships a failing reproducer, which is the whole
point of SC-02.

`solutions/` additionally holds the reference *answers* a graded session is measured against. They
must never run as part of this repo's suite, and must never be shown to a task performer.

Without this, `pytest` aborts with collection errors before running anything.
"""

collect_ignore_glob = ["fixtures/*", "holdouts/*", "solutions/*"]
