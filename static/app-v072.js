let config = null;
let selectedVoice = 'es-MX-DaliaNeural';
let readMode = 'all';
let testPlatform = 'twitch';
let saveTimer = null;
let loading = true;
let runtimePaused = false;
const $ = id => document.getElementById(id);
const STORE_KEY = 'kztts_settings_v06';

const platformMeta = {
  twitch:{name:'Twitch',icon:'T',cls:'twitch'},
  kick:{name:'Kick',icon:'K',cls:'kick'},
  youtube:{name:'YouTube',icon:'▶',cls:'youtube'},
  tiktok:{name:'TikTok',icon:'♪',cls:'tiktok'}
};

function showPage(name){
  document.querySelectorAll('.page').forEach(p=>p.classList.toggle('active',p.dataset.pagePanel===name));
  document.querySelectorAll('.nav-item').forEach(b=>b.classList.toggle('active',b.dataset.page===name));
  const titles={home:'Resumen',platforms:'Plataformas',tts:'TTS · Voz',filters:'Filtros',obs:'OBS'};
  $('pageTitle').textContent=titles[name]||'KZTTS';
  history.replaceState(null,'',`#${name}`);
}

document.querySelectorAll('.nav-item').forEach(b=>b.onclick=()=>showPage(b.dataset.page));
document.querySelectorAll('[data-goto]').forEach(b=>b.onclick=()=>showPage(b.dataset.goto));

function loadLocal(){try{return JSON.parse(localStorage.getItem(STORE_KEY)||'{}')}catch{return {}}}
function setSaveState(mode,text){
  const el=$('saveState'); el.className=`save-state ${mode||''}`; el.innerHTML=`<span></span> ${text}`;
}
function cloudToSaved(c){
  if(!c)return null;
  return {
    channel:c.channel||'',youtubeHandle:c.youtube_handle||'',tiktokHandle:c.tiktok_handle||'',voice:c.voice||'es-MX-DaliaNeural',
    rate:c.rate??0,pitch:c.pitch??0,volume:c.volume??100,maxChars:c.max_chars??180,cooldown:c.cooldown??2,
    ignoreCommands:c.ignore_commands??true,ignoreUrls:c.ignore_urls??true,readUsername:c.read_username??false,
    blacklist:Array.isArray(c.blacklist)?c.blacklist.join('\n'):'',enableTwitch:c.enable_twitch??true,enableKick:c.enable_kick??false,
    enableYoutube:c.enable_youtube??false,enableTiktok:c.enable_tiktok??false,ttsEnabled:c.tts_enabled??true,
    readMode:c.read_mode||'all',commandPrefix:c.command_prefix||'!tts'
  };
}
function currentSettings(){
  return {
    channel:$('channel').value.trim(),youtubeHandle:$('youtubeHandle').value.trim(),tiktokHandle:$('tiktokHandle').value.trim(),
    voice:selectedVoice,rate:Number($('rate').value),pitch:Number($('pitch').value),volume:Number($('volume').value),
    maxChars:Number($('maxChars').value),cooldown:Number($('cooldown').value),ignoreCommands:$('ignoreCommands').checked,
    ignoreUrls:$('ignoreUrls').checked,readUsername:$('readUsername').checked,blacklist:$('blacklist').value,
    enableTwitch:$('enableTwitch').checked,enableKick:$('enableKick').checked,enableYoutube:$('enableYoutube').checked,
    enableTiktok:$('enableTiktok').checked,ttsEnabled:$('ttsEnabled').checked,readMode,commandPrefix:$('commandPrefix').value.trim()||'!tts'
  };
}
function saveLocal(){localStorage.setItem(STORE_KEY,JSON.stringify(currentSettings()))}
function payload(){
  const s=currentSettings();
  return {
    channel:s.channel,enable_twitch:s.enableTwitch,enable_kick:s.enableKick,enable_youtube:s.enableYoutube,youtube_handle:s.youtubeHandle,
    enable_tiktok:s.enableTiktok,tiktok_handle:s.tiktokHandle,overlay_key:config?.overlay_key||null,voice:s.voice,rate:s.rate,pitch:s.pitch,
    blacklist:s.blacklist.split('\n').map(x=>x.trim()).filter(Boolean),ignore_commands:s.ignoreCommands,ignore_urls:s.ignoreUrls,
    read_username:s.readUsername,max_chars:s.maxChars,cooldown:s.cooldown,tts_enabled:s.ttsEnabled,read_mode:s.readMode,
    command_prefix:s.commandPrefix,volume:s.volume
  };
}
function enabledCount(){return ['enableTwitch','enableKick','enableYoutube','enableTiktok'].filter(id=>$(id).checked).length}
async function saveCloud({manual=false}={}){
  saveLocal(); updateHome();
  if(loading || !(config?.twitch_connected||config?.kick_connected))return;
  if(enabledCount()===0){setSaveState('error','Activa una plataforma');return;}
  setSaveState('saving','Guardando…');
  try{
    const r=await fetch('/api/overlay',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload())});
    const data=await r.json().catch(()=>({}));
    if(!r.ok)throw new Error(data.detail||'No se pudo guardar');
    config.overlay_key=data.key;config.overlay_url=data.url;config.overlay_configured=true;
    $('sourceUrl').value=data.url; updateObsState(true); setSaveState('','Todo guardado');
    if(manual){const b=$('generateBtn');const old=b.textContent;b.textContent='Guardado ✓';setTimeout(()=>b.textContent=old,1200)}
  }catch(e){setSaveState('error','Error al guardar');if(manual)alert(e.message)}
}
function scheduleSave(delay=650){if(loading)return;clearTimeout(saveTimer);saveTimer=setTimeout(()=>saveCloud(),delay)}

function voiceInfo(label){
  const name=label.split(' — ')[0]||label;
  const gender=label.includes('masculina')?'Hombre':'Mujer';
  return {name,gender,country:'MX'};
}
function renderVoices(){
  const box=$('voiceCards');box.innerHTML='';
  Object.entries(config.voices||{}).forEach(([value,label])=>{
    const v=voiceInfo(label);const card=document.createElement('button');card.type='button';card.className=`voice-card ${value===selectedVoice?'active':''}`;
    card.dataset.voice=value;card.innerHTML=`<span class="voice-country">${v.country}</span><span class="voice-play">▶</span><h4>${v.name}</h4><p>${v.gender} · Español de México</p>`;
    card.onclick=()=>{selectedVoice=value;$('voice').value=value;renderVoices();updateHome();scheduleSave()};
    box.appendChild(card);
  });
}
function renderReadMode(){
  document.querySelectorAll('[data-read-mode]').forEach(b=>b.classList.toggle('active',b.dataset.readMode===readMode));
  $('commandPrefix').classList.toggle('hidden',readMode!=='command');
  $('runtimeMode').textContent=readMode==='command'?$('commandPrefix').value||'!tts':'Todo';
}
document.querySelectorAll('[data-read-mode]').forEach(b=>b.onclick=()=>{readMode=b.dataset.readMode;renderReadMode();scheduleSave()});

function platformState(p){
  if(p==='twitch')return {connected:!!config.twitch_connected,enabled:$('enableTwitch').checked,label:config.twitch_account||'No conectado'};
  if(p==='kick')return {connected:!!config.kick_connected,enabled:$('enableKick').checked,label:config.kick_account||'No conectado'};
  if(p==='youtube')return {connected:!!config.youtube_configured&&!!$('youtubeHandle').value.trim(),enabled:$('enableYoutube').checked,label:$('youtubeHandle').value.trim()||'Sin canal'};
  return {connected:!!config.tiktok_configured&&!!$('tiktokHandle').value.trim(),enabled:$('enableTiktok').checked,label:$('tiktokHandle').value.trim()||'Sin usuario'};
}
function renderPlatformSummary(){
  const box=$('homePlatforms');box.innerHTML='';let active=0;
  Object.keys(platformMeta).forEach(p=>{
    const m=platformMeta[p],st=platformState(p);if(st.connected&&st.enabled)active++;
    const el=document.createElement('article');el.className=`summary-platform ${st.connected&&st.enabled?'on':''}`;
    el.innerHTML=`<div class="top"><span class="picon">${m.icon}</span><span class="small-dot"></span></div><h4>${m.name}</h4><p>${st.connected?st.label:'No conectado'} · ${st.enabled?'Activo':'Inactivo'}</p>`;
    box.appendChild(el);
  });
  $('navPlatformCount').textContent=active;
}
function updateHome(){
  if(!config)return;renderPlatformSummary();
  const label=config.voices?.[selectedVoice]||'Dalia — México (femenina)';const v=voiceInfo(label);
  $('homeVoiceName').textContent=v.name;$('homeVoiceMeta').textContent=`México · ${v.gender}`;
  $('runtimeVolume').textContent=`${$('volume').value}%`;$('runtimeMode').textContent=readMode==='command'?($('commandPrefix').value||'!tts'):'Todo';
}
function updateObsState(known=config?.overlay_configured){
  const has=!!(known&&config?.overlay_url);$('obsMiniBadge').textContent=has?'Lista':'Sin fuente';$('obsMiniBadge').className=`badge ${has?'good':'neutral'}`;
  if(has)$('sourceUrl').value=config.overlay_url;
}

async function load(){
  try{
    const r=await fetch('/api/config');config=await r.json();
    $('dbWarning').classList.toggle('hidden',config.database_configured!==false);
    $('twitchStatus').textContent=config.twitch_connected?`● ${config.twitch_account}`:'No conectado';
    $('kickStatus').textContent=config.kick_connected?`● ${config.kick_account}`:(config.kick_configured?'No conectado':'Falta configurar servidor');
    $('youtubeStatus').textContent=config.youtube_configured?'Usa tu @handle':'Falta configurar servidor';
    $('tiktokStatus').textContent=config.tiktok_configured?'Usa tu @usuario':'TikTok no disponible';
    $('twitchConnect').textContent=config.twitch_connected?'Reconectar':'Conectar Twitch';$('kickConnect').textContent=config.kick_connected?'Reconectar':'Conectar Kick';
    $('account').textContent=[config.twitch_connected?`Twitch: ${config.twitch_account}`:null,config.kick_connected?`Kick: ${config.kick_account}`:null].filter(Boolean).join(' · ')||'Conecta Twitch o Kick';
    if(config.kick_connected&&!config.kick_subscription_ok){$('kickWarning').textContent=`Kick conectado, pero el webhook del chat necesita atención: ${config.kick_subscription_error||'reconecta Kick'}`;$('kickWarning').classList.remove('hidden')}
    $('youtubeHandle').disabled=!config.youtube_configured;$('tiktokHandle').disabled=!config.tiktok_configured;

    Object.entries(config.voices||{}).forEach(([value,label])=>{const o=document.createElement('option');o.value=value;o.textContent=label;$('voice').appendChild(o)});
    const saved=cloudToSaved(config.saved_settings)||loadLocal();
    $('channel').value=saved.channel||config.twitch_account||'';$('youtubeHandle').value=saved.youtubeHandle||'@KhrizYT';$('tiktokHandle').value=saved.tiktokHandle||'';
    $('blacklist').value=saved.blacklist||config.default_blacklist.join('\n');selectedVoice=saved.voice||'es-MX-DaliaNeural';$('voice').value=selectedVoice;
    $('rate').value=saved.rate??0;$('pitch').value=saved.pitch??0;$('volume').value=saved.volume??100;$('maxChars').value=saved.maxChars??180;$('cooldown').value=saved.cooldown??2;
    $('ignoreCommands').checked=saved.ignoreCommands??true;$('ignoreUrls').checked=saved.ignoreUrls??true;$('readUsername').checked=saved.readUsername??false;$('ttsEnabled').checked=saved.ttsEnabled??true;
    readMode=saved.readMode||'all';$('commandPrefix').value=saved.commandPrefix||'!tts';
    $('enableTwitch').checked=!!config.twitch_connected&&(saved.enableTwitch??true);$('enableKick').checked=!!config.kick_connected&&!!config.kick_subscription_ok&&(saved.enableKick??true);
    $('enableYoutube').checked=!!config.youtube_configured&&!!$('youtubeHandle').value.trim()&&(saved.enableYoutube??true);$('enableTiktok').checked=!!config.tiktok_configured&&!!$('tiktokHandle').value.trim()&&(saved.enableTiktok??false);
    $('enableTwitch').disabled=!config.twitch_connected;$('enableKick').disabled=!config.kick_connected||!config.kick_subscription_ok;$('enableYoutube').disabled=!config.youtube_configured;$('enableTiktok').disabled=!config.tiktok_configured;
    $('rateValue').textContent=`${$('rate').value}%`;$('pitchValue').textContent=`${$('pitch').value}Hz`;$('volumeValue').textContent=`${$('volume').value}%`;
    if(config.overlay_url)$('sourceUrl').value=config.overlay_url;
    renderVoices();renderReadMode();updateHome();updateObsState();
    loading=false;setSaveState('','Todo guardado');
    const initial=(location.hash||'#home').slice(1);if(['home','platforms','tts','filters','obs'].includes(initial))showPage(initial);
    await pollRuntime();setInterval(pollRuntime,1800);
  }catch(e){console.error(e);setSaveState('error','No se pudo cargar')}
}

['enableTwitch','enableKick','enableYoutube','enableTiktok','ttsEnabled','ignoreCommands','ignoreUrls','readUsername','maxChars','cooldown','blacklist','youtubeHandle','tiktokHandle','commandPrefix'].forEach(id=>{
  $(id).addEventListener(id==='blacklist'||id.includes('Handle')||id==='commandPrefix'?'input':'change',()=>{if(id==='youtubeHandle')$('enableYoutube').disabled=!config?.youtube_configured||!$('youtubeHandle').value.trim();if(id==='tiktokHandle')$('enableTiktok').disabled=!config?.tiktok_configured||!$('tiktokHandle').value.trim();renderReadMode();updateHome();scheduleSave(id==='blacklist'?1000:650)});
});
['rate','pitch','volume'].forEach(id=>$(id).addEventListener('input',()=>{
  $('rateValue').textContent=`${$('rate').value}%`;$('pitchValue').textContent=`${$('pitch').value}Hz`;$('volumeValue').textContent=`${$('volume').value}%`;updateHome();scheduleSave(450);
}));

$('testBtn').onclick=async()=>{
  const btn=$('testBtn');btn.disabled=true;btn.textContent='Generando…';
  try{const r=await fetch('/api/tts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:$('testText').value,voice:selectedVoice,rate:Number($('rate').value),pitch:Number($('pitch').value)})});if(!r.ok)throw new Error(await r.text());const blob=await r.blob();const url=URL.createObjectURL(blob);const audio=new Audio(url);audio.volume=Number($('volume').value)/100;audio.onended=()=>URL.revokeObjectURL(url);await audio.play()}catch(e){alert(`Error: ${e.message}`)}finally{btn.disabled=false;btn.textContent='▶ Probar voz'}
};
$('generateBtn').onclick=()=>saveCloud({manual:true});
async function copyObs(){if(!$('sourceUrl').value)return alert('Primero guarda la configuración para generar tu enlace.');await navigator.clipboard.writeText($('sourceUrl').value);return true}
$('copyBtn').onclick=async()=>{if(await copyObs()){const b=$('copyBtn');b.textContent='Copiado ✓';setTimeout(()=>b.textContent='Copiar',1100)}};
$('homeCopyObs').onclick=async()=>{if(await copyObs()){const b=$('homeCopyObs');b.textContent='Copiado ✓';setTimeout(()=>b.textContent='Copiar enlace de OBS',1100)}};

$('tiktokTestBtn').onclick=()=>sendTest('tiktok','probando KZTTS desde TikTok');
document.querySelectorAll('.test-platform').forEach(b=>b.onclick=()=>{testPlatform=b.dataset.testPlatform;document.querySelectorAll('.test-platform').forEach(x=>x.classList.toggle('active',x===b))});
$('obsTestBtn').onclick=()=>sendTest(testPlatform,$('obsTestText').value);
async function sendTest(platform,text){
  if(!config?.overlay_key)return alert('Primero guarda la configuración para crear tu Browser Source.');
  try{const r=await fetch('/api/test-message',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({platform,user:'PruebaKZTTS',text,overlay_key:config.overlay_key})});const data=await r.json().catch(()=>({}));if(!r.ok)throw new Error(data.detail||'No se pudo enviar la prueba');}catch(e){alert(e.message)}
}

async function control(action,value=null){
  try{const r=await fetch('/api/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,value})});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||'No se pudo controlar OBS');}catch(e){alert(e.message)}
}
$('pauseBtn').onclick=async()=>{await control(runtimePaused?'resume':'pause');runtimePaused=!runtimePaused;$('pauseBtn').innerHTML=runtimePaused?'▶ <span>Reanudar</span>':'Ⅱ <span>Pausar</span>'};
$('skipBtn').onclick=()=>control('skip');$('clearBtn').onclick=()=>control('clear');

async function pollRuntime(){
  if(!(config?.twitch_connected||config?.kick_connected))return;
  try{
    const r=await fetch('/api/runtime');if(!r.ok)return;const data=await r.json();const st=data.state||{};const online=!!data.online;
    $('sidebarDot').classList.toggle('online',online);$('obsPreviewDot').classList.toggle('online',online);$('sidebarStatus').textContent=online?'OBS conectado':'OBS offline';$('obsPreviewStatus').textContent=online?'Fuente conectada':'Esperando OBS';
    $('runtimeBadge').textContent=online?'OBS online':'OBS offline';$('runtimeBadge').className=`badge ${online?'good':'neutral'}`;$('obsMiniBadge').textContent=online?'Online':(config.overlay_configured?'Lista':'Sin fuente');$('obsMiniBadge').className=`badge ${online?'good':'neutral'}`;
    $('queueCount').textContent=st.queue_length??0;runtimePaused=!!st.paused;$('pauseBtn').innerHTML=runtimePaused?'▶ <span>Reanudar</span>':'Ⅱ <span>Pausar</span>';
    $('nowMessage').textContent=st.current|| (online?'Esperando mensajes':'KZTTS está listo');$('nowPlatform').textContent=st.platform?`${st.platform} · ${st.speaking?'Reproduciendo':'En cola'}`:(online?'Browser Source conectada':'Esperando mensajes');
    if(st.volume!=null)$('runtimeVolume').textContent=`${st.volume}%`;
  }catch{}
}

$('logoutBtn').onclick=async()=>{await fetch('/auth/logout',{method:'POST'});location.reload()};
load();


// KZTTS visual interaction layer — intentionally isolated from TTS/business logic.
(function initKzVisuals(){
  const glow=document.getElementById('cursorGlow');
  if(glow && !window.matchMedia('(prefers-reduced-motion: reduce)').matches){
    const layers=[...glow.querySelectorAll('.cursor-glow-layer')];
    let tx=innerWidth*.5,ty=innerHeight*.4;
    const pts=layers.map(()=>({x:tx,y:ty}));
    window.addEventListener('pointermove',e=>{tx=e.clientX;ty=e.clientY;glow.style.opacity='1'},{passive:true});
    document.documentElement.addEventListener('mouseleave',()=>glow.style.opacity='.25');
    const speeds=[.17,.24,.34];
    function frame(){
      layers.forEach((layer,i)=>{const p=pts[i];p.x+=(tx-p.x)*speeds[i];p.y+=(ty-p.y)*speeds[i];layer.style.transform=`translate3d(${p.x}px,${p.y}px,0)`});
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  const reactive='.nav-item,.primary-button,.platform-card,.voice-card,.summary-platform,.card';
  document.addEventListener('pointermove',e=>{
    const el=e.target.closest(reactive);if(!el)return;
    const r=el.getBoundingClientRect();
    el.style.setProperty('--mx',`${((e.clientX-r.left)/r.width*100).toFixed(1)}%`);
    el.style.setProperty('--my',`${((e.clientY-r.top)/r.height*100).toFixed(1)}%`);
  },{passive:true});
})();

// v0.7.2 — VALRadiant-inspired cursor pressure / 3D tilt.
// Visual only: does not touch TTS, auth, platform or OBS logic.
(function initKzTilt(){
  const reduced=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const fine=window.matchMedia('(hover:hover) and (pointer:fine)').matches;
  if(reduced||!fine)return;

  const selector='.hero-card,.platform-card,.summary-platform,.voice-card,.obs-preview';
  const strength=new Map([
    ['hero-card',5.4],['platform-card',3.7],['summary-platform',3.0],['voice-card',3.4],['obs-preview',4.0]
  ]);
  let active=null;

  function maxTilt(el){
    for(const [cls,value] of strength)if(el.classList.contains(cls))return value;
    return 3;
  }
  function reset(el){
    if(!el)return;
    el.classList.remove('kz-tilting');
    el.classList.add('kz-tilt-return');
    el.style.setProperty('--tilt-x','0deg');
    el.style.setProperty('--tilt-y','0deg');
    el.style.setProperty('--tilt-shadow-x','0px');
    el.style.setProperty('--tilt-shadow-y','18px');
    setTimeout(()=>el.classList.remove('kz-tilt-return'),620);
  }
  function move(el,e){
    const r=el.getBoundingClientRect();
    if(!r.width||!r.height)return;
    const nx=Math.max(-1,Math.min(1,((e.clientX-r.left)/r.width-.5)*2));
    const ny=Math.max(-1,Math.min(1,((e.clientY-r.top)/r.height-.5)*2));
    const max=maxTilt(el);
    // "Pressure": the side under the pointer sinks slightly away from the viewer.
    const rx=(-ny*max).toFixed(2);
    const ry=(nx*max).toFixed(2);
    el.classList.remove('kz-tilt-return');
    el.classList.add('kz-tilting');
    el.style.setProperty('--tilt-x',`${rx}deg`);
    el.style.setProperty('--tilt-y',`${ry}deg`);
    el.style.setProperty('--tilt-shadow-x',`${(-nx*11).toFixed(1)}px`);
    el.style.setProperty('--tilt-shadow-y',`${(18-ny*5).toFixed(1)}px`);
    el.style.setProperty('--mx',`${((nx+1)*50).toFixed(1)}%`);
    el.style.setProperty('--my',`${((ny+1)*50).toFixed(1)}%`);
  }

  document.addEventListener('pointermove',e=>{
    const el=e.target.closest(selector);
    if(el!==active){reset(active);active=el;}
    if(active)move(active,e);
  },{passive:true});

  document.addEventListener('pointerout',e=>{
    if(!active)return;
    const next=e.relatedTarget;
    if(next&&active.contains(next))return;
    if(!next||!active.contains(next)){
      const leaving=e.target.closest(selector);
      if(leaving===active){reset(active);active=null;}
    }
  },{passive:true});

  window.addEventListener('blur',()=>{reset(active);active=null});
})();
