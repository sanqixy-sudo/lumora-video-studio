"""Five isolated Jinja design samples. No production routes or writes are added."""
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import sys, shutil, argparse, json, random
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import preview_studio as studio
from scripts import preview_ui as preview

DESIGN = ROOT / 'design/mature'
CONTEXTS = {}
SAMPLES = {'login.html', 'app/dashboard.html', 'app/job_detail.html',
           'admin/job_detail.html', 'admin/users.html', 'admin/usage_monthly.html'}

class SampleEnvironment(Environment):
    def get_template(self, name, parent=None, globals=None):
        if parent is None and name not in SAMPLES:
            original = Environment(loader=FileSystemLoader(ROOT / 'app/templates'), autoescape=self.autoescape)
            original.globals.update(self.globals)
            original.filters.update(self.filters)
            return original.get_template(name, globals=globals)
        template = super().get_template(name, parent, globals)
        if parent is None and name in SAMPLES and not getattr(template, '_sample_wrapped', False):
            original = template.render
            def render_context(*args, **kwargs):
                context = dict(*args, **kwargs)
                if name not in CONTEXTS: CONTEXTS[name] = context.copy()
                if name == 'login.html':
                    manifest = DESIGN / 'static/login-materials/manifest.json'
                    pool = json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else []
                    images = []
                    rng = random.SystemRandom()
                    while pool and len(images) < 28:
                        batch = rng.sample(pool,len(pool))
                        if images and len(batch)>1 and images[-1]['src']==batch[0]['src']: batch[0],batch[-1]=batch[-1],batch[0]
                        images.extend(batch)
                    context['login_wall_images'] = images[:28]
                if name == 'app/dashboard.html':
                    pictures = [('雨夜城市', 'city', 960, 640), ('自然光人物', 'person', 560, 700), ('产品特写', 'product', 700, 560), ('城市光影 A10', 'city', 960, 640)]
                    context['reference_presets'] = [preview.ns(**{**vars(p), 'name': pictures[i][0], 'image_url': '/static/mature/' + pictures[i][1] + '.svg', 'width': pictures[i][2], 'height': pictures[i][3]}) for i,p in enumerate(context['reference_presets'])]
                return original(context)
            template.render = render_context
            template._sample_wrapped = True
        return template

def sample_environment(*args, **kwargs):
    kwargs['loader'] = FileSystemLoader([DESIGN / 'templates', ROOT / 'app/templates'])
    return SampleEnvironment(*args, **kwargs)

class Handler(studio.Handler):
    def send_text(self, text, kind):
        if urlparse(self.path).path.startswith('/before/'):
            text = text.replace('http://127.0.0.1:8100/preview/', '/before/preview/')
        return super().send_text(text, kind)
    def do_GET(self):
        path = urlparse(self.path).path
        query = {k:v[0] for k,v in parse_qs(urlparse(self.path).query).items()}
        if path == '/login':
            context = CONTEXTS['login.html'].copy()
            context['request'] = preview.fixtures.request(path,query)
            return self.send_text(self.usage_env.get_template('login.html').render(context),'text/html; charset=utf-8')
        if path == '/admin/users/page' and query:
            context = CONTEXTS['admin/users.html'].copy()
            rows = context['rows']
            q = query.get('q','').lower()
            rows = [(u,w) for u,w in rows if (not q or q in u.username.lower() or q in u.display_name.lower() or q == str(u.id)) and query.get('role','all') in ('all',u.role) and query.get('status','all') in ('all',u.status)]
            if query.get('state') == 'empty': rows=[]
            context.update(rows=rows, filters=preview.ns(q=q,role=query.get('role','all'),status=query.get('status','all')), request=preview.fixtures.request(path,query))
            return self.send_text(self.usage_env.get_template('admin/users.html').render(context),'text/html; charset=utf-8')
        if path == '/admin/usage/monthly/page' and query.get('role') == 'sub_admin':
            data=studio.build_usage_preview(preview.fixtures.user,query.get('month') or '2026-06',query.get('q',''),query.get('hide_zero')=='true')
            context={**preview.fixtures.common,**data,'current_user':preview.ns(**{**vars(preview.fixtures.admin),'role':'sub_admin'}),'can_manage':False,'request':preview.fixtures.request(path,query)}
            return self.send_text(self.usage_env.get_template('admin/usage_monthly.html').render(context),'text/html; charset=utf-8')
        if path == '/design': return self.file(DESIGN / 'review.html')
        if path.startswith('/static/mature/'):
            asset = (DESIGN / 'static' / path[len('/static/mature/'):]).resolve()
            if asset.is_relative_to((DESIGN / 'static').resolve()) and asset.is_file(): return self.file(asset)
            return self.send_error(404)
        return super().do_GET()

def render():
    # Freeze the current local v9.3 baseline once, before sample template rendering.
    baseline = DESIGN / 'baseline'
    if not (baseline / 'routes.json').exists():
        studio.render()
        baseline.mkdir(parents=True, exist_ok=True)
        shutil.copytree(preview.OUT, baseline / 'rendered', dirs_exist_ok=True)
        shutil.copytree(ROOT / 'app/static', baseline / 'static', dirs_exist_ok=True)
        shutil.copy2(preview.OUT / 'routes.json', baseline / 'routes.json')
    studio.BASELINE = baseline
    studio.PORT = 8101
    studio.Environment = sample_environment
    preview.Environment = sample_environment
    original_render = preview.render
    def render_samples():
        preview.OUT = DESIGN / 'rendered'
        return original_render()
    preview.render = render_samples
    studio.render()
    Handler.routes = studio.Handler.routes
    Handler.usage_env = studio.Handler.usage_env
    Handler.baseline_routes = studio.Handler.baseline_routes
    print('Five samples: http://127.0.0.1:8101/design', flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--serve', action='store_true')
    args = parser.parse_args()
    render()
    if args.serve: ThreadingHTTPServer(('127.0.0.1', 8101), Handler).serve_forever()
