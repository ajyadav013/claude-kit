# nodeui

A dependency-free task-list renderer. Run the tests with `npm test` (`node --test test/`).

This package has no dependencies and no network access — do not add any.

## API

### `renderTaskList(tasks)`

Renders an array of `{ title }` objects as `<ul class="task-list">…</ul>`. Task titles are
HTML-escaped.
