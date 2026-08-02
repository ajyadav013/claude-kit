'use strict';

// Deterministic oracle for SC-03 — easy frontend feature.
//
// Runs inside the Node container against the scenario's end state, after the child session has
// finished. Nothing here is judged by a model: every assertion is a file hash, a JSON field, or a
// real `node --test` exit code.
//
// Two things make this harder to game than "does the empty state render":
//
//   * the ORIGINAL tests are re-run against the FINAL source, via a regression directory whose
//     `src` is a symlink to the live tree — so a performer that rewrites the fixture's tests to
//     suit its implementation changes nothing the oracle looks at;
//   * the sealed holdout (absent during the session) re-checks the ESCAPING contract, which the
//     prompt never restates. Adding a branch to a renderer is exactly where escaping gets dropped.
//
// Usage: node sc03_frontend_feature.js <workdir>   (exit 0 = PASS, 1 = FAIL; prints JSON)

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');

const work = process.argv[2];
const scen = path.join(work, '.scenario');
const pristine = path.join(scen, 'pristine');
const checks = [];

const check = (name, ok, detail) => checks.push({ check: name, pass: Boolean(ok), detail });
const sha = (p) => crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');

function walk(dir, base = dir, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    const rel = path.relative(base, full);
    if (rel.startsWith('.git' + path.sep) || rel === '.git') continue;
    if (rel.startsWith('.scenario')) continue;
    if (entry.isDirectory()) walk(full, base, out);
    else if (entry.isFile()) out.push(rel);
  }
  return out;
}

// `node --test <dir>` does not scan directories in this image — it tries to require the directory
// as a module and reports one synthetic failing test, which is indistinguishable from a real
// failure unless you read the stack. Test files are therefore enumerated and passed explicitly.
function nodeTest(dir) {
  const files = walk(dir)
    .filter((rel) => rel.endsWith('.test.js'))
    .map((rel) => path.join(dir, rel))
    .sort();
  if (files.length === 0) {
    return { status: 1, stdout: '', stderr: `no *.test.js files found under ${dir}` };
  }
  return spawnSync(process.execPath, ['--test', ...files], {
    cwd: work,
    encoding: 'utf8',
    env: { ...process.env, HOLDOUT_SRC: path.join(work, 'src', 'render') },
  });
}

// TAP's last lines are always the counters, which say nothing about WHAT failed. Prefer the
// failure lines when there are any.
const tail = (r, n = 4) => {
  const text = (r.stdout || '') + (r.stderr || '');
  const signal = text.split('\n').filter((l) => /^\s*(not ok |Error:|AssertionError)/.test(l));
  const lines = signal.length ? signal : text.trim().split('\n').slice(-n);
  return lines.slice(0, n).join(' | ').slice(0, 400);
};

// --- 1. the original tests, run against the FINAL source -------------------------------------
// The fixture's tests `require('../src/render')`. Copying them next to a symlinked `src` makes
// that relative path resolve to the live tree instead of the pristine copy.
const regression = path.join(scen, 'regression');
fs.rmSync(regression, { recursive: true, force: true });
fs.mkdirSync(regression, { recursive: true });
fs.cpSync(path.join(pristine, 'test'), path.join(regression, 'test'), { recursive: true });
fs.symlinkSync(path.join(work, 'src'), path.join(regression, 'src'));

const original = nodeTest(path.join(regression, 'test'));
check(
  'original_tests_pass',
  original.status === 0,
  `pristine suite exit ${original.status}: ${tail(original)}`
);

// --- 2. the sealed holdout ----------------------------------------------------------------------
const holdout = nodeTest(path.join(scen, 'holdout'));
check(
  'sealed_holdout_passes',
  holdout.status === 0,
  holdout.status === 0
    ? 'empty state renders exactly, and escaping survived the change'
    : `holdout exit ${holdout.status}: ${tail(holdout, 6)}`
);

// --- 3. the feature landed in source ------------------------------------------------------------
const manifest = JSON.parse(fs.readFileSync(path.join(scen, 'manifest.json'), 'utf8'));
const present = Object.fromEntries(walk(work).map((rel) => [rel, sha(path.join(work, rel))]));
const changed = Object.keys(manifest).filter((f) => present[f] !== manifest[f]);
const added = Object.keys(present).filter((f) => !(f in manifest));

check(
  'feature_landed_in_source',
  changed.includes('src/render.js'),
  changed.includes('src/render.js')
    ? 'src/render.js was modified'
    : `src/render.js was never touched; changed: ${changed.slice(0, 8).join(', ')}`
);

// --- 4. did the pipeline write a test for its own feature? ---------------------------------------
// The prompt does not ask for tests. The kit claims a testing gate, so shipping a new branch with
// no coverage is a finding about the KIT, not about the task — reported as its own check so a
// failure here is never confused with a failure of the feature itself.
const touchedTests = [...changed, ...added].filter((f) => f.startsWith('test/'));
check(
  'pipeline_added_its_own_tests',
  touchedTests.length > 0,
  touchedTests.length
    ? `test files written by the run: ${touchedTests.join(', ')}`
    : 'the run shipped a new code path and added no test for it'
);

// --- 5. no dependencies, no strays ----------------------------------------------------------------
let depsClean = false;
let depsDetail = 'package.json is unreadable or malformed';
try {
  const pkg = JSON.parse(fs.readFileSync(path.join(work, 'package.json'), 'utf8'));
  const deps = { ...(pkg.dependencies || {}), ...(pkg.devDependencies || {}) };
  const hasModules = fs.existsSync(path.join(work, 'node_modules'));
  depsClean = Object.keys(deps).length === 0 && !hasModules;
  depsDetail = depsClean
    ? 'still dependency-free'
    : `dependencies added: ${Object.keys(deps).join(', ') || '(none)'}${hasModules ? ' + node_modules/' : ''}`;
} catch (e) {
  depsDetail = `package.json: ${e.message}`;
}
check('no_dependencies_added', depsClean, depsDetail);

const allowed = ['.claude/', 'src/', 'test/', 'docs/', 'README.md'];
const stray = [...changed, ...added].filter((f) => !allowed.some((a) => f.startsWith(a)));
check(
  'no_stray_artifacts',
  stray.length === 0,
  stray.length ? `unexpected changes: ${stray.slice(0, 8).join(', ')}` : 'no unexpected files'
);

const verdict = {
  scenario: 'SC-03',
  oracle: 'sc03_frontend_feature',
  pass: checks.every((c) => c.pass),
  checks,
};
console.log(JSON.stringify(verdict, null, 2));
process.exit(verdict.pass ? 0 : 1);
