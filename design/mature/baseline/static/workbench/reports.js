/* Monthly usage stays a native table; arrow keys help operate its dense editable cells. */
document.addEventListener('DOMContentLoaded',()=>{
 const table=document.querySelector('.usage-table');if(!table)return;
 const wrap=table.closest('.usage-table-wrap'),month=table.dataset.month;
 const heads=[...table.querySelectorAll('thead [data-day]')],rows=[...table.querySelectorAll('tbody tr')];
 const digits=[...table.querySelectorAll('.usage-cell')].reduce((max,cell)=>Math.max(max,cell.textContent.trim().length),1);table.closest('.usage-report-card').style.setProperty('--usage-digit-width',`${digits*7+4}px`);
 const weekday=new Intl.DateTimeFormat('zh-CN',{weekday:'short',timeZone:'UTC'});
 heads.forEach((head,index)=>{const day=Number(head.dataset.day),date=new Date(`${month}-${String(day).padStart(2,'0')}T00:00:00Z`);if(Number.isNaN(date.getTime()))return;head.querySelector('small').textContent=weekday.format(date).replace('周','');head.setAttribute('aria-label',`${month}-${day}，${weekday.format(date)}`);if([0,6].includes(date.getUTCDay()))head.dataset.weekend='';if(date.getUTCDay()===1){head.dataset.weekStart='';rows.forEach(row=>{if(row.children[index+2])row.children[index+2].dataset.weekStart='';});}});
 const buttons=[...table.querySelectorAll('.usage-edit-btn')];buttons.forEach((button,index)=>button.tabIndex=index===0?0:-1);
 let current=buttons[0];
 table.addEventListener('focusin',event=>{const button=event.target.closest('.usage-edit-btn');if(!button)return;if(current&&current!==button)current.tabIndex=-1;current=button;current.tabIndex=0;});
 table.addEventListener('keydown',event=>{const button=event.target.closest('.usage-edit-btn');if(!button)return;const index=buttons.indexOf(button),columns=heads.length;let next;if(event.key==='ArrowRight')next=index+1;else if(event.key==='ArrowLeft')next=index-1;else if(event.key==='ArrowDown')next=index+columns;else if(event.key==='ArrowUp')next=index-columns;else if(event.key==='Home')next=event.ctrlKey?0:index-index%columns;else if(event.key==='End')next=event.ctrlKey?buttons.length-1:index-index%columns+columns-1;else return;event.preventDefault();buttons[Math.max(0,Math.min(buttons.length-1,next))]?.focus();});
 const nav=document.querySelector('.usage-scroll-actions'),previous=document.querySelector('[data-usage-scroll="-1"]'),next=document.querySelector('[data-usage-scroll="1"]'),range=document.getElementById('usage-date-range');
 let frame;
 function sync(){frame=null;const overflow=wrap.scrollWidth>wrap.clientWidth+2;nav.hidden=!overflow;if(!overflow){range.textContent=`1–${heads.length} 日 · ${heads.length} 天`;return;}const bounds=wrap.getBoundingClientRect(),fixed=Number.parseFloat(getComputedStyle(table).getPropertyValue('--usage-user'))+Number.parseFloat(getComputedStyle(table).getPropertyValue('--usage-total'));const visible=heads.filter(head=>{const r=head.getBoundingClientRect();return r.right>bounds.left+fixed+2&&r.left<bounds.right-2;});range.textContent=visible.length?`${visible[0].dataset.day}–${visible.at(-1).dataset.day} 日 · 共 ${heads.length} 天`:`共 ${heads.length} 天`;previous.disabled=wrap.scrollLeft<2;next.disabled=wrap.scrollLeft+wrap.clientWidth>=wrap.scrollWidth-2;}
 function schedule(){if(!frame)frame=requestAnimationFrame(sync);}
 wrap.addEventListener('scroll',schedule,{passive:true});new ResizeObserver(schedule).observe(wrap);
 document.querySelectorAll('[data-usage-scroll]').forEach(button=>button.addEventListener('click',()=>{const dayWidth=heads[0]?.getBoundingClientRect().width||28;wrap.scrollBy({left:Number(button.dataset.usageScroll)*Math.min(dayWidth*7,Math.max(dayWidth,wrap.clientWidth-200)),behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});}));
 sync();
});
