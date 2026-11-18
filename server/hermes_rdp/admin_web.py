from __future__ import annotations

ADMIN_HTML = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#0b0f0d">
<title>Bakunity RDP</title>
<style>
:root{color-scheme:dark;--bg:#090d0b;--card:#111713;--card2:#0d1310;--line:#263229;--text:#f2f7f3;--muted:#91a399;--green:#2fa866;--green2:#174e31;--red:#e76565;--amber:#f0bd64}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 15% 0,#122019 0,transparent 30%),var(--bg);color:var(--text);font:14px/1.45 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
button,input{font:inherit}button{cursor:pointer}.shell{max-width:1180px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:24px}
.brand{display:flex;align-items:center;gap:12px}.logo{width:42px;height:42px;border-radius:13px;background:linear-gradient(145deg,#1f8c51,#143924);display:grid;place-items:center;font-weight:900;font-size:18px;box-shadow:0 10px 35px #0d4f2b55}
h1{font-size:22px;margin:0}.sub{color:var(--muted);font-size:13px}.actions{display:flex;gap:8px;flex-wrap:wrap}
.btn{border:1px solid var(--line);background:#111814;color:var(--text);padding:10px 14px;border-radius:11px;transition:.15s}.btn:hover{border-color:#3c5144;transform:translateY(-1px)}
.btn.primary{background:var(--green);border-color:var(--green);color:#06140c;font-weight:800}.btn.danger{background:#3d1919;border-color:#6a2929;color:#ffbaba}.btn.ghost{background:transparent}
.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:14px}.card{background:linear-gradient(180deg,#121915,#0f1511);border:1px solid var(--line);border-radius:18px;padding:18px;box-shadow:0 16px 45px #0000001f}
.span4{grid-column:span 4}.span8{grid-column:span 8}.span12{grid-column:span 12}.label{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}.value{font-size:22px;font-weight:800;margin-top:5px}.mono{font-family:"SFMono-Regular",Consolas,monospace}
.status{display:inline-flex;align-items:center;gap:7px;padding:6px 10px;border-radius:999px;background:#122018;border:1px solid #284031;color:#b9e8ca;font-size:12px}.dot{width:7px;height:7px;border-radius:50%;background:#51d47f;box-shadow:0 0 0 4px #51d47f17}
.section-head{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:14px}.section-head h2{font-size:16px;margin:0}.muted{color:var(--muted)}
.devices{display:grid;gap:10px}.device{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:14px;align-items:center;background:var(--card2);border:1px solid #202b24;border-radius:14px;padding:14px}
.dev-title{display:flex;align-items:center;gap:8px;font-weight:800;font-size:15px}.online,.offline{width:8px;height:8px;border-radius:50%}.online{background:#4ed27c;box-shadow:0 0 0 4px #4ed27c16}.offline{background:#c35d5d}
.dev-meta{display:flex;gap:10px;flex-wrap:wrap;margin-top:6px;color:var(--muted);font-size:12px}.dev-meta code{color:#d4e3d9}
.empty{padding:32px;text-align:center;color:var(--muted);border:1px dashed #2a372e;border-radius:14px}
.pairbox{display:none;margin-top:14px;background:#0a100d;border:1px solid #29362e;border-radius:14px;padding:16px}.pairbox.show{display:block}
.pair-top{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}.code{font-size:28px;font-weight:900;letter-spacing:.08em}.ttl{color:var(--muted);font-size:12px}
.cmd{margin-top:14px;position:relative}.cmd pre{margin:0;max-height:260px;overflow:auto;white-space:pre-wrap;word-break:break-word;background:#070b09;border:1px solid #202a23;border-radius:12px;padding:14px 110px 14px 14px;color:#cfe7d6;font-size:12px;line-height:1.5}.copy{position:absolute;right:9px;top:9px}
.login-wrap{max-width:520px;margin:10vh auto}.login-wrap .card{padding:24px}.input{width:100%;border:1px solid #314037;background:#0a100d;color:var(--text);padding:12px 13px;border-radius:11px;outline:none}.input:focus{border-color:#3c9c62}.hidden{display:none!important}
.toast{position:fixed;right:20px;bottom:20px;background:#172119;border:1px solid #36503d;border-radius:12px;padding:11px 14px;opacity:0;transform:translateY(8px);pointer-events:none;transition:.2s}.toast.show{opacity:1;transform:none}
.modal{position:fixed;inset:0;background:#0009;display:none;align-items:center;justify-content:center;padding:18px;z-index:10}.modal.show{display:flex}.modal-card{width:min(480px,100%);background:#111713;border:1px solid #2c3a31;border-radius:18px;padding:18px}.modal-card h3{margin:0 0 14px}.field{display:grid;gap:7px;margin:12px 0}.field label{font-size:12px;color:var(--muted)}
@media(max-width:820px){.span4,.span8{grid-column:span 12}.shell{padding:14px}.top{align-items:flex-start;flex-direction:column}.device{grid-template-columns:1fr}.dev-actions{display:flex;flex-wrap:wrap}.cmd pre{padding-right:14px;padding-top:52px}.copy{left:9px;right:auto}.value{font-size:19px}}
</style>
</head>
<body>
<div id="login" class="login-wrap hidden"><div class="card"><div class="brand"><div class="logo">B</div><div><h1>Bakunity RDP</h1><div class="sub">Вход в панель сервера</div></div></div><div class="field"><label>WEB ADMIN TOKEN</label><input id="token" class="input mono" type="password" placeholder="Вставь токен из установщика"></div><button class="btn primary" style="width:100%" onclick="saveToken()">ВОЙТИ</button></div></div>

<div id="app" class="shell hidden">
  <div class="top">
    <div class="brand"><div class="logo">B</div><div><h1>Bakunity RDP</h1><div class="sub">Управление удалёнными компьютерами</div></div></div>
    <div class="actions"><span class="status"><span class="dot"></span>Сервер работает</span><button class="btn" onclick="load()">↻ Обновить</button><button class="btn ghost" onclick="logout()">Выйти</button></div>
  </div>

  <div class="grid">
    <div class="card span4"><div class="label">Сервер</div><div id="serverHost" class="value mono">—</div><div id="serverApi" class="muted">—</div></div>
    <div class="card span4"><div class="label">Компьютеры</div><div id="deviceCount" class="value">0</div><div id="onlineCount" class="muted">0 онлайн</div></div>
    <div class="card span4"><div class="label">RDP-домен</div><div id="domain" class="value mono">—</div><div class="muted">Именованные адреса устройств</div></div>

    <div class="card span12">
      <div class="section-head"><div><h2>Добавить Windows-компьютер</h2><div class="muted">Создай одноразовый код и запусти готовую команду в PowerShell от администратора.</div></div><button class="btn primary" onclick="pair()">+ ДОБАВИТЬ ПК</button></div>
      <div id="pairbox" class="pairbox">
        <div class="pair-top"><div><div class="label">Код подключения</div><div id="pairCode" class="code mono">—</div><div id="pairTtl" class="ttl"></div></div><button class="btn" onclick="copyPairCode()">Копировать код</button></div>
        <div class="cmd"><pre id="pairCommand"></pre><button class="btn primary copy" onclick="copyCommand()">КОПИРОВАТЬ КОМАНДУ</button></div>
        <div id="pairDetails" class="muted" style="margin-top:10px"></div>
      </div>
    </div>

    <div class="card span12">
      <div class="section-head"><div><h2>Компьютеры</h2><div class="muted">Статус и управление подключёнными устройствами.</div></div></div>
      <div id="devices" class="devices"></div>
    </div>
  </div>
</div>

<div id="modal" class="modal" onclick="if(event.target===this)closeModal()"><div class="modal-card"><h3 id="modalTitle">Изменить</h3><div class="field"><label id="modalLabel">Значение</label><input id="modalInput" class="input"></div><div class="actions" style="justify-content:flex-end"><button class="btn" onclick="closeModal()">Отмена</button><button class="btn primary" onclick="submitModal()">Сохранить</button></div></div></div>
<div id="toast" class="toast">Скопировано</div>

<script>
let T=localStorage.getItem('bakunity_admin_token')||'';
let STATE=null, EDIT=null, PAIR=null;
const H=()=>({'Authorization':'Bearer '+T,'Content-Type':'application/json'});
async function api(path,body){const r=await fetch(path,{method:body!==undefined?'POST':'GET',headers:H(),body:body!==undefined?JSON.stringify(body):undefined});let j={};try{j=await r.json()}catch{}if(!r.ok)throw Error(j.error||('HTTP '+r.status));return j}
function showToast(s='Готово'){const t=document.getElementById('toast');t.textContent=s;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),1500)}
function saveToken(){T=document.getElementById('token').value.trim();if(!T)return;localStorage.setItem('bakunity_admin_token',T);load()}
function logout(){localStorage.removeItem('bakunity_admin_token');T='';location.reload()}
async function load(){try{STATE=await api('/v1/admin/state');document.getElementById('login').classList.add('hidden');document.getElementById('app').classList.remove('hidden');renderState()}catch(e){document.getElementById('app').classList.add('hidden');document.getElementById('login').classList.remove('hidden');if(T)showToast(e.message)}}
function renderState(){const ds=STATE.devices||[];document.getElementById('serverHost').textContent=STATE.public_host;document.getElementById('serverApi').textContent='HTTPS API · '+STATE.api_port;document.getElementById('deviceCount').textContent=ds.length;document.getElementById('onlineCount').textContent=ds.filter(x=>x.online).length+' онлайн';document.getElementById('domain').textContent=STATE.device_domain||'не настроен';renderDevices(ds)}
function renderDevices(ds){const root=document.getElementById('devices');root.innerHTML='';if(!ds.length){root.innerHTML='<div class="empty">Пока нет подключённых компьютеров.<br>Нажми «Добавить ПК» выше.</div>';return}for(const d of ds){const x=document.createElement('div');x.className='device';const info=document.createElement('div');const title=document.createElement('div');title.className='dev-title';const dot=document.createElement('span');dot.className=d.online?'online':'offline';const name=document.createElement('span');name.textContent=d.name;title.append(dot,name);const meta=document.createElement('div');meta.className='dev-meta';const machine=document.createElement('span');machine.textContent=d.machine_name;const rdp=document.createElement('code');rdp.textContent=d.rdp;const state=document.createElement('span');state.textContent=d.enabled?'RDP включён':'RDP выключен';meta.append(machine,rdp,state);info.append(title,meta);const acts=document.createElement('div');acts.className='dev-actions actions';acts.append(btn('Имя',()=>editName(d)),btn('RDP-адрес',()=>editSlug(d)),btn(d.enabled?'Выключить':'Включить',()=>cmd(d.id,d.enabled?'off':'on'),d.enabled?'danger':'primary'));x.append(info,acts);root.appendChild(x)}}
function btn(text,fn,kind=''){const b=document.createElement('button');b.className='btn '+kind;b.textContent=text;b.onclick=fn;return b}
async function pair(){try{PAIR=await api('/v1/admin/pair',{});document.getElementById('pairbox').classList.add('show');document.getElementById('pairCode').textContent=PAIR.code;document.getElementById('pairTtl').textContent='Действует '+Math.round(PAIR.ttl_seconds/60)+' минут';document.getElementById('pairCommand').textContent=PAIR.command;document.getElementById('pairDetails').textContent='Fingerprint: '+PAIR.fingerprint+' · Ref: '+PAIR.repository_ref;showToast('Код создан')}catch(e){showToast(e.message)}}
async function copyText(v){await navigator.clipboard.writeText(v);showToast('Скопировано')}
function copyCommand(){if(PAIR)copyText(PAIR.command)}
function copyPairCode(){if(PAIR)copyText(PAIR.code)}
function editName(d){EDIT={type:'rename',id:d.id};openModal('Изменить имя','Название компьютера',d.name)}
function editSlug(d){EDIT={type:'slug',id:d.id};openModal('Изменить RDP-адрес','Часть адреса до домена',d.slug||'')}
function openModal(title,label,value){document.getElementById('modalTitle').textContent=title;document.getElementById('modalLabel').textContent=label;const i=document.getElementById('modalInput');i.value=value;document.getElementById('modal').classList.add('show');setTimeout(()=>{i.focus();i.select()},50)}
function closeModal(){document.getElementById('modal').classList.remove('show');EDIT=null}
async function submitModal(){if(!EDIT)return;const v=document.getElementById('modalInput').value.trim();if(!v)return;try{if(EDIT.type==='rename')await api('/v1/admin/device/'+encodeURIComponent(EDIT.id)+'/rename',{name:v});else await api('/v1/admin/device/'+encodeURIComponent(EDIT.id)+'/slug',{slug:v});closeModal();await load();showToast('Сохранено')}catch(e){showToast(e.message)}}
async function cmd(id,a){try{await api('/v1/admin/device/'+encodeURIComponent(id)+'/command',{action:a});await load();showToast('Команда '+a.toUpperCase()+' отправлена')}catch(e){showToast(e.message)}}
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal();if(e.key==='Enter'&&document.getElementById('modal').classList.contains('show'))submitModal()});
if(T)load();else document.getElementById('login').classList.remove('hidden');
</script>
</body></html>"""
