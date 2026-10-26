import json, sys, urllib.request
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from PIL import Image, ImageDraw
ROOT=Path('/Users/zhaoli/git/haymant/rehab-video-maker')
OUT=ROOT/'out/autopilot/playlist-covers'; OUT.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(ROOT/'tools/gen'))
sys.path.insert(0,str(ROOT/'skills/podcast-avatar-commentary/scripts'))
import comfy
from lib import find_font, draw_paragraph, contains_cjk
sys.path.insert(0,str(ROOT/'skills/podcast-youtuber-agent/scripts'))
import youtube_upload as y
from googleapiclient.http import MediaFileUpload
SERVER='http://127.0.0.1:8188'
comfy.SERVER=SERVER
try:
    urllib.request.urlopen(SERVER+'/system_stats',timeout=5)
except Exception as e:
    print('ComfyUI not running',e); raise SystemExit(1)
config=json.loads((ROOT/'state/youtube-playlists.json').read_text())
by_name={p['name']:p for p in config['playlists']}
NEG='text, letters, typography, watermark, logo, signature, caption, deformed, distorted, low quality, blurry, oversaturated, cartoon, anime, 3d render, cluttered, hud, infographic, chart, graph, people, faces, photograph, photorealistic, neon, glossy'
BASE='architectural ink and watercolour sketch of Singapore Marina Bay skyline, fine linework, cross-hatching, muted teal and amber watercolour washes, cream paper, editorial magazine cover, one focal point, no people, no text, no logos, square 1:1'
jobs=[
 ('AI Advances','helix',900,'a single illuminated AI server rack in the foreground','AI ADVANCES','人工智能前沿','Models · Agents · Product'),
 ('AI Capex & Power','gardens',901,'high-voltage transmission lines and a data-centre cooling stack in the foreground','AI CAPEX & POWER','算力与电力','Data centres · Grids · Chips'),
 ('Macro & Markets','esplanade',902,'government bond certificates and currency notes on a foreground ledge','MACRO & MARKETS','宏观与市场','Rates · Bonds · Currencies'),
 ('Energy & Commodities','waterfront',903,'a lone oil tanker and refinery storage tanks in the foreground','ENERGY & COMMODITIES','能源与大宗商品','Oil · Diesel · Metals'),
 ('Europe & Fiscal Policy','merlion',904,'euro banknotes and government bond certificates on a foreground ledge','EUROPE & FISCAL','欧洲与财政','France · Euro · Debt'),
 ('Investor Conversations','aerial',905,'an empty boardroom table and a studio microphone in the foreground','INVESTOR CONVERSATIONS','投资者对话','Funds · Allocators · Markets'),
]
angles={a['id']:a['prompt'] for a in json.loads((ROOT/'skills/podcast-cover-agent/config/cover-styles.json').read_text())['angles']}
def overlay(plate: Path, out: Path, title: str, zh: str, desc: str):
    with Image.open(plate) as im:
        im=im.convert('RGB').resize((1024,1024),Image.LANCZOS)
    # Cream panel over the lower third.
    panel=Image.new('RGBA',(1024,1024),(0,0,0,0)); d=ImageDraw.Draw(panel)
    d.rectangle([0,560,1024,1024],fill=(247,243,234,244))
    d.rectangle([60,596,69,700],fill=(178,92,48))
    im=Image.alpha_composite(im.convert('RGBA'),panel).convert('RGB')
    draw=ImageDraw.Draw(im)
    kicker=find_font(26,bold=True,text=title); draw.text((88,596),'LINK ZAG SERIES',font=kicker,fill=(178,92,48))
    tfont=find_font(66 if len(title)<=18 else 54,bold=True,text=title)
    draw_paragraph(draw,title,tfont,(88,636),860,(18,20,24),8,2)
    zfont=find_font(38,bold=True,text=zh); draw.text((88,748),zh,font=zfont,fill=(24,116,112))
    dfont=find_font(24,text=desc); draw.text((88,812),desc,font=dfont,fill=(78,80,84))
    brand=find_font(22,text='LINKZAG.SHOW'); draw.text((88,960),'LINKZAG.SHOW',font=brand,fill=(78,80,84))
    im.save(out,'PNG')
    print('wrote',out,flush=True)
auth=SimpleNamespace(token_file=str(y.DEFAULT_TOKEN_FILE), client_secrets=str(y.DEFAULT_CLIENT_SECRETS))
yt=y._youtube(auth,[y.SCOPE_FORCE_SSL],False)
uploaded={}
for name,angle,seed,subject,title,zh,desc in jobs:
    plate=OUT/f'{name.replace(" & ","-").replace(" ","-").lower()}.plate.png'
    out=plate.with_suffix('').with_suffix('.png')
    prompt=f'{BASE}, {angles[angle]}, {subject}, premium financial magazine cover, one focal point, no people, no text, no logos, square 1:1'
    graph=comfy.graph(prompt,NEG,width=1024,height=1024,steps=28,cfg=5.5,seed=seed,ckpt='sd_xl_base_1.0.safetensors')
    print('generate',name,angle,seed,flush=True)
    comfy.generate(graph,plate,timeout=1200)
    overlay(plate,out,title,zh,desc)
    pid=by_name[name]['id']
    body={'snippet':{'playlistId':pid,'type':'hero'}}
    try:
        yt.playlistImages().insert(part='snippet',body=body,media_body=MediaFileUpload(str(out),mimetype='image/png')).execute()
        uploaded[name]=str(out)
        print('uploaded playlist image',name,pid,flush=True)
    except Exception as e:
        print('playlist image upload failed',name,str(e)[:500],flush=True)
(OUT/'uploaded.json').write_text(json.dumps(uploaded,ensure_ascii=False,indent=2)+'\n')
print('done',len(uploaded),'of',len(jobs),flush=True)
