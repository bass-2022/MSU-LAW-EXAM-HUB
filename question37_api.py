# V3.7 additive question-bank manager; Flask + PostgreSQL. Admin-only.
import csv
import io
import json
from urllib.parse import urlsplit
from flask import Blueprint, jsonify, render_template, request, session, Response
from sqlalchemy import text

bp=Blueprint('question37',__name__)
_engine=None
DIFFICULTIES={'easy','medium','hard'}
HEADERS=['subject_id','text','option_1','option_2','option_3','option_4','answer','explain','topic','difficulty','statute']

def configure(engine):
    global _engine
    _engine=engine

def migrate():
    with _engine.begin() as c:
        c.execute(text("ALTER TABLE questions ADD COLUMN IF NOT EXISTS topic TEXT NOT NULL DEFAULT ''"))
        c.execute(text("ALTER TABLE questions ADD COLUMN IF NOT EXISTS difficulty TEXT NOT NULL DEFAULT 'medium'"))
        c.execute(text("ALTER TABLE questions ADD COLUMN IF NOT EXISTS statute TEXT NOT NULL DEFAULT ''"))
        c.execute(text("CREATE INDEX IF NOT EXISTS idx_questions_v37_filters ON questions(subject_id,active,difficulty)"))

def require_admin():
    if not session.get('admin'):
        return jsonify(error='ต้องเข้าสู่ระบบผู้ดูแล'),403
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin=request.headers.get('Origin') or request.headers.get('Referer')
        if not origin:
            return jsonify(error='ไม่มีข้อมูลต้นทางคำขอ'),403
        a=urlsplit(origin);b=urlsplit(request.host_url)
        if a.netloc!=b.netloc or a.scheme not in ('http','https'):
            return jsonify(error='ต้นทางคำขอไม่ถูกต้อง'),403

@bp.before_request
def gate():
    return require_admin()

def normalize(raw,valid_subjects):
    if not isinstance(raw,dict):raise ValueError('รูปแบบข้อมูลไม่ถูกต้อง')
    try:
        sid=int(raw.get('subject_id'))
        answer=int(raw.get('answer'))
    except (ValueError,TypeError):raise ValueError('รายวิชาหรือเฉลยไม่ถูกต้อง')
    if sid not in valid_subjects:raise ValueError('ไม่พบรายวิชา')
    q=str(raw.get('text') or '').strip()
    options=[str(raw.get('option_'+str(i)) or '').strip() for i in range(1,5)]
    explain=str(raw.get('explain') or '').strip()
    topic=str(raw.get('topic') or '').strip()
    statute=str(raw.get('statute') or '').strip()
    difficulty=str(raw.get('difficulty') or 'medium').strip().lower()
    if not 1<=len(q)<=2000:raise ValueError('โจทย์ต้องยาว 1–2000 ตัวอักษร')
    if any(not 1<=len(o)<=500 for o in options):raise ValueError('ตัวเลือกทั้ง 4 ต้องยาว 1–500 ตัวอักษร')
    if len(set(options))!=4:raise ValueError('ตัวเลือกต้องไม่ซ้ำกัน')
    if answer not in (1,2,3,4):raise ValueError('เฉลยต้องเป็นเลข 1–4')
    if len(explain)>4000 or len(topic)>200 or len(statute)>200:raise ValueError('คำอธิบาย/หัวข้อ/มาตรายาวเกินกำหนด')
    if difficulty not in DIFFICULTIES:raise ValueError('ระดับความยากต้องเป็น easy, medium หรือ hard')
    return {'sid':sid,'q':q,'opts':json.dumps(options,ensure_ascii=False),'answer':answer-1,
            'explain':explain,'topic':topic,'difficulty':difficulty,'statute':statute}

def subjects(c):
    return set(c.execute(text('SELECT id FROM subjects')).scalars().all())

@bp.get('/admin/questions-v37')
def page():
    return render_template('questions_v37.html')

@bp.get('/api/v37/admin/subjects')
def subject_list():
    with _engine.connect() as c:
        rows=c.execute(text('SELECT id,code,name FROM subjects ORDER BY name')).mappings().all()
    return jsonify([dict(r) for r in rows])

@bp.get('/api/v37/admin/questions')
def list_questions():
    try:
        page=max(1,min(100000,int(request.args.get('page','1'))))
        size=max(1,min(100,int(request.args.get('size','25'))))
        sid=int(request.args.get('subject_id') or 0)
    except ValueError:return jsonify(error='ตัวกรองไม่ถูกต้อง'),400
    query=(request.args.get('q') or '').strip()[:100]
    status=request.args.get('status','all')
    difficulty=request.args.get('difficulty','all')
    if status not in ('all','active','inactive') or difficulty not in ('all',*DIFFICULTIES):
        return jsonify(error='ตัวกรองไม่ถูกต้อง'),400
    where=['(:sid=0 OR q.subject_id=:sid)','(:search=\'\' OR q.text ILIKE :like OR q.topic ILIKE :like OR q.statute ILIKE :like)',
           "(:status='all' OR q.active=(:status='active'))", "(:difficulty='all' OR q.difficulty=:difficulty)"]
    params={'sid':sid,'search':query,'like':'%'+query+'%','status':status,'difficulty':difficulty,'limit':size,'offset':(page-1)*size}
    base=' FROM questions q JOIN subjects s ON s.id=q.subject_id WHERE '+' AND '.join(where)
    with _engine.connect() as c:
        total=c.execute(text('SELECT COUNT(*)'+base),params).scalar_one()
        rows=c.execute(text('SELECT q.id,q.subject_id,s.name AS subject_name,q.text,q.options,q.answer,q.explain,q.topic,q.difficulty,q.statute,q.active'+base+' ORDER BY q.id DESC LIMIT :limit OFFSET :offset'),params).mappings().all()
    items=[]
    for r in rows:
        d=dict(r);d['options']=json.loads(d['options']);d['answer']=d['answer']+1;items.append(d)
    return jsonify(items=items,total=total,page=page,size=size)

@bp.post('/api/v37/admin/questions')
def create():
    raw=request.get_json(silent=True)
    with _engine.begin() as c:
        try:p=normalize(raw,subjects(c))
        except ValueError as e:return jsonify(error=str(e)),400
        qid=c.execute(text('''INSERT INTO questions(subject_id,text,options,answer,explain,topic,difficulty,statute)
            VALUES(:sid,:q,:opts,:answer,:explain,:topic,:difficulty,:statute) RETURNING id'''),p).scalar_one()
    return jsonify(ok=True,id=qid),201

@bp.put('/api/v37/admin/questions/<int:qid>')
def update(qid):
    raw=request.get_json(silent=True)
    with _engine.begin() as c:
        try:p=normalize(raw,subjects(c))
        except ValueError as e:return jsonify(error=str(e)),400
        p['id']=qid
        result=c.execute(text('''UPDATE questions SET subject_id=:sid,text=:q,options=:opts,answer=:answer,
          explain=:explain,topic=:topic,difficulty=:difficulty,statute=:statute WHERE id=:id'''),p)
        if not result.rowcount:return jsonify(error='ไม่พบข้อสอบ'),404
    return jsonify(ok=True)

@bp.patch('/api/v37/admin/questions/<int:qid>/active')
def toggle(qid):
    raw=request.get_json(silent=True) or {}
    if type(raw.get('active')) is not bool:return jsonify(error='active ต้องเป็น true/false'),400
    with _engine.begin() as c:
        result=c.execute(text('UPDATE questions SET active=:active WHERE id=:id'),{'active':raw['active'],'id':qid})
        if not result.rowcount:return jsonify(error='ไม่พบข้อสอบ'),404
    return jsonify(ok=True)

@bp.get('/api/v37/admin/template.csv')
def template():
    out=io.StringIO();w=csv.writer(out);w.writerow(HEADERS)
    w.writerow([1,'ตัวอย่างคำถาม (แก้ subject_id ตามรายวิชาจริง)','ก','ข','ค','ง',1,'คำอธิบาย','ทั่วไป','medium','ป.พ.พ. มาตรา ...'])
    return Response('\ufeff'+out.getvalue(),mimetype='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="questions_v37_template.csv"'})

def parse_csv():
    file=request.files.get('file')
    if not file:raise ValueError('กรุณาเลือกไฟล์ CSV')
    raw=file.read(1024*1024+1)
    if len(raw)>1024*1024:raise ValueError('ไฟล์ต้องไม่เกิน 1 MB')
    try:content=raw.decode('utf-8-sig')
    except UnicodeDecodeError:raise ValueError('ไฟล์ต้องเข้ารหัส UTF-8')
    reader=csv.DictReader(io.StringIO(content))
    if not reader.fieldnames or any(h not in reader.fieldnames for h in HEADERS):
        raise ValueError('หัวคอลัมน์ CSV ไม่ครบตามเทมเพลต')
    rows=list(reader)
    if not rows or len(rows)>200:raise ValueError('นำเข้าได้ครั้งละ 1–200 ข้อ')
    return rows

@bp.post('/api/v37/admin/import')
def bulk_import():
    try:rows=parse_csv()
    except ValueError as e:return jsonify(error=str(e)),400
    dry=request.form.get('dry_run')=='1'
    errors=[];validated=[]
    with _engine.begin() as c:
        ids=subjects(c)
        for i,row in enumerate(rows,2):
            try:validated.append(normalize(row,ids))
            except ValueError as e:errors.append({'line':i,'error':str(e)})
        if errors:return jsonify(ok=False,valid=len(validated),total=len(rows),errors=errors),400
        if not dry:
            stmt=text('''INSERT INTO questions(subject_id,text,options,answer,explain,topic,difficulty,statute)
               VALUES(:sid,:q,:opts,:answer,:explain,:topic,:difficulty,:statute)''')
            c.execute(stmt,validated)
    return jsonify(ok=True,dry_run=dry,count=len(validated))
