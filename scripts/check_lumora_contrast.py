"""Evaluate sampled rendered backgrounds; use after check_lumora_contrast.cjs."""
import json,re,math
from pathlib import Path
from PIL import Image
root=Path('runtime/guidelines_review')
def luminance(rgb):
 c=[v/255 for v in rgb]
 return sum((v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4)*weight for v,weight in zip(c,[.2126,.7152,.0722]))
results=[]
for view in json.loads((root/'contrast-samples.json').read_text(encoding='utf-8')):
 im=Image.open(root/view['file']).convert('RGB')
 for sample in view['samples']:
  rgb=[float(x) for x in re.findall(r'[\d.]+',sample['color'])];alpha=sample['opacity']*(rgb[3] if len(rgb)>3 else 1)
  rect=sample['rect'];ratios=[]
  for y in range(math.ceil(rect['y'])+1,math.floor(rect['y']+rect['height'])-1,3):
   for x in range(math.ceil(rect['x'])+1,math.floor(rect['x']+rect['width'])-1,3):
    bg=im.getpixel((x,y));fg=[a*alpha+b*(1-alpha) for a,b in zip(rgb,bg)];a,b=luminance(fg),luminance(bg);ratios.append((max(a,b)+.05)/(min(a,b)+.05))
  if not ratios:continue
  minimum=min(ratios);threshold=3 if sample['size']>=24 or sample['size']>=18.66 and sample['weight']>=700 else 4.5
  results.append({'route':view['route'],'theme':view['theme'],'text':sample['text'],'contrast':round(minimum,2),'threshold':threshold,'passed':minimum>=threshold})
failures=[r for r in results if not r['passed']]
(root/'rendered-contrast.json').write_text(json.dumps({'results':results,'failures':failures},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'samples':len(results),'minimum':min(r['contrast'] for r in results),'failures':failures},ensure_ascii=False))
raise SystemExit(bool(failures))
