// Uses the existing New API frontend source, not a reimplementation of pricing.
// Optional argument: path to the matching New API web/src directory.
import { registerHooks, stripTypeScriptTypes } from 'node:module';
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';
registerHooks({
  resolve(specifier, context, next) {
    if (specifier.startsWith('.') && context.parentURL?.endsWith('.ts')) {
      const url = new URL(specifier + '.ts', context.parentURL);
      if (existsSync(fileURLToPath(url))) return { url: url.href, shortCircuit: true };
    }
    return next(specifier, context);
  },
  load(url, context, next) {
    if (url.endsWith('.ts')) return { format: 'module', source: stripTypeScriptTypes(readFileSync(fileURLToPath(url), 'utf8'), { mode: 'transform' }), shortCircuit: true };
    return next(url, context);
  },
});
const sourceRoot = path.resolve(process.argv[2] || 'runtime/new-api-readonly-source/full/web/src');
const moduleURL = name => pathToFileURL(path.join(sourceRoot, 'features/pricing/lib', name + '.ts')).href;
const { getTaskPricingDisplayTiers } = await import(moduleURL('task-matrix-display'));
const { createDefaultTaskMatrixConfig, taskMatrixToTiers, generateTaskExprFromConfig,
        getTaskNumberFields, evaluateTaskUsageExamples, tryParseTaskMatrixConfig } = await import(moduleURL('task-expr'));
const source = readFileSync(new URL('./plugin.js', import.meta.url), 'utf8');
const plugin = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const report = [];
for (const [index, profile] of plugin.meta.usageProfiles.entries()) {
  const schema = profile.schema;
  const fixed = index === 2;
  const field = fixed ? 'requests' : 'seconds';
  assert.deepEqual(getTaskNumberFields(schema).map(([key]) => key), [field]);
  const config = createDefaultTaskMatrixConfig(schema);
  assert.equal(config.rows.length, [2,3,1][index]);
  if (!fixed) assert.deepEqual(config.rows.map(row => row.combination.resolution), schema.resolution.enum);
  // Deliberately artificial test prices: never write these to an account.
  config.rows.forEach((row, i) => { row.unitPrices[field] = i + 2; row.constant = 0; });
  const expression = generateTaskExprFromConfig({ tiers: taskMatrixToTiers(config, schema) }, schema);
  assert.ok(expression.includes(`u("${field}")`));
  assert.ok(!expression.includes(`u("${fixed ? 'seconds' : 'requests'}")`));
  const tiers = getTaskPricingDisplayTiers(expression, schema);
  assert.equal(tiers.length, config.rows.length, 'price table expands every supported resolution');
  tiers.forEach((tier, i) => {
    assert.equal(tier.unitPrices[field], i + 2);
    assert.equal(tier.constant, 0);
    if (!fixed) assert.deepEqual(tier.conditions, [{field:'resolution',value:schema.resolution.enum[i]}]);
  });
  const roundTrip = tryParseTaskMatrixConfig(expression, schema);
  assert.ok(roundTrip, 'saved expression remains editable in visual editor');
  assert.deepEqual(roundTrip.rows.map(r => r.unitPrices[field]), config.rows.map(r => r.unitPrices[field]));
  const previews = evaluateTaskUsageExamples(expression, schema, profile.examples);
  assert.deepEqual(previews.map(p => p.total), config.rows.map((_, i) => (i + 2) * (fixed ? 1 : 6)));
  assert.equal(schema[field].unit, fixed ? 'count' : 'second');
  if (fixed) assert.equal(schema[field].unitLabel.zh, '次');
  assert.equal(schema[field].description.zh, fixed ? '生成次数' : '视频时长');
  report.push({ model: profile.models[0], rows: tiers.length, unit: fixed ? '次' : '秒', preview: previews.map(p => p.total) });
}
console.log('PASS: existing frontend editor, price table, expression round-trip and fee preview.');
console.log(JSON.stringify(report, null, 2));
