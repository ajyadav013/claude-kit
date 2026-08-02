'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { sum } = require('./sum');

test('sums an empty array to zero', () => {
  assert.strictEqual(sum([]), 0);
});

test('sums positive and negative numbers', () => {
  assert.strictEqual(sum([1, 2, -3, 10]), 10);
});

test('rejects a non-array argument', () => {
  assert.throws(() => sum('nope'), TypeError);
});
