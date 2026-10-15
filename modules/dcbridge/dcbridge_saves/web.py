"""WSGI app: JSON API + a small save-manager page.

It runs on 127.0.0.1:8085 (dcbridge-saves.service) and the dashboard's web service passes /dcbridge/ on to it
(modules/dcbridge/netswitch_dcbridge.py), so the page needs no port of its own. Mount it anywhere (all URLs in the page are
relative), e.g. in a Flask dashboard:

    from werkzeug.middleware.dispatcher import DispatcherMiddleware
    app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {"/saves": saves_app})

API (all JSON unless noted)
  GET    api/status
  GET    api/bridge                                  RP2040 mode + W5500/PPP link state
  GET    api/saves                                   games, slots, pending
  GET    api/saves/<serial>/<slot>                   current file (application/octet-stream)
  PUT    api/saves/<serial>/<slot>[?title=..]        body = 131072-byte VMU image -> queued
  DELETE api/saves/<serial>/<slot>                   queued delete (old copy kept in history)
  POST   api/saves/<serial>/<slot>/label             {"label": "..."} -> queued
  GET    api/saves/<serial>/<slot>/history           versions, newest first
  GET    api/saves/<serial>/<slot>/history/<id>      that version (octet-stream)
  POST   api/saves/<serial>/<slot>/history/<id>/restore  -> queued
  GET    api/pending                                 queued edits
  DELETE api/pending/<id>                            cancel one
  GET    api/export.zip                              every save on the card + titles/labels
"""
import io
import json
import re
import time
import zipfile

from . import SAVES_DIR, VMU_SIZE, NUM_SLOTS, __version__
from .store import StoreError, slot_path, check_serial, check_slot

MAX_BODY = VMU_SIZE + 4096


class HTTPError(Exception):
    def __init__(self, code, msg):
        Exception.__init__(self, msg)
        self.code = code


_STATUS = {200: "200 OK", 202: "202 Accepted", 400: "400 Bad Request", 404: "404 Not Found",
           405: "405 Method Not Allowed", 413: "413 Payload Too Large", 500: "500 Internal Server Error"}


def make_app(service, bridge=None):
    store, fat, lock = service.store, service.fat, service.fat_lock

    def send(start, code, body, ctype="application/json", extra=()):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        start(_STATUS.get(code, "%d X" % code),
              [("Content-Type", ctype), ("Content-Length", str(len(body))),
               ("Cache-Control", "no-store")] + list(extra))
        return [body]

    def body_of(env):
        try:
            n = int(env.get("CONTENT_LENGTH") or 0)
        except ValueError:
            n = 0
        if n > MAX_BODY:
            raise HTTPError(413, "upload too large")
        return env["wsgi.input"].read(n) if n else b""

    def json_body(env):
        try:
            return json.loads(body_of(env).decode("utf-8") or "{}")
        except ValueError:
            raise HTTPError(400, "invalid JSON")

    def query(env, key):
        for part in (env.get("QUERY_STRING") or "").split("&"):
            k, _, v = part.partition("=")
            if k == key:
                try:
                    from urllib.parse import unquote_plus
                except ImportError:            # pragma: no cover
                    from urllib import unquote_plus
                return unquote_plus(v)
        return None

    def vmu_download(start, data, name):
        return send(start, 200, data, "application/octet-stream",
                    [("Content-Disposition", 'attachment; filename="%s"' % name)])

    def queued(start, entry):
        ld = store.lastdisc()
        warn = None
        if ld == (entry["serial"], entry["slot"]) and entry["action"] in ("put", "delete"):
            warn = ("This is the slot openMenu will refresh from the physical VMU on its next "
                    "boot, so your change may be overwritten. Both versions stay in history.")
        return send(start, 202, {"queued": entry["id"], "warning": warn,
                                 "note": "Written to the card the next time openMenu boots."})

    def route(env, start):
        method = env["REQUEST_METHOD"]
        path = env.get("PATH_INFO", "/") or "/"

        if path in ("/", "/index.html"):
            return send(start, 200, PAGE.replace("__VERSION__", __version__).encode(), "text/html; charset=utf-8")

        if path == "/api/status":
            st = dict(service.status)
            st.update({"image": service.image, "sectors": service.sectors, "version": __version__,
                       "pending": len(store.pending_list()), "now": time.time()})
            return send(start, 200, st)

        if path == "/api/bridge":
            if bridge is None:
                raise HTTPError(404, "bridge status not enabled")
            return send(start, 200, bridge.snapshot())

        if path == "/api/saves" and method == "GET":
            return send(start, 200, store.summary())

        if path == "/api/pending" and method == "GET":
            return send(start, 200, store.pending_list())

        m = re.match(r"^/api/pending/([\w-]+)$", path)
        if m and method == "DELETE":
            store.pending_cancel(m.group(1))
            return send(start, 200, {"cancelled": m.group(1)})

        if path == "/api/export.zip":
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                with lock:
                    paths = fat.walk(SAVES_DIR)
                for p in paths:
                    if p.endswith("/"):
                        continue
                    with lock:
                        data = fat.read(p)
                    if data is not None:
                        z.writestr(p.lstrip("/"), data)
            name = time.strftime("dreamcast-saves-%Y%m%d-%H%M.zip")
            return send(start, 200, buf.getvalue(), "application/zip",
                        [("Content-Disposition", 'attachment; filename="%s"' % name)])

        m = re.match(r"^/api/saves/([^/]+)/(\d)(/.*)?$", path)
        if not m:
            raise HTTPError(404, "not found")
        serial, slot, rest = check_serial(m.group(1)), check_slot(m.group(2)), m.group(3) or ""

        if rest == "":
            if method == "GET":
                with lock:
                    data = fat.read(slot_path(serial, slot))
                if data is None:
                    raise HTTPError(404, "no save in that slot on the card")
                return vmu_download(start, data, "%s_SLOT%d.VMU" % (serial, slot))
            if method in ("PUT", "POST"):
                return queued(start, store.queue_put(serial, slot, body_of(env), title=query(env, "title")))
            if method == "DELETE":
                return queued(start, store.queue_delete(serial, slot))
            raise HTTPError(405, "method not allowed")

        if rest == "/label" and method == "POST":
            return queued(start, store.queue_label(serial, slot, json_body(env).get("label", "")))

        if rest == "/history" and method == "GET":
            return send(start, 200, store.history_list(serial, slot))

        m = re.match(r"^/history/([\w.-]+\.VMU)(/restore)?$", rest)
        if m:
            if m.group(2) and method == "POST":
                return queued(start, store.queue_restore(serial, slot, m.group(1)))
            if not m.group(2) and method == "GET":
                return vmu_download(start, store.history_get(serial, slot, m.group(1)),
                                    "%s_SLOT%d_%s" % (serial, slot, m.group(1)))
        raise HTTPError(404, "not found")

    def app(env, start):
        try:
            return route(env, start)
        except HTTPError as e:
            return send(start, e.code, {"error": str(e)})
        except StoreError as e:
            return send(start, 400, {"error": str(e)})
        except Exception as e:                               # pragma: no cover
            import logging
            logging.getLogger("dcbridge-saves").exception("request failed")
            return send(start, 500, {"error": str(e)})

    return app


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dreamcast saves</title>
<style>
:root{--bg:#f6f5f2;--card:#fff;--ink:#1d1d1f;--mute:#6b6b70;--line:#e3e1dc;--acc:#e8541e;--ok:#2f8f4e;--warn:#b7791f}
@media (prefers-color-scheme:dark){:root{--bg:#141416;--card:#1d1d21;--ink:#ececee;--mute:#9a9aa2;--line:#2c2c32;--acc:#ff7a45;--ok:#5cc27f;--warn:#e0a84a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
header{display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between;padding:18px 16px 8px;max-width:960px;margin:0 auto}
h1{font-size:20px;margin:0;letter-spacing:.2px}h1 span{color:var(--acc)}
.status{font-size:13px;color:var(--mute)}.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;background:var(--mute)}
.dot.on{background:var(--ok)}main{max-width:960px;margin:0 auto;padding:8px 16px 40px}
.bar{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 14px}
button,.btn{font:inherit;font-size:13px;border:1px solid var(--line);background:var(--card);color:var(--ink);padding:5px 10px;border-radius:7px;cursor:pointer;text-decoration:none}
button:hover,.btn:hover{border-color:var(--acc)}button.pri{background:var(--acc);border-color:var(--acc);color:#fff}
.game{background:var(--card);border:1px solid var(--line);border-radius:12px;margin:0 0 12px;overflow:hidden}
.game h2{font-size:16px;margin:0;padding:12px 14px 2px}.game .serial{font:12px ui-monospace,Menlo,monospace;color:var(--mute);padding:0 14px 8px}
.slot{display:grid;grid-template-columns:64px 1fr auto;gap:10px;align-items:center;padding:9px 14px;border-top:1px solid var(--line)}
.slot b{font-size:13px}.meta{font-size:13px;color:var(--mute);min-width:0}.meta .lab{color:var(--ink)}
.acts{display:flex;flex-wrap:wrap;gap:6px;justify-content:flex-end}
.tag{font-size:11px;padding:1px 6px;border-radius:5px;border:1px solid var(--line);margin-left:6px;white-space:nowrap}
.tag.pend{color:var(--warn);border-color:var(--warn)}.tag a{color:inherit}.tag.last{color:var(--acc);border-color:var(--acc)}
.hist{grid-column:1/-1;font-size:13px;margin:4px 0 2px;padding:8px 10px;border-radius:8px;background:var(--bg)}
.hist div{display:flex;justify-content:space-between;gap:8px;padding:3px 0}
.empty{color:var(--mute);padding:30px 0;text-align:center}
#toast{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);background:var(--ink);color:var(--bg);padding:9px 14px;border-radius:9px;font-size:13px;max-width:92vw;display:none}
dialog{border:1px solid var(--line);border-radius:12px;background:var(--card);color:var(--ink);max-width:420px;width:92vw}
dialog input{width:100%;font:inherit;padding:6px 8px;margin:4px 0 10px;border:1px solid var(--line);border-radius:7px;background:var(--bg);color:var(--ink)}
@media (max-width:560px){.slot{grid-template-columns:52px 1fr}.acts{grid-column:1/-1;justify-content:flex-start}}
</style></head><body>
<header><h1>Dreamcast <span>saves</span></h1><div class="status" id="st">…</div></header>
<main>
<div class="bar"><button class="pri" onclick="newSave()">Upload save for a game…</button>
<a class="btn" href="api/export.zip">Download all (zip)</a><button onclick="load()">Refresh</button></div>
<div id="list"><div class="empty">Loading…</div></div>
<p class="status">Changes are queued and written to the virtual SD card the next time openMenu boots
(the card is never edited while the Dreamcast is using it). Every version that ever existed is kept in history. v__VERSION__</p>
</main>
<input type="file" id="file" accept=".vmu,.VMU,.bin" hidden>
<dialog id="dlg"><form method="dialog"><h3 style="margin-top:0">Upload save</h3>
<label>Game serial (folder name, e.g. T-36802N)<input id="d_serial" required pattern="[A-Za-z0-9._-]{1,31}"></label>
<label>Title (optional)<input id="d_title"></label>
<label>Slot (1-5)<input id="d_slot" type="number" min="1" max="5" value="1"></label>
<div class="acts"><button value="cancel">Cancel</button><button class="pri" value="ok">Choose file…</button></div></form></dialog>
<div id="toast"></div>
<script>
const $=s=>document.querySelector(s);let DATA=null;
function toast(t){const e=$('#toast');e.textContent=t;e.style.display='block';clearTimeout(e._t);e._t=setTimeout(()=>e.style.display='none',6000)}
function ago(t){if(!t)return'';const s=Date.now()/1000-t;if(s<90)return'just now';if(s<5400)return Math.round(s/60)+' min ago';if(s<172800)return Math.round(s/3600)+' h ago';return new Date(t*1000).toLocaleDateString()}
function esc(s){return(s==null?'':String(s)).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
// Behind the dashboard (modules/dcbridge): the dashboard's web service answers /dcbridge/ and passes it on. It only takes POST, so PUT and DELETE go as POST with
// ?_method=, every change says it comes from a page, and when Settings is locked with a PIN the PIN is asked for once.
let PIN='';
async function api(m,u,b,h){h=Object.assign({'X-Requested-With':'page'},h||{});let meth=m,url=u;
  if(m==='PUT'||m==='DELETE'){meth='POST';url+=(u.indexOf('?')<0?'?':'&')+'_method='+m}
  if(PIN)h['X-Pin']=PIN;
  const r=await fetch(url,{method:meth,body:b,headers:h});let j={};try{j=await r.json()}catch(e){}
  if((r.status===401||r.status===429)&&meth==='POST'){const p=prompt(j.message||'Enter the PIN');if(p!==null){PIN=p;return api(m,u,b,h)}}
  if(!r.ok)throw new Error(j.error||j.message||r.statusText);return j}
async function load(){
  try{const [s,st]=await Promise.all([api('GET','api/saves'),api('GET','api/status')]);DATA=s;render(s);
    let br=null;try{br=await api('GET','api/bridge')}catch(e){}
    let net='';if(br){const L=br.links;net=' · Dreamcast: '+esc(br.summary)+
      (L.w5500.dreamcast?' · W5500 '+esc(L.w5500.dreamcast):'')+(L.ppp.present?' · PPP '+esc(L.ppp.dreamcast||'up'):'')}
    $('#st').innerHTML='<span class="dot '+(st.connected?'on':'')+'"></span>'+(st.connected?'card online':'card offline')+
      ' · '+st.pending+' queued'+(st.last_session?' · card last used '+ago(st.last_session):'')+net;
  }catch(e){$('#list').innerHTML='<div class="empty">'+esc(e.message)+'</div>'}}
function B(act,g,n,txt,extra){return '<button data-act="'+act+'" data-s="'+esc(g)+'" data-n="'+n+'"'+(extra||'')+'>'+txt+'</button>'}
function render(s){
  if(!s.games.length){$('#list').innerHTML='<div class="empty">No saves yet. Boot a game from openMenu with serial VMU enabled, or upload one.</div>';return}
  $('#list').innerHTML=s.games.map(g=>'<section class="game"><h2>'+esc(g.title||g.serial)+'</h2><div class="serial">'+esc(g.serial)+'</div>'+
   g.slots.map(sl=>{const u='api/saves/'+encodeURIComponent(g.serial)+'/'+sl.slot;
    const tags=(sl.lastdisc?'<span class="tag last" title="openMenu copies the VMU back into this slot on its next boot">last played</span>':'')+
      sl.pending.map(p=>'<span class="tag pend">'+esc(p.action)+' queued <a href="#" data-act="undo" data-id="'+esc(p.id)+'">undo</a></span>').join('');
    return '<div class="slot"><b>Slot '+sl.slot+'</b><div class="meta">'+(sl.label?'<span class="lab">'+esc(sl.label)+'</span> · ':'')+
      (sl.on_card?(sl.valid?'changed '+ago(sl.changed_at):'<span style="color:var(--warn)">wrong size</span>'):'not on card')+
      ' · '+sl.history+' version'+(sl.history==1?'':'s')+tags+'</div><div class="acts">'+
      (sl.on_card?'<a class="btn" href="'+u+'">Download</a>':'')+
      B('upload',g.serial,sl.slot,'Replace…')+B('label',g.serial,sl.slot,'Label')+B('hist',g.serial,sl.slot,'History')+
      (sl.on_card?B('del',g.serial,sl.slot,'Delete'):'')+'</div></div>'}).join('')+'</section>').join('')}
function slotOf(serial,n){const g=DATA&&DATA.games.find(x=>x.serial===serial);return g&&g.slots.find(x=>x.slot===n)}
function pick(){return new Promise(res=>{const f=$('#file');f.value='';f.onchange=()=>res(f.files[0]);f.click()})}
const U=(s,n)=>'api/saves/'+encodeURIComponent(s)+'/'+n;
async function send(serial,slot,file,title){
  if(!file)return;if(file.size!==131072){toast('A VMU save must be exactly 131072 bytes (this is '+file.size+').');return}
  try{const j=await api('PUT',U(serial,slot)+(title?'?title='+encodeURIComponent(title):''),file,{'Content-Type':'application/octet-stream'});
    toast(j.warning||j.note);load()}catch(e){toast(e.message)}}
function newSave(){const d=$('#dlg');d.returnValue='';d.showModal();d.onclose=async()=>{if(d.returnValue!=='ok')return;
  const s=$('#d_serial').value.trim(),n=+$('#d_slot').value||1;send(s,n,await pick(),$('#d_title').value.trim())}}
async function run(fn){try{const j=await fn();if(j&&(j.warning||j.note))toast(j.warning||j.note);load()}catch(e){toast(e.message)}}
document.addEventListener('click',async ev=>{const t=ev.target.closest('[data-act]');if(!t)return;ev.preventDefault();
  const s=t.dataset.s,n=+t.dataset.n,act=t.dataset.act;
  if(act==='upload')return send(s,n,await pick());
  if(act==='undo')return run(()=>api('DELETE','api/pending/'+encodeURIComponent(t.dataset.id)));
  if(act==='label'){const sl=slotOf(s,n);const l=prompt('Slot label shown in openMenu (max 28 characters, empty to remove):',(sl&&sl.label)||'');
    if(l===null)return;return run(()=>api('POST',U(s,n)+'/label',JSON.stringify({label:l}),{'Content-Type':'application/json'}))}
  if(act==='del'){if(!confirm('Delete '+s+' slot '+n+' from the card? The current version stays in history.'))return;return run(()=>api('DELETE',U(s,n)))}
  if(act==='restore')return run(()=>api('POST',U(s,n)+'/history/'+encodeURIComponent(t.dataset.id)+'/restore'));
  if(act==='hist'){const row=t.closest('.slot');const old=row.querySelector('.hist');if(old){old.remove();return}
    const h=await api('GET',U(s,n)+'/history');const d=document.createElement('div');d.className='hist';
    d.innerHTML=h.length?h.map(v=>'<div><span>'+new Date(v.time*1000).toLocaleString()+' · '+esc(v.reason)+' · '+esc(v.sha1)+'</span><span class="acts">'+
      '<a class="btn" href="'+U(s,n)+'/history/'+encodeURIComponent(v.id)+'">Download</a>'+B('restore',s,n,'Restore',' data-id="'+esc(v.id)+'"')+'</span></div>').join(''):'No versions yet.';
    row.appendChild(d)}});
load();setInterval(load,15000);
</script></body></html>
"""
