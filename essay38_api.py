"""V3.8: additive essay archive and moderated PDF/image uploads."""
import io, os, uuid
from urllib.parse import urlsplit
from flask import Blueprint, request, jsonify, render_template, session, send_file, abort
from sqlalchemy import text
from PIL import Image, UnidentifiedImageError
import boto3
bp=Blueprint('essay38',__name__)
engine=None

def configure(e):
    global engine
    engine=e

def migrate():
    with engine.begin() as c:
        c.execute(text('''CREATE TABLE IF NOT EXISTS essay38_exams (
            id TEXT PRIMARY KEY, subject_id INTEGER NOT NULL REFERENCES subjects(id),
            title TEXT NOT NULL, question_text TEXT NOT NULL DEFAULT '', topic TEXT NOT NULL DEFAULT '',
            academic_year INTEGER, semester TEXT NOT NULL DEFAULT '', exam_type TEXT NOT NULL DEFAULT '',
            source_note TEXT NOT NULL DEFAULT '', answer_issues TEXT NOT NULL DEFAULT '',
            answer_law TEXT NOT NULL DEFAULT '', answer_analysis TEXT NOT NULL DEFAULT '',
            answer_conclusion TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS essay38_files (
            id TEXT PRIMARY KEY, exam_id TEXT NOT NULL REFERENCES essay38_exams(id) ON DELETE CASCADE,
            object_key TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL,
            mime_type TEXT NOT NULL, file_size INTEGER NOT NULL)'''))
        c.execute(text('CREATE INDEX IF NOT EXISTS idx_essay38_subject_status ON essay38_exams(subject_id,status,created_at DESC)'))

def admin():return bool(session.get('admin'))

@bp.before_request
def csrf():
    if request.method in ('POST','PUT','PATCH','DELETE'):
        origin=request.headers.get('Origin') or request.headers.get('Referer')
        if not origin:return jsonify(error='ไม่พบข้อมูลต้นทางคำขอ'),403
        a,b=urlsplit(origin),urlsplit(request.host_url)
        if (a.scheme,a.netloc)!=(b.scheme,b.netloc):return jsonify(error='ต้นทางคำขอไม่ถูกต้อง'),403

def client():
    return boto3.client('s3',endpoint_url=os.environ['R2_ENDPOINT'],
        aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'],region_name='auto')

def values(raw):
    try:sid=int(raw.get('subject_id'))
    except (ValueError,TypeError):raise ValueError('กรุณาเลือกรายวิชา')
    with engine.connect() as c:
        if not c.execute(text('SELECT 1 FROM subjects WHERE id=:id'),{'id':sid}).first():raise ValueError('ไม่พบรายวิชา')
    lengths={'title':180,'question_text':20000,'topic':200,'semester':20,'exam_type':30,
             'source_note':500,'answer_issues':15000,'answer_law':15000,
             'answer_analysis':15000,'answer_conclusion':15000}
    d={k:str(raw.get(k) or '').strip() for k in lengths}
    if not d['title'] or any(len(d[k])>n for k,n in lengths.items()):raise ValueError('ชื่อหรือเนื้อหายาวเกินกำหนด')
    if d['semester'] not in ('','1','2','ฤดูร้อน') or d['exam_type'] not in ('','กลางภาค','ปลายภาค','อื่น ๆ'):
        raise ValueError('ภาคเรียนหรือประเภทข้อสอบไม่ถูกต้อง')
    try:year=int(raw['academic_year']) if str(raw.get('academic_year') or '').strip() else None
    except (ValueError,TypeError):raise ValueError('ปีการศึกษาไม่ถูกต้อง')
    if year is not None and not 2500<=year<=2700:raise ValueError('ปีการศึกษาไม่ถูกต้อง')
    d.update(subject_id=sid,academic_year=year)
    return d

COLUMNS=('subject_id','title','question_text','topic','academic_year','semester','exam_type',
         'source_note','answer_issues','answer_law','answer_analysis','answer_conclusion')

def insert(c,d,eid):
    cols=','.join(COLUMNS)
    params=','.join(':'+k for k in COLUMNS)
    c.execute(text('INSERT INTO essay38_exams (id,'+cols+') VALUES (:id,'+params+')'),{'id':eid,**d})

@bp.get('/essays')
def page():return render_template('essay38.html')

@bp.get('/api/v38/essays')
def listing():
    status=request.args.get('status','approved')
    if status not in ('approved','pending','rejected','all'):return jsonify(error='สถานะไม่ถูกต้อง'),400
    if status!='approved' and not admin():return jsonify(error='ไม่มีสิทธิ์'),403
    try:sid=int(request.args.get('subject_id') or 0)
    except ValueError:return jsonify(error='รายวิชาไม่ถูกต้อง'),400
    q=(request.args.get('q') or '')[:100]
    with engine.connect() as c:
        rows=c.execute(text('''SELECT e.id,e.subject_id,s.name AS subject_name,e.title,e.topic,
            e.academic_year,e.semester,e.exam_type,e.status,e.created_at,
            EXISTS(SELECT 1 FROM essay38_files f WHERE f.exam_id=e.id) AS has_file
            FROM essay38_exams e JOIN subjects s ON s.id=e.subject_id
            WHERE (:status='all' OR e.status=:status) AND (:sid=0 OR e.subject_id=:sid)
            AND (:q='' OR e.title ILIKE :like OR e.topic ILIKE :like OR e.question_text ILIKE :like OR s.name ILIKE :like)
            ORDER BY e.created_at DESC LIMIT 100'''),{'status':status,'sid':sid,'q':q,'like':'%'+q+'%'}).mappings().all()
    return jsonify([{**dict(r),'created_at':r['created_at'].isoformat()} for r in rows])

@bp.get('/api/v38/essays/<eid>')
def detail(eid):
    with engine.connect() as c:
        row=c.execute(text('SELECT * FROM essay38_exams WHERE id=:id'),{'id':eid}).mappings().first()
        if not row or (row['status']!='approved' and not admin()):abort(404)
        files=c.execute(text('SELECT id,display_name,mime_type,file_size FROM essay38_files WHERE exam_id=:id'),{'id':eid}).mappings().all()
    d=dict(row);d['created_at']=d['created_at'].isoformat();d['files']=[dict(f) for f in files]
    if not admin():d.pop('source_note',None)
    return jsonify(d)

@bp.post('/api/v38/essays')
def create():
    raw=request.get_json(silent=True) or {}
    if not admin() and raw.get('rights') is not True:return jsonify(error='กรุณายืนยันสิทธิ์เผยแพร่'),400
    try:d=values(raw)
    except ValueError as e:return jsonify(error=str(e)),400
    if not d['question_text']:return jsonify(error='กรุณากรอกโจทย์ข้อความ'),400
    if not admin():
        for k in ('answer_issues','answer_law','answer_analysis','answer_conclusion'):d[k]=''
    eid=uuid.uuid4().hex
    with engine.begin() as c:insert(c,d,eid)
    return jsonify(ok=True,id=eid,status='pending'),201

@bp.post('/api/v38/essays/upload')
def upload():
    raw=request.form.to_dict();f=request.files.get('file')
    if not admin() and raw.get('rights')!='yes':return jsonify(error='กรุณายืนยันสิทธิ์เผยแพร่'),400
    if not f:return jsonify(error='กรุณาเลือกไฟล์'),400
    try:d=values(raw)
    except ValueError as e:return jsonify(error=str(e)),400
    if not admin():
        for k in ('answer_issues','answer_law','answer_analysis','answer_conclusion'):d[k]=''
    data=f.read(10*1024*1024+1)
    if not data or len(data)>10*1024*1024:return jsonify(error='ไฟล์ต้องไม่เกิน 10 MB'),400
    if data.startswith(b'%PDF-') and (f.filename or '').lower().endswith('.pdf'):
        mime,ext='application/pdf','.pdf'
    else:
        try:
            with Image.open(io.BytesIO(data)) as im:im.verify()
            with Image.open(io.BytesIO(data)) as im:
                if im.format not in ('JPEG','PNG') or im.width*im.height>30000000:raise ValueError()
                output=io.BytesIO();im.convert('RGB').save(output,'JPEG',quality=85);data=output.getvalue()
            mime,ext='image/jpeg','.jpg'
        except (UnidentifiedImageError,OSError,ValueError):return jsonify(error='รองรับ PDF, JPG, PNG เท่านั้น'),400
    eid,fid=uuid.uuid4().hex,uuid.uuid4().hex
    key='essays/v38/'+eid+'/'+fid+ext
    try:client().put_object(Bucket=os.environ['R2_BUCKET_NAME'],Key=key,Body=data,ContentType=mime)
    except Exception:return jsonify(error='อัปโหลดไฟล์ไม่สำเร็จ'),502
    try:
        with engine.begin() as c:
            insert(c,d,eid)
            c.execute(text('''INSERT INTO essay38_files(id,exam_id,object_key,display_name,mime_type,file_size)
                VALUES(:id,:eid,:key,:name,:mime,:size)'''),{'id':fid,'eid':eid,'key':key,
                'name':(f.filename or 'file')[:180],'mime':mime,'size':len(data)})
    except Exception:
        try:client().delete_object(Bucket=os.environ['R2_BUCKET_NAME'],Key=key)
        except Exception:pass
        return jsonify(error='บันทึกข้อมูลไม่สำเร็จ'),500
    return jsonify(ok=True,id=eid,status='pending'),201

@bp.get('/api/v38/files/<fid>')
def file(fid):
    with engine.connect() as c:
        r=c.execute(text('''SELECT f.object_key,f.display_name,f.mime_type,e.status FROM essay38_files f
            JOIN essay38_exams e ON e.id=f.exam_id WHERE f.id=:id'''),{'id':fid}).mappings().first()
    if not r or (r['status']!='approved' and not admin()):abort(404)
    try:
        obj=client().get_object(Bucket=os.environ['R2_BUCKET_NAME'],Key=r['object_key'])
        return send_file(io.BytesIO(obj['Body'].read()),mimetype=r['mime_type'],download_name=r['display_name'])
    except Exception:return jsonify(error='ไม่สามารถเปิดไฟล์ได้'),502

@bp.put('/api/v38/admin/essays/<eid>')
def update(eid):
    if not admin():return jsonify(error='ไม่มีสิทธิ์'),403
    try:d=values(request.get_json(silent=True) or {})
    except ValueError as e:return jsonify(error=str(e)),400
    assigns=','.join(k+'=:'+k for k in COLUMNS)
    with engine.begin() as c:
        n=c.execute(text('UPDATE essay38_exams SET '+assigns+' WHERE id=:id'),{'id':eid,**d}).rowcount
    return jsonify(ok=True) if n else (jsonify(error='ไม่พบข้อสอบ'),404)

@bp.patch('/api/v38/admin/essays/<eid>/status')
def set_status(eid):
    if not admin():return jsonify(error='ไม่มีสิทธิ์'),403
    status=(request.get_json(silent=True) or {}).get('status')
    if status not in ('approved','pending','rejected'):return jsonify(error='สถานะไม่ถูกต้อง'),400
    with engine.begin() as c:
        n=c.execute(text('UPDATE essay38_exams SET status=:status WHERE id=:id'),{'id':eid,'status':status}).rowcount
    return jsonify(ok=True) if n else (jsonify(error='ไม่พบข้อสอบ'),404)
