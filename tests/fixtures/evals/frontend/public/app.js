'use strict';

const list = document.getElementById('items');
const statusLine = document.getElementById('status-line');
const select = document.getElementById('status');

async function load() {
  const query = select.value ? `?status=${encodeURIComponent(select.value)}` : '';
  statusLine.textContent = 'Loading…';
  try {
    const res = await fetch(`/api/items${query}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    list.replaceChildren(
      ...data.items.map((item) => {
        const li = document.createElement('li');
        const title = document.createElement('span');
        title.textContent = item.title;
        const status = document.createElement('span');
        status.className = 'status';
        status.textContent = ` ${item.status}`;
        li.append(title, status);
        return li;
      }),
    );
    statusLine.textContent = `${data.count} item(s)`;
  } catch (err) {
    statusLine.textContent = `Failed to load: ${err.message}`;
  }
}

document.getElementById('reload').addEventListener('click', load);
select.addEventListener('change', load);
load();
