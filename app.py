                c.execute(text('INSERT INTO subjects(code,name,category) VALUES(:code,:name,:category)'), {'code':code,'name':name,'category':category})
        if not c.execute(text('SELECT 1 FROM questions LIMIT 1')).first():
            sid = c.execute(text('SELECT id FROM subjects WHERE code=:code'), {'code':'DEMO-101'}).scalar_one_or_none()
            if sid is not None:
                c.execute(text('INSERT INTO questions(subject_id,text,options,answer,explain) VALUES(:sid,:q,:opts,:answer,:explain)'),
                          {'sid':sid,'q':'ข้อใดเป็นบ่อเกิดแห่งหนี้ตามกฎหมายแพ่ง?',
                           'opts':json.dumps(['นิติกรรมและนิติเหตุ','เฉพาะคำพิพากษา','เฉพาะสัญญาซื้อขาย','เฉพาะการกระทำละเมิด'],ensure_ascii=False),
                           'answer':0,'explain':'บ่อเกิดแห่งหนี้อาจเกิดจากนิติกรรมและนิติเหตุ ทั้งนี้เป็นโจทย์ตัวอย่างเพื่อฝึกทบทวน'})

def hashpw(p,s):
    return hashlib.pbkdf2_hmac('sha256',p.encode(),bytes.fromhex(s),600000).hex()

def bootstrap_admin():
    username=os.environ.get('MSU_ADMIN_USERNAME','').strip()
    password=os.environ.get('MSU_ADMIN_PASSWORD','')
    if not username and not password:
        return
    if not username or len(password)<12:
        raise RuntimeError('Set MSU_ADMIN_USERNAME and MSU_ADMIN_PASSWORD (at least 12 characters)')
    with engine.begin() as c:
        if c.execute(text('SELECT 1 FROM admins LIMIT 1')).first():
            return
        salt=secrets.token_hex(16)
        c.execute(text('INSERT INTO admins(username,salt,password_hash) VALUES(:u,:s,:h)'), {'u':username,'s':salt,'h':hashpw(password,salt)})

# Run initialization as a separate one-off command before starting Gunicorn.
# This avoids concurrent table creation when Gunicorn has multiple workers.
def admin(): return bool(session.get('admin'))
def forbidden(): return jsonify(error='ต้องเข้าสู่ระบบผู้ดูแล'),403

@app.after_request
def security_headers(r):
    r.headers['X-Content-Type-Options']='nosniff'
    r.headers['X-Frame-Options']='DENY'
    r.headers['Referrer-Policy']='strict-origin-when-cross-origin'
    return r

@app.route('/')
def home(): return render_template('index.html')

@app.get('/api/session')
def auth_state(): return jsonify(admin=admin(),username=session.get('admin'))

@app.post('/api/login')
def login():
    d=request.get_json(silent=True) or {}
    u=str(d.get('username','')); p=str(d.get('password',''))
    r=fetchone('SELECT * FROM admins WHERE username=:u',{'u':u})
    if not r or not hmac.compare_digest(hashpw(p,r['salt']),r['password_hash']):
        return jsonify(error='ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง'),401
    session.clear();session['admin']=u;session.permanent=True
    return jsonify(admin=True)

@app.post('/api/logout')
def logout(): session.clear();return jsonify(ok=True)

@app.get('/api/subjects')
def subjects(): return jsonify(fetchall('SELECT * FROM subjects ORDER BY id'))

@app.post('/api/subjects')
def add_subject():
    if not admin(): return forbidden()
    d=request.get_json(silent=True) or {}
    code=str(d.get('code','')).strip()[:30]
    name=str(d.get('name','')).strip()[:150]
    cat=d.get('category')
    if not code or not name or cat not in CATS: return jsonify(error='ข้อมูลรายวิชาไม่ถูกต้อง'),400
    try:
        execute('INSERT INTO subjects(code,name,category) VALUES(:code,:name,:cat)',{'code':code,'name':name,'cat':cat})
    except IntegrityError:
        return jsonify(error='รหัสวิชาซ้ำ'),409
    return jsonify(ok=True),201

@app.get('/api/documents')
def documents():
    status=request.args.get('status','approved')
    if status!='approved' and not admin(): return forbidden()
    if status not in ('approved','pending','rejected','all'): return jsonify(error='สถานะไม่ถูกต้อง'),400
    sql='SELECT id,title,subject_id AS "subjectId",year,type,description,status,created_at AS "createdAt" FROM documents'
    args={}
    if status!='all':
        sql+=' WHERE status=:status';args={'status':status}
    sql+=' ORDER BY created_at DESC,id DESC'
    rows=fetchall(sql,args)
    for row in rows:
        if row['createdAt'] is not None: row['createdAt']=row['createdAt'].isoformat(sep=' ')
    return jsonify(rows)

@app.post('/api/submissions')
def submit():
    f=request.files.get('file')
    title=request.form.get('title','').strip()[:140]
    description=request.form.get('description','').strip()[:2000]
    try:
        sid=int(request.form.get('subjectId',0));year=int(request.form.get('year',0))
    except (ValueError,TypeError): return jsonify(error='ข้อมูลไม่ถูกต้อง'),400
    typ=request.form.get('type','')
    if not title or not description or year not in range(1,5) or typ not in ('แนวข้อสอบ','สรุปบทเรียน','แบบฝึกหัด') or not f or not request.form.get('rights'):
        return jsonify(error='กรอกข้อมูลและยืนยันสิทธิ์ให้ครบ'),400
    if not fetchone('SELECT 1 FROM subjects WHERE id=:id',{'id':sid}): return jsonify(error='ไม่พบรายวิชา'),400
    header=f.stream.read(5);f.stream.seek(0)
    if header!=b'%PDF-' or not (f.filename or '').lower().endswith('.pdf'):
        return jsonify(error='รองรับเฉพาะไฟล์ PDF'),400
    file_id=uuid.uuid4().hex
    name=file_id+'.pdf'
    try:
        r2.upload_fileobj(f.stream,R2_BUCKET,name,ExtraArgs={'ContentType':'application/pdf'})
    except (ClientError,BotoCoreError,OSError):
        app.logger.exception('R2 upload failed')
        return jsonify(error='ไม่สามารถบันทึกไฟล์ PDF ได้ กรุณาลองใหม่'),502
    try:
        execute('INSERT INTO documents(id,title,subject_id,year,type,description,filename) VALUES(:id,:title,:sid,:year,:type,:description,:filename)',
                {'id':file_id,'title':title,'sid':sid,'year':year,'type':typ,'description':description,'filename':name})
    except Exception:
        app.logger.exception('Document metadata insert failed')
        try:r2.delete_object(Bucket=R2_BUCKET,Key=name)
        except Exception:app.logger.exception('R2 rollback delete failed')
        return jsonify(error='ไม่สามารถบันทึกข้อมูลเอกสารได้'),500
    return jsonify(ok=True,status='pending'),201

@app.get('/api/documents/<doc_id>/file')
def file(doc_id):
    r=fetchone('SELECT filename,status FROM documents WHERE id=:id',{'id':doc_id})
    if not r or (r['status']!='approved' and not admin()): abort(404)
    try:
        obj=r2.get_object(Bucket=R2_BUCKET,Key=r['filename'])
        body=obj['Body'].read()
    except (ClientError,BotoCoreError,OSError):
        app.logger.exception('R2 download failed')
        return jsonify(error='ไม่สามารถอ่านไฟล์ PDF ได้'),502
    return send_file(io.BytesIO(body),mimetype='application/pdf',as_attachment=False,download_name=r['filename'])

@app.post('/api/documents/<doc_id>/status')
def change_status(doc_id):
    if not admin(): return forbidden()
    status=(request.get_json(silent=True) or {}).get('status')
    if status not in ('approved','rejected'): return jsonify(error='สถานะไม่ถูกต้อง'),400
    count=execute('UPDATE documents SET status=:status WHERE id=:id',{'status':status,'id':doc_id})
    if not count: return jsonify(error='ไม่พบเอกสาร'),404
    return jsonify(ok=True)

@app.get('/api/questions')
def questions():
    rows=fetchall('SELECT id,subject_id,text,options FROM questions')
    return jsonify([dict(id=r['id'],subjectId=r['subject_id'],text=r['text'],options=json.loads(r['options'])) for r in rows])

@app.post('/api/quiz/grade')
def grade():
    answers=(request.get_json(silent=True) or {}).get('answers',{})
    if not isinstance(answers,dict): return jsonify(error='รูปแบบคำตอบไม่ถูกต้อง'),400
    result=[]
    for k,v in list(answers.items())[:100]:
        try:qid=int(k)
        except (TypeError,ValueError):continue
        q=fetchone('SELECT id,answer,explain FROM questions WHERE id=:id',{'id':qid})
        if q: result.append(dict(id=q['id'],correct=v==q['answer'],answer=q['answer'],explain=q['explain']))
    return jsonify(results=result,score=sum(x['correct'] for x in result),total=len(result))

@app.errorhandler(413)
def too_big(e): return jsonify(error='ไฟล์มีขนาดเกิน 10 MB'),413
