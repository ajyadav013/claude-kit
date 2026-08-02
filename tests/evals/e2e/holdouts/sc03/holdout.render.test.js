'use strict';

// SEALED HOLDOUT for SC-03 — never present in the performer's workspace during the session.
//
// The prompt states the empty-state requirement exactly, so a performer that reads the prompt can
// satisfy it. What the prompt does NOT restate is that the existing escaping contract must survive
// the change: a new branch in the renderer is exactly where escaping gets dropped. That is the
// regression this holdout exists to catch, alongside the feature itself.

const test = require('node:test');
const assert = require('node:assert');

const SRC = process.env.HOLDOUT_SRC || '/work/src/render';
const { renderTaskList, escapeHtml } = require(SRC);

test('empty list renders the empty state exactly', () => {
  assert.strictEqual(renderTaskList([]), '<p class="task-list-empty">No tasks yet</p>');
});

test('empty list does not render a list element at all', () => {
  assert.ok(!renderTaskList([]).includes('<ul'));
  assert.ok(!renderTaskList([]).includes('<li'));
});

test('non-empty rendering is unchanged', () => {
  assert.strictEqual(
    renderTaskList([{ title: 'Buy milk' }]),
    '<ul class="task-list"><li class="task">Buy milk</li></ul>'
  );
});

test('task titles are still escaped after the change', () => {
  const html = renderTaskList([{ title: '<script>alert(1)</script>' }]);
  assert.ok(!html.includes('<script>'), 'raw script tag survived escaping');
  assert.ok(html.includes('&lt;script&gt;'));
});

test('quotes and ampersands are still escaped', () => {
  assert.strictEqual(escapeHtml('a & "b" <c>'), 'a &amp; &quot;b&quot; &lt;c&gt;');
});

test('a list of one empty-titled task is still a list, not the empty state', () => {
  const html = renderTaskList([{ title: '' }]);
  assert.ok(html.startsWith('<ul class="task-list">'));
});
