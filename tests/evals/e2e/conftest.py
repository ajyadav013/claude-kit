"""Keep scenario fixtures and sealed holdouts out of the repository's own test run.

`fixtures/` and `holdouts/` are DATA, not tests of claude-kit. They are pytest files on purpose —
they get copied into a scenario workspace and executed there against that workspace's source — so
collecting them here is wrong twice over: their imports (`calc`, `inventory`) do not resolve in this
repo, and `pybug` deliberately ships a failing reproducer, which is the whole point of SC-02.

Without this, `pytest` aborts with collection errors before running anything.
"""

collect_ignore_glob = ["fixtures/*", "holdouts/*"]
