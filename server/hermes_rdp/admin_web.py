from __future__ import annotations

ADMIN_HTML = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bakunity RDP</title>
<style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;font:15px system-ui;background:#0b0f0d;color:#eef7f0}
main{max-width:980px;margin:auto;padding:24px}.card{background:#121814;border:1px solid #253229;border-radius:18px;padding:18px;margin:14px 0}
h1{margin:0 0 4px}small,.muted{color:#91a399}.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
button,input{border-radius:12px;border:1px solid #314238;background:#0d1310;color:#eef7f0;padding:10px 12px}
button{cursor:pointer}button.primary{background:#1e7a46;border-color:#2da75f}.danger{background:#5b2020}
.device{display:grid;grid-template-columns:1fr auto;gap:12px;align-items:center}.ok{color:#57d982}.bad{color:#ef7b7b}
code{word-break:break-all}.hidden{display:none}
@media(max-width:650px){main{padding:14px}.device{grid-template-columns:1fr}}
</style></head>
<body><main>
<h1>Bakunity RDP</h1><div class="muted">Веб-панель управления сервером</div>
<div id="login" class="card"><b>Токен администратора</b><div class="row" style="margin-top:10px"><input id="token" type="password" placeholder="web admin token" style="flex:1"><button class="primary" onclick="saveToken()">ВОЙТИ</button></div></div>
<div id="app" class="hidden">
<div class="card"><div class="row"><button class="primary" onclick="pair()">НОВЫЙ КОД</button><button onclick="load()">ОБНОВИТЬ</button><span id="server" class="muted"></span></div><div id="pair" style="margin-top:12px"></div></div>
<div id="devices"></div>
</div>
<script>
let T=localStorage.getItem('bakunity_admin_token')||'';
const H=()=>({'Authorization':'Bearer '+T,'Content-Type':'application/json'});
async function api(path,body){let r=await fetch(path,{method:body?'POST':'GET',headers:H(),body:body?JSON.stringify(body):undefined});let j=await r.json();if(!r.ok)throw Error(j.error||('HTTP '+r.status));return j}
function saveToken(){T=document.getElementById('token').value.trim();localStorage.setItem('bakunity_admin_token',T);load()}
async function load(){try{let j=await api('/v1/admin/state');document.getElementById('login').classList.add('hidden');document.getElementById('app').classList.remove('hidden');document.getElementById('server').textContent=j.public_host+':'+j.api_port;render(j.devices)}catch(e){document.getElementById('login').classList.remove('hidden');document.getElementById('app').classList.add('hidden');alert(e.message)}}
function render(ds){let root=document.getElementById('devices');root.innerHTML='';for(const d of ds){let x=document.createElement('div');x.className='card device';x.innerHTML=`<div><b>${esc(d.name)}</b> <span class="${d.online?'ok':'bad'}">${d.online?'● онлайн':'● офлайн'}</span><div class="muted">${esc(d.machine_name)} · RDP: <code>${esc(d.rdp)}</code></div></div><div class="row"><button onclick="renameDev('${d.id}','${escq(d.name)}')">ИМЯ</button><button onclick="slugDev('${d.id}','${escq(d.slug)}')">АДРЕС</button><button onclick="cmd('${d.id}','${d.enabled?'off':'on'}')" class="${d.enabled?'danger':'primary'}">${d.enabled?'ВЫКЛ':'ВКЛ'}</button></div>`;root.appendChild(x)}}
async function pair(){try{let j=await api('/v1/admin/pair',{});document.getElementById('pair').innerHTML='Код: <b>'+esc(j.code)+'</b><br><small>Действует '+j.ttl_seconds+' сек.</small>'}catch(e){alert(e.message)}}
async function renameDev(id,current){let v=prompt('Новое имя',current);if(!v)return;try{await api('/v1/admin/device/'+id+'/rename',{name:v});load()}catch(e){alert(e.message)}}
async function slugDev(id,current){let v=prompt('Часть адреса до домена',current);if(!v)return;try{let j=await api('/v1/admin/device/'+id+'/slug',{slug:v});alert('Новый адрес: '+j.rdp);load()}catch(e){alert(e.message)}}
async function cmd(id,a){try{await api('/v1/admin/device/'+id+'/command',{action:a});load()}catch(e){alert(e.message)}}
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function escq(s){return String(s??'').replace(/['\\]/g,'')}
if(T)load();
</script></main></body></html>"""
