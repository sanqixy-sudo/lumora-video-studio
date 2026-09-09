"""User-authorized local preview: read existing covers of public, unprotected works."""
from pathlib import Path
import os
import getpass, json, shlex, base64, io
import paramiko
from PIL import Image,ImageOps
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'design/mature/static/login-materials'
def main():
 password=getpass.getpass('SSH password: ')
 ssh=paramiko.SSHClient();ssh.load_host_keys(str(ROOT/'runtime/ssh_known_hosts'));ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
 ssh.connect(os.environ['LUMORA_SSH_HOST'],port=int(os.getenv('LUMORA_SSH_PORT','22')),username=os.environ['LUMORA_SSH_USER'],password=password,timeout=15)
 code="""from pathlib import Path
from sqlalchemy import text
from app.db import engine
import random,json,base64,hashlib
with engine.connect() as c:
 rows=c.execute(text("SELECT f.file_path FROM job_files f JOIN jobs j ON j.id=f.job_id JOIN users u ON u.id=j.user_id WHERE j.status='completed' AND u.showcase_enabled IS TRUE AND j.is_private_protected IS NOT TRUE AND f.file_type='output_video' ORDER BY j.id DESC LIMIT 300")).fetchall()
random.SystemRandom().shuffle(rows)
images=[];seen=set()
for row in rows:
 video=Path(row[0]);p=video.with_name(video.stem+'_poster.jpg')
 if not video.is_file() or not p.is_file() or p.stat().st_size>800000:continue
 data=p.read_bytes();digest=hashlib.sha256(data).hexdigest()
 if digest in seen:continue
 seen.add(digest);images.append(base64.b64encode(data).decode())
 if len(images)>=24:break
print(json.dumps({'candidates':len(rows),'posters':images}))
"""
 stdin,stdout,stderr=ssh.exec_command("sudo -S -p '' docker exec sora-v2-sora-1 /opt/venv/bin/python -c "+shlex.quote(code),timeout=45)
 stdin.write(password+'\n');stdin.flush();stdin.channel.shutdown_write()
 raw=stdout.read();status=stdout.channel.recv_exit_status();ssh.close();password=None
 if status:raise RuntimeError('Read-only public cover selection failed')
 result=json.loads(raw);OUT.mkdir(parents=True,exist_ok=True);images=[]
 for i,encoded in enumerate(result['posters']):
  img=ImageOps.exif_transpose(Image.open(io.BytesIO(base64.b64decode(encoded)))).convert('RGB');img.thumbnail((640,720))
  name=f'public-cover-{i:02d}.webp';img.save(OUT/name,'WEBP',quality=80)
  images.append({'src':'/static/mature/login-materials/'+name,'width':img.width,'height':img.height})
 if not images:raise RuntimeError('No existing eligible posters; previous preview pool retained')
 (OUT/'manifest.json').write_text(json.dumps(images,indent=2),encoding='utf-8')
 proof={'source':'existing public showcase video posters','candidates':result['candidates'],'selected':len(images),'filters':['completed','showcase_enabled=true','is_private_protected is not true','output_video','existing video and poster'],'bytes':sum((OUT/Path(x['src']).name).stat().st_size for x in images),'server_writes':False}
 (ROOT/'design/mature/evidence/login-poster-source.json').write_text(json.dumps(proof,indent=2),encoding='utf-8');print(json.dumps(proof))
if __name__=='__main__':main()
