import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('./plugin.js', import.meta.url), 'utf8');
const plugin = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const fixture = JSON.parse(await readFile(new URL('./fixture.json', import.meta.url), 'utf8'));
for (const item of fixture.cases) {
  let hook = plugin[item.hook];
  for (const part of item.path || []) hook = hook[part];
  const args = structuredClone(item.args);
  if (item.expectedError) {
    assert.throws(() => hook(...args), e => e.message.includes(item.expectedError), item.name);
  } else {
    assert.deepEqual(hook(...args), item.expected, item.name);
  }
  assert.deepEqual(args, item.args, item.name + ': must not mutate input');
}
// Exercise both stages together: decode -> submit must preserve the entire JSON.
for (const item of fixture.cases.filter(c => c.name.endsWith(' decode'))) {
  const decoded = plugin.protocols.openai_video.decodeRequest(structuredClone(item.args[0]));
  const submitted = plugin.buildSubmitRequest({ requestBody: decoded.requestBody, upstreamModel: decoded.model, baseUrl: 'https://example.invalid', apiKey: 'fixture-key' });
  assert.deepEqual(submitted.body, item.args[0].body.value, item.name + ': end-to-end body');
}
assert.equal(plugin.meta.key, 'oaireg-flow-omni');
assert.equal(plugin.meta.name, 'oaireg flow omni 专用插件');
assert.equal(plugin.meta.channelTypes, undefined, 'must not override shared OpenAI channel type');
assert.deepEqual(Object.keys(plugin.meta.usageSchema), ['requests', 'mode'], 'Flow billing must expose requests and generation modes only');
assert.equal(plugin.meta.usageSchema.requests.unit, 'count');
assert.equal(plugin.meta.usageSchema.requests.unitLabel.zh, '次');
console.log(`PASS: ${fixture.cases.length} fixtures, 10 decode-to-submit cases; no network calls.`);
