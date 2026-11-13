const $=s=>document.querySelector(s), $$=s=>document.querySelectorAll(s);
const categories=['กฎหมายแพ่ง','กฎหมายอาญา','กฎหมายมหาชน','กฎหมายวิธีพิจารณา','กฎหมายพาณิชย์','กฎหมายระหว่างประเทศ'];
let subjects=[],docs=[],questions=[],isAdmin=false;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const el=(tag,content,cls)=>{let x=document.createElement(tag);if(content!==undefined)x.textContent=content;if(cls)x.className=cls;return x};
const subject=id=>subjects.find(s=>s.id==id)||{name:'ไม่พบรายวิชา',code:'',category:''};
async function api(path,opts={}){const r=await fetch('/api'+path,{credentials:'same-origin',...opts});let d=await r.json().catch(()=>({error:'ไม่สามารถอ่านข้อมูลตอบกลับ'}));if(!r.ok)throw Error(d.error||'เกิดข้อผิดพลาด');return d}
const json=(method,body)=>({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
function tab(name){if(name==='admin'&&!isAdmin){loginModal();return}$$('.panel').forEach(p=>p.classList.toggle('active',p.id===name));$$('[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===name));window.scrollTo(0,0);if(name==='admin')renderAdmin();if(name==='contact')loadDeveloper()}
$$('[data-tab]').forEach(b=>b.onclick=()=>tab(b.dataset.tab));$('#heroGo').onclick=()=>{$('#docSearch').value=$('#heroSearch').value;tab('library');renderDocs()};$('#heroSearch').onkeydown=e=>{if(e.key==='Enter')$('#heroGo').click()};
function docCard(d){const card=el('article',undefined,'card');card.innerHTML=`<span class="tag">${esc(d.type)}</span><h3>${esc(d.title)}</h3><p class="muted">${esc(subject(d.subjectId).name)} • ชั้นปี ${esc(d.year)}</p><p>${esc(d.description)}</p>`;const a=el('a','เปิด PDF','primary');a.href='/api/documents/'+encodeURIComponent(d.id)+'/file';a.target='_blank';a.rel='noopener';a.style.cssText='display:inline-block;text-decoration:none;margin-top:12px';card.append(a);return card}
function renderHome(){$('#statSubjects').textContent=subjects.length;$('#statDocs').textContent=docs.length;$('#statQuestions').textContent=questions.length;$('#categoryGrid').replaceChildren();categories.forEach(c=>{const card=el('div',undefined,'card');card.innerHTML=`<div style="font-size:27px">⚖️</div><h3>${esc(c)}</h3><p class="muted">${subjects.filter(s=>s.category===c).length} รายวิชา</p>`;const b=el('button','ดูรายวิชา →','outline');b.onclick=()=>{$('#categoryFilter').value=c;tab('library');renderDocs()};card.append(b);$('#categoryGrid').append(card)});$('#recentDocs').replaceChildren();if(!docs.length)$('#recentDocs').append(el('div','ยังไม่มีเอกสารเผยแพร่','empty'));docs.slice(0,3).forEach(d=>$('#recentDocs').append(docCard(d)))}
function renderDocs(){const q=$('#docSearch').value.toLowerCase(),cat=$('#categoryFilter').value,year=$('#yearFilter').value;const found=docs.filter(d=>(!cat||subject(d.subjectId).category===cat)&&(!year||String(d.year)===year)&&[d.title,d.description,subject(d.subjectId).name,subject(d.subjectId).code].join(' ').toLowerCase().includes(q));$('#docsGrid').replaceChildren();if(!found.length)$('#docsGrid').append(el('div','ไม่พบเอกสารตามเงื่อนไขที่เลือก','empty'));found.forEach(d=>$('#docsGrid').append(docCard(d)))}
['docSearch','categoryFilter','yearFilter'].forEach(id=>$('#'+id).addEventListener(id==='docSearch'?'input':'change',renderDocs));
function refreshSelects(){let cat=$('#categoryFilter'),old=cat.value;cat.innerHTML='<option value="">ทุกหมวดหมู่</option>'+categories.map(c=>`<option>${esc(c)}</option>`).join('');cat.value=old;$('#newSubjectCategory').innerHTML=categories.map(c=>`<option>${esc(c)}</option>`).join('');let options=subjects.map(s=>`<option value="${s.id}">${esc(s.code+' • '+s.name)}</option>`).join('');$('#submitSubject').innerHTML=options;$('#practiceSubject').innerHTML='<option value="">ทุกวิชา</option>'+options;$('#questionSubject').innerHTML=options}
$('#startPractice').onclick=()=>{const sid=$('#practiceSubject').value,qs=questions.filter(q=>!sid||q.subjectId==sid),area=$('#practiceArea');area.replaceChildren();if(!qs.length){area.append(el('p','ยังไม่มีข้อฝึกหัดในวิชานี้'));return}const form=el('form');qs.forEach((q,i)=>{let block=el('div',undefined,'question');block.innerHTML=`<strong>ข้อ ${i+1}. ${esc(q.text)}</strong><p class="muted">${esc(subject(q.subjectId).name)}</p>`;q.options.forEach((o,j)=>{let label=el('label',undefined,'option'),radio=el('input');radio.type='radio';radio.name='q'+i;radio.value=j;label.append(radio,document.createTextNode(' '+o));block.append(label)});form.append(block)});let b=el('button','ตรวจคำตอบ','primary');b.type='submit';form.append(b);form.onsubmit=async e=>{e.preventDefault();const answers={};qs.forEach((q,i)=>{let checked=form.querySelector(`input[name="q${i}"]:checked`);if(checked)answers[q.id]=Number(checked.value)});try{let result=await api('/quiz/grade',json('POST',{answers}));
        // Persist only authenticated members' answers, grouped by subject.
        // The backend calculates and stores the score independently.
        let savedMessage='';
        const selected=Object.entries(answers);
        if(selected.length){
          try{
            const me=await api('/members/me');
            if(me && me.id){
              const groups={};
              for(const [qid,answer] of selected){
                const question=qs.find(q=>String(q.id)===qid);
                if(!question)continue;
                const sid=String(question.subjectId);
                (groups[sid]??={})[qid]=answer;
              }
              let saved=0;
              for(const [sid,group] of Object.entries(groups)){
                await api('/members/exams/submit',json('POST',{subjectId:Number(sid),answers:group}));
                saved++;
              }
              savedMessage=saved?'บันทึกผลการฝึกลงประวัติสมาชิกแล้ว ('+saved+' รายวิชา)':'';
            }
          }catch(saveError){
            if(!saveError.message.includes('กรุณาเข้าสู่ระบบสมาชิก')){
              savedMessage='ตรวจคำตอบได้แล้ว แต่ยังบันทึกประวัติสมาชิกไม่ได้: '+saveError.message;
            }else{
              savedMessage='เข้าสู่ระบบสมาชิกเพื่อบันทึกคะแนนย้อนหลัง';
            }
          }
        }
        $('#feedback')?.remove();let fb=el('div',undefined,'card');fb.id='feedback';fb.style.marginTop='16px';fb.append(el('h3',`คะแนน ${result.score} / ${qs.length}`));if(savedMessage)fb.append(el('p',savedMessage,'muted'));result.results.forEach(x=>fb.append(el('p',`${x.correct?'✅':'❌'} ข้อ ${qs.findIndex(q=>q.id===x.id)+1}: ${x.explain}`)));area.append(fb)}catch(err){alert(err.message)}};area.append(form)};
async function refresh(){const [s,d,q,a]=await Promise.all([api('/subjects'),api('/documents'),api('/questions'),api('/session')]);subjects=s;docs=d;questions=q;isAdmin=a.admin;$('#accountBtn').textContent=isAdmin?'ออกจากระบบผู้ดูแล':'เข้าสู่ระบบ';refreshSelects();renderHome();renderDocs();if(isAdmin)await renderAdmin();$('#developerEditor')?.classList.toggle('hidden',!isAdmin)}
async function renderAdmin(){if(!isAdmin)return;$('#adminLocked').classList.add('hidden');$('#adminContent').classList.remove('hidden');try{const pending=await api('/documents?status=pending');$('#pendingList').replaceChildren();if(!pending.length)$('#pendingList').append(el('div','ไม่มีเอกสารรออนุมัติ','empty'));pending.forEach(d=>{const card=el('div',undefined,'card');card.style.marginBottom='10px';card.innerHTML=`<strong>${esc(d.title)}</strong><p class="muted">${esc(subject(d.subjectId).name)} • ${esc(d.description)}</p>`;const row=el('div',undefined,'actions');let link=el('a','ดูไฟล์','outline');link.href='/api/documents/'+d.id+'/file';link.target='_blank';row.append(link);[['อนุมัติ','approved'],['ปฏิเสธ','rejected']].forEach(([label,status])=>{let b=el('button',label,status==='approved'?'primary':'outline');b.onclick=async()=>{try{await api('/documents/'+d.id+'/status',json('POST',{status}));await refresh()}catch(e){alert(e.message)}};row.append(b)});card.append(row);$('#pendingList').append(card)});$('#adminDocs').replaceChildren();docs.forEach(d=>{let row=el('div',undefined,'card');row.style.marginBottom='8px';row.append(el('strong',d.title+' — '+subject(d.subjectId).name));let b=el('button','ถอนเผยแพร่','outline');b.style.marginLeft='12px';b.onclick=async()=>{if(confirm('ถอนเผยแพร่เอกสารนี้?')){await api('/documents/'+d.id+'/status',json('POST',{status:'rejected'}));await refresh()}};row.append(b);$('#adminDocs').append(row)});await renderAdminQuestions()}catch(e){alert(e.message)}}
$('#subjectForm').onsubmit=async e=>{e.preventDefault();let f=new FormData(e.target);try{await api('/subjects',json('POST',Object.fromEntries(f)));e.target.reset();await refresh()}catch(err){alert(err.message)}};
$('#submissionForm').onsubmit=async e=>{e.preventDefault();const f=new FormData(e.target);const file=f.get('file');if(!file||file.size>10*1024*1024){alert('กรุณาเลือก PDF ไม่เกิน 10 MB');return}f.set('rights','yes');try{await api('/submissions',{method:'POST',body:f});e.target.reset();$('#submissionMessage').textContent='ส่งเอกสารสำเร็จ รอผู้ดูแลอนุมัติ';await refresh()}catch(err){alert(err.message)}};
async function logout(){await api('/logout',{method:'POST'});isAdmin=false;$('#adminLocked').classList.remove('hidden');$('#adminContent').classList.add('hidden');await refresh();tab('home')}
function loginModal(){if(isAdmin){if(confirm('ออกจากระบบผู้ดูแล?'))logout();return}let bg=el('div',undefined,'modalbg'),modal=el('div',undefined,'modal');modal.innerHTML='<div class="modal-head"><h2>เข้าสู่ระบบผู้ดูแล</h2><button class="close">×</button></div><form id="authForm"><label class="field">ชื่อผู้ใช้<input name="username" autocomplete="username" required></label><label class="field">รหัสผ่าน<input name="password" type="password" autocomplete="current-password" required></label><p id="authError" style="color:#c62828"></p><button class="primary">เข้าสู่ระบบ</button></form>';bg.append(modal);$('#modalRoot').replaceChildren(bg);modal.querySelector('.close').onclick=()=>bg.remove();bg.onclick=e=>{if(e.target===bg)bg.remove()};modal.querySelector('form').onsubmit=async e=>{e.preventDefault();let f=new FormData(e.target);try{await api('/login',json('POST',Object.fromEntries(f)));bg.remove();await refresh();tab('admin')}catch(err){$('#authError').textContent=err.message}};modal.querySelector('input').focus()}
$('#accountBtn').onclick=loginModal;$('#adminLogin').onclick=loginModal;
refresh().catch(err=>alert('เชื่อมต่อเซิร์ฟเวอร์ไม่สำเร็จ: '+err.message));


// V2.3: Admin-only question editor. Server validates permissions and answers.
let adminQuestionRows=[];
function resetQuestionForm(){
  $('#questionForm').reset();$('#editingQuestionId').value='';
  $('#questionSave').textContent='บันทึกข้อสอบ';$('#questionMessage').textContent='';
}
$('#questionCancel').onclick=resetQuestionForm;
async function renderAdminQuestions(){
  adminQuestionRows=await api('/admin/questions');
  const root=$('#adminQuestions');root.replaceChildren();
  if(!adminQuestionRows.length){root.append(el('div','ยังไม่มีข้อสอบ','empty'));return}
  for(const q of adminQuestionRows){
    const card=el('div',undefined,'card');card.style.marginBottom='10px';
    const heading=el('strong',`ข้อ ${q.id}: ${q.text}`);card.append(heading);
    card.append(el('p',`${subject(q.subjectId).name} • ${q.active?'เผยแพร่':'ถอนเผยแพร่'}`,'muted'));
    card.append(el('p',`เฉลย: ${['ก','ข','ค','ง'][q.answer]} — ${q.options[q.answer]}`,'muted'));
    const row=el('div',undefined,'actions');
    const edit=el('button','แก้ไข','outline');edit.onclick=()=>{
      $('#editingQuestionId').value=q.id;$('#questionSubject').value=q.subjectId;
      $('#questionText').value=q.text;
      q.options.forEach((o,i)=>$('#questionOption'+i).value=o);
      $('#questionAnswer').value=q.answer;$('#questionExplain').value=q.explain;
      $('#questionSave').textContent='บันทึกการแก้ไข';$('#questionForm').scrollIntoView({behavior:'smooth'});
    };
    const toggle=el('button',q.active?'ถอนเผยแพร่':'เผยแพร่อีกครั้ง','outline');
    toggle.onclick=async()=>{
      if(!confirm(q.active?'ถอนข้อสอบออกจากชุดฝึก? ประวัติคะแนนเดิมจะยังอยู่':'นำข้อสอบกลับมาเผยแพร่?'))return;
      try{await api('/admin/questions/'+q.id+'/active',json('PATCH',{active:!q.active}));await refresh()}catch(err){alert(err.message)}
    };
    row.append(edit,toggle);card.append(row);root.append(card);
  }
}
$('#questionForm').onsubmit=async e=>{
  e.preventDefault();const id=$('#editingQuestionId').value;
  const body={subjectId:Number($('#questionSubject').value),text:$('#questionText').value,
    options:[0,1,2,3].map(i=>$('#questionOption'+i).value),
    answer:Number($('#questionAnswer').value),explain:$('#questionExplain').value};
  const save=$('#questionSave');save.disabled=true;
  try{
    await api(id?'/admin/questions/'+id:'/admin/questions',json(id?'PUT':'POST',body));
    resetQuestionForm();await refresh();$('#questionMessage').textContent='บันทึกข้อสอบเรียบร้อยแล้ว';
  }catch(err){$('#questionMessage').textContent='เกิดข้อผิดพลาด: '+err.message}
  finally{save.disabled=false}
};


// V2.4 developer profile, no changes to existing quiz/member workflows.
let developerData=null;
async function loadDeveloper(){
  try{
    const d=await api('/developer');developerData=d;
    $('#developerName').textContent=d.displayName||'';
    $('#developerRole').textContent=d.role||'';
    $('#developerBio').textContent=d.bio||'';
    $('#developerPhoto').src=(d.photoUrl||'/static/developer.jpg')+'?v='+Date.now();
    const links=$('#developerLinks');links.replaceChildren();
    for(const [label,url] of [['Facebook',d.facebook],['Instagram',d.instagram],['GitHub',d.github]]){
      if(!url||!/^https:\/\//i.test(url))continue;
      const a=el('a',label,'dev-link');a.href=url;a.target='_blank';a.rel='noopener noreferrer';links.append(a);
    }
    if(d.email){const a=el('a','✉ Email','dev-link');a.href='mailto:'+encodeURIComponent(d.email);links.append(a)}
    for(const [id,key] of [['devName','displayName'],['devRole','role'],['devBio','bio'],['devFacebook','facebook'],['devInstagram','instagram'],['devGithub','github'],['devEmail','email']])$('#'+id).value=d[key]||'';
    $('#developerEditor').classList.toggle('hidden',!isAdmin);
  }catch(err){$('#developerMessage').textContent='โหลดข้อมูลผู้พัฒนาไม่สำเร็จ: '+err.message}
}
$('#developerForm').onsubmit=async e=>{
  e.preventDefault();const body={};
  for(const [id,key] of [['devName','displayName'],['devRole','role'],['devBio','bio'],['devFacebook','facebook'],['devInstagram','instagram'],['devGithub','github'],['devEmail','email']])body[key]=$('#'+id).value.trim();
  try{await api('/admin/developer',json('PUT',body));await loadDeveloper();$('#developerMessage').textContent='บันทึกข้อมูลเรียบร้อยแล้ว'}
  catch(err){$('#developerMessage').textContent=err.message}
};
$('#developerPhotoForm').onsubmit=async e=>{
  e.preventDefault();const file=$('#devPhotoInput').files[0];if(!file)return;
  if(file.size>4*1024*1024){$('#developerMessage').textContent='รูปภาพต้องไม่เกิน 4 MB';return}
  const f=new FormData();f.append('photo',file);
  try{await api('/admin/developer/photo',{method:'POST',body:f});await loadDeveloper();e.target.reset();$('#developerMessage').textContent='เปลี่ยนรูปภาพเรียบร้อยแล้ว'}
  catch(err){$('#developerMessage').textContent=err.message}
};
