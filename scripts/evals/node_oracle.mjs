// Oracle for `node --test` fixtures, emitting the same record shape as tier_a_agents.py's python
// path. It exists because the python eval image has no node and the node image has no python, so
// one of the two languages had to have its own runner rather than a faked verdict.
//
// Only touches run directories whose workspace is a node fixture. A python workspace is left
// exactly as the python pass wrote it -- overwriting a good record from the right container with
// a "could not run" from the wrong one would destroy real evidence.
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

if (!fs.existsSync("/.dockerenv")) {
  console.error("refusing to run project code outside Docker");
  process.exit(2);
}

const probeDir = process.argv[2];
if (!probeDir) {
  console.error("usage: node_oracle.mjs <probe-dir>");
  process.exit(2);
}
const REPO = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../..");

function counts(ws) {
  let out = "";
  try {
    out = execFileSync("node", ["--test", "test/"], {
      cwd: ws,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
      timeout: 600000,
    });
  } catch (e) {
    out = `${e.stdout || ""}${e.stderr || ""}`;
  }
  const pass = /^# pass (\d+)/m.exec(out);
  const fail = /^# fail (\d+)/m.exec(out);
  const passed = pass ? Number(pass[1]) : 0;
  const failed = fail ? Number(fail[1]) : 0;
  return {
    // Neither counter present means the runner could not even parse the suite.
    collects: Boolean(pass || fail),
    tests_passed: passed,
    tests_failed: failed,
    tests_total: passed + failed,
    tests_tail: out.slice(-600),
  };
}

function changed(ws) {
  let out = "";
  try {
    out = execFileSync("git", ["status", "--porcelain"], { cwd: ws, encoding: "utf8" });
  } catch {
    return [];
  }
  const scaffold = [".claude/", ".claude", ".ck-selection.yaml", "CLAUDE.md", ".mcp.json"];
  return out
    .split("\n")
    .filter((l) => l.trim())
    .filter((l) => !scaffold.some((s) => l.slice(3).trim().replace(/^"|"$/g, "").startsWith(s)));
}

const baselines = {};
for (const name of fs.readdirSync(probeDir).sort()) {
  const d = path.join(probeDir, name);
  const probeFile = path.join(d, "probe.json");
  if (!fs.existsSync(probeFile)) continue;
  const ws = path.join(d, "workspace");
  if (!fs.existsSync(path.join(ws, "package.json")) || fs.existsSync(path.join(ws, "pyproject.toml"))) {
    continue; // not a node fixture; the python pass owns this one
  }
  const probe = JSON.parse(fs.readFileSync(probeFile, "utf8"));
  const fx = probe.fixture || "";
  if (fx && !baselines[fx]) {
    const src = path.join(REPO, "tests/evals/e2e/fixtures", fx);
    const tmp = path.join(probeDir, `.baseline-${fx}`);
    if (fs.existsSync(src)) {
      if (!fs.existsSync(tmp)) fs.cpSync(src, tmp, { recursive: true });
      baselines[fx] = counts(tmp);
    }
  }
  const ch = changed(ws);
  const rec = {
    workspace_present: true,
    baseline: baselines[fx] || null,
    ...counts(ws),
    changed_paths: ch.slice(0, 50),
    changed_count: ch.length,
    test_files_touched: ch.filter((x) => x.toLowerCase().includes("test")).length,
  };
  fs.writeFileSync(path.join(d, "oracle.json"), `${JSON.stringify(rec, null, 2)}\n`);
  console.log(
    `${name}: collects=${rec.collects} total=${rec.tests_total} failed=${rec.tests_failed} changed=${rec.changed_count}`,
  );
}
