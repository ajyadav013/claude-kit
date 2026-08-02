'use strict';

/** Escape the five characters that can break out of HTML text or an attribute value. */
function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** Render one task as a list item. */
function renderTask(task) {
  return `<li class="task">${escapeHtml(task.title)}</li>`;
}

/** Render a list of tasks as an unordered list. */
function renderTaskList(tasks) {
  return `<ul class="task-list">${tasks.map(renderTask).join('')}</ul>`;
}

module.exports = { renderTaskList, renderTask, escapeHtml };
