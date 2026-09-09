"""Local read-only UI preview with fictional data; never connects to a database/upstream."""
from __future__ import annotations

import argparse
import json
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import render_ui_snapshots as fixtures
from jinja2 import Environment, FileSystemLoader, select_autoescape
from app.services.system_settings import SYSTEM_SETTING_DEFS

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'runtime' / 'ui_preview'
ns = fixtures.ns
BASE = 'http://127.0.0.1:8099'

def render():
    OUT.mkdir(parents=True, exist_ok=True)
    common = dict(fixtures.common)
    common["app_name"] = "流光 Lumora"
    common.update(
        quota_stats=ns(total_available=85, total_reserved=3, package_available=40, personal_available=45),
        quota_stats_by_user={2:ns(total_available=85,package_available=40,personal_available=45,total_reserved=3,package_reserved=1,personal_reserved=2)},
        model_options=[dict(value='key:1:12',provider_name='sora_api',provider_label='Sora',model_id='sora-2-12s',seconds=12,label='Sora · sora-2-12s · 12 秒'),dict(value='key:2:10',provider_name='veo_omni',provider_label='VEO Omni',model_id='veo-omni-flash',seconds=10,label='VEO Omni · veo-omni-flash · 10 秒'),dict(value='key:3:10',provider_name='wuyin_omni',provider_label='Wuyin Omni',model_id='wuyin-omni',seconds=10,label='Wuyin Omni · 10 秒')],
        product_name='',region_name='',package_rows=[],quota_plans=[],assignments=[],risk_rules=[],
        settings_rows=[ns(**item,value=item['default']) for item in SYSTEM_SETTING_DEFS],
        new_request_id='00000000-0000-4000-8000-000000000001',
    )
    common['reference_presets'] = [ns(id=i,name=name,image_url=BASE+'/preview/portrait.svg',width=720,height=1280,aspect_ratio='9:16',status='active',sort_order=i,owner_user_id=None if i<3 else 2) for i,name in enumerate(['城市日光','人物剪影','品牌主视觉','雨夜霓虹'],1)]
    common['presets'] = common['reference_presets']
    for job in fixtures.jobs:
        job.batch_index = 1 if job.id == 101 else 2
        job.error_message = None; job.error_code = None; job.upstream_response = None
        job.failed_at=None; job.completed_at=fixtures.now if job.status=='completed' else None
    for user in [fixtures.user,fixtures.admin]:
        user.hidden_from_subadmin_reports=False; user.daily_job_limit=None; user.concurrent_job_limit=None; user.min_submit_interval_seconds=None; user.display_name=user.username
    common['stats'] = ns(**{**vars(common['stats']),'active':9,'total_available':85,'package_available':40,'package_reserved':1})
    common['summary'].update(completed_count=1,active_count=1,failed_count=0,downloadable_count=1)
    common['summary_map']={12:common['summary']}; common['batch_summary_map']=common['summary_map']
    for card in common['cards']:
        card.update(is_private_protected=False,model='sora-2-8s')
    for key in common['provider_keys']: key.is_retired=False
    common['provider_keys'].append(ns(**{**vars(common['provider_keys'][0]),'id':4,'name':'Pod 历史渠道','provider_name':'podsora','is_retired':True}))
    env=Environment(loader=FileSystemLoader(ROOT/'app/templates'),autoescape=select_autoescape(['html']))
    env.globals.update(status_label=fixtures.status_label,role_label=fixtures.role_label,user_display_name=fixtures.user_display_name,quota_plan_period_label=lambda value: {'day':'每日','week':'每周','month':'每月'}.get(value,value),plan_quota_amount=lambda plan,assignment:100)
    env.filters.update(dt=fixtures.dt,dt_full=fixtures.dt)
    pages=list(fixtures.pages)
    pages.extend([('admin/quota_plans.html','/admin/quota-plans/page',fixtures.admin,{'rows':[]} ),('admin/risk_control.html','/admin/risk-control/page',fixtures.admin,{'rows':[]}),('app/reference_images.html','/app/reference-images/page',fixtures.user,{'rows':common['reference_presets']})])
    plan=ns(id=1,name='创作月套餐',period_type='monthly',quota_amount=100,status='active')
    pages=[(t,p,u,({**extra,'rows':[ns(plan=plan,assignment_count=4)]} if t=='admin/quota_plans.html' else {**extra,'rows':[ns(id=1,keywords=['示例限制词','示例校验'],error_message='请调整提示词后重试。',status='active',updated_at=fixtures.now)]} if t=='admin/risk_control.html' else extra)) for t,p,u,extra in pages]
    common['cards']=[{**common['cards'][0],'job_id':101+i,'prompt':text,'product_name':name,'size':size,'is_starred':i==0} for i,(name,size,text) in enumerate([('NiceReels','720x1280','雨后城市的电影感镜头，街道的倒影伴随镜头缓缓移动。'),('FlowStudio','1280x720','柔和光线下的产品展示，细节清晰，节奏舒缓。'),('Visual Lab','720x1280','以人物为中心的竖屏广告，强调自然表情和环境氛围。'),('Archive','1280x720','宽画幅的海岸风景与日光，保持主体完整。')])]
    routes={}; errors=[]
    for template,path,user,extra in pages:
        if template == 'errors/403.html': path = '/preview/access-denied'
        if template=='admin/settings.html': extra={**extra,'settings_rows':common['settings_rows']}
        if template=='admin/provider_keys.html': extra={**extra,'rows':common['provider_keys']}
        context={**common,**extra,'request':fixtures.request(path),'current_user':user}
        try:
            html=env.get_template(template).render(context)
            # Preview-only links never expose app credentials or production endpoints.
            html=html.replace('https://cdn.nodeimage.com/i/lFX6eomsgS02u3sMZ7xTW53XYP65QxaK.webp','/preview/mark.svg')
            filename=template.replace('/','__')
            (OUT/filename).write_text(html,encoding='utf-8'); routes[path]=filename
            if template=='admin/jobs.html':
                batch_context={**context,'selected_batch':context['batch'],'selected_batch_summary':context['summary'],'batch_files':{102:ns(id=9)}}
                (OUT/'admin__jobs__batch.html').write_text(env.get_template(template).render(batch_context),encoding='utf-8')
            empty_context={**context,**{key:[] for key in ['rows','jobs','cards','batches','running_jobs','queued_jobs','stuck_jobs','rankings','quota_requests']}}
            if template=='admin/usage_monthly.html':empty_context.update(daily_totals=[],real_total=0,display_total=0,override_count=0)
            if template not in {'login.html','errors/403.html'}:
                empty_html=env.get_template(template).render(empty_context)
                (OUT/filename.replace('.html','__empty.html')).write_text(empty_html,encoding='utf-8')
        except Exception as exc: errors.append(f'{template}: {exc}')
    index='<!doctype html><meta charset="utf-8"><title>流光 Lumora 本地预览</title><style>body{font:16px system-ui;max-width:900px;margin:50px auto;line-height:2}a{color:#3268df}</style><h1>流光 Lumora 界面预览</h1><p>全部为模拟数据，保存和生成不会发送到上游。</p><ul>' + ''.join(f'<li><a href="{path}">{path}</a></li>' for path in routes) + '</ul>'
    (OUT/'index.html').write_text(index,encoding='utf-8')
    if errors: raise RuntimeError('\n'.join(errors))
    print(f'Rendered {len(routes)} pages: {OUT}',flush=True)
    return routes

class Handler(SimpleHTTPRequestHandler):
    routes={}
    def do_POST(self):
        self.send_error(405,'Read-only preview. No jobs are created.')
    def do_GET(self):
        path=urlparse(self.path).path
        if path in {'/app/jobs/101', '/admin/jobs/101'}:
            job = fixtures.jobs[0]
            return self.json({'job': {'id': job.id, 'status': job.status, 'status_label': fixtures.status_label(job.status), 'progress': job.progress, 'queue_text': job.queue_text, 'remote_task_id': 'mock-task', 'download_attempts': 0, 'output_file': None, 'model': job.model, 'prompt': job.prompt, 'size': job.size, 'seconds': job.seconds}, 'events': [], 'api_calls': [], 'can_redownload': False, 'can_resume': False, 'can_pause': True})
        if path=='/app/reference-image/dimensions': return self.json({'width':720,'height':1280})
        if path=='/app/job-batches/12': return self.json({'batch':{'state_label':'进行中','summary':'1 运行中 / 1 已完成','completed_count':1,'active_count':1,'failed_count':0,'downloadable_count':1},'jobs':[{'id':job.id,'status':job.status,'status_label':fixtures.status_label(job.status),'progress':job.progress,'queue_text':job.queue_text,'output_file':{'id':9} if job.id==102 else None} for job in fixtures.jobs]})
        if path.endswith('.svg') or path.endswith('/poster'):
            mark=path.endswith('mark.svg')
            svg='<svg xmlns="http://www.w3.org/2000/svg" width="720" height="1280" viewBox="0 0 720 1280"><defs><linearGradient id="g" x2="1" y2="1"><stop stop-color="#80a7e2"/><stop offset="1" stop-color="#283c69"/></linearGradient></defs><rect width="720" height="1280" fill="url(#g)"/><circle cx="560" cy="280" r="170" fill="#f3d8b0" opacity=".65"/><path d="M0 840L210 530 390 820 570 620 720 860V1280H0" fill="#182942" opacity=".65"/></svg>'
            if mark: svg='<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48"><rect width="48" height="48" rx="14" fill="#3268df"/><path d="M32 15H21a6 6 0 0 0 0 12h6a4 4 0 0 1 0 8H16" fill="none" stroke="white" stroke-width="4" stroke-linecap="round"/></svg>'
            self.send_response(200); self.send_header('Content-Type','image/svg+xml'); self.end_headers(); self.wfile.write(svg.encode()); return
        if path.startswith('/static/'):
            target=(ROOT/'app'/path.lstrip('/')).resolve()
            if not target.is_relative_to((ROOT/'app/static').resolve()) or not target.is_file(): return self.send_error(404)
        elif path in self.routes: target=OUT/self.routes[path]
        elif path=='/': target=OUT/'index.html'
        else: return self.send_error(404)
        self.send_response(200); self.send_header('Content-Type',self.guess_type(str(target))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(target.read_bytes())
    def json(self,data):
        self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(json.dumps(data).encode())
    def log_message(self,*args): pass

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--serve',action='store_true'); args=parser.parse_args()
    Handler.routes=render()
    if args.serve:
        print(BASE,flush=True); ThreadingHTTPServer(('127.0.0.1',8099),Handler).serve_forever()
