const $ = (id) => document.getElementById(id);
const sizeLabel = (n) => { const units=['B','KB','MB','GB']; let i=0; while(n>=1024 && i<3){ n/=1024; i++; } return `${n.toFixed(i ? 1 : 0)} ${units[i]}`; };
document.querySelectorAll('[data-bytes]').forEach(e => e.textContent = sizeLabel(Number(e.dataset.bytes)));
async function copy(value, button) {
  let done=false;
  try { if(navigator.clipboard?.writeText){await navigator.clipboard.writeText(value);done=true;} } catch {}
  if(!done){
    const helper=document.createElement('textarea');helper.value=value;helper.style.position='fixed';helper.style.opacity='0';document.body.appendChild(helper);helper.focus();helper.select();
    try {done=document.execCommand('copy');} catch {}
    helper.remove();
  }
  if(done){const before=button.textContent;button.textContent='Copiado ✓';setTimeout(()=>button.textContent=before,1800);}
  else window.prompt('Copie o link:',value);
}
document.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click',()=>copy(button.dataset.copy,button)));
if ($('copy-content')) $('copy-content').addEventListener('click', async () => { const b=$('copy-content'); const r=await fetch(b.dataset.raw); if(r.ok) copy(await r.text(), b); });
if ($('composer')) {
  const zone=$('dropzone'), input=$('file-input'), editor=$('text-content'), attachment=$('attachment'), max=Number($('composer').dataset.max);
  let selected=null, preview=null;
  function message(value) { $('message').textContent=value; $('message').classList.toggle('hidden',!value); }
  function refresh() { $('editor-wrap').classList.toggle('hidden',!!selected || !editor.value); zone.classList.toggle('hidden',!!selected || !!editor.value); $('create-btn').disabled=!selected && !editor.value.trim(); $('state-hint').textContent=selected?sizeLabel(selected.size):editor.value?`${editor.value.length} caracteres`:'Adicione algo para começar.'; }
  function setFile(file) {
    if(!file) return;
    if(file.size > max){ message(`Arquivo acima do limite de ${sizeLabel(max)}.`); return; }
    message(''); selected=file; editor.value='';
    if(preview) URL.revokeObjectURL(preview); preview=URL.createObjectURL(file);
    attachment.replaceChildren(); const info=document.createElement('div'); info.className='attachment-info';
    const name=document.createElement('strong'); name.textContent=file.name || 'Imagem colada'; const size=document.createElement('small'); size.textContent=sizeLabel(file.size); info.append(name,size);
    const remove=document.createElement('button'); remove.type='button'; remove.className='subtle'; remove.textContent='Remover'; remove.addEventListener('click',()=>{ selected=null; attachment.classList.add('hidden'); input.value=''; refresh(); });
    attachment.append(info,remove);
    if(file.type.startsWith('image/')) { const img=document.createElement('img'); img.src=preview; img.alt='Prévia do arquivo'; attachment.prepend(img); }
    else if(file.type.startsWith('video/')) { const video=document.createElement('video'); video.src=preview; video.controls=true; video.preload='metadata'; attachment.prepend(video); }
    attachment.classList.remove('hidden'); refresh();
  }
  zone.addEventListener('click',()=>input.click()); zone.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();input.click();}});
  input.addEventListener('change',()=>setFile(input.files[0]));
  ['dragenter','dragover'].forEach(type=>document.addEventListener(type,e=>{e.preventDefault();zone.classList.add('dragging');}));
  ['dragleave','drop'].forEach(type=>document.addEventListener(type,e=>{e.preventDefault();zone.classList.remove('dragging');}));
  document.addEventListener('drop',e=>{if(e.dataTransfer?.files?.length) setFile(e.dataTransfer.files[0]);});
  document.addEventListener('paste',e=>{
    const files=[...(e.clipboardData?.items || [])].filter(x=>x.kind==='file');
    if(files.length){ const file=files[0].getAsFile(); if(file){e.preventDefault();setFile(file);} return; }
    if(e.target===editor || e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
    const text=e.clipboardData?.getData('text/plain'); if(text){e.preventDefault();selected=null;attachment.classList.add('hidden');editor.value=text;refresh();editor.focus();}
  });
  editor.addEventListener('input',refresh);
  $('clear-text').addEventListener('click',()=>{editor.value='';refresh();});
  $('create-form').addEventListener('submit',async e=>{
    e.preventDefault(); if(!selected && !editor.value.trim()) return;
    const button=$('create-btn'); button.disabled=true; button.textContent='Criando...'; message('');
    const options={title:$('title').value,password:$('password').value,expiration:Number($('expiration').value),delete_after_view:$('delete-after-view').checked};
    try {
      let response;
      if(selected){const data=new FormData();data.append('file',selected,selected.name);for(const [key,value] of Object.entries(options))data.append(key,String(value));response=await fetch('/api/upload',{method:'POST',body:data});}
      else response=await fetch('/api/paste',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...options,text_content:editor.value,format:$('format').value})});
      const result=await response.json(); if(!response.ok) throw new Error(typeof result.detail==='string'?result.detail:'Não foi possível criar o link.');
      try {localStorage.setItem(`pastedrop:delete:${result.id}`,result.delete_token);} catch {}
      $('result-url').value=result.url; $('open-result').href=result.url; $('qr-result').href=`/qr/${result.id}`;
      $('result').classList.remove('hidden'); $('create-form').classList.add('hidden'); attachment.classList.add('hidden'); $('editor-wrap').classList.add('hidden');zone.classList.add('hidden');$('result').scrollIntoView({behavior:'smooth',block:'center'});
    } catch(err){message(err.message || 'Falha ao enviar.');button.disabled=false;} finally {button.textContent='Criar link ↗';}
  });
  $('copy-result').addEventListener('click',()=>copy($('result-url').value,$('copy-result')));
  $('new-result').addEventListener('click',()=>location.reload());
  refresh();
}
