/* Recent field values are local to this browser and scoped to the signed-in account. */
(() => {
  function init() {
    const form=document.querySelector('#create-job-form[data-history-scope]');
    if(!form || !form.dataset.historyScope) return;
    for(const name of ['product_name','batch_name']) {
      const input=form.elements.namedItem(name);
      if(!input) continue;
      const key=`lumora.creation-history.v1.${form.dataset.historyScope}.${name}`;
      const valid=value=>typeof value==='string'&&value.trim().length>0&&value.trim().length<=input.maxLength;
      let values=[];
      try {const saved=JSON.parse(localStorage.getItem(key)||'[]');if(Array.isArray(saved))values=[...new Set(saved.filter(valid).map(v=>v.trim()))].slice(0,3);} catch(_) {}
      const wrapper=document.createElement('span');wrapper.className='wb-field-history';input.before(wrapper);wrapper.append(input);
      const menu=document.createElement('span');menu.className='wb-history-menu';menu.id=`history-${name}`;menu.hidden=true;menu.setAttribute('role','listbox');menu.setAttribute('aria-label','最近填写的记录');wrapper.append(menu);
      input.setAttribute('aria-label',name==='product_name'?'APP 名称':'批次名称');input.setAttribute('role','combobox');input.setAttribute('aria-autocomplete','none');input.setAttribute('aria-controls',menu.id);input.setAttribute('aria-expanded','false');input.setAttribute('aria-haspopup','listbox');
      let active=-1;
      function remember(){
        const value=input.value.trim();if(!valid(value))return;
        values=[value,...values.filter(v=>v!==value)].slice(0,3);
        try{localStorage.setItem(key,JSON.stringify(values));}catch(_){}
      }
      function close(){menu.hidden=true;input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');active=-1;}
      function choose(index){
        const value=values[index];if(!value)return;
        input.value=value;remember();close();input.focus({preventScroll:true});
        input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));
      }
      function open(){
        if(!values.length){close();return;}
        menu.replaceChildren();active=-1;
        values.forEach((value,index)=>{const option=document.createElement('span');option.className='wb-history-option';option.id=`${menu.id}-${index}`;option.setAttribute('role','option');option.setAttribute('aria-selected','false');option.textContent=value;option.addEventListener('pointerdown',event=>event.preventDefault());option.addEventListener('click',event=>{event.preventDefault();event.stopPropagation();choose(index);});menu.append(option);});
        menu.hidden=false;input.setAttribute('aria-expanded','true');
      }
      input.addEventListener('focus',open);input.addEventListener('click',()=>{if(menu.hidden)open();});
      input.addEventListener('input',close);
      input.addEventListener('blur',()=>{remember();close();});
      input.addEventListener('keydown',event=>{
        if(event.isComposing)return;
        if(event.key==='Escape'&&!menu.hidden){event.preventDefault();event.stopPropagation();close();return;}
        if(event.key==='ArrowDown'||event.key==='ArrowUp'){
          if(menu.hidden)open();if(menu.hidden)return;
          event.preventDefault();active=active<0?(event.key==='ArrowDown'?0:values.length-1):(active+(event.key==='ArrowDown'?1:-1)+values.length)%values.length;
          [...menu.children].forEach((option,index)=>option.setAttribute('aria-selected',String(index===active)));
          input.setAttribute('aria-activedescendant',menu.children[active].id);
        }else if(event.key==='Enter'&&!menu.hidden&&active>=0){event.preventDefault();choose(active);}
        else if(event.key==='Tab')close();
      });
      form.addEventListener('submit',remember);
      document.addEventListener('pointerdown',event=>{if(!wrapper.contains(event.target))close();});
    }
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
