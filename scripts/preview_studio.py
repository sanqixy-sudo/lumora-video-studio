"""Review the real redesigned templates with local fictional data and mock-only actions."""
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from http.server import ThreadingHTTPServer
from jinja2 import Environment,FileSystemLoader,select_autoescape
from datetime import datetime
import json,sys,re,argparse
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import preview_ui as preview
from scripts.preview_usage import build_usage_preview
BASELINE=ROOT/'runtime/before-studio-20260908'
PORT=8100

class Handler(preview.Handler):
    baseline_routes={}
    def do_GET(self):
        parsed=urlparse(self.path); path=parsed.path
        if path=='/admin/usage/monthly/page':
            query={k:v[0] for k,v in parse_qs(parsed.query).items()}
            try:data=build_usage_preview(preview.fixtures.user,query.get('month') or '2026-06',query.get('q',''),query.get('hide_zero','')=='true',query.get('state')=='empty')
            except (ValueError,OverflowError):return self.json_status({'detail':'请选择有效月份。'},400)
            context={**preview.fixtures.common,**data,'current_user':preview.fixtures.admin,'can_manage':True,'request':preview.fixtures.request(path,query)}
            return self.send_text(self.usage_env.get_template('admin/usage_monthly.html').render(context),'text/html; charset=utf-8')
        if path.startswith('/static/'):
            asset=(ROOT/'app/static'/path[len('/static/'):]).resolve()
            if asset.is_relative_to((ROOT/'app/static').resolve()) and asset.is_file(): return self.file(asset)
            return self.send_error(404)
        if path in {'/app/files/9/stream','/app/files/9/download'}:
            return self.file(ROOT/'runtime/studio_preview/sample.webm')
        if path in {'/app/jobs/101/page','/admin/jobs/101/page'} and parse_qs(parsed.query).get('state',[''])[0] in {'completed','failed'}:
            state=parse_qs(parsed.query)['state'][0]
            role='admin' if path.startswith('/admin') else 'app'
            return self.file(preview.OUT/f'{role}__job_detail__{state}.html')
        if parse_qs(parsed.query).get('state',[''])[0]=='empty' and path in self.routes and path not in {'/login','/preview/access-denied'}:
            return self.file(preview.OUT/self.routes[path].replace('.html','__empty.html'))
        if path=='/admin/jobs/page' and parse_qs(parsed.query).get('batch_id',[''])[0]=='12':return self.file(preview.OUT/'admin__jobs__batch.html')
        if path=='/app/plaza/jobs/101':
            return self.json({'creator':'创作一组','product_name':'NiceReels','region_name':'美国','size':'720x1280','seconds':10,'model':'veo-omni-flash','created_at':'2026-09-08 10:24','prompt':'雨后城市的电影感镜头。','output_file':{'id':9},'is_private_protected':False})
        if path=='/design': return self.file(ROOT/'scripts/studio_review.html')
        if path.startswith('/before/'):
            if not self.baseline_routes:return self.send_text('<!doctype html><meta charset="utf-8"><p>上一版快照仅在原本地工作区提供。</p>','text/html; charset=utf-8')
            original=path[len('/before'):]
            if original.startswith('/static/'):
                asset=(BASELINE/'static'/original[len('/static/'):]).resolve()
                if asset.is_relative_to((BASELINE/'static').resolve()) and asset.is_file(): return self.file(asset)
            elif original in self.baseline_routes:
                html=(BASELINE/'rendered'/self.baseline_routes[original]).read_text(encoding='utf-8')
                html=re.sub(r'((?:href|src|action)=")/(?!/)',r'\1/before/',html)
                # Historical mock image URLs remain local on this review server.
                html=html.replace('http://127.0.0.1:8099','http://127.0.0.1:8100')
                return self.send_text(html,'text/html; charset=utf-8')
            elif original.startswith('/preview/') or original.endswith('/poster'):
                self.path=original; return super().do_GET()
            return self.send_error(404)
        if path in {'/app/jobs/101','/admin/jobs/101'}:
            state=parse_qs(parsed.query).get('state',[''])[0]
            if state in {'completed','failed'}:
                job=preview.fixtures.jobs[0]
                return self.json({'job':{'id':101,'status':state,'status_label':'已完成' if state=='completed' else '失败','progress':100 if state=='completed' else 62,'queue_text':'已完成' if state=='completed' else '已结束','remote_task_id':job.remote_task_id,'download_attempts':1,'output_file':{'id':9} if state=='completed' else None,'error_text':'上游返回处理失败，示例错误原因：素材无法读取。请检查图片链接后重新提交。' if state=='failed' else None,'model':job.model},'events':[],'api_calls':[],'can_redownload':False,'can_resume':state=='failed','can_pause':False})
            scenario=parse_qs(parsed.query).get('scenario',[''])[0]
            if scenario=='network-error':return self.json_status({'detail':'模拟更新失败'},503)
            job=preview.fixtures.jobs[0]
            return self.json({'job':{'id':job.id,'status':job.status,'status_label':preview.fixtures.status_label(job.status),'progress':job.progress,'queue_text':job.queue_text,'remote_task_id':job.remote_task_id,'download_attempts':1,'output_file':None,'model':job.model,'prompt':job.prompt,'size':job.size,'seconds':job.seconds,'error_text':None},'events':[{'created_at':'09-08 10:24','message':'上游已接收任务，正在生成。'}],'api_calls':[],'can_redownload':False,'can_resume':False,'can_pause':True})
        return super().do_GET()
    def do_POST(self):
        path=urlparse(self.path).path
        self.rfile.read(int(self.headers.get('Content-Length',0)))
        params=parse_qs(urlparse(self.headers.get('Referer','')).query)
        if params.get('scenario',[''])[0]=='error':return self.json_status({'detail':'模拟请求失败，输入内容已保留。请稍后重试。'},400)
        if path in {'/auth/login-browser','/auth/login-form','/auth/register-form'}:return self.json({'target':'/app'})
        if path=='/auth/logout':
            self.send_response(303);self.send_header('Location','/login');self.end_headers();return
        if path=='/app/jobs/batch':return self.json({'batch_id':12,'target':'/app/job-batches/12/result','jobs':[]})
        if path=='/admin/users':return self.json({'target':'/admin/users/page?notice=sample_created'})
        if re.fullmatch(r'/(app|admin)/jobs/\d+/(pause|resume|redownload)',path):return self.json({'ok':True})
        if re.fullmatch(r'/app/jobs/\d+/toggle-star',path):return self.json({'is_starred':True})
        if re.fullmatch(r'/app/jobs/\d+/toggle-protection',path):return self.json({'is_private_protected':True})
        if re.fullmatch(r'/(app|admin)/[a-z0-9/-]+/form',path):
            referer=urlparse(self.headers.get('Referer',''))
            target=referer.path+('?' + referer.query if referer.query else '') if referer.path in self.routes else '/admin'
            return self.json({'target':target,'mock':True})
        return self.json_status({'detail':'本地预览不执行实际业务写入。'},405)
    def json_status(self,data,status):
        self.send_response(status);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps(data).encode())
    def send_text(self,text,kind):
        self.send_response(200);self.send_header('Content-Type',kind);self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(text.encode('utf-8'))
    def file(self,path):
        self.send_response(200);self.send_header('Content-Type',self.guess_type(str(path)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(path.read_bytes())

def render():
    preview.BASE=f'http://127.0.0.1:{PORT}'
    preview.OUT=ROOT/'runtime/studio_preview'
    preview.fixtures.jobs[0].remote_task_id='task_yXJ8JCb62hbuVRqPmVkCF0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    preview.fixtures.jobs[0].model='veo-omni-flash'
    preview.fixtures.jobs[0].product_name='NiceReels'
    preview.fixtures.jobs[0].region_name='美国'
    preview.fixtures.jobs[0].seconds=10
    preview.fixtures.now=datetime(2026,9,8,10,24)
    for job in preview.fixtures.jobs:
        job.created_at=preview.fixtures.now;job.updated_at=preview.fixtures.now;job.started_at=preview.fixtures.now;job.queued_at=preview.fixtures.now
    preview.fixtures.common['output_file']=None
    people=[]
    for i,(name,display,role,status) in enumerate([('creator01','创作一组','user','active'),('studio_02','品牌视觉组','user','active'),('operator','运营管理','sub_admin','active'),('visual_lab','视觉实验室','user','active'),('archive_user','历史账号','user','disabled'),('creator06','创作六组','user','active')]):
        user=preview.ns(**{**vars(preview.fixtures.user),'id':i+2,'username':name,'display_name':display,'role':role,'status':status,'hidden_from_subadmin_reports':False,'daily_job_limit':None,'concurrent_job_limit':None,'min_submit_interval_seconds':None})
        people.append((user,preview.fixtures.wallet))
    for i,(template,path,user,extra) in enumerate(preview.fixtures.pages):
        if template=='admin/users.html':
            quota=preview.ns(total_available=85,package_available=40,personal_available=45,total_reserved=3,package_reserved=1,personal_reserved=2)
            stats=preview.ns(total=6,active=5,disabled=1,sub_admin=1)
            preview.fixtures.pages[i]=(template,path,user,{**extra,'rows':people,'stats':stats,'quota_stats_by_user':{person.id:quota for person,_ in people}})
    usage_data=build_usage_preview(preview.fixtures.user)
    report_people=usage_data['rows']
    for index,(template,path,user,extra) in enumerate(preview.fixtures.pages):
        if template=='admin/usage_monthly.html':
            preview.fixtures.pages[index]=(template,path,user,{**extra,**usage_data})
        elif template=='admin/rankings.html':
            ranked=sorted(report_people,key=lambda row:row.monthly_real,reverse=True)
            preview.fixtures.pages[index]=(template,path,user,{**extra,'rankings':[preview.ns(user_id=r.user.id,username=r.user.username,display_name=r.user.display_name,usage_count=r.monthly_real,success_count=r.monthly_real-12-i,failure_count=8+i,download_failure_count=4) for i,r in enumerate(ranked)]})
    # Same production Jinja templates, with a full timestamp and fictional content.
    preview.fixtures.dt=lambda v:v.strftime('%Y-%m-%d %H:%M') if hasattr(v,'strftime') else str(v or '-')
    Handler.routes=preview.render()
    env=Environment(loader=FileSystemLoader(ROOT/'app/templates'),autoescape=select_autoescape(['html']))
    env.globals.update(status_label=preview.fixtures.status_label,role_label=preview.fixtures.role_label,user_display_name=preview.fixtures.user_display_name)
    Handler.usage_env=env
    env.filters.update(dt=preview.fixtures.dt,dt_full=preview.fixtures.dt)
    for role in ['app','admin']:
        for state in ['completed','failed']:
            job=preview.ns(**{**vars(preview.fixtures.jobs[0]),'status':state,'progress':100 if state=='completed' else 62,'queue_text':'已完成' if state=='completed' else '已结束','error_text':'上游返回处理失败，示例错误原因：素材无法读取。请检查图片链接后重新提交。' if state=='failed' else None})
            context={**preview.fixtures.common,'job':job,'current_user':preview.fixtures.admin if role=='admin' else preview.fixtures.user,'request':preview.fixtures.request(f'/{role}/jobs/101/page'),'can_manage':role=='admin','can_pause':False,'can_resume':state=='failed','can_redownload':False,'output_file':preview.ns(id=9) if state=='completed' else None,'data_endpoint':f'/{role}/jobs/101?state={state}','remote_download_url':None,'public_remote_download_url':None}
            (preview.OUT/f'{role}__job_detail__{state}.html').write_text(env.get_template(f'{role}/job_detail.html').render(context),encoding='utf-8')
    (preview.OUT/'routes.json').write_text(json.dumps(Handler.routes,ensure_ascii=False),encoding='utf-8')
    Handler.baseline_routes=json.loads((BASELINE/'routes.json').read_text(encoding='utf-8')) if (BASELINE/'routes.json').exists() else {}
    print(f'Mock-only review: http://127.0.0.1:{PORT}/design',flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--serve',action='store_true');args=parser.parse_args()
    render()
    if args.serve:ThreadingHTTPServer(('127.0.0.1',PORT),Handler).serve_forever()
