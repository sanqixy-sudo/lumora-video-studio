const {chromium}=require(process.env.SORA_PLAYWRIGHT||'C:/Users/sanqi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const base='http://127.0.0.1:8100',out=path.resolve('runtime/lumora_review');
(async()=>{
const browser=await chromium.launch({headless:true});const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'});const page=await context.newPage();page.on('dialog',dialog=>dialog.accept());const errors=[],checks=[];page.on('pageerror',e=>errors.push(e.message));
await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
async function record(name,action){await action();checks.push(name);console.log('PASS '+name);}
await record('后台和个人素材的新建/修改抽屉，失败保留输入、重复提交防护、Esc 焦点返回',async()=>{
 for(const route of ['/app/reference-images/page','/admin/reference-images/page','/admin/provider-keys/page','/admin/quota-plans/page','/admin/risk-control/page']){
  await page.goto(base+route+'?scenario=error');const trigger=page.locator('.wb-create-launch');await trigger.click();const dialog=page.locator('dialog[open]');
  const fields=dialog.locator('input:not([type=hidden]),textarea');for(const field of await fields.all()){if(!await field.isVisible())continue;const type=await field.getAttribute('type'),name=await field.getAttribute('name');await field.fill(type==='number'?'10':type==='url'||name==='api_base_url'?'https://example.test/image.png':type==='password'?'mock-secret':`测试-${name}`);}
  let posts=0;const count=request=>{if(request.method()==='POST')posts++;};page.on('request',count);
  await dialog.locator('button[type=submit]').click({clickCount:2});await dialog.locator('[data-form-error]').waitFor();assert.equal(posts,1);page.off('request',count);
  assert.match(await fields.first().inputValue(),/测试|https/);assert.equal(await dialog.locator('button[type=submit]').isEnabled(),true);
  await page.keyboard.press('Escape');assert.equal(await trigger.evaluate(el=>el===document.activeElement),true);
  const edit=page.locator('.wb-main [data-open-drawer]:not(.wb-create-launch)').first();if(await edit.count()){await edit.click();assert.equal(await page.locator('dialog[open] form').count(),1);await page.keyboard.press('Escape');assert.equal(await edit.evaluate(el=>el===document.activeElement),true);}
 }
});
await record('系统设置跨分组保留、完整提交、保存失败恢复、键盘切换',async()=>{
 await page.goto(base+'/admin/settings/page?scenario=error');await page.fill('[name=max_running_jobs]','17');await page.click('[data-tab-target=settings-2]');await page.fill('[name=download_retry_delays_seconds]','5,10,20');await page.click('[data-tab-target=settings-3]');await page.fill('[name=default_daily_job_limit]','42');
 let body='';page.once('request',request=>{body=request.postData()||'';});await page.locator('.settings-form button[type=submit]').click();await page.locator('.settings-form [data-form-error]').waitFor();assert.match(body,/max_running_jobs/);assert.match(body,/17/);assert.match(body,/5,10,20/);assert.match(body,/default_daily_job_limit/);
 await page.click('[data-tab-target=settings-1]');assert.equal(await page.inputValue('[name=max_running_jobs]'),'17');await page.keyboard.press('ArrowRight');assert.equal(await page.locator('[data-tab-target=settings-2]').getAttribute('aria-selected'),'true');
});
await record('用户详情短编辑、账号删除确认校验、列表筛选返回',async()=>{
 await page.goto(base+'/admin/users/page?q=creator&status=active');await page.locator('.wb-user-table a[href="/admin/users/2/page"]').click();await page.waitForLoadState();const returnLink=page.getByRole('link',{name:'返回用户列表'});assert.match(await returnLink.getAttribute('href'),/q=creator/);
 await page.locator('.wb-editor-launch button').first().click();await page.locator('dialog[open] [name=display_name]').fill('修改后的名字');await page.keyboard.press('Escape');
 await page.locator('form[data-confirm-username] button').click();const confirmation=page.locator('.confirm-dialog[open]');assert.equal(await confirmation.locator('.danger-btn').isDisabled(),true);await confirmation.locator('input').fill('wrong');assert.equal(await confirmation.locator('.danger-btn').isDisabled(),true);await page.keyboard.press('Escape');
});
await record('作品当前页选择范围、预览播放、广场详情关闭后焦点返回',async()=>{
 await page.goto(base+'/app/library/page');assert.equal(await page.locator('.library-select-checkbox').count(),4);await page.check('#library-select-all');assert.match(await page.textContent('#library-selected-count'),/4/);await page.click('#library-clear-selection');assert.match(await page.textContent('#library-selected-count'),/0/);await page.locator('.library-select-checkbox').first().check();assert.match(await page.textContent('#library-selected-count'),/1/);
 await page.locator('button.plaza-preview-trigger').first().click();await page.waitForTimeout(300);assert.equal(await page.locator('.plaza-inline-video:not(.hidden)').count(),1);await page.locator('button.plaza-preview-trigger').first().click();assert.equal(await page.locator('.plaza-inline-video:not(.hidden)').count(),0);
 await page.goto(base+'/app/plaza/page');const trigger=page.locator('.plaza-open-btn').first();await trigger.click();await page.locator('#plaza-modal:not(.hidden)').waitFor();assert.equal(await page.locator('.wb-shell').evaluate(el=>el.inert),true);await page.keyboard.press('Escape');assert.equal(await page.locator('.wb-shell').evaluate(el=>el.inert),false);assert.equal(await trigger.evaluate(el=>el===document.activeElement),true);
});
await record('表格菜单不被裁切、缩小屏幕后移动导航可关闭',async()=>{
 await page.goto(base+'/admin/jobs/page');await page.locator('.wb-row-trigger').first().click();const menu=page.locator('body>.wb-menu-open');assert.equal(await menu.count(),1);const box=await menu.boundingBox();assert.ok(box.x>=0&&box.x+box.width<=1440&&box.y+box.height<=1000);await page.keyboard.press('Escape');
 await page.setViewportSize({width:390,height:844});await page.click('[data-open-nav]');await page.keyboard.press('Escape');assert.equal(await page.locator('dialog[open]').count(),0);
});
await record('无数据与筛选无结果、后台错误状态',async()=>{
 for(const route of ['/app/library/page','/app/jobs/page','/admin/risk-control/page','/admin/quota-plans/page','/admin/users/page']){await page.goto(base+route+'?state=empty');assert.equal(await page.locator('.empty-state,.empty-panel').first().isVisible(),true);assert.equal(await page.locator('dialog[open]').count(),0);}
 await page.goto(base+'/app/library/page?state=empty&product_name=missing');assert.match(await page.locator('.empty-state').textContent(),/筛选/);
 await page.goto(base+'/preview/access-denied');assert.match(await page.textContent('h1'),/无权访问/);
});
assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'interactions.json'),JSON.stringify({checks,errors,passed:true},null,2));await browser.close();
})().catch(error=>{console.error(error);process.exit(1)});
