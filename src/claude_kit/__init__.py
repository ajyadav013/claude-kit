"""claude-kit — an autonomous, stack-agnostic SDLC for Claude Code.

A Cookiecutter-style scaffolder for a Claude Code **configuration** (no application code, no
Docker): ``claude-kit init`` asks ordered questions and lays down ``CLAUDE.md`` + ``.claude/``
(rules, the chosen profile's agents/skills, hooks, artifact templates, config) plus an optional
``.mcp.json``. The same payload is consumed directly by Claude Code when claude-kit is installed
as a plugin. Extensibility is data-driven via the ``catalog/`` (stacks, profiles, MCP).
"""

__version__ = "0.7.0"
