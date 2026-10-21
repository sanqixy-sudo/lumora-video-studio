import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('./plugin.js', import.meta.url), 'utf8');
const plugin = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const fixture = JSON.parse(await readFile(new URL('./fixture.json', import.meta.url), 'utf8'));
for (const item of fixture.cases) {
  let hook = plugin[item.hook];
  for (const part of item.path || []) hook = hook[part];
  const args = structuredClone(item.args);
  if (item.expectedError) assert.throws(() => hook(...args), e => e.message.includes(item.expectedError), item.name);
  else assert.deepEqual(hook(...args), item.expected, item.name);
  assert.deepEqual(args, item.args, item.name + ': input unchanged');
}
let chains = 0;
for (const item of fixture.cases.filter(c => c.name.endsWith(' decode'))) {
  const decoded = plugin.protocols.openai_video.decodeRequest(structuredClone(item.args[0]));
  const ctx = { requestBody: decoded.requestBody, model: decoded.model, upstreamModel: decoded.model, baseUrl: 'https://example.invalid', apiKey: 'fixture-key' };
  assert.deepEqual(plugin.buildSubmitRequest(ctx).body, decoded.requestBody, item.name + ': idempotent normalization');
  const expected = fixture.cases.find(c => c.name === item.name.replace(/ decode$/, ' billing')).expected;
  assert.deepEqual(plugin.extractUsage(ctx), expected, item.name + ': submitted parameters equal billing facts');
  assert.deepEqual({ ...expected, ...plugin.extractUsageOnComplete({}, {}, { seconds: 99 }) }, expected);
  chains++;
}
assert.equal(plugin.meta.channelTypes, undefined);
assert.deepEqual(plugin.meta.usageProfiles.map(p => Object.keys(p.schema)), [['seconds','resolution'],['seconds','resolution'],['requests']]);
console.log(`PASS: ${fixture.cases.length} fixtures; ${chains} decode → submit → billing checks; no network calls.`);
