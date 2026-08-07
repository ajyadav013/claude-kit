// Node fixture for the evaluation harness. Dependency-free on purpose: the harness proves Node
// tests run inside Docker, and an npm install would make that proof depend on network access.
'use strict';

function sum(values) {
  if (!Array.isArray(values)) {
    throw new TypeError('sum expects an array');
  }
  return values.reduce((total, n) => total + n, 0);
}

module.exports = { sum };
