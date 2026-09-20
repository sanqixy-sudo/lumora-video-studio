(() => {
  document.querySelectorAll('[data-password-toggle]').forEach(button => {
    button.addEventListener('click', () => {
      const input = document.getElementById(button.getAttribute('aria-controls'));
      const show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      button.textContent = show ? '隐藏' : '显示';
      button.setAttribute('aria-pressed', String(show));
      const label = document.querySelector(`label[for="${input.id}"]`).textContent;
      button.setAttribute('aria-label', (show ? '隐藏' : '显示') + label);
    });
  });
  const form = document.querySelector('[data-account-password]');
  if (form) {
    const password = form.elements.namedItem('new_password');
    const confirmation = form.elements.namedItem('confirm_password');
    function validate() {
      password.setCustomValidity(new TextEncoder().encode(password.value).length > 72 ? '新密码不能超过 72 字节，请减少字符数量' : '');
      confirmation.setCustomValidity(confirmation.value && confirmation.value !== password.value ? '两次输入的新密码不一致' : '');
    }
    password.addEventListener('input', validate);
    confirmation.addEventListener('input', validate);
  }
  const profile = document.querySelector('[data-account-profile]');
  profile?.addEventListener('input', () => profile.querySelector('[data-profile-saved]')?.remove());
})();
