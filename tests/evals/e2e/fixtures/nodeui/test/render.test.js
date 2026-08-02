'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { renderTaskList, escapeHtml } = require('../src/render');

test('renders one task', () => {
  assert.strictEqual(
    renderTaskList([{ title: 'Buy milk' }]),
    '<ul class="task-list"><li class="task">Buy milk</li></ul>'
  );
});

test('renders several tasks in order', () => {
  const html = renderTaskList([{ title: 'One' }, { title: 'Two' }]);
  assert.ok(html.indexOf('One') < html.indexOf('Two'));
});

test('escapes markup in a task title', () => {
  assert.strictEqual(escapeHtml('<b>&"hi"</b>'), '&lt;b&gt;&amp;&quot;hi&quot;&lt;/b&gt;');
});
