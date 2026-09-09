// Mock-only behavioral checks for fixes that a static accessibility scan cannot prove.
const {chromium}=require(process.env.SORA_PLAYWRIGHT||'C:/Users/sanqi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true});const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'});const page=await context.newPage();const base='http://127.0.0.1:8100',checks=[],errors=[];
 await context.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());page.on('pageerror',e=>errors.push(e.message));
 async function check(name,run){await run();checks.push(name);console.log('PASS '+name);}
 async function scan(){await page.addScriptTag({path:'runtime/axe.min.js'});const result=await page.evaluate(async()=>{const r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa','best-practice']}});return r.violations.map(v=>({id:v.id,targets:v.nodes.map(n=>n.target)}));});assert.deepEqual(result,[]);}
 let allowLeave=false;page.on('dialog',d=>allowLeave?d.accept():d.dismiss());
 await check('失败保存保留输入和离页保护，成功保存解除当前表单保护',async()=>{
  await page.goto(base+'/admin/settings/page');await page.fill('[name=max_running_jobs]','17');
  const endpoint=base+'/admin/settings/update/form';
  await page.route(endpoint,r=>r.fulfill({status:200,contentType:'text/html',body:'<div class="login-alert">模拟保存失败，请重试。</div>'}));
  await page.click('.settings-form button[type=submit]');await page.locator('[data-form-error]').waitFor();
  assert.equal(await page.inputValue('[name=max_running_jobs]'),'17');
  const leaving=page.waitForEvent('dialog');await page.locator('a.wb-nav-link[href="/admin"]').click();assert.equal((await leaving).type(),'beforeunload');assert.match(page.url(),/settings/);
  await page.unroute(endpoint);await page.route(endpoint,r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({target:'/admin'})}));
  let unexpected=0;const count=()=>unexpected++;page.on('dialog',count);await page.click('.settings-form button[type=submit]');await page.waitForURL(base+'/admin');assert.equal(unexpected,0);page.off('dialog',count);await page.unroute(endpoint);
 });
 await check('字段错误关联提示，跨设置分组聚焦首个错误',async()=>{
  await page.goto(base+'/admin/settings/page');const endpoint=base+'/admin/settings/update/form';
  await page.fill('[name=max_running_jobs]','17');
  await page.route(endpoint,r=>r.fulfill({status:422,contentType:'application/json',body:JSON.stringify({detail:[{loc:['body','default_daily_job_limit'],msg:'请填写有效的每日上限。'}]})}));
  await page.click('.settings-form button[type=submit]');await page.locator('[aria-invalid=true]').waitFor();
  assert.equal(await page.evaluate(()=>document.activeElement.name),'default_daily_job_limit');const id=await page.getAttribute('[aria-invalid=true]','aria-describedby');assert.ok(await page.locator('#'+id).isVisible());await scan();
  // A repeated failure replaces its description rather than accumulating stale IDs.
  await page.click('.settings-form button[type=submit]');await page.waitForTimeout(50);assert.equal(await page.locator('.field-error').count(),1);await page.unroute(endpoint);allowLeave=true;
 });
 await check('手机抽屉和注册切换不自动打开输入键盘，Esc 返回来源',async()=>{
  await page.setViewportSize({width:390,height:844});await page.goto(base+'/admin/users/page');const trigger=page.locator('[data-open-drawer="wb-user-drawer"]');await trigger.click();assert.equal(await page.evaluate(()=>document.activeElement.tagName),'BUTTON');await scan();await page.keyboard.press('Escape');assert.ok(await trigger.evaluate(el=>el===document.activeElement));
  await page.goto(base+'/login');await page.click('[data-show-register]');assert.equal(await page.evaluate(()=>document.activeElement.id),'login-panel-title');await scan();
 });
 await check('100 条导入使用延迟渲染，动态输入命名可访问，键盘焦点不被提交栏遮挡',async()=>{
  await page.setViewportSize({width:1440,height:1000});await page.goto(base+'/app');await page.click('#batch-import-toggle');await page.fill('#batch-import-textarea',Array.from({length:100},(_,i)=>`场景 ${i+1}`).join('\n\n'));await page.click('#batch-import-apply');assert.equal(await page.locator('#prompt-list textarea').count(),100);assert.equal(await page.locator('#prompt-list.wb-large-list').count(),1);assert.equal(await page.locator('#prompt-list textarea:not([autocomplete])').count(),0);
  const last=page.locator('#prompt-list textarea').last();await last.focus();await page.waitForFunction(()=>{const all=document.querySelectorAll('#prompt-list textarea'),b=all[all.length-1].getBoundingClientRect(),f=document.querySelector('.wb-submit').getBoundingClientRect();return b.top>=56&&b.bottom<=f.top+2;},{},{timeout:2000});const box=await last.boundingBox(),footer=await page.locator('.wb-submit').boundingBox();assert.ok(box.y>=56&&box.y+box.height<=footer.y+2,JSON.stringify({box,footer}));
  await page.setViewportSize({width:390,height:844});await last.focus();await last.press('Shift+Tab');await page.waitForFunction(()=>{const b=document.activeElement.getBoundingClientRect();return b.top>=60&&b.bottom<=innerHeight;},{},{timeout:2000});const visible=await page.evaluate(()=>{const a=document.activeElement.getBoundingClientRect();return a.top>=60&&a.bottom<=innerHeight;});assert.ok(visible);
  await page.setViewportSize({width:1440,height:1000});const option=await page.locator('#job-model-select option[data-provider=veo_omni]').first().getAttribute('value');await page.selectOption('#job-model-select',option);await page.locator('#omni-material-card summary').click();await page.click('#omni-add-image');assert.equal(await page.locator('#omni-image-url-list input:not([autocomplete])').count(),0);await scan();
 });
 await check('最近任务阅读状态可以复制链接恢复，日期保留北京时间语义',async()=>{
  await page.goto(base+'/app');await page.locator('.wb-recent summary').click();await page.waitForTimeout(20);assert.match(page.url(),/panels=/);const url=page.url();await page.goto(url);assert.ok(await page.locator('.wb-recent').evaluate(el=>el.open));assert.match(await page.locator('.wb-recent time').first().getAttribute('datetime'),/\+08:00$/);assert.equal(await page.evaluate(()=>LumoraFormat.number(12345)),new Intl.NumberFormat('zh-CN').format(12345));
 });
 await check('预览使用原生按钮，空格键开关及焦点可用',async()=>{
  await page.goto(base+'/app/library/page');const shell=page.locator('button.plaza-video-shell').first();await shell.focus();await page.keyboard.press('Space');assert.equal(await page.locator('.plaza-inline-video:not(.hidden)').count(),1);await page.keyboard.press('Space');assert.equal(await page.locator('.plaza-inline-video:not(.hidden)').count(),0);
 });
 assert.deepEqual(errors,[]);fs.writeFileSync('runtime/guidelines_review/behaviors.json',JSON.stringify({checks,errors,passed:true},null,2));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
