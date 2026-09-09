const {chromium}=require(process.env.SORA_PLAYWRIGHT||'C:/Users/sanqi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),path=require('node:path');
const base='http://127.0.0.1:8101',out='design/mature/evidence';fs.mkdirSync(out,{recursive:true});
(async()=>{const browser=await chromium.launch({headless:true});const context=await browser.newContext({reducedMotion:'reduce'});const page=await context.newPage();const errors=[],results=[];
 await context.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
 const routes=[['login','/login'],['create','/app'],['detail','/app/jobs/101/page?state=completed'],['users','/admin/users/page'],['usage','/admin/usage/monthly/page']];
 for(const theme of ['light','dark'])for(const width of (process.env.QUICK? [1440,390]:[375,390,768,1024,1440,1920,844])){
  await page.setViewportSize({width,height:width===844?390:width<768?844:1000});
  await page.addInitScript(t=>localStorage.setItem('sora.theme',t),theme);
  for(const [name,url]of routes){await page.goto(base+url);await page.waitForTimeout(100);
   if(name==='create'){await page.selectOption('#job-model-select','key:2:10');await page.fill('[name=product_name]','Lumora Studio');await page.fill('[name=region_name]','美国');await page.fill('[name=prompts]','雨夜城市，湿润的路面映出暖色灯光。镜头缓慢推进，路人撑伞走过街道，保持电影质感与自然的景深。');await page.click('[data-open-materials]');await page.locator('[data-preset-choice]').first().check();await page.click('#wb-apply-materials');}
   const metrics=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth+1,scrollWidth:document.documentElement.scrollWidth,width:innerWidth,bg:getComputedStyle(document.body).backgroundColor,body:getComputedStyle(document.body).fontSize,small:[...document.querySelectorAll('label,small,.muted,.field-hint')].filter(e=>e.getClientRects().length&&parseFloat(getComputedStyle(e).fontSize)<12).length}));
   let violations=[];if(width===1440||width===390){await page.addScriptTag({path:'runtime/axe.min.js'});violations=await page.evaluate(async()=>{const r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa','best-practice']}});return r.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))}));});await page.evaluate(()=>{document.activeElement?.blur();scrollTo(0,0);});await page.screenshot({path:path.join(out,`${name}-${theme}-${width}.png`),fullPage:true});}
   results.push({name,theme,width,...metrics,violations});console.log(name,theme,width,metrics.overflow?'OVERFLOW':'ok',violations.map(v=>v.id).join(','));
  }
 }
 fs.writeFileSync(path.join(out,'matrix.json'),JSON.stringify({results,errors},null,2));await browser.close();if(errors.length||results.some(r=>r.overflow||r.violations.length))process.exitCode=1;})();
