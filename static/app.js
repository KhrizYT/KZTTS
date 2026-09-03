let config;
const $ = id => document.getElementById(id);
const STORE_KEY = 'kztts_settings_v031';

function loadSaved(){
  try { return JSON.parse(localStorage.getItem(STORE_KEY) || '{}'); }
  catch { return {}; }
}
function saveSettings(){
  const data = {
    channel:$('channel').value,
    youtubeHandle:$('youtubeHandle').value,
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
  };
  localStorage.setItem(STORE_KEY, JSON.stringify(data));
}

async function load(){
  const r = await fetch('/api/config');
  config = await r.json();

  $('twitchStatus').textContent = config.twitch_connected ? `● ${config.twitch_account}` : 'No conectado';
  $('kickStatus').textContent = config.kick_connected ? `● ${config.kick_account}` : (config.kick_configured ? 'No conectado' : 'Falta configurar servidor');
  $('youtubeStatus').textContent = config.youtube_configured ? 'Usa tu @handle' : 'Falta configurar servidor';
  $('twitchConnect').textContent = config.twitch_connected ? 'Reconectar' : 'Conectar Twitch';
  $('kickConnect').textContent = config.kick_connected ? 'Reconectar' : 'Conectar Kick';
  $('kickConnect').classList.toggle('disabled', !config.kick_configured);
  if(!config.kick_configured) $('kickConnect').onclick = e => { e.preventDefault(); alert('Primero agrega KICK_CLIENT_ID y KICK_CLIENT_SECRET en Railway.'); };
  $('youtubeHandle').disabled = !config.youtube_configured;
  if(!config.youtube_configured) $('youtubeHandle').placeholder = 'Falta YOUTUBE_API_KEY';

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

  const saved = loadSaved();
  $('channel').value = saved.channel || config.twitch_account || '';
  $('youtubeHandle').value = saved.youtubeHandle || '@KhrizYT';
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
  $('enableTwitch').disabled = !config.twitch_connected;
  $('enableKick').disabled = !config.kick_connected || !config.kick_subscription_ok;
  $('enableYoutube').disabled = !config.youtube_configured || !$('youtubeHandle').value.trim();
  $('rateValue').textContent = `${$('rate').value}%`;
  $('pitchValue').textContent = `${$('pitch').value}Hz`;
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
  $('sourceBox').classList.remove('hidden');
};

$('copyBtn').onclick = async () => {
  await navigator.clipboard.writeText($('sourceUrl').value);
  $('copyBtn').textContent = 'Copiado ✓';
  setTimeout(()=>$('copyBtn').textContent='Copiar',1200);
};

['channel','youtubeHandle','voice','maxChars','cooldown','ignoreCommands','ignoreUrls','readUsername','blacklist','enableTwitch','enableKick','enableYoutube'].forEach(id => {
  $(id).addEventListener('change', saveSettings);
});

$('youtubeHandle').addEventListener('input', () => {
  $('enableYoutube').disabled = !config?.youtube_configured || !$('youtubeHandle').value.trim();
  saveSettings();
});

load();
