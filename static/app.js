let config;
const $ = id => document.getElementById(id);
const STORE_KEY = 'kztts_settings_v031';

function loadSaved(){
  try { return JSON.parse(localStorage.getItem(STORE_KEY) || '{}'); }
  catch { return {}; }
}

function cloudToSaved(c){
  if(!c) return null;
  return {
    channel:c.channel || '',
    youtubeHandle:c.youtube_handle || '',
    tiktokHandle:c.tiktok_handle || '',
    voice:c.voice || 'es-MX-DaliaNeural',
    rate:c.rate ?? 0,
    pitch:c.pitch ?? 0,
    maxChars:c.max_chars ?? 180,
    cooldown:c.cooldown ?? 2,
    ignoreCommands:c.ignore_commands ?? true,
    ignoreUrls:c.ignore_urls ?? true,
    readUsername:c.read_username ?? false,
    blacklist:Array.isArray(c.blacklist) ? c.blacklist.join('\n') : '',
    enableTwitch:c.enable_twitch ?? true,
    enableKick:c.enable_kick ?? false,
    enableYoutube:c.enable_youtube ?? false,
    enableTiktok:c.enable_tiktok ?? false,
  };
}
function saveSettings(){
  const data = {
    channel:$('channel').value,
    youtubeHandle:$('youtubeHandle').value,
    tiktokHandle:$('tiktokHandle').value,
    voice:$('voice').value,
    rate:$('rate').value,
    pitch:$('pitch').value,
    maxChars:$('maxChars').value,
    cooldown:$('cooldown').value,
    ignoreCommands:$('ignoreCommands').checked,
    ignoreUrls:$('ignoreUrls').checked,
    readUsername:$('readUsername').checked,
    blacklist:$('blacklist').value,
    enableTwitch:$('enableTwitch').checked,
    enableKick:$('enableKick').checked,
    enableYoutube:$('enableYoutube').checked,
    enableTiktok:$('enableTiktok').checked,
  };
  localStorage.setItem(STORE_KEY, JSON.stringify(data));
}

async function load(){
  const r = await fetch('/api/config');
  config = await r.json();

  const dbWarning = $('dbWarning');
  if(dbWarning){
    dbWarning.classList.toggle('hidden', config.database_configured !== false);
  }

  $('twitchStatus').textContent = config.twitch_connected ? `● ${config.twitch_account}` : 'No conectado';
  $('kickStatus').textContent = config.kick_connected ? `● ${config.kick_account}` : (config.kick_configured ? 'No conectado' : 'Falta configurar servidor');
  $('youtubeStatus').textContent = config.youtube_configured ? 'Usa tu @handle' : 'Falta configurar servidor';
  $('tiktokStatus').textContent = config.tiktok_configured ? 'Usa tu @usuario' : 'TikTok no disponible';
  $('twitchConnect').textContent = config.twitch_connected ? 'Reconectar' : 'Conectar Twitch';
  $('kickConnect').textContent = config.kick_connected ? 'Reconectar' : 'Conectar Kick';
  $('kickConnect').classList.toggle('disabled', !config.kick_configured || config.database_configured === false);
  $('twitchConnect').classList.toggle('disabled', config.database_configured === false);
  if(config.database_configured === false){
    $('twitchConnect').onclick = e => { e.preventDefault(); alert('Primero conecta PostgreSQL a KZTTS en Railway.'); };
    $('kickConnect').onclick = e => { e.preventDefault(); alert('Primero conecta PostgreSQL a KZTTS en Railway.'); };
  }else if(!config.kick_configured){
    $('kickConnect').onclick = e => { e.preventDefault(); alert('Primero agrega KICK_CLIENT_ID y KICK_CLIENT_SECRET en Railway.'); };
  }
  $('youtubeHandle').disabled = !config.youtube_configured;
  if(!config.youtube_configured) $('youtubeHandle').placeholder = 'Falta YOUTUBE_API_KEY';
  $('tiktokHandle').disabled = !config.tiktok_configured;

  $('account').textContent = [
    config.twitch_connected ? `Twitch: ${config.twitch_account}` : null,
    config.kick_connected ? `Kick: ${config.kick_account}` : null,
  ].filter(Boolean).join(' · ') || 'No conectado';

  if(config.kick_connected && !config.kick_subscription_ok){
    $('kickWarning').textContent = `Kick conectado, pero el webhook de chat no quedó suscrito: ${config.kick_subscription_error || 'reconecta Kick'}`;
    $('kickWarning').classList.remove('hidden');
  }

  const anyConnected = config.twitch_connected || config.kick_connected;
  $('settingsCard').classList.toggle('hidden', !anyConnected);

  for(const [value,label] of Object.entries(config.voices)){
    const option = document.createElement('option');
    option.value = value;
    option.textContent = label;
    $('voice').appendChild(option);
  }

  // Prefer the cloud copy. localStorage is only a one-time migration/fallback from v0.4.
  const saved = cloudToSaved(config.saved_settings) || loadSaved();
  $('channel').value = saved.channel || config.twitch_account || '';
  $('youtubeHandle').value = saved.youtubeHandle || '@KhrizYT';
  $('tiktokHandle').value = saved.tiktokHandle || '';
  $('blacklist').value = saved.blacklist || config.default_blacklist.join('\n');
  $('voice').value = saved.voice || 'es-MX-DaliaNeural';
  $('rate').value = saved.rate ?? 0;
  $('pitch').value = saved.pitch ?? 0;
  $('maxChars').value = saved.maxChars ?? 180;
  $('cooldown').value = saved.cooldown ?? 2;
  $('ignoreCommands').checked = saved.ignoreCommands ?? true;
  $('ignoreUrls').checked = saved.ignoreUrls ?? true;
  $('readUsername').checked = saved.readUsername ?? false;
  $('enableTwitch').checked = config.twitch_connected && (saved.enableTwitch ?? true);
  $('enableKick').checked = config.kick_connected && config.kick_subscription_ok && (saved.enableKick ?? true);
  $('enableYoutube').checked = config.youtube_configured && !!$('youtubeHandle').value.trim() && (saved.enableYoutube ?? true);
  $('enableTiktok').checked = config.tiktok_configured && !!$('tiktokHandle').value.trim() && (saved.enableTiktok ?? false);
  $('enableTwitch').disabled = !config.twitch_connected;
  $('enableKick').disabled = !config.kick_connected || !config.kick_subscription_ok;
  $('enableYoutube').disabled = !config.youtube_configured || !$('youtubeHandle').value.trim();
  $('enableTiktok').disabled = !config.tiktok_configured || !$('tiktokHandle').value.trim();
  $('rateValue').textContent = `${$('rate').value}%`;
  $('pitchValue').textContent = `${$('pitch').value}Hz`;

  if(config.overlay_configured && config.overlay_url){
    $('sourceUrl').value = config.overlay_url;
    $('sourceBox').classList.remove('hidden');
  }
}

$('rate').oninput = () => { $('rateValue').textContent = `${$('rate').value}%`; saveSettings(); };
$('pitch').oninput = () => { $('pitchValue').textContent = `${$('pitch').value}Hz`; saveSettings(); };

$('testBtn').onclick = async () => {
  const btn = $('testBtn');
  btn.disabled = true;
  btn.textContent = 'Generando…';
  try{
    const r = await fetch('/api/tts', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        text:$('testText').value,
        voice:$('voice').value,
        rate:Number($('rate').value),
        pitch:Number($('pitch').value)
      })
    });
    if(!r.ok) throw new Error(await r.text());
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio.onended = () => URL.revokeObjectURL(url);
    await audio.play();
  }catch(e){ alert(`Error: ${e.message}`); }
  finally{ btn.disabled = false; btn.textContent = 'Probar voz'; }
};

$('generateBtn').onclick = async () => {
  saveSettings();
  const payload = {
    channel:$('channel').value.trim(),
    enable_twitch:$('enableTwitch').checked,
    enable_kick:$('enableKick').checked,
    enable_youtube:$('enableYoutube').checked,
    youtube_handle:$('youtubeHandle').value.trim(),
    enable_tiktok:$('enableTiktok').checked,
    tiktok_handle:$('tiktokHandle').value.trim(),
    overlay_key: config?.overlay_key || null,
    voice:$('voice').value,
    rate:Number($('rate').value),
    pitch:Number($('pitch').value),
    blacklist:$('blacklist').value.split('\n').map(x=>x.trim()).filter(Boolean),
    ignore_commands:$('ignoreCommands').checked,
    ignore_urls:$('ignoreUrls').checked,
    read_username:$('readUsername').checked,
    max_chars:Number($('maxChars').value),
    cooldown:Number($('cooldown').value)
  };
  const r = await fetch('/api/overlay', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify(payload)
  });
  const data = await r.json();
  if(!r.ok){ alert(data.detail || 'Error generando fuente'); return; }
  $('sourceUrl').value = data.url;
  config.overlay_key = data.key;
  config.overlay_url = data.url;
  config.overlay_configured = true;
  $('sourceBox').classList.remove('hidden');
  const old = $('generateBtn').textContent;
  $('generateBtn').textContent = 'Guardado en la nube ✓';
  setTimeout(()=>$('generateBtn').textContent=old, 1600);
};

$('copyBtn').onclick = async () => {
  await navigator.clipboard.writeText($('sourceUrl').value);
  $('copyBtn').textContent = 'Copiado ✓';
  setTimeout(()=>$('copyBtn').textContent='Copiar',1200);
};

['channel','youtubeHandle','tiktokHandle','voice','maxChars','cooldown','ignoreCommands','ignoreUrls','readUsername','blacklist','enableTwitch','enableKick','enableYoutube','enableTiktok'].forEach(id => {
  $(id).addEventListener('change', saveSettings);
});

$('youtubeHandle').addEventListener('input', () => {
  $('enableYoutube').disabled = !config?.youtube_configured || !$('youtubeHandle').value.trim();
  saveSettings();
});

$('tiktokHandle').addEventListener('input', () => {
  $('enableTiktok').disabled = !config?.tiktok_configured || !$('tiktokHandle').value.trim();
  saveSettings();
});

$('tiktokTestBtn').onclick = async () => {
  const btn = $('tiktokTestBtn');
  if(!config?.overlay_key){
    alert('Primero marca TikTok y pulsa “Guardar / actualizar Browser Source”.');
    return;
  }
  btn.disabled = true;
  btn.textContent = 'Enviando…';
  try{
    const r = await fetch('/api/test-message', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        platform:'tiktok',
        user:'PruebaTikTok',
        text:'probando KZTTS desde TikTok',
        overlay_key:config.overlay_key
      })
    });
    const data = await r.json().catch(()=>({}));
    if(!r.ok) throw new Error(data.detail || 'No se pudo enviar la prueba');
    btn.textContent = 'Enviado ✓';
    setTimeout(()=>btn.textContent='Probar TikTok sin LIVE',1400);
  }catch(e){
    alert(e.message);
    btn.textContent = 'Probar TikTok sin LIVE';
  }finally{
    btn.disabled = false;
  }
};

load();
