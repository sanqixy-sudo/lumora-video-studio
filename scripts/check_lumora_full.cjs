const {chromium}=require(process.env.SORA_PLAYWRIGHT||'C:/Users/sanqi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const base='http://127.0.0.1:8100',out=path.resolve('runtime/lumora_review');fs.mkdirSync(out,{recursive:true});
(async()=>{
const browser=await chromium.launch({headless:true});const context=await browser.newContext({reducedMotion:'reduce'});
await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
const page=await context.newPage();page.on('dialog',dialog=>dialog.accept());const errors=[],failures=[],views=[];page.on('pageerror',e=>errors.push({url:page.url(),error:e.message}));
const routes=Object.keys(JSON.parse(fs.readFileSync('runtime/studio_preview/routes.json','utf8')));
for(const theme of ['light','dark'])for(const width of [375,390,768,1024,1440,1920]){
 await page.setViewportSize({width,height:1000});await page.addInitScript(t=>localStorage.setItem('sora.theme',t),theme);
 for(const route of routes){
  await page.goto(base+route);await page.waitForTimeout(30);
  const result=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth+2,oldStyles:[...document.styleSheets].map(s=>s.href).filter(s=>s&&/\/static\/(app|theme|components|studio)\.css/.test(s)),drawers:document.querySelectorAll('.wb-drawer').length,fields:[...document.querySelectorAll('.meta-grid .v,.wb-detail-fields dd')].filter(e=>e.getClientRects().length).map(e=>({width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height,text:e.textContent.trim().slice(0,100)}))}));
  views.push({route,theme,width,...result});if(result.overflow||result.oldStyles.length)failures.push({route,theme,width,...result});
  if([390,1440].includes(width))await page.screenshot({path:path.join(out,route.replaceAll('/','_')+'-'+theme+'-'+width+'.png'),fullPage:true});
 }
 console.log(`${theme} ${width}: ${routes.length} routes`);
}
fs.writeFileSync(path.join(out,'full-layout.json'),JSON.stringify({views,failures,errors},null,2));
console.log(JSON.stringify({views:views.length,failures,errors},null,2));await browser.close();if(failures.length||errors.length)process.exitCode=1;
})().catch(error=>{console.error(error);process.exit(1)});
