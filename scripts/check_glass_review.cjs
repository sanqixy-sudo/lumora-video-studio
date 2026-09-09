const {chromium}=require(process.env.SORA_PLAYWRIGHT||'C:/Users/sanqi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch();try{
 const page=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'}),errors=[],requests=[];
 page.on('pageerror',e=>errors.push(e.message));await page.route('**/*',r=>new URL(r.request().url()).origin==='http://127.0.0.1:8101'?r.continue():r.abort());page.on('request',r=>{if(r.method()==='POST')requests.push(r.url());});
 await page.goto('http://127.0.0.1:8101/design');const frame=page.frameLocator('#new');await frame.locator('#prompt-list textarea').nth(2).waitFor();assert.equal(await frame.locator('#prompt-list textarea').count(),3);assert.equal(await frame.locator('#wb-selected-materials img').count(),1);assert.equal(requests.length,0);
 const materials=[];for(const theme of ['light','dark']){
  await page.addInitScript(t=>localStorage.setItem('sora.theme',t),theme);await page.goto('http://127.0.0.1:8101/app');
  const normal=await page.locator('.glass-workbench').evaluate(e=>({background:getComputedStyle(e).backgroundColor,blur:getComputedStyle(e).backdropFilter}));
  await page.emulateMedia({contrast:'more'});const solid=await page.locator('.glass-workbench').evaluate(e=>({background:getComputedStyle(e).backgroundColor,blur:getComputedStyle(e).backdropFilter}));assert.equal(solid.blur,'none');assert(!solid.background.startsWith('rgba'));materials.push({theme,normal,increasedContrast:solid});await page.emulateMedia({contrast:'no-preference'});
 }
 const additional=JSON.parse(fs.readFileSync('design/mature/evidence/additional.json'));assert(additional.every(x=>!x.overflow));for(const row of additional)for(const size of row.sizes||[])assert(size.width>=44&&size.height>=44,JSON.stringify(size));assert.deepEqual(errors,[]);
 fs.writeFileSync('design/mature/evidence/glass-review.json',JSON.stringify({passed:true,examplePrompts:3,exampleMaterials:1,initialPostRequests:requests.length,materials,errors},null,2));console.log('PASS review examples, no automatic submission, solid high-contrast fallback, equivalent zoom layouts and mobile primary targets');
 }finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
