import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { afterEach, mock, test } from 'node:test';
import ts from 'typescript';

// Use the real client with a build-time env substitution, as Vite does.
const source = await readFile(new URL('../src/api/client.ts', import.meta.url), 'utf8');
const code = ts.transpileModule(source.replaceAll('import.meta.env', '{}'), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
let moduleId = 0;
const loadClient = () => import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}#${++moduleId}`);
afterEach(() => mock.restoreAll());

test('temporary startup failures preserve the saved session for retry', async () => {
  const client = await loadClient();
  client.setAuthToken('saved-token');
  mock.method(globalThis, 'fetch', async () => new Response('Unavailable', { status: 503 }));
  await assert.rejects(client.getCurrentUser(), (error) => error.status === 503);
  assert.equal(client.getAuthToken(), 'saved-token');
  mock.method(globalThis, 'fetch', async () => Response.json({ userId: 'user-1' }));
  assert.equal((await client.getCurrentUser()).userId, 'user-1');
});

test('a request that never returns is aborted with a useful error', async () => {
  const client = await loadClient();
  client.setAuthToken('saved-token');
  mock.method(globalThis, 'setTimeout', (callback) => { queueMicrotask(callback); return 1; });
  mock.method(globalThis, 'clearTimeout', () => {});
  mock.method(globalThis, 'fetch', (_url, { signal }) => new Promise((_resolve, reject) => {
    signal.addEventListener('abort', () => reject(signal.reason), { once: true });
  }));
  await assert.rejects(client.getCurrentUser(), /took too long/);
  assert.equal(client.getAuthToken(), 'saved-token');
});

test('timeout also covers a response whose body never finishes', async () => {
  const client = await loadClient();
  let expire;
  mock.method(globalThis, 'setTimeout', (callback) => { expire = callback; return 1; });
  mock.method(globalThis, 'clearTimeout', () => {});
  mock.method(globalThis, 'fetch', async (_url, { signal }) => ({
    ok: true, status: 200,
    json: () => new Promise((_resolve, reject) => {
      signal.addEventListener('abort', () => reject(signal.reason), { once: true });
      expire();
    }),
  }));
  await assert.rejects(client.getCurrentUser(), /took too long/);
});
