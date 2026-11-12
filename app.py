import os, sqlite3, secrets, hashlib, hmac, uuid, json, argparse, getpass
from pathlib import Path
from datetime import timedelta
from flask import Flask, request, jsonify, render_template, send_from_directory, session, abort
from werkzeug.utils import secure_filename

BASE=Path(__file__).resolve().parent
DATA=Path(os.environ.get('MSU_DATA_DIR',str(BASE/'data')))
DATA.mkdir(parents=True,exist_ok=True)
UPLOADS=DATA/'uploads';UPLOADS.mkdir(exist_ok=True)
app=Flask(__name__)
keyfile=DATA/'secret.key'
if not keyfile.exists():
    keyfile.write_bytes(secrets.token_bytes(32));os.chmod(keyfile,0o600)
app.secret_key=keyfile.read_bytes()
app.config.update(MAX_CONTENT_LENGTH=10*1024*1024+4096,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',SESSION_COOKIE_SECURE=os.environ.get('MSU_HTTPS')=='1',PERMANENT_SESSION_LIFETIME=timedelta(hours=8))
CATS=['กฎหมายแพ่ง','กฎหมายอาญา','กฎหมายมหาชน','กฎหมายวิธีพิจารณา','กฎหมายพาณิชย์','กฎหมายระหว่างประเทศ']
SEEDS=[('DEMO-101','กฎหมายลักษณะหนี้',CATS[0]),('DEMO-102','กฎหมายอาญา ภาคทั่วไป',CATS[1]),('DEMO-103','กฎหมายรัฐธรรมนูญ',CATS[2]),('DEMO-104','กฎหมายวิธีพิจารณาความแพ่ง',CATS[3]),('DEMO-105','กฎหมายเอกเทศสัญญา',CATS[0]),('DEMO-106','กฎหมายบริษัท',CATS[4])]
def conn():
    c=sqlite3.connect(DATA/'hub.sqlite3');c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');return c
def init():
    with conn() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS admins(username TEXT PRIMARY KEY,salt TEXT NOT NULL,password_hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS subjects(id INTEGER PRIMARY KEY AUTOINCREMENT,code TEXT UNIQUE NOT NULL,name TEXT NOT NULL,category TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,title TEXT NOT NULL,subject_id INTEGER NOT NULL REFERENCES subjects(id),year INTEGER NOT NULL,type TEXT NOT NULL,description TEXT NOT NULL,filename TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS questions(id INTEGER PRIMARY KEY AUTOINCREMENT,subject_id INTEGER NOT NULL REFERENCES subjects(id),text TEXT NOT NULL,options TEXT NOT NULL,answer INTEGER NOT NULL,explain TEXT NOT NULL);''')
        if not c.execute('SELECT 1 FROM subjects LIMIT 1').fetchone():c.executemany('INSERT INTO subjects(code,name,category) VALUES(?,?,?)',SEEDS)
        if not c.execute('SELECT 1 FROM questions LIMIT 1').fetchone():
            c.execute('INSERT INTO questions(subject_id,text,options,answer,explain) VALUES(?,?,?,?,?)',(1,'ข้อใดเป็นบ่อเกิดแห่งหนี้ตามกฎหมายแพ่ง?',json.dumps(['นิติกรรมและนิติเหตุ','เฉพาะคำพิพากษา','เฉพาะสัญญาซื้อขาย','เฉพาะการกระทำละเมิด'],ensure_ascii=False),0,'บ่อเกิดแห่งหนี้อาจเกิดจากนิติกรรมและนิติเหตุ ทั้งนี้เป็นโจทย์ตัวอย่างเพื่อฝึกทบทวน'))
init()
def hashpw(p,s):return hashlib.pbkdf2_hmac('sha256',p.encode(),bytes.fromhex(s),600000).hex()

def bootstrap_admin():
    """Create the first admin without overwriting existing accounts."""
    username = os.environ.get('MSU_ADMIN_USERNAME', '').strip()
    password = os.environ.get('MSU_ADMIN_PASSWORD', '')

    if not username and not password:
        return

    if not username or len(password) < 12:
        raise RuntimeError(
            'Set MSU_ADMIN_USERNAME and MSU_ADMIN_PASSWORD '
            '(at least 12 characters)'
        )

    with conn() as c:
        existing = c.execute(
            'SELECT 1 FROM admins LIMIT 1'
        ).fetchone()

        if existing:
            return

        salt = secrets.token_hex(16)
        c.execute(
            'INSERT INTO admins(username,salt,password_hash) VALUES(?,?,?)',
            (username, salt, hashpw(password, salt))
        )

bootstrap_admin()
def admin():return bool(session.get('admin'))
def forbidden():return jsonify(error='ต้องเข้าสู่ระบบผู้ดูแล'),403
def rowdict(r):return dict(r)
@app.after_request
def security_headers(r):
    r.headers['X-Content-Type-Options']='nosniff';r.headers['X-Frame-Options']='DENY';r.headers['Referrer-Policy']='strict-origin-when-cross-origin';return r
@app.route('/')
def home():return render_template('index.html')
@app.get('/api/session')
def auth_state():return jsonify(admin=admin(),username=session.get('admin'))
@app.post('/api/login')
def login():
    d=request.get_json(silent=True) or {};u=str(d.get('username',''));p=str(d.get('password',''))
    with conn() as c:r=c.execute('SELECT * FROM admins WHERE username=?',(u,)).fetchone()
    if not r or not hmac.compare_digest(hashpw(p,r['salt']),r['password_hash']):return jsonify(error='ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง'),401
    session.clear();session['admin']=u;session.permanent=True;return jsonify(admin=True)
@app.post('/api/logout')
def logout():session.clear();return jsonify(ok=True)
@app.get('/api/subjects')
def subjects():
    with conn() as c:return jsonify([rowdict(r) for r in c.execute('SELECT * FROM subjects ORDER BY id')])
@app.post('/api/subjects')
def add_subject():
    if not admin():return forbidden()
    d=request.get_json(silent=True) or {};code=str(d.get('code','')).strip()[:30];name=str(d.get('name','')).strip()[:150];cat=d.get('category')
    if not code or not name or cat not in CATS:return jsonify(error='ข้อมูลรายวิชาไม่ถูกต้อง'),400
    try:
        with conn() as c:c.execute('INSERT INTO subjects(code,name,category) VALUES(?,?,?)',(code,name,cat))
    except sqlite3.IntegrityError:return jsonify(error='รหัสวิชาซ้ำ'),409
    return jsonify(ok=True),201
@app.get('/api/documents')
def documents():
    status=request.args.get('status','approved')
    if status!='approved' and not admin():return forbidden()
    if status not in ('approved','pending','rejected','all'):return jsonify(error='สถานะไม่ถูกต้อง'),400
    sql='SELECT id,title,subject_id AS subjectId,year,type,description,status,created_at AS createdAt FROM documents'
    args=[]
    if status!='all':sql+=' WHERE status=?';args=[status]
    sql+=' ORDER BY created_at DESC,id DESC'
    with conn() as c:return jsonify([rowdict(r) for r in c.execute(sql,args)])
@app.post('/api/submissions')
def submit():
    f=request.files.get('file');title=request.form.get('title','').strip()[:140];description=request.form.get('description','').strip()[:2000]
    try:sid=int(request.form.get('subjectId',0));year=int(request.form.get('year',0))
    except ValueError:return jsonify(error='ข้อมูลไม่ถูกต้อง'),400
    typ=request.form.get('type','')
    if not title or not description or year not in range(1,5) or typ not in ('แนวข้อสอบ','สรุปบทเรียน','แบบฝึกหัด') or not f or not request.form.get('rights'):return jsonify(error='กรอกข้อมูลและยืนยันสิทธิ์ให้ครบ'),400
    with conn() as c:
        if not c.execute('SELECT 1 FROM subjects WHERE id=?',(sid,)).fetchone():return jsonify(error='ไม่พบรายวิชา'),400
    header=f.stream.read(5);f.stream.seek(0)
    if header!=b'%PDF-' or not f.filename.lower().endswith('.pdf'):return jsonify(error='รองรับเฉพาะไฟล์ PDF'),400
    file_id=uuid.uuid4().hex;name=file_id+'.pdf';f.save(UPLOADS/name)
    with conn() as c:c.execute('INSERT INTO documents(id,title,subject_id,year,type,description,filename) VALUES(?,?,?,?,?,?,?)',(file_id,title,sid,year,typ,description,name))
    return jsonify(ok=True,status='pending'),201
@app.get('/api/documents/<doc_id>/file')
def file(doc_id):
    with conn() as c:r=c.execute('SELECT filename,status FROM documents WHERE id=?',(doc_id,)).fetchone()
    if not r or (r['status']!='approved' and not admin()):abort(404)
    return send_from_directory(UPLOADS,r['filename'],mimetype='application/pdf',as_attachment=False)
@app.post('/api/documents/<doc_id>/status')
def change_status(doc_id):
    if not admin():return forbidden()
    status=(request.get_json(silent=True) or {}).get('status')
    if status not in ('approved','rejected'):return jsonify(error='สถานะไม่ถูกต้อง'),400
    with conn() as c:
        cur=c.execute('UPDATE documents SET status=? WHERE id=?',(status,doc_id))
        if not cur.rowcount:return jsonify(error='ไม่พบเอกสาร'),404
    return jsonify(ok=True)
@app.get('/api/questions')
def questions():
    with conn() as c:return jsonify([dict(id=r['id'],subjectId=r['subject_id'],text=r['text'],options=json.loads(r['options'])) for r in c.execute('SELECT * FROM questions')])
@app.post('/api/quiz/grade')
def grade():
    answers=(request.get_json(silent=True) or {}).get('answers',{})
    if not isinstance(answers,dict):return jsonify(error='รูปแบบคำตอบไม่ถูกต้อง'),400
    result=[]
    with conn() as c:
        for k,v in list(answers.items())[:100]:
            try:q=c.execute('SELECT * FROM questions WHERE id=?',(int(k),)).fetchone()
            except (TypeError,ValueError):continue
            if q:result.append(dict(id=q['id'],correct=v==q['answer'],answer=q['answer'],explain=q['explain']))
    return jsonify(results=result,score=sum(x['correct'] for x in result),total=len(result))
@app.errorhandler(413)
def too_big(e):return jsonify(error='ไฟล์มีขนาดเกิน 10 MB'),413
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--setup-admin',action='store_true');parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=5000);args=parser.parse_args()
    if args.setup_admin:
        user=input('Admin username [Siriroat2004]: ').strip() or 'Siriroat2004'
        password=getpass.getpass('Admin password: ')
        if len(password)<8:raise SystemExit('Password must contain at least 8 characters')
        salt=secrets.token_hex(16)
        with conn() as c:c.execute('INSERT OR REPLACE INTO admins VALUES(?,?,?)',(user,salt,hashpw(password,salt)))
        print('Admin account configured.')
    else:app.run(host=args.host,port=args.port,debug=False)
