const {chromium} = require(process.env.SORA_PLAYWRIGHT || 'C:/Users/sanqi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<link rel="stylesheet" href="/static/workbench/form-controls.css">
<style>body{margin:0;font:14px sans-serif}.wb-drawer{position:fixed;left:auto;right:12px;top:12px;width:520px;height:calc(100vh - 24px);padding:24px;box-sizing:border-box;border:0;border-radius:16px}.wb-dialog-body{height:100%;overflow:auto}.provider-key-config-form{display:grid;gap:18px}.provider-key-config-form label{display:grid;gap:8px}input{height:42px}.wb-page-heading{padding:20px}</style>
</head><body class="wb"><section class="wb-page-heading"></section>
<form data-create-editor="新增渠道密钥" class="provider-key-config-form">
<label>名称<input name="name"></label><label>原始密钥<input name="raw_key"></label>
<label>调用地址<input name="api_base_url"></label>
<label>渠道<select name="provider_name"><option value="sora_api">Sora</option><option value="flow_omni">oaire-flow omni</option><option value="oaire_omni">oaire omni</option></select></label>
<label>权重<input name="weight"></label><label>日调用上限<input name="daily_limit"></label><label>渠道并发上限<input name="concurrent_limit"></label>
</form><script src="/static/workbench/collections.js"></script><script src="/static/workbench/interactions.js"></script><script src="/static/workbench/form-controls.js"></script></body></html>`;
(async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({viewport:{width:1920,height:911}});
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', route => {
      const pathname = new URL(route.request().url()).pathname;
      if (pathname === '/') return route.fulfill({contentType:'text/html',body:html});
      const file = path.resolve(root, 'app', pathname.slice(1));
      if (pathname.startsWith('/static/workbench/') && file.startsWith(path.resolve(root, 'app/static/workbench') + path.sep) && fs.existsSync(file)) {
        return route.fulfill({contentType:file.endsWith('.css')?'text/css':'text/javascript',body:fs.readFileSync(file)});
      }
      return route.fulfill({status:404,body:'Not found'});
    });
    await page.goto('http://local.test/');
    await page.getByRole('button',{name:'新增渠道密钥'}).click();
    const combo = page.getByRole('combobox',{name:'渠道'});
    const select = page.locator('form[data-create-editor] select[name=provider_name]');
    for (const [label,value] of [['oaire-flow omni','flow_omni'],['oaire omni','oaire_omni']]) {
      await combo.click();
      const option = page.getByRole('listbox').getByRole('option',{name:label,exact:true});
      await option.click();
      assert.equal(await select.inputValue(),value);
      assert.equal(await combo.getAttribute('aria-expanded'),'false');
    }
    assert.deepEqual(errors,[]);
    console.log('PASS: both oaire channels select inside the moved modal drawer');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
