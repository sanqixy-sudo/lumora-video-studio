const {chromium} = require(process.env.SORA_PLAYWRIGHT || 'C:/Users/sanqi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const {spawn} = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const assert = require('node:assert/strict');

const python = process.env.SORA_TEST_PYTHON || path.resolve('.venv/Scripts/python.exe');
const oldPassword = ' old-password ';
const newPassword = ' new-password ';
const output = path.resolve('runtime/account-settings');
const bootstrap = [
  "import sys, socket",
  "sys.path.insert(0, 'tests')",
  "from account_settings_support import AccountTestEnvironment",
  "import uvicorn",
  "env = AccountTestEnvironment()",
  "sock = socket.socket()",
  "sock.bind(('127.0.0.1', 0))",
  "print('READY:' + str(sock.getsockname()[1]), flush=True)",
  "uvicorn.Server(uvicorn.Config(env.app, log_level='error')).run(sockets=[sock])",
].join('\n');

async function main() {
  fs.mkdirSync(output, {recursive:true});
  const server = spawn(python, ['-B', '-c', bootstrap], {windowsHide:true, env:{...process.env, PYTHONIOENCODING:'utf-8'}});
  let browser;
  try {
    const base = await new Promise((resolve, reject) => {
      let stdout = '', stderr = '';
      const timer = setTimeout(() => reject(new Error('Test server startup timed out: ' + stderr)), 15000);
      server.stderr.on('data', data => {stderr += data;});
      server.stdout.on('data', data => {
        stdout += data;
        const match = stdout.match(/READY:(\d+)/);
        if (match) {clearTimeout(timer); resolve('http://127.0.0.1:' + match[1]);}
      });
      server.once('exit', code => {clearTimeout(timer); reject(new Error('Test server exited ' + code + ': ' + stderr));});
    });
    for (let attempt = 0; ; attempt++) {
      try {await fetch(base + '/login'); break;}
      catch (error) {if (attempt === 50) throw error; await new Promise(resolve => setTimeout(resolve, 100));}
    }
    browser = await chromium.launch();
    const context = await browser.newContext({reducedMotion:'reduce'});
    await context.route('**/*', route => new URL(route.request().url()).origin === base ? route.continue() : route.abort());
    const login = await context.request.post(base + '/auth/login-browser', {data:{username:'creator', password:oldPassword}});
    assert.equal(login.status(), 200);
    const second = await browser.newContext();
    assert.equal((await second.request.post(base + '/auth/login-browser', {data:{username:'creator', password:oldPassword}})).status(), 200);
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    // Stress the header and popover with a maximum-length name.
    const longName = '流光创作者'.repeat(25) + '甲乙丙';
    assert.equal(longName.length, 128);
    assert.equal((await context.request.post(base + '/app/settings/profile/form', {
      form:{display_name:longName}, headers:{Origin:base}, maxRedirects:0,
    })).status(), 303);
    for (const [width,height] of [[1440,1000],[768,1024],[390,844],[320,740]]) {
      for (const theme of ['light','dark']) {
        await page.setViewportSize({width,height});
        await page.goto(base + '/app/settings/page');
        await page.getByRole('button', {name:theme === 'dark' ? '深色' : '浅色', exact:true}).click();
        await page.getByRole('button', {name:'账户菜单', exact:true}).click();
        assert.equal(await page.getByRole('link', {name:'个人设置', exact:true}).count(), 1);
        assert.ok(await page.locator('#wb-account-menu').isVisible());
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
        assert.equal(overflow, false, width + 'px page overflow');
        const bounds = await page.locator('#wb-account-menu').boundingBox();
        assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= width, 'popover overflow');
        await page.keyboard.press('Escape');
        assert.equal(await page.getByRole('button', {name:'账户菜单', exact:true}).evaluate(el => el === document.activeElement), true);
        await page.keyboard.press('Enter');
        await page.keyboard.press('Tab');
        assert.equal(await page.evaluate(() => document.activeElement.getAttribute('href')), '/app/settings/page');
        await Promise.all([page.waitForEvent('load'), page.keyboard.press('Enter')]);
        assert.equal(await page.locator('html').getAttribute('data-theme'), theme);
        assert.equal(await page.getByRole('button', {name:theme === 'dark' ? '深色' : '浅色', exact:true}).getAttribute('aria-pressed'), 'true');
        assert.equal(await page.locator('#account-username').getAttribute('readonly'), '');
        if (width === 1440 || width === 390) await page.screenshot({path:path.join(output, width + '-' + theme + '.png'), fullPage:true});
        console.log(width + 'px ' + theme + ': layout/menu/keyboard PASS');
      }
    }
    await page.setViewportSize({width:1440,height:1000});
    await page.goto(base + '/app/settings/page');
    let profileWrites = 0;
    page.on('request', request => {if (request.method() === 'POST' && request.url().includes('/settings/profile/form')) profileWrites++;});
    await page.locator('#account-display-name').fill('  新的显示姓名  ');
    await page.route('**/settings/profile/form', async route => {
      await new Promise(resolve => setTimeout(resolve, 150));
      await route.continue();
    });
    await page.locator('[data-account-profile]').evaluate(form => {form.requestSubmit(); form.requestSubmit();});
    await page.waitForURL('**/app/settings/page?notice=profile_saved');
    assert.equal(profileWrites, 1);
    assert.equal(await page.locator('.account-display-name').textContent(), '新的显示姓名');
    assert.ok(await page.getByText('姓名已保存。', {exact:true}).isVisible());
    await page.locator('#account-current_password').fill('incorrect');
    await page.locator('#account-new_password').fill(newPassword);
    await page.locator('#account-confirm_password').fill(newPassword);
    await page.getByRole('button', {name:'修改密码并重新登录', exact:true}).click();
    await page.locator('[data-account-password] [data-form-error]').filter({hasText:'当前密码不正确'}).waitFor();
    assert.ok(await page.locator('[data-profile-saved]').isVisible(), 'password errors changed the profile feedback');
    await page.locator('#account-current_password').fill(oldPassword);
    await page.getByRole('button', {name:'显示新密码', exact:true}).click();
    assert.equal(await page.locator('#account-new_password').getAttribute('type'), 'text');
    assert.equal(await page.locator('#account-new_password').inputValue(), newPassword);
    await page.getByRole('button', {name:'修改密码并重新登录', exact:true}).click();
    await page.waitForURL('**/login?notice=password_changed');
    assert.ok(await page.getByText('密码已修改，请使用新密码重新登录。', {exact:true}).isVisible());
    assert.equal((await second.request.get(base + '/auth/me')).status(), 401);
    const cookieNames = (await context.cookies()).map(cookie => cookie.name);
    assert.ok(!cookieNames.includes('sora_session'));
    assert.equal((await context.request.post(base + '/auth/login-browser', {data:{username:'creator',password:oldPassword}})).status(), 401);
    assert.equal((await context.request.post(base + '/auth/login-browser', {data:{username:'creator',password:newPassword}})).status(), 200);
    await page.goto(base + '/app/settings/page');
    assert.equal(await page.locator('.account-display-name').textContent(), '新的显示姓名');
    assert.deepEqual(errors, []);
    console.log('Name persistence, duplicate submit, scoped errors, password visibility, redirect and two-device logout: PASS');
    await second.close();
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
}
main().catch(error => {console.error(error); process.exitCode = 1;});
