from __future__ import annotations

ADMIN_HTML = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0a0f0c">
<title>Bakunity RDP</title>
<style>
:root{
  color-scheme:dark;
  --bg:#090d0b;--panel:#0f1511;--panel2:#121a15;--panel3:#0b100d;
  --line:#223029;--line2:#2d3c33;--text:#f3f7f4;--muted:#8d9c93;
  --green:#39d27d;--green2:#1e8e51;--green3:#123824;--red:#ff6b6b;
  --orange:#f0b35d;--blue:#67a7ff;--shadow:0 20px 60px rgba(0,0,0,.28);
  --radius:18px;
}
*{box-sizing:border-box}
html,body{margin:0;min-height:100%;background:var(--bg);color:var(--text);font:14px/1.45 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
body{background:
 radial-gradient(circle at 15% -10%,rgba(49,120,77,.18),transparent 34%),
 radial-gradient(circle at 90% 5%,rgba(39,82,61,.12),transparent 25%),var(--bg)}
button,input{font:inherit}button{color:inherit}
.hidden{display:none!important}
.app{min-height:100vh;display:grid;grid-template-columns:236px minmax(0,1fr)}
.sidebar{position:sticky;top:0;height:100vh;border-right:1px solid var(--line);background:rgba(10,15,12,.88);backdrop-filter:blur(18px);padding:18px 14px;display:flex;flex-direction:column}
.brand{display:flex;align-items:center;gap:11px;padding:6px 8px 18px}
.logo{width:40px;height:40px;border-radius:13px;background:#07110f;display:grid;place-items:center;box-shadow:0 10px 28px rgba(39,180,101,.18);border:1px solid #1d3b2b;overflow:hidden}.logo svg{width:40px;height:40px;display:block}
.brand-title{font-size:16px;font-weight:800;letter-spacing:-.02em}.brand-sub{font-size:11px;color:var(--muted);margin-top:1px}
.nav{display:grid;gap:5px}.nav button{width:100%;border:0;background:transparent;border-radius:11px;padding:10px 11px;text-align:left;color:var(--muted);display:flex;align-items:center;gap:10px;cursor:pointer}
.nav button:hover{background:#111a14;color:var(--text)}.nav button.active{background:#15251b;color:#dff8e9}
.nav .ico{width:24px;text-align:center;color:#8fcaa7}
.side-bottom{margin-top:auto}.server-mini{border:1px solid var(--line);background:#0c130f;border-radius:14px;padding:11px}
.server-mini .row{display:flex;align-items:center;justify-content:space-between;gap:8px}.dot{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 0 4px rgba(57,210,125,.1)}
.main{min-width:0}.topbar{height:70px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:16px;padding:0 28px;background:rgba(9,13,11,.72);backdrop-filter:blur(16px);position:sticky;top:0;z-index:5}
.page-title{font-size:18px;font-weight:800;letter-spacing:-.02em}.top-actions{display:flex;align-items:center;gap:8px}
.btn{border:1px solid var(--line2);background:#101713;border-radius:11px;padding:9px 13px;cursor:pointer;transition:.15s}.btn:hover{transform:translateY(-1px);border-color:#43574b}.btn.primary{background:var(--green2);border-color:#2aa963;color:white;font-weight:750}.btn.ghost{background:transparent}.btn.danger{background:#351717;border-color:#672828;color:#ffb1b1}.btn.small{padding:7px 10px;font-size:12px}
.content{padding:26px;max-width:1500px;margin:auto}
.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:18px}
.card{border:1px solid var(--line);background:linear-gradient(180deg,rgba(19,27,22,.96),rgba(13,19,15,.96));border-radius:var(--radius);box-shadow:0 8px 30px rgba(0,0,0,.12)}
.stat{padding:17px}.stat-label{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}.stat-value{font-size:25px;font-weight:850;margin-top:6px;letter-spacing:-.04em}.stat-foot{font-size:12px;color:var(--muted);margin-top:3px}
.layout{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(320px,.7fr);gap:14px}.section{padding:18px}.section-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:14px}.section-title{font-size:15px;font-weight:800}.section-sub{font-size:12px;color:var(--muted);margin-top:2px}
.device-list{display:grid;gap:9px}.device-row{border:1px solid #202b24;background:#0c120e;border-radius:14px;padding:14px;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:14px;align-items:center;cursor:pointer;transition:.15s}.device-row:hover{border-color:#35483c;background:#0f1712}
.device-name{display:flex;align-items:center;gap:9px;font-weight:800}.state-dot{width:8px;height:8px;border-radius:50%}.state-dot.on{background:var(--green);box-shadow:0 0 0 4px rgba(57,210,125,.08)}.state-dot.off{background:#8d4e4e}.device-meta{margin-top:5px;color:var(--muted);font-size:12px;display:flex;gap:10px;flex-wrap:wrap}.mono{font-family:"SFMono-Regular",Consolas,monospace}
.resources{display:grid;grid-template-columns:repeat(3,78px);gap:8px}.res{font-size:11px;color:var(--muted)}.bar{height:5px;background:#1b261f;border-radius:99px;overflow:hidden;margin-top:5px}.bar>i{display:block;height:100%;background:linear-gradient(90deg,#248b52,#40d17d);border-radius:99px}
.empty{padding:38px 16px;text-align:center;color:var(--muted);border:1px dashed #2a382f;border-radius:14px}.empty strong{display:block;color:var(--text);margin-bottom:4px}
.quick{display:grid;gap:9px}.quick-item{padding:13px;border:1px solid #202c24;background:#0c120e;border-radius:13px}.quick-label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.07em}.quick-value{font-weight:750;margin-top:4px;word-break:break-word}.pill{display:inline-flex;align-items:center;gap:6px;padding:5px 9px;border-radius:999px;background:#122018;border:1px solid #263c2e;color:#bfe9cd;font-size:11px}.pill.warn{background:#2a2315;border-color:#4c3b1f;color:#f0ca86}.pill.bad{background:#281616;border-color:#4e2525;color:#ffaaaa}
.incident{display:none;margin-bottom:14px;padding:14px 16px;border:1px solid #62392a;background:linear-gradient(180deg,#241814,#1a1210);border-radius:14px;color:#ffd2bd}.incident.show{display:flex;align-items:flex-start;gap:11px}.incident strong{display:block;color:#fff1e9;margin-bottom:2px}.incident .icon{font-size:18px;line-height:1}
.device-state-grid{display:grid;grid-template-columns:repeat(2,max-content);gap:6px;justify-content:end}.state-chip{display:inline-flex;align-items:center;gap:5px;border:1px solid #29352e;background:#101713;color:#aab8b0;border-radius:999px;padding:5px 8px;font-size:10px;white-space:nowrap}.state-chip.ok{border-color:#28543a;background:#102219;color:#a9e8c0}.state-chip.warn{border-color:#5a4727;background:#241f14;color:#eacb8f}.state-chip.bad{border-color:#603030;background:#241414;color:#ffb3b3}.state-chip i{width:6px;height:6px;border-radius:50%;background:currentColor;display:block}
.device-side{display:grid;gap:10px;justify-items:end}.device-side .resources{justify-content:end}
.add-grid{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;align-items:end;margin-top:18px}.add-grid .field{margin:0}.migration-note{margin-top:12px;padding:12px 14px;border:1px solid #3b472a;background:#171b10;border-radius:12px;color:#d7dfbb;font-size:12px}
.toolbar{display:flex;gap:8px;flex-wrap:wrap}.search{min-width:220px;border:1px solid var(--line2);background:#0b110d;color:var(--text);border-radius:11px;padding:9px 12px;outline:none}.search:focus{border-color:#47805d}
.page{display:none}.page.active{display:block}
.server-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.kv{display:grid;grid-template-columns:160px 1fr;gap:9px 16px;padding:16px 0;border-bottom:1px solid #1d2821}.kv:last-child{border-bottom:0}.kv .k{color:var(--muted)}.kv .v{font-weight:650;word-break:break-word}
.add-hero{padding:24px}.steps{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:18px 0}.step{padding:14px;border:1px solid #26332b;background:#0d140f;border-radius:13px}.step-num{width:24px;height:24px;border-radius:8px;background:#183c27;color:#83dfa8;display:grid;place-items:center;font-size:11px;font-weight:800;margin-bottom:8px}
.pair{display:none;margin-top:16px}.pair.show{display:block}.pair-code{font-size:30px;font-weight:900;letter-spacing:.12em}.cmd-wrap{position:relative;margin-top:12px}.cmd{margin:0;padding:16px 150px 16px 16px;max-height:320px;overflow:auto;background:#070b09;border:1px solid #1f2b23;border-radius:14px;color:#cfe8d7;white-space:pre-wrap;word-break:break-word;font:12px/1.55 "SFMono-Regular",Consolas,monospace}.copy-btn{position:absolute;right:9px;top:9px}
.device-hero{padding:22px;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:18px;align-items:center;margin-bottom:14px}
.device-heading{display:flex;align-items:center;gap:14px}.device-avatar{width:48px;height:48px;border-radius:15px;border:1px solid #2b4334;background:#102319;display:grid;place-items:center}.device-avatar svg{width:24px;height:24px;stroke:#70dfa0}
.device-title{font-size:25px;font-weight:850;letter-spacing:-.035em}.device-sub{color:var(--muted);margin-top:4px;display:flex;gap:9px;flex-wrap:wrap}
.device-actions{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}.device-back{display:inline-flex;align-items:center;gap:7px;color:var(--muted);cursor:pointer;margin-bottom:12px;border:0;background:transparent;padding:0}.device-back:hover{color:var(--text)}
.icon{width:18px;height:18px;display:inline-block;vertical-align:-4px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.icon.sm{width:15px;height:15px;vertical-align:-3px}.nav .ico{width:24px;display:grid;place-items:center}.nav .ico .icon{width:18px;height:18px}
.device-layout{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(310px,.65fr);gap:14px}.device-stack{display:grid;gap:14px}.device-panel{padding:18px}.panel-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:14px}
.access-cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.access-card{border:1px solid #26342b;background:#0c130f;border-radius:15px;padding:15px}.access-card.ready{border-color:#315d41;background:#0e1912}.access-card.disabled{opacity:.67}.access-title{font-weight:800;display:flex;align-items:center;gap:8px}.access-desc{font-size:12px;color:var(--muted);margin:7px 0 13px}.access-foot{display:flex;gap:7px;flex-wrap:wrap}
.health-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.health-item{border:1px solid #213027;background:#0d140f;border-radius:12px;padding:12px}.health-top{display:flex;justify-content:space-between;gap:8px;align-items:center}.health-name{font-size:12px;color:var(--muted)}.health-value{font-weight:800;margin-top:4px}
.metrics-wide{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px}.metric{border:1px solid #213027;background:#0f1712;border-radius:13px;padding:13px}.metric .m-label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}.metric .m-value{font-size:18px;font-weight:800;margin-top:5px}
.detail-block{padding:15px;border:1px solid #213027;background:#0e1511;border-radius:14px}.detail-block h3{font-size:13px;margin:0 0 12px}.detail-row{display:flex;justify-content:space-between;gap:18px;padding:7px 0;color:var(--muted);border-bottom:1px solid #18221c}.detail-row:last-child{border-bottom:0}.detail-row span:last-child{color:var(--text);text-align:right;word-break:break-word}
.actions-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}.danger-zone{margin-top:12px;padding-top:12px;border-top:1px solid #2a211f}
.live-wrap{display:none}.live-wrap.show{display:block}.live-toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px}.live-stage{position:relative;background:#050806;border:1px solid #243229;border-radius:15px;overflow:hidden;min-height:260px;display:grid;place-items:center;outline:none}.live-stage img{display:block;max-width:100%;max-height:72vh;user-select:none;-webkit-user-drag:none}.live-stage.control{cursor:crosshair;border-color:#3e7a55}.live-empty{color:var(--muted);padding:60px 20px;text-align:center}.live-mode{margin-left:auto;font-size:11px;color:var(--muted)}
.status-dot{width:7px;height:7px;border-radius:50%;display:inline-block;background:#6e7772}.status-dot.ok{background:var(--green);box-shadow:0 0 0 3px rgba(57,210,125,.1)}.status-dot.bad{background:var(--red)}.status-dot.warn{background:var(--orange)}
.modal-back{position:fixed;inset:0;background:rgba(0,0,0,.62);display:none;align-items:center;justify-content:center;padding:18px;z-index:30}.modal-back.show{display:flex}.modal{width:min(480px,100%);border:1px solid var(--line2);background:#101713;border-radius:18px;padding:18px;box-shadow:var(--shadow)}.modal h2{font-size:17px;margin:0 0 14px}.field{display:grid;gap:6px;margin:12px 0}.field label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}.input{width:100%;border:1px solid var(--line2);background:#0a100c;color:var(--text);border-radius:11px;padding:11px 12px;outline:none}.input:focus{border-color:#4d8b64}.modal-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:15px}
.login{max-width:480px;margin:12vh auto;padding:0 18px}.login .card{padding:24px}.login h1{margin:0;font-size:22px}.toast{position:fixed;right:20px;bottom:20px;background:#16231a;border:1px solid #35503d;border-radius:12px;padding:11px 14px;z-index:50;opacity:0;transform:translateY(10px);transition:.18s;pointer-events:none}.toast.show{opacity:1;transform:none}
.mobile-menu{display:none}
@media(max-width:1050px){.stats{grid-template-columns:repeat(2,1fr)}.layout{grid-template-columns:1fr}.server-grid{grid-template-columns:1fr}}
@media(max-width:760px){
 .app{display:block}.sidebar{position:fixed;left:0;top:0;bottom:0;width:245px;z-index:40;transform:translateX(-102%);transition:.18s}.sidebar.open{transform:none;box-shadow:40px 0 80px rgba(0,0,0,.45)}
 .topbar{height:62px;padding:0 14px}.mobile-menu{display:inline-flex}.content{padding:14px}.stats{grid-template-columns:1fr 1fr;gap:8px}.stat{padding:14px}.stat-value{font-size:21px}
 .device-row{grid-template-columns:1fr}.device-side{justify-items:start}.device-state-grid{justify-content:start}.resources{grid-template-columns:repeat(3,1fr)}.steps{grid-template-columns:1fr}.add-grid{grid-template-columns:1fr}.server-grid{grid-template-columns:1fr}.device-layout{grid-template-columns:1fr}.metrics-wide{grid-template-columns:1fr 1fr}.access-cards{grid-template-columns:1fr}.actions-grid{grid-template-columns:1fr 1fr}.device-hero{grid-template-columns:1fr}.device-actions{justify-content:flex-start}.cmd{padding:58px 14px 14px}.copy-btn{left:9px;right:auto}.search{min-width:0;width:100%}
}
</style>
</head>
<body>
<div id="login" class="login hidden">
  <div class="card">
    <div class="brand" style="padding:0 0 18px"><div class="logo" aria-hidden="true"><svg viewBox="0 0 64 64"><defs><linearGradient id="bg" x1="8" y1="4" x2="56" y2="60"><stop stop-color="#75f1c0"/><stop offset="1" stop-color="#39c991"/></linearGradient></defs><rect width="64" height="64" rx="18" fill="#07110f"/><path d="M32 8 53 18.5v14.2c0 11.5-7.3 19.7-21 23.8-13.7-4.1-21-12.3-21-23.8V18.5L32 8Z" fill="url(#bg)" opacity=".18"/><path d="M32 11.5 49 20v11.7c0 9.4-5.8 16.1-17 19.6-11.2-3.5-17-10.2-17-19.6V20l17-8.5Z" fill="none" stroke="url(#bg)" stroke-width="3"/><path d="M23 32h18M32 23v18" stroke="url(#bg)" stroke-width="3" stroke-linecap="round"/></svg></div><div><div class="brand-title">Bakunity RDP</div><div class="brand-sub">Server Control</div></div></div>
    <h1>Вход в Bakunity</h1>
    <p id="loginHint" style="color:var(--muted);margin-top:6px">Введи логин и пароль администратора.</p>
    <div class="field"><label>Логин</label><input id="loginUser" class="input" type="text" autocomplete="username" value="admin"></div>
    <div class="field"><label>Пароль</label><input id="loginPassword" class="input" type="password" autocomplete="current-password" placeholder="Пароль"></div>
    <button id="loginButton" class="btn primary" style="width:100%" onclick="login()">Войти</button>
  </div>
</div>

<div id="app" class="app hidden">
  <aside id="sidebar" class="sidebar">
    <div class="brand"><div class="logo" aria-hidden="true"><svg viewBox="0 0 64 64"><defs><linearGradient id="bg" x1="8" y1="4" x2="56" y2="60"><stop stop-color="#75f1c0"/><stop offset="1" stop-color="#39c991"/></linearGradient></defs><rect width="64" height="64" rx="18" fill="#07110f"/><path d="M32 8 53 18.5v14.2c0 11.5-7.3 19.7-21 23.8-13.7-4.1-21-12.3-21-23.8V18.5L32 8Z" fill="url(#bg)" opacity=".18"/><path d="M32 11.5 49 20v11.7c0 9.4-5.8 16.1-17 19.6-11.2-3.5-17-10.2-17-19.6V20l17-8.5Z" fill="none" stroke="url(#bg)" stroke-width="3"/><path d="M23 32h18M32 23v18" stroke="url(#bg)" stroke-width="3" stroke-linecap="round"/></svg></div><div><div class="brand-title">Bakunity RDP</div><div class="brand-sub">Server Control</div></div></div>
    <nav class="nav">
      <button data-page="overview" class="active" onclick="go('overview')"><span class="ico"><svg class="icon" viewBox="0 0 24 24"><path d="M3 11.5 12 4l9 7.5"/><path d="M5.5 10.5V20h13v-9.5"/><path d="M9.5 20v-5.5h5V20"/></svg></span>Обзор</button>
      <button data-page="computers" onclick="go('computers')"><span class="ico"><svg class="icon" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg></span>Компьютеры</button>
      <button data-page="add" onclick="go('add')"><span class="ico"><svg class="icon" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg></span>Добавить ПК</button>
      <button data-page="server" onclick="go('server')"><span class="ico"><svg class="icon" viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="6" rx="2"/><rect x="4" y="14" width="16" height="6" rx="2"/><path d="M8 7h.01M8 17h.01"/></svg></span>Сервер</button>
    </nav>
    <div class="side-bottom">
      <div class="server-mini">
        <div class="row"><span style="font-weight:750">Сервер</span><span class="dot"></span></div>
        <div id="sideHost" class="mono" style="font-size:11px;color:var(--muted);margin-top:5px">—</div>
      </div>
      <button class="btn ghost" style="width:100%;margin-top:8px" onclick="logout()">Выйти</button>
    </div>
  </aside>

  <main class="main">
    <header class="topbar">
      <div style="display:flex;align-items:center;gap:9px"><button class="btn mobile-menu" aria-label="Меню" onclick="toggleMenu()"><svg class="icon" viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h16"/></svg></button><div id="pageTitle" class="page-title">Обзор</div></div>
      <div class="top-actions"><span id="topStatus" class="pill"><span class="status-dot ok"></span>Система работает</span><button class="btn small" onclick="load()"><svg class="icon sm" viewBox="0 0 24 24"><path d="M20 7v5h-5"/><path d="M19 12a7 7 0 1 1-2-5"/></svg> Обновить</button></div>
    </header>

    <div class="content">
      <section id="page-overview" class="page active">
        <div id="incidentBanner" class="incident"><div><svg class="icon" viewBox="0 0 24 24"><path d="M12 3 2.8 20h18.4L12 3Z"/><path d="M12 9v5M12 17.5h.01"/></svg></div><div><strong id="incidentTitle">Есть проблемы с подключением</strong><div id="incidentText"></div></div></div>
        <div class="stats">
          <div class="card stat"><div class="stat-label">Компьютеры</div><div id="statDevices" class="stat-value">0</div><div id="statOnline" class="stat-foot">0 агентов онлайн</div></div>
          <div class="card stat"><div class="stat-label">Доступны</div><div id="statReady" class="stat-value">0</div><div class="stat-foot">RDP или Live Screen готовы</div></div>
          <div class="card stat"><div class="stat-label">Требуют внимания</div><div id="statProblems" class="stat-value">0</div><div class="stat-foot">агент онлайн, доступа нет</div></div>
          <div class="card stat"><div class="stat-label">OpenSSH</div><div id="statSsh" class="stat-value">—</div><div class="stat-foot">серверный транспорт</div></div>
        </div>
        <div class="layout">
          <div class="card section">
            <div class="section-head"><div><div class="section-title">Компьютеры</div><div class="section-sub">Состояние и загрузка подключённых Windows-машин.</div></div><button class="btn small primary" onclick="go('add')">+ Добавить</button></div>
            <div id="overviewDevices" class="device-list"></div>
          </div>
          <div class="card section">
            <div class="section-head"><div><div class="section-title">Система</div><div class="section-sub">Ключевые компоненты сервера.</div></div></div>
            <div id="quickSystem" class="quick"></div>
          </div>
        </div>
      </section>

      <section id="page-computers" class="page">
        <div class="card section">
          <div class="section-head"><div><div class="section-title">Все компьютеры</div><div class="section-sub">Открой компьютер, чтобы увидеть подробности и управление.</div></div><div class="toolbar"><input id="search" class="search" placeholder="Поиск по имени, ПК или адресу" oninput="renderComputers()"><button class="btn primary" onclick="go('add')">+ Добавить ПК</button></div></div>
          <div id="allDevices" class="device-list"></div>
        </div>
      </section>

      <section id="page-add" class="page">
        <div class="card add-hero">
          <div class="section-head"><div><div class="section-title" style="font-size:18px">Добавить Windows-компьютер</div><div class="section-sub">Подключение занимает одну команду PowerShell.</div></div></div>
          <div class="steps">
            <div class="step"><div class="step-num">1</div><b>Задай имя</b><div class="section-sub">Имя сразу попадёт в команду — установщик не будет спрашивать его позже.</div></div>
            <div class="step"><div class="step-num">2</div><b>Открой PowerShell</b><div class="section-sub">От имени администратора на подключаемом Windows-ПК.</div></div>
            <div class="step"><div class="step-num">3</div><b>Вставь одну команду</b><div class="section-sub">Pro получает RDP + Live Screen. Home автоматически работает через Live Screen.</div></div>
          </div>
          <div class="add-grid">
            <div class="field"><label>Название компьютера</label><input id="pairName" class="input" placeholder="Например: FSRV" autocomplete="off"></div>
            <button class="btn primary" onclick="createPair()">Создать команду</button>
          </div>
          <div class="migration-note"><b>Если Hermes RDP уже установлен:</b> установщик покажет старый и новый сервер и попросит только слово <span class="mono">REPLACE</span>. После подтверждения дополнительных вопросов больше не будет; при неудаче старое подключение откатывается.</div>
          <div id="pairBox" class="pair">
            <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;flex-wrap:wrap;margin-top:18px">
              <div><div class="stat-label">Код подключения</div><div id="pairCode" class="pair-code mono">—</div><div id="pairTtl" class="section-sub">—</div></div>
              <button class="btn" onclick="copyPairCode()">Копировать код</button>
            </div>
            <div class="cmd-wrap"><pre id="pairCommand" class="cmd"></pre><button class="btn primary copy-btn" onclick="copyCommand()">Копировать команду</button></div>
            <div id="pairMeta" class="section-sub" style="margin-top:10px"></div>
          </div>
        </div>
      </section>

      <section id="page-server" class="page">
        <div class="server-grid">
          <div class="card section"><div class="section-title">Сервер</div><div id="serverInfo"></div></div>
          <div class="card section"><div class="section-title">Транспорт и маршрутизация</div><div id="transportInfo"></div></div>
        </div>
      </section>
      <section id="page-device" class="page">
        <button class="device-back" onclick="go('computers')"><svg class="icon sm" viewBox="0 0 24 24"><path d="m15 18-6-6 6-6"/></svg> Назад к компьютерам</button>
        <div class="card device-hero">
          <div class="device-heading">
            <div class="device-avatar"><svg class="icon" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg></div>
            <div><div id="deviceState" class="pill">—</div><div id="deviceTitle" class="device-title">—</div><div id="deviceSub" class="device-sub"></div></div>
          </div>
          <div class="device-actions">
            <button id="liveViewBtn" class="btn primary" onclick="startLive(false)">Live Screen</button>
            <button id="liveControlBtn" class="btn" onclick="startLive(true)">Управлять</button>
            <button id="copyRdpBtn" class="btn" onclick="copySelectedRdp()">Копировать RDP</button>
            <button id="deviceAccessBtn" class="btn" onclick="toggleAccess()">Доступ</button>
          </div>
        </div>

        <div class="device-layout">
          <div class="device-stack">
            <div class="card device-panel">
              <div class="panel-head"><div><div class="section-title">Доступ</div><div class="section-sub">Два независимых способа подключения к этому компьютеру.</div></div></div>
              <div id="deviceAccessCards" class="access-cards"></div>
            </div>

            <div id="liveWrap" class="card device-panel live-wrap">
              <div class="panel-head"><div><div class="section-title">Live Screen</div><div id="liveSub" class="section-sub">Просмотр текущей локальной сессии.</div></div></div>
              <div class="live-toolbar">
                <button id="viewModeBtn" class="btn primary small" onclick="setLiveControl(false)">Только просмотр</button>
                <button id="controlModeBtn" class="btn small" onclick="setLiveControl(true)">Управление</button>
                <button class="btn small" onclick="stopLive()">Закрыть</button>
                <span id="liveModeText" class="live-mode">View Only</span>
              </div>
              <div id="liveStage" class="live-stage" tabindex="0">
                <div id="liveEmpty" class="live-empty">Подключение к экрану…</div>
                <img id="liveImage" class="hidden" alt="Экран компьютера" draggable="false">
              </div>
            </div>

            <div class="card device-panel">
              <div class="panel-head"><div><div class="section-title">Ресурсы</div><div class="section-sub">Последняя телеметрия Windows.</div></div></div>
              <div id="deviceMetrics" class="metrics-wide"></div>
            </div>

            <div class="card device-panel">
              <div class="panel-head"><div><div class="section-title">Подключение и маршруты</div></div></div>
              <div id="deviceConnection" class="detail-block"></div>
            </div>
          </div>

          <div class="device-stack">
            <div class="card device-panel">
              <div class="panel-head"><div><div class="section-title">Здоровье</div><div class="section-sub">Что реально работает прямо сейчас.</div></div></div>
              <div id="deviceHealth" class="health-grid"></div>
            </div>

            <div class="card device-panel">
              <div class="panel-head"><div><div class="section-title">Клиент</div></div></div>
              <div id="deviceClient" class="detail-block"></div>
            </div>

            <div class="card device-panel">
              <div class="panel-head"><div><div class="section-title">Обслуживание</div><div class="section-sub">Изменения и восстановление клиента.</div></div></div>
              <div class="actions-grid">
                <button class="btn" onclick="editSelected('name')">Переименовать</button>
                <button id="editSlugBtn" class="btn" onclick="editSelected('slug')">RDP-адрес</button>
                <button class="btn" onclick="deviceCommand('restart')">Перезапустить tunnel</button>
                <button class="btn" onclick="deviceCommand('repair')">Repair</button>
                <button class="btn" onclick="deviceCommand('update')">Update</button>
              </div>
              <div class="danger-zone"><button class="btn danger" style="width:100%" onclick="deleteSelected()">Удалить компьютер</button></div>
            </div>
          </div>
        </div>
      </section>
    </div>
  </main>
</div>

<div id="modalBack" class="modal-back" onclick="if(event.target===this)closeModal()"><div class="modal">
  <h2 id="modalTitle">Изменить</h2>
  <div class="field"><label id="modalLabel">Значение</label><input id="modalInput" class="input"></div>
  <div class="modal-actions"><button class="btn" onclick="closeModal()">Отмена</button><button class="btn primary" onclick="saveEdit()">Сохранить</button></div>
</div></div>

<div id="toast" class="toast">Готово</div>

<script>
localStorage.removeItem('bakunity_admin_token');
let SESSION=localStorage.getItem('bakunity_admin_session')||'',STATE=null,PAIR=null,SELECTED=null,EDIT=null,CURRENT='overview';
let LIVE=false,LIVE_CONTROL=false,LIVE_TIMER=null,LIVE_META={width:0,height:0,left:0,top:0},LIVE_MOVE_AT=0,LIVE_URL=null;
const $=id=>document.getElementById(id);
const H=()=>Object.assign({'Content-Type':'application/json'},SESSION?{'X-Bakunity-Session':SESSION}:{});
async function api(path,body){const r=await fetch(path,{method:body===undefined?'GET':'POST',headers:H(),credentials:'same-origin',body:body===undefined?undefined:JSON.stringify(body)});let j={};try{j=await r.json()}catch{}if(!r.ok)throw Error(j.error||('HTTP '+r.status));return j}
function toast(s){$('toast').textContent=s;$('toast').classList.add('show');setTimeout(()=>$('toast').classList.remove('show'),1800)}
async function login(){const username=$('loginUser').value.trim(),password=$('loginPassword').value;if(!username||!password)return;try{const result=await api('/v1/admin/auth/login',{username,password});SESSION=String(result.session||'');if(SESSION)localStorage.setItem('bakunity_admin_session',SESSION);$('loginPassword').value='';await load()}catch(e){toast(e.message)}}
async function logout(){stopLive();try{await api('/v1/admin/auth/logout',{})}catch{}SESSION='';localStorage.removeItem('bakunity_admin_session');location.reload()}
async function boot(){try{const a=await api('/v1/admin/auth/status');if(!a.configured){$('loginHint').textContent='Администратор ещё не настроен. На сервере выполни: bakunity-rdpctl admin password --generate';$('loginButton').disabled=true;$('login').classList.remove('hidden');return}if(a.username)$('loginUser').value=a.username;if(a.authenticated){await load()}else{$('login').classList.remove('hidden')}}catch(e){$('login').classList.remove('hidden');toast(e.message)}}
function fmtBytes(v){v=Number(v||0);if(!v)return '0 Б';const u=['Б','КБ','МБ','ГБ','ТБ'];let i=0;while(v>=1024&&i<u.length-1){v/=1024;i++}return (v>=10||i===0?v.toFixed(0):v.toFixed(1))+' '+u[i]}
function pct(v){return Math.max(0,Math.min(100,Number(v||0)))}
function ago(s){if(s===null||s===undefined)return 'нет данных';s=Number(s);if(s<60)return s+' сек. назад';if(s<3600)return Math.floor(s/60)+' мин. назад';if(s<86400)return Math.floor(s/3600)+' ч. назад';return Math.floor(s/86400)+' дн. назад'}
function esc(v){return String(v??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function stateDot(v){return '<span class="status-dot '+(v===true?'ok':v===false?'bad':'warn')+'"></span>'}
function go(page){if(page!=='device')stopLive();CURRENT=page;document.querySelectorAll('.page').forEach(x=>x.classList.remove('active'));const target=$('page-'+page);if(target)target.classList.add('active');document.querySelectorAll('.nav button').forEach(x=>x.classList.toggle('active',x.dataset.page===page));$('pageTitle').textContent={overview:'Обзор',computers:'Компьютеры',add:'Добавить ПК',server:'Сервер',device:SELECTED?SELECTED.name:'Компьютер'}[page]||'Bakunity RDP';$('sidebar').classList.remove('open');if(page==='computers')renderComputers();if(page==='device'&&SELECTED)renderDevice()}
function toggleMenu(){$('sidebar').classList.toggle('open')}
function accessReady(d){const t=d.telemetry||{};const rdp=!!(t.rdp_supported!==false&&t.rdp_endpoint_available===true);const live=!!(t.live_screen_endpoint_available===true);return !!(d.online&&d.enabled&&(rdp||live))}
function hasIncident(d){const t=d.telemetry||{};if(!d.online||!d.enabled)return false;return !accessReady(d)}
async function load(){try{STATE=await api('/v1/admin/state');$('login').classList.add('hidden');$('app').classList.remove('hidden');if(SELECTED){SELECTED=(STATE.devices||[]).find(d=>d.id===SELECTED.id)||null;if(!SELECTED&&CURRENT==='device')go('computers')}renderAll();if(SELECTED&&CURRENT==='device')renderDevice()}catch(e){if(e.message==='unauthorized'||e.message.includes('401')){SESSION='';localStorage.removeItem('bakunity_admin_session');$('app').classList.add('hidden');$('login').classList.remove('hidden')}else{toast(e.message)}}}
function renderAll(){const s=STATE.server,ds=STATE.devices||[],online=ds.filter(d=>d.online).length,ready=ds.filter(accessReady).length,problems=ds.filter(hasIncident);$('sideHost').textContent=s.public_host+':'+s.api_port;$('statDevices').textContent=ds.length;$('statOnline').textContent=online+' агентов онлайн';$('statReady').textContent=ready;$('statProblems').textContent=problems.length;$('statSsh').textContent=':'+s.ssh_port;const ib=$('incidentBanner');if(problems.length){ib.classList.add('show');$('incidentTitle').textContent='Есть компьютеры без рабочего доступа';$('incidentText').textContent=problems.map(d=>d.name).join(', ')+' — агент онлайн, но ни RDP, ни Live Screen не готовы.';$('topStatus').className='pill warn';$('topStatus').innerHTML=stateDot(null)+'Есть проблемы: '+problems.length}else{ib.classList.remove('show');$('topStatus').className='pill';$('topStatus').innerHTML=stateDot(true)+'Система работает'}renderDeviceList($('overviewDevices'),ds.slice(0,6));renderComputers();renderQuick();renderServer()}
function renderDeviceList(root,ds){root.innerHTML='';if(!ds.length){root.innerHTML='<div class="empty"><strong>Компьютеров пока нет</strong>Добавь первый Windows-ПК.</div>';return}for(const d of ds)root.appendChild(deviceNode(d))}
function stateChip(label,value,unknownWarn=false){let cls='bad',txt='нет';if(value===true){cls='ok';txt='да'}else if(value===null||value===undefined){cls=unknownWarn?'warn':'';txt='?'}return '<span class="state-chip '+cls+'"><i></i>'+esc(label)+' '+txt+'</span>'}
function deviceNode(d){const t=d.telemetry||{},el=document.createElement('div');el.className='device-row';el.onclick=()=>openDevice(d.id);const left=document.createElement('div');const mode=t.rdp_supported===false?'Live Screen':(t.rdp_endpoint_available===true&&t.live_screen_endpoint_available===true?'RDP + Live Screen':t.rdp_endpoint_available===true?'RDP':'Live Screen');left.innerHTML='<div class="device-name"><span class="state-dot '+(accessReady(d)?'on':'off')+'"></span><span>'+esc(d.name)+'</span>'+(d.pending_command?'<span class="pill warn">'+esc(d.pending_command)+'</span>':'')+'</div><div class="device-meta"><span>'+esc(d.machine_name)+'</span><span>'+esc(t.windows_edition||t.os||'Windows')+'</span><span>'+esc(mode)+'</span><span>'+ago(d.last_seen_age)+'</span></div>';const side=document.createElement('div');side.className='device-side';side.innerHTML='<div class="device-state-grid">'+stateChip('Агент',d.online)+stateChip('SSH',t.ssh_tunnel_running,true)+stateChip('Live',t.live_screen_endpoint_available,true)+(t.rdp_supported===false?stateChip('RDP Home',false):stateChip('RDP',t.rdp_endpoint_available,true))+'</div><div class="resources">'+resHtml('CPU',t.cpu_percent)+resHtml('RAM',t.ram_percent)+resHtml('DISK',t.disk_percent)+'</div>';el.append(left,side);return el}
function resHtml(n,v){return '<div class="res"><div>'+n+' '+pct(v).toFixed(0)+'%</div><div class="bar"><i style="width:'+pct(v)+'%"></i></div></div>'}
function renderComputers(){if(!STATE)return;let ds=STATE.devices||[];const q=($('search')?.value||'').trim().toLowerCase();if(q)ds=ds.filter(d=>[d.name,d.machine_name,d.rdp,d.slug,d.telemetry?.windows_edition].join(' ').toLowerCase().includes(q));renderDeviceList($('allDevices'),ds)}
function quickItem(label,value,kind=''){return '<div class="quick-item"><div class="quick-label">'+esc(label)+'</div><div class="quick-value">'+(kind?'<span class="pill '+kind+'">'+esc(value)+'</span>':esc(value))+'</div></div>'}
function renderQuick(){const s=STATE.server,ad=s.autodeploy||{},adKind=!ad.enabled?'warn':(['blocked','failed','error'].includes(ad.state)?'bad':(['waiting-ci','deploying'].includes(ad.state)?'warn':''));$('quickSystem').innerHTML=quickItem('API','HTTPS · '+s.api_port)+quickItem('RDP domain',s.device_domain||'не настроен',s.device_domain?'':'warn')+quickItem('RDP ports',s.rdp_port_start+'–'+s.rdp_port_end)+quickItem('Telegram',s.telegram_enabled?'Подключён':'Не используется',s.telegram_enabled?'':'warn')+quickItem('Smart Route',s.smart_route_enabled?'Включён':'Выключен',s.smart_route_enabled?'':'warn')+quickItem('Native Transport',s.native_transport_enabled?'Включён':'Выключен',s.native_transport_enabled?'':'warn')+quickItem('Auto deploy',ad.enabled?(ad.state||'enabled'):'выключен',adKind)+quickItem('Client ref',(s.client_ref||'—').slice(0,12))}
function row(k,v){return '<div class="kv"><div class="k">'+esc(k)+'</div><div class="v">'+esc(v??'—')+'</div></div>'}
function renderServer(){const s=STATE.server,ad=s.autodeploy||{},adState=ad.enabled?(ad.state||'enabled'):'выключен';$('serverInfo').innerHTML=row('Public host',s.public_host)+row('HTTPS API',s.api_port)+row('OpenSSH',s.ssh_port)+row('RDP ports',s.rdp_port_start+'–'+s.rdp_port_end)+row('Device domain',s.device_domain||'не настроен')+row('Tracking ref',s.repository_requested_ref||'—')+row('Repository ref',(s.repository_ref||'').slice(0,16))+row('Client ref',(s.client_ref||'').slice(0,16));$('transportInfo').innerHTML=row('Telegram',s.telegram_enabled?'подключён':'не используется')+row('Smart Route',s.smart_route_enabled?'включён':'выключен')+row('Mesh control',s.smart_route_control_url||'—')+row('Native Transport',s.native_transport_enabled?'включён':'выключен')+row('Relay',s.native_transport_relay_addr||'—')+row('Auto deploy',adState)+row('Auto deploy target',(ad.target_sha||'—').slice(0,16))+row('Auto deploy detail',ad.detail||'—')+'<div style="margin-top:14px"><button class="btn '+(ad.enabled?'danger':'primary')+'" onclick="toggleAutodeploy()">'+(ad.enabled?'Выключить автодеплой':'Включить автодеплой')+'</button></div>'}
async function toggleAutodeploy(){const ad=STATE?.server?.autodeploy||{};try{await api('/v1/admin/autodeploy',{enabled:!ad.enabled});await load();toast(ad.enabled?'Автодеплой выключен':'Автодеплой включён')}catch(e){toast(e.message)}}
async function createPair(){const name=$('pairName').value.trim();if(!name){toast('Сначала укажи название компьютера');$('pairName').focus();return}try{PAIR=await api('/v1/admin/pair',{name});$('pairBox').classList.add('show');$('pairCode').textContent=PAIR.code;$('pairTtl').textContent='Действует '+Math.round(PAIR.ttl_seconds/60)+' минут';$('pairCommand').textContent=PAIR.command;$('pairMeta').textContent='Имя: '+PAIR.name+' · Ref: '+PAIR.repository_ref;toast('Команда создана')}catch(e){toast(e.message)}}
async function copyText(v){try{await navigator.clipboard.writeText(v);toast('Скопировано')}catch{toast('Не удалось скопировать')}}
function copyCommand(){if(PAIR)copyText(PAIR.command)}function copyPairCode(){if(PAIR)copyText(PAIR.code)}
function openDevice(id){SELECTED=(STATE.devices||[]).find(d=>d.id===id)||null;if(!SELECTED)return;go('device')}
function metric(label,value,sub=''){return '<div class="metric"><div class="m-label">'+esc(label)+'</div><div class="m-value">'+esc(value)+'</div>'+(sub?'<div class="section-sub">'+esc(sub)+'</div>':'')+'</div>'}
function detail(k,v){return '<div class="detail-row"><span>'+esc(k)+'</span><span>'+esc(v??'—')+'</span></div>'}
function boolState(v,yes='Да',no='Нет'){return v===null||v===undefined?'Неизвестно':v?yes:no}
function health(label,value,goodText,badText){return '<div class="health-item"><div class="health-top"><span class="health-name">'+esc(label)+'</span>'+stateDot(value)+'</div><div class="health-value">'+esc(value===true?goodText:value===false?badText:'Неизвестно')+'</div></div>'}
function renderDevice(){if(!SELECTED)return;const d=SELECTED,t=d.telemetry||{},sr=d.smart_route||{},nt=d.native_transport||{},ready=accessReady(d),rdpSupported=t.rdp_supported!==false,rdpReady=rdpSupported&&t.rdp_endpoint_available===true,liveReady=t.live_screen_endpoint_available===true;$('pageTitle').textContent=d.name;$('deviceState').className='pill '+(ready?'':d.online?'warn':'bad');$('deviceState').innerHTML=stateDot(ready?true:d.online?null:false)+(ready?'Доступен':d.online?'Требует внимания':'Не в сети');$('deviceTitle').textContent=d.name;$('deviceSub').innerHTML='<span>'+esc(d.machine_name)+'</span><span>'+esc(t.windows_edition||t.os||'Windows')+'</span><span>'+esc(t.user?'Пользователь: '+t.user:'Нет активного пользователя')+'</span><span>'+ago(d.last_seen_age)+'</span>';$('liveViewBtn').disabled=!liveReady;$('liveControlBtn').disabled=!liveReady;$('copyRdpBtn').disabled=!rdpReady;$('editSlugBtn').disabled=!rdpSupported;$('deviceAccessBtn').textContent=d.enabled?'Отключить доступ':'Включить доступ';$('deviceAccessBtn').className='btn '+(d.enabled?'danger':'primary');
$('deviceAccessCards').innerHTML='<div class="access-card '+(liveReady?'ready':'disabled')+'"><div class="access-title">'+stateDot(liveReady)+'Live Screen</div><div class="access-desc">'+(liveReady?'Текущая локальная сессия. Пользователь на компьютере остаётся в системе.':'Недоступен: нужен активный пользователь и работающий Live Screen helper.')+'</div><div class="access-foot"><button class="btn small primary" '+(liveReady?'':'disabled')+' onclick="startLive(false)">Только просмотр</button><button class="btn small" '+(liveReady?'':'disabled')+' onclick="startLive(true)">Управлять</button></div></div><div class="access-card '+(rdpReady?'ready':'disabled')+'"><div class="access-title">'+stateDot(rdpReady)+(rdpSupported?'Microsoft RDP':'Microsoft RDP · не поддерживается редакцией')+'</div><div class="access-desc">'+(rdpSupported?(rdpReady?'Отдельная RDP-сессия через '+esc(d.rdp):'RDP поддерживается Windows, но публичный endpoint сейчас не готов.'):'Windows Home не принимает входящие Microsoft RDP. Используй Live Screen.')+'</div><div class="access-foot"><button class="btn small" '+(rdpReady?'':'disabled')+' onclick="copySelectedRdp()">Копировать адрес</button></div></div>';
$('deviceMetrics').innerHTML=metric('CPU',pct(t.cpu_percent).toFixed(1)+'%')+metric('RAM',pct(t.ram_percent).toFixed(1)+'%',fmtBytes(t.ram_used_bytes)+' / '+fmtBytes(t.ram_total_bytes))+metric('Диск C',pct(t.disk_percent).toFixed(1)+'%',fmtBytes(t.disk_used_bytes)+' / '+fmtBytes(t.disk_total_bytes))+metric('Данные',ago(d.last_seen_age));
$('deviceHealth').innerHTML=health('Агент',d.online,'Онлайн','Оффлайн')+health('SSH tunnel',t.ssh_tunnel_running,'Работает','Остановлен')+health('Live Screen',t.live_screen_endpoint_available,'Готов','Недоступен')+(rdpSupported?health('RDP endpoint',t.rdp_endpoint_available,'Готов','Недоступен'):health('RDP edition',false,'Поддерживается','Windows Home'));
$('deviceConnection').innerHTML=detail('Windows',t.os||'—')+detail('Редакция',t.windows_edition||'—')+detail('Пользователь',t.user||'—')+detail('Сетевой маршрут',t.route||'—')+detail('RDP',rdpSupported?d.rdp:'Не поддерживается редакцией')+detail('LAN',(sr.lan_ipv4||[]).join(', ')||'—')+detail('Mesh',sr.mesh_online?(sr.mesh_ipv4||'online'):'offline')+detail('Native Transport',nt.online?'online':'offline')+detail('Transport path',nt.path||'—')+detail('Relay',nt.relay_connected?'connected':'—');
const lr=d.last_result||{},ms=t.maintenance_status||{};$('deviceClient').innerHTML=detail('Client ref',(t.client_repository_ref||'—').slice(0,16))+detail('Certificate',rdpSupported?boolState(t.certificate_lifecycle_ok,'активен','нужен repair'):'не нужен')+detail('Maintenance',ms.state||'—')+detail('Pending',d.pending_command||'—')+detail('Последняя команда',lr.action?(lr.action+' · '+(lr.ok?'OK':'ERROR')):'—')+(lr.message?detail('Сообщение',lr.message):'')}
function copySelectedRdp(){if(SELECTED)copyText(SELECTED.rdp)}
function editSelected(type){if(!SELECTED)return;if(type==='slug'&&SELECTED.telemetry?.rdp_supported===false){toast('RDP недоступен в этой редакции Windows');return}EDIT=type;$('modalTitle').textContent=type==='name'?'Изменить имя':'Изменить RDP-адрес';$('modalLabel').textContent=type==='name'?'Название компьютера':'Часть адреса до домена';$('modalInput').value=type==='name'?SELECTED.name:(SELECTED.slug||'');$('modalBack').classList.add('show');setTimeout(()=>$('modalInput').focus(),30)}
function closeModal(){$('modalBack').classList.remove('show');EDIT=null}
async function saveEdit(){if(!SELECTED||!EDIT)return;const v=$('modalInput').value.trim();if(!v)return;try{await api('/v1/admin/device/'+encodeURIComponent(SELECTED.id)+'/'+(EDIT==='name'?'rename':'slug'),EDIT==='name'?{name:v}:{slug:v});closeModal();await load();toast('Сохранено')}catch(e){toast(e.message)}}
async function deviceCommand(action){if(!SELECTED)return;try{await api('/v1/admin/device/'+encodeURIComponent(SELECTED.id)+'/command',{action});await load();toast('Команда отправлена')}catch(e){toast(e.message)}}
function toggleAccess(){deviceCommand(SELECTED&&SELECTED.enabled?'off':'on')}
async function deleteSelected(){if(!SELECTED)return;if(!confirm('Удалить '+SELECTED.name+'? Для повторного доступа компьютер нужно будет подключить заново.'))return;try{await api('/v1/admin/device/'+encodeURIComponent(SELECTED.id)+'/delete',{});stopLive();SELECTED=null;await load();go('computers');toast('Компьютер удалён')}catch(e){toast(e.message)}}
async function fetchLiveFrame(){if(!LIVE||!SELECTED)return;try{const r=await fetch('/v1/admin/device/'+encodeURIComponent(SELECTED.id)+'/screen',{headers:SESSION?{'X-Bakunity-Session':SESSION}:{},credentials:'same-origin',cache:'no-store'});if(!r.ok){let m='Live Screen HTTP '+r.status;try{const j=await r.json();m=j.error||m}catch{}throw Error(m)}LIVE_META={width:Number(r.headers.get('X-Bakunity-Width')||0),height:Number(r.headers.get('X-Bakunity-Height')||0),left:Number(r.headers.get('X-Bakunity-Left')||0),top:Number(r.headers.get('X-Bakunity-Top')||0)};const b=await r.blob();if(LIVE_URL)URL.revokeObjectURL(LIVE_URL);LIVE_URL=URL.createObjectURL(b);$('liveImage').src=LIVE_URL;$('liveImage').classList.remove('hidden');$('liveEmpty').classList.add('hidden')}catch(e){$('liveEmpty').classList.remove('hidden');$('liveEmpty').textContent=e.message}finally{if(LIVE)LIVE_TIMER=setTimeout(fetchLiveFrame,500)}}
function startLive(control){if(!SELECTED||SELECTED.telemetry?.live_screen_endpoint_available!==true){toast('Live Screen недоступен');return}LIVE=true;$('liveWrap').classList.add('show');setLiveControl(!!control);$('liveEmpty').textContent='Подключение к экрану…';$('liveEmpty').classList.remove('hidden');$('liveImage').classList.add('hidden');clearTimeout(LIVE_TIMER);fetchLiveFrame();setTimeout(()=>$('liveStage').scrollIntoView({behavior:'smooth',block:'center'}),80)}
function stopLive(){LIVE=false;LIVE_CONTROL=false;clearTimeout(LIVE_TIMER);LIVE_TIMER=null;if(LIVE_URL){URL.revokeObjectURL(LIVE_URL);LIVE_URL=null}const w=$('liveWrap');if(w)w.classList.remove('show');const st=$('liveStage');if(st)st.classList.remove('control')}
function setLiveControl(v){LIVE_CONTROL=!!v;$('viewModeBtn').className='btn small '+(!LIVE_CONTROL?'primary':'');$('controlModeBtn').className='btn small '+(LIVE_CONTROL?'primary':'');$('liveModeText').textContent=LIVE_CONTROL?'Control · ввод отправляется на ПК':'View Only · ввод заблокирован';$('liveStage').classList.toggle('control',LIVE_CONTROL);if(LIVE_CONTROL)$('liveStage').focus()}
async function sendLiveInput(body){if(!LIVE||!LIVE_CONTROL||!SELECTED)return;try{await api('/v1/admin/device/'+encodeURIComponent(SELECTED.id)+'/screen-input',body)}catch(e){toast(e.message);setLiveControl(false)}}
function livePoint(e){const img=$('liveImage'),r=img.getBoundingClientRect();if(!r.width||!r.height)return null;const rx=Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),ry=Math.max(0,Math.min(1,(e.clientY-r.top)/r.height));return{x:Math.round(LIVE_META.left+rx*LIVE_META.width),y:Math.round(LIVE_META.top+ry*LIVE_META.height)}}
$('liveStage').addEventListener('mousemove',e=>{if(!LIVE_CONTROL)return;const now=Date.now();if(now-LIVE_MOVE_AT<45)return;LIVE_MOVE_AT=now;const p=livePoint(e);if(p)sendLiveInput({kind:'move',x:p.x,y:p.y})});
$('liveStage').addEventListener('mousedown',e=>{if(!LIVE_CONTROL)return;e.preventDefault();const p=livePoint(e);if(p)sendLiveInput({kind:'move',x:p.x,y:p.y});sendLiveInput({kind:'button',button:e.button===2?'right':'left',down:true});$('liveStage').focus()});
$('liveStage').addEventListener('mouseup',e=>{if(!LIVE_CONTROL)return;e.preventDefault();sendLiveInput({kind:'button',button:e.button===2?'right':'left',down:false})});
$('liveStage').addEventListener('contextmenu',e=>{if(LIVE_CONTROL)e.preventDefault()});
$('liveStage').addEventListener('wheel',e=>{if(!LIVE_CONTROL)return;e.preventDefault();sendLiveInput({kind:'wheel',delta:e.deltaY<0?120:-120})},{passive:false});
$('liveStage').addEventListener('keydown',e=>{if(!LIVE_CONTROL)return;e.preventDefault();sendLiveInput({kind:'key',vk:e.keyCode||e.which||0,down:true})});
$('liveStage').addEventListener('keyup',e=>{if(!LIVE_CONTROL)return;e.preventDefault();sendLiveInput({kind:'key',vk:e.keyCode||e.which||0,down:false})});
document.addEventListener('keydown',e=>{if(e.key==='Escape'){if(LIVE)stopLive();closeModal()}if(e.key==='Enter'&&$('modalBack').classList.contains('show'))saveEdit()});
boot();
setInterval(()=>{if(STATE&&!document.hidden&&!LIVE)load()},15000);
</script>
</body>
</html>"""
