const {chromium}=require(process.env.SORA_PLAYWRIGHT||'C:/Users/sanqi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
function luminance(color){if(color.length===4)color='#'+[...color.slice(1)].map(c=>c+c).join('');return color.match(/[a-f\d]{2}/gi).map(v=>parseInt(v,16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);}
(async()=>{
 const browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000}});page.on('dialog',dialog=>dialog.accept());
 await page.goto('http://127.0.0.1:8100/design');await page.frameLocator('#new').locator('[data-login-form]').waitFor();await page.click('#compare');await page.frameLocator('#old').locator('form').first().waitFor();
 await page.selectOption('#route','/app');await page.frameLocator('#new').locator('#create-job-form').waitFor();await page.frameLocator('#old').locator('#create-job-form').waitFor();
 await page.goto('http://127.0.0.1:8100/app');const contrasts=[];
 for(const theme of ['light','dark']){
  await page.evaluate(t=>document.documentElement.dataset.theme=t,theme);
  const tokens=await page.evaluate(()=>{const style=getComputedStyle(document.documentElement);return Object.fromEntries(['bg','surface','inset','raised','ink','muted','faint','accent','on-accent','selection','success','success-bg','error','error-bg','warning','warning-bg'].map(name=>[name,style.getPropertyValue('--wb-'+name).trim()]));});
  const pairs=['bg','surface','inset','raised','selection'].flatMap(bg=>['ink','muted','faint'].map(fg=>[fg,bg]));pairs.push(['on-accent','accent'],['accent','surface'],['success','success-bg'],['error','error-bg'],['warning','warning-bg']);
  for(const [fg,bg] of pairs){const a=luminance(tokens[fg]),b=luminance(tokens[bg]),ratio=(Math.max(a,b)+.05)/(Math.min(a,b)+.05);contrasts.push({theme,fg,bg,ratio:Number(ratio.toFixed(2))});assert(ratio>=4.5,`${theme} ${fg}/${bg}: ${ratio}`);}
 }
 fs.writeFileSync('runtime/studio_review/delivery-report.json',JSON.stringify({reviewAndBaseline:'passed',contrasts,limits:['Token contrast pairs only; not a complete rendered-element contrast audit']},null,2));
 console.log(JSON.stringify({reviewAndBaseline:'passed',contrastPairs:contrasts.length,minimumContrast:Math.min(...contrasts.map(c=>c.ratio))}));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
