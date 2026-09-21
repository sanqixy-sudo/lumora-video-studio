/* Enhance date and month filters across the workbench; the original ISO-valued inputs still own submission. */
(() => {
function initDateControls() {
  if (!window.flatpickr) return;
  let calendarId = 0;
  document.querySelectorAll('.wb form').forEach(form => {
    const instances = new Map();
    function syncBounds() {
      const start = instances.get('start_date'), end = instances.get('end_date');
      if (!start || !end) return;
      start.set('maxDate', end.selectedDates[0] || null);
      end.set('minDate', start.selectedDates[0] || null);
    }
    form.querySelectorAll('input[type="date"],input[type="month"]').forEach(input => {
      if (input._flatpickr) return;
      const monthOnly = input.type === 'month';
      if (monthOnly && !window.monthSelectPlugin) return;
      const index = ++calendarId;
      const label = input.closest('label');
      const title = input.getAttribute('aria-label') || label?.querySelector('span')?.textContent.trim() || label?.textContent.trim() || '日期';
      const picker = flatpickr(input, {
        locale: {...flatpickr.l10ns.zh, firstDayOfWeek: 1},
        dateFormat: monthOnly ? 'Y-m' : 'Y-m-d', altInput: true, altFormat: monthOnly ? 'Y年m月' : 'Y年m月d日',
        plugins: monthOnly ? [new monthSelectPlugin({shorthand:false,dateFormat:'Y-m',altFormat:'Y年m月'})] : [],
        minDate: input.min || undefined, maxDate: input.max || undefined,
        altInputClass: 'lumora-date-input', ariaDateFormat: monthOnly ? 'Y年m月' : 'Y年m月d日',
        disableMobile: true, monthSelectorType: 'static', animate: false,
        onReady(_dates, _value, instance) {
          const calendar = instance.calendarContainer;
          calendar.classList.add('lumora-calendar');
          calendar.id = 'lumora-calendar-' + index;
          calendar.setAttribute('role', 'dialog');
          calendar.setAttribute('aria-label', title + '日历');
          instance.altInput.placeholder = '选择' + title;
          instance.altInput.setAttribute('aria-label', title);
          instance.altInput.setAttribute('aria-haspopup', 'dialog');
          instance.altInput.setAttribute('aria-controls', calendar.id);
          instance.altInput.setAttribute('aria-expanded', 'false');
          instance.currentYearElement.setAttribute('aria-label', '年份');
          label?.classList.add('date-field-ready');
          for (const [arrow, text] of [[instance.prevMonthNav, monthOnly ? '上一年' : '上个月'], [instance.nextMonthNav, monthOnly ? '下一年' : '下个月']]) {
            arrow.setAttribute('role', 'button');
            arrow.setAttribute('tabindex', '0');
            arrow.setAttribute('aria-label', text);
            arrow.addEventListener('keydown', event => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault(); event.stopPropagation(); arrow.click();
              }
            });
          }
          if (monthOnly) {
            const syncMonths = () => calendar.querySelectorAll('.flatpickr-monthSelect-month').forEach(cell => {
              cell.setAttribute('role', 'button');
              cell.setAttribute('aria-pressed', String(cell.classList.contains('selected')));
              cell.setAttribute('aria-disabled', String(cell.classList.contains('flatpickr-disabled')));
            });
            syncMonths();
            instance.config.onOpen.push(syncMonths);
            instance.config.onYearChange.push(syncMonths);
            instance.config.onValueUpdate.push(syncMonths);
            calendar.addEventListener('keydown', event => {
              if (event.key === ' ' && event.target.matches('.flatpickr-monthSelect-month')) {
                event.preventDefault(); event.target.click();
              }
            });
          }
          const footer = document.createElement('div');
          footer.className = 'calendar-footer';
          const help = document.createElement('span');
          help.textContent = '方向键选择 · Esc 关闭';
          const clear = document.createElement('button');
          clear.hidden = input.required; clear.type = 'button'; clear.textContent = '清除';
          clear.setAttribute('aria-label', '清除' + title);
          clear.addEventListener('click', () => {
            instance.clear(); instance.altInput.focus(); instance.close();
          });
          const today = document.createElement('button');
          today.type = 'button'; today.textContent = monthOnly ? '本月' : '今天';
          today.addEventListener('click', () => {
            if (instance.isEnabled(new Date(), true)) {
              instance.setDate(new Date(), true); instance.altInput.focus(); instance.close();
            }
          });
          footer.append(help, clear, today);
          calendar.append(footer);
          calendar.addEventListener('keydown', event => {
            if (event.key === 'Escape') {
              event.preventDefault(); event.stopPropagation();
              instance.altInput.focus(); instance.close();
            }
          }, true);
          instance.config.onOpen.push(() => {
            today.disabled = !instance.isEnabled(new Date(), true);
          });
        },
        onOpen(_dates, _value, instance) { instance.altInput.setAttribute('aria-expanded', 'true'); },
        onClose(_dates, _value, instance) { instance.altInput.setAttribute('aria-expanded', 'false'); },
        onChange: syncBounds,
      });
      instances.set(input.name, picker);
      addEventListener('resize', () => {
        picker.close();
        // Settle the outgoing surface before its old desktop position can overflow a narrow viewport.
        void picker.calendarContainer.offsetWidth;
        picker.calendarContainer.getAnimations().forEach(animation => animation.cancel());
      });
    });
    syncBounds();
  });
}
if (document.body) initDateControls();
else document.addEventListener('DOMContentLoaded', initDateControls, {once:true});
})();
