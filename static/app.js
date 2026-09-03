let config;
const $ = id => document.getElementById(id);

async function load(){
  const r = await fetch('/api/config');
  config = await r.json();
  $('loginCard').classList.toggle('hidden', config.connected);
  $('settingsCard').classList.toggle('hidden', !config.connected);
  $('account').textContent = config.connected ? `● ${config.account}` : 'No conectado';

  if(config.connected){
    $('channel').value = config.account || '';
    $('blacklist').value = config.default_blacklist.join('\n');
    for(const [value,label] of Object.entries(config.voices)){
      const option = document.createElement('option');
      option.value = value;
      option.textContent = label;
      $('voice').appendChild(option);
    }
  }
}

$('rate').oninput = () => $('rateValue').textContent = `${$('rate').value}%`;
$('pitch').oninput = () => $('pitchValue').textContent = `${$('pitch').value}Hz`;

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
  const payload = {
    channel:$('channel').value.trim(),
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

load();
