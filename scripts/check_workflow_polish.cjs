const {chromium}=require('C:/Users/sanqi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
(async()=>{const b=await chromium.launch();try{fs.mkdirSync('runtime/workflows',{recursive:true});const p=await b.newPage({viewport:{width:1329,height:912}});const errors=[];p.on('pageerror',e=>errors.push(e.message));p.on('dialog',d=>d.dismiss());
await p.goto('http://127.0.0.1:8129/app');await p.waitForTimeout(300);
assert.match(await p.locator('#create-readiness').innerText(),/选择模型/);
await p.locator('#job-model-select').selectOption({index:1});await p.locator('[name=product_name]').fill('测试 APP');await p.locator('[name=region_name]').fill('美国');
await p.locator('button[type=submit]').last().click();await p.waitForTimeout(100);
assert.match(await p.locator('.field-error').innerText(),/提示词/);
assert.equal(await p.locator('textarea[name=prompts]').evaluate(e=>e===document.activeElement),true);
await p.locator('textarea[name=prompts]').fill('雨后的城市，镜头缓慢推进');assert.equal(await p.locator('.field-error').count(),0);assert.equal(await p.locator('#studio-form-error').isVisible(),false);
assert.equal(await p.locator('#create-readiness').getAttribute('data-ready'),'true');
await p.screenshot({path:'runtime/workflows/create-desktop.png'});
await p.route('**/app/jobs/batch',r=>r.fulfill({status:422,contentType:'application/json',body:JSON.stringify({detail:[{loc:['body','prompts',0],msg:'模拟校验失败，请补充描述。'}]})}));
await p.locator('#create-job-form button[type=submit]').click();await p.locator('.confirm-dialog .primary-btn').click();await p.locator('.field-error').waitFor();
assert.equal(await p.locator('textarea[name=prompts]').inputValue(),'雨后的城市，镜头缓慢推进');assert.equal(await p.locator('[name=product_name]').inputValue(),'测试 APP');assert.equal(await p.locator('#create-job-form button[type=submit]').isEnabled(),true);
await p.evaluate(()=>document.dispatchEvent(new CustomEvent('lumora:saved')));
await p.goto('http://127.0.0.1:8129/app/library/page');await p.locator('.library-select-checkbox').first().check();
assert.equal(await p.locator('#library-select-all').evaluate(e=>e.indeterminate),true);
assert.equal(await p.locator('.library-card-check').first().innerText(),'已选择');
await p.evaluate(()=>window.scrollTo(0,550));await p.waitForTimeout(200);const bar=await p.locator('[data-library-bulk-toolbar]').boundingBox();assert.ok(bar.y>=75&&bar.y<100,JSON.stringify(bar));
await p.screenshot({path:'runtime/workflows/library-selected.png'});
await p.locator('#library-clear-selection').click();assert.equal(await p.locator('.library-select-checkbox:checked').count(),0);assert.equal(await p.locator('#library-download-selected').isDisabled(),true);
await p.setViewportSize({width:390,height:844});await p.goto('http://127.0.0.1:8129/app/library/page');assert.equal(await p.locator('.filter-bar').isVisible(),false);await p.locator('.wb-filter-toggle').click();assert.equal(await p.locator('.filter-bar').isVisible(),true);await p.locator('[name=product_name]').fill('手机筛选');await p.locator('.wb-filter-toggle').click();await p.locator('.wb-filter-toggle').click();assert.equal(await p.locator('[name=product_name]').inputValue(),'手机筛选');
assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await p.screenshot({path:'runtime/workflows/library-mobile.png'});
for(const theme of ['light','dark'])for(const path of ['/app','/app/jobs/page','/app/jobs/101/page?state=failed','/app/plaza/page']){
 await p.goto('http://127.0.0.1:8129'+path);await p.evaluate(t=>document.documentElement.dataset.theme=t,theme);await p.waitForTimeout(200);assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,path+' overflow');
 if(path==='/app'){await p.locator('[data-create-step=prompts]').click();const input=await p.locator('textarea[name=prompts]').boundingBox(),footer=await p.locator('.wb-submit').boundingBox();assert.ok(input.y<footer.y&&input.y+input.height<=footer.y+1,JSON.stringify({input,footer}));}
 await p.screenshot({path:'runtime/workflows/'+theme+path.replaceAll('/','_').replaceAll('?','_')+'.png'});
}
// Required material guidance follows the selected provider; short screens remain usable.
await p.goto('http://127.0.0.1:8129/app');
await p.locator('#job-model-select').selectOption(await p.locator('#job-model-select option[data-provider=veo_omni]').first().getAttribute('value'));
assert.match(await p.locator('#create-readiness').innerText(),/参考图/);
assert.match(await p.locator('#material-step-hint').innerText(),/必需/);
for(const size of [{width:320,height:640},{width:390,height:400}]){
 await p.setViewportSize(size);await p.locator('[data-create-step=prompts]').click();
 assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 await p.locator('#create-job-form button[type=submit]').scrollIntoViewIfNeeded();const rect=await p.locator('#create-job-form button[type=submit]').boundingBox();assert.ok(rect.y>=0 && rect.y+rect.height<=size.height+1);
}
await p.evaluate(()=>document.dispatchEvent(new CustomEvent('lumora:saved')));
await p.setViewportSize({width:390,height:844});await p.goto('http://127.0.0.1:8129/app/jobs/101/page?state=failed');
const statusBox=await p.locator('.wb-task-status').boundingBox(),mediaBox=await p.locator('.wb-result-media').boundingBox();assert.ok(statusBox.y<mediaBox.y,'failure recovery precedes portrait preview');
await p.route('**/app/jobs/101**',r=>r.request().method()==='POST'?r.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'模拟重试失败，请稍后重试。'})}):r.continue());
await p.locator('#resume-btn').click();await p.locator('.confirm-dialog .primary-btn').click();await p.locator('#job-action-error:not(.hidden)').waitFor();assert.match(await p.locator('#job-action-error').innerText(),/模拟重试失败/);assert.equal(await p.locator('#resume-btn').isEnabled(),true);
await p.waitForTimeout(250);await p.evaluate(()=>scrollTo(0,0));await p.screenshot({path:'runtime/workflows/recovery-mobile.png'});
// Shared form mapping handles repeated fields, custom select triggers and password wrappers.
await p.goto('http://127.0.0.1:8129/app');
await p.evaluate(()=>{
 const form=document.querySelector('#create-job-form');
 const error=new Error('字段错误');error.detail=[{loc:['body','model_choice'],msg:'选择可用模型'}];SoraUI.formError(form,error);
});
assert.equal(await p.locator('#job-model-select').locator('..').locator('.soft-select-trigger').getAttribute('aria-invalid'),'true');
await p.locator('#job-model-select').selectOption({index:1});assert.equal(await p.locator('.field-error').count(),0);
await p.evaluate(()=>document.dispatchEvent(new CustomEvent('lumora:saved')));await p.goto('http://127.0.0.1:8129/login');await p.locator('[data-login-form] [name=password]').fill('');await p.locator('[data-login-form] button[type=submit]').click();assert.equal(await p.locator('[data-login-form] .field-error').count()>0,true);
assert.deepEqual(errors,[]);console.log('PASS: creation guidance, inline errors/focus, failed submission retains input, selected card/sticky toolbar, filter disclosure and responsive light/dark pages.');}finally{await b.close();}})().catch(e=>{console.error(e);process.exitCode=1});
