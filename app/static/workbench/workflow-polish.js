/* Small-screen filter disclosure keeps the original GET form and its values. */
(() => {
  function init() {
    if (!document.body.classList.contains('wb')) return;
    const mobile = matchMedia('(max-width:767px)');
    document.querySelectorAll('.wb-collection-page form.filter-bar').forEach((form,index) => {
      const button = document.createElement('button'); button.type='button'; button.className='wb-filter-toggle secondary-btn';
      form.id ||= 'collection-filter-' + index;
      button.setAttribute('aria-controls',form.id);
      const names = ['start_date','end_date','product_name','region_name'];
      const count = names.filter(name => form.elements.namedItem(name)?.value.trim()).length;
      let expanded = count > 0;
      function sync() {
        form.hidden = mobile.matches && !expanded;
        button.hidden = !mobile.matches;
        button.setAttribute('aria-expanded',String(!form.hidden));
        button.textContent = (expanded ? '收起筛选' : '展开筛选') + (count ? ` · ${count} 项已生效` : '');
      }
      form.before(button);button.addEventListener('click',()=>{expanded=!expanded;sync();});
      // A browser-restored invalid form must be operable even when initially collapsed.
      form.addEventListener('invalid',()=>{expanded=true;sync();},true);
      mobile.addEventListener('change',sync);sync();
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded',init,{once:true}); else init();
})();
