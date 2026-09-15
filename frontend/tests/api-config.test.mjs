import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../src/lib/api-config.js', import.meta.url), 'utf8');
const { resolveApiConfig } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
for (const value of [undefined, '', ' ', 'undefined', 'not-a-url', 'https://api.example.test/api', 'https://user:secret@api.example.test', 'https://api.example.test?key=secret', 'https://api.example.test#token', 'http://api.example.test', 'http://localhost:8000']) {
  test(`reject production backend: ${String(value)}`, () => {
    const actual = resolveApiConfig(value, true);
    assert.equal(actual.baseURL, null);
    assert.ok(actual.error);
  });
}
test('normalizes a valid production origin', () => {
  assert.deepEqual(resolveApiConfig(' https://api.example.test/// ', true), {baseURL:'https://api.example.test/api', error:null});
});
test('permits HTTP localhost only in development', () => {
  assert.equal(resolveApiConfig('http://localhost:8000', false).baseURL, 'http://localhost:8000/api');
});
