/* Run against scripts/preview_studio.py only; no generation/auth requests. */
const {chromium}=require(process.env.SORA_PLAYWRIGHT || 'C:/Users/sanqi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict');
const base=process.env.SORA_PREVIEW_URL || 'http://127.0.0.1:8129';
(async()=>{
 const browser=await chromium.launch();
 try {
  const page=await browser.newPage({viewport:{width:1329,height:912}});
  const errors=[]; page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/app');
  const model=page.getByRole('combobox',{name:'生成模型',exact:true});
  await model.click(); await page.getByRole('option',{name:/VEO Omni/}).click();
  assert.equal(await page.locator('#job-seconds-select').inputValue(),'10');
  const saved=await page.locator('#job-model-select').inputValue();
  await model.press('ArrowDown');await model.press('End');await model.press('Escape');
  assert.equal(await page.locator('#job-model-select').inputValue(),saved);
  await model.press('s');await model.press('Enter');assert.equal(await page.locator('#job-seconds-select').inputValue(),'12');
  for (const width of [390,320]) {
   await page.setViewportSize({width,height:844});await model.click();
   const r=await page.getByRole('listbox').boundingBox();assert.ok(r.x>=0&&r.x+r.width<=width+1);
   await model.press('Escape');
  }
  await page.setViewportSize({width:1329,height:912});
  await page.goto(base+'/admin/usage/monthly/page');
  const month=page.getByRole('textbox',{name:'报表月份',exact:true});
  await month.click();await page.locator('.lumora-calendar.open .flatpickr-monthSelect-month').nth(2).click();
  assert.match(await page.locator('.compact-month-form input[name=month]').inputValue(),/-03$/);
  await month.click();await month.press('ArrowRight');await page.keyboard.press('Enter');
  assert.match(await page.locator('.compact-month-form input[name=month]').inputValue(),/-04$/);
  assert.equal(await page.evaluate(()=>new FormData(document.querySelector('.compact-month-form')).getAll('month').length),1);
  const html='<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><link rel="stylesheet" href="/static/mature/tokens.css"><link rel="stylesheet" href="/static/workbench/form-controls.css"></head><body class="wb"><form id="test"><label for="choice">测试选择</label><select id="choice" name="choice" required><option value="">请选择</option><optgroup label="可用"><option value="a">Alpha</option><option disabled value="b">Beta</option><option value="c">Charlie</option></optgroup><optgroup disabled label="停用"><option value="d">Delta</option></optgroup></select><button type="reset">重置</button><input name="after" aria-label="下一项"><fieldset id="fieldset"><label>开关<select name="toggle"><option>开</option><option>关</option></select></label></fieldset></form><dialog id="dialog"><label>弹窗选项<select name="dialog-choice"><option>一</option><option>二</option></select></label></dialog><form method="get" data-per-page-form><input type="hidden" name="page" value="1"><label>每页<select name="per_page" data-per-page-select><option value="12">12 条</option><option value="48">48 条</option></select></label></form><script src="/static/app.js"></script><script src="/static/workbench/form-controls.js"></script></body></html>';
  await page.route('**/preview-controls-test*',r=>r.fulfill({contentType:'text/html',body:html}));
  await page.goto(base+'/preview-controls-test');
  const perPage=page.getByRole('combobox',{name:'每页',exact:true});
  await perPage.click();const last=page.getByRole('listbox').getByRole('option').last();
  const perValue=(await last.textContent()).match(/\d+/)[0];await last.click();
  await page.waitForURL(url=>url.searchParams.get('per_page')===perValue);

  const choice=page.getByRole('combobox',{name:'测试选择',exact:true});
  assert.equal(await page.evaluate(()=>document.querySelector('#test').reportValidity()),false);
  assert.equal(await choice.getAttribute('aria-invalid'),'true');
  assert.equal(await choice.evaluate(e=>e===document.activeElement),true);
  await choice.press('Home');await choice.press('ArrowDown');await choice.press('ArrowDown');
  await choice.press('Tab');assert.equal(await page.locator('#choice').inputValue(),'c');
  assert.equal(await page.getByRole('button',{name:'重置'}).evaluate(e=>e===document.activeElement),true);
  assert.equal(await page.evaluate(()=>new FormData(document.querySelector('#test')).getAll('choice').length),1);
  await page.getByRole('button',{name:'重置'}).click();await page.waitForFunction(()=>document.querySelector('#choice').nextElementSibling.textContent.includes('请选择'));assert.equal(await page.locator('#choice').inputValue(),'');assert.match(await choice.textContent(),/请选择/);
  await page.evaluate(()=>document.querySelector('#fieldset').disabled=true);
  assert.equal(await page.getByRole('combobox',{name:'开关',exact:true}).getAttribute('aria-disabled'),'true');
  assert.equal(await page.getByRole('combobox',{name:'开关',exact:true}).getAttribute('tabindex'),'-1');
  await page.evaluate(()=>{const s=document.querySelector('#choice');for(let i=0;i<60;i++)s.add(new Option('很长的选项 <img src=x onerror=alert(1)> '+i,'item-'+i));});
  await choice.press('End');
  assert.equal(await page.getByRole('listbox').locator('img').count(),0);
  assert.ok(await page.getByRole('listbox').evaluate(e=>e.scrollTop>0));
  await choice.press('Enter');assert.equal(await page.locator('#choice').inputValue(),'item-59');
  const frames=await choice.evaluate(async trigger=>{
    const menu=document.getElementById(trigger.getAttribute('aria-controls')),values=[];
    trigger.click();for(let i=0;i<14;i++){await new Promise(requestAnimationFrame);values.push(+getComputedStyle(menu).opacity)}return values;
  });
  assert.ok(frames.some(x=>x>0&&x<1),'opening opacity interpolates');
  const closing=await choice.evaluate(async trigger=>{
    const menu=document.getElementById(trigger.getAttribute('aria-controls')),values=[];
    trigger.click();for(let i=0;i<12;i++){await new Promise(requestAnimationFrame);values.push(+getComputedStyle(menu).opacity)}return values;
  });
  assert.ok(closing.some(x=>x>0&&x<1),'closing opacity interpolates');
  await page.evaluate(()=>document.querySelector('#dialog').showModal());
  const dialogChoice=page.getByRole('combobox',{name:'弹窗选项',exact:true});
  await dialogChoice.click();await page.getByRole('option',{name:'二',exact:true}).click();
  assert.equal(await page.locator('select[name=dialog-choice]').inputValue(),'二');await page.evaluate(()=>document.querySelector('#dialog').close());
  await page.emulateMedia({reducedMotion:'reduce'});await choice.click();
  assert.equal(await page.getByRole('listbox').evaluate(e=>e.getAnimations().length),0);await choice.press('Escape');
  await page.emulateMedia({forcedColors:'active'});await choice.click();
  assert.notEqual(await page.getByRole('listbox').getByRole('option',{selected:true}).evaluate(e=>getComputedStyle(e).outlineStyle),'none');await choice.press('Escape');
  assert.deepEqual(errors,[]);
  console.log('PASS: model linkage, grouped options, keyboard/Escape/typeahead/Tab, pagination navigation, month keyboard/ISO, 320px, validation, reset, disabled fieldset/options, long list scrolling/escaping, opening/closing motion, modal dialog, reduced motion, forced colors.');
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
