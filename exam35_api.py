"""V3.5 additive, server-graded exam system. Does not alter legacy member attempts."""
import json
import random
import secrets
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit
from flask import Blueprint, request, jsonify, session
from sqlalchemy import text

bp = Blueprint('exam35', __name__)
_engine = None

def configure(engine):
    global _engine
    _engine = engine

def migrate():
    with _engine.begin() as c:
        c.execute(text("ALTER TABLE questions ADD COLUMN IF NOT EXISTS topic TEXT NOT NULL DEFAULT ''"))
        c.execute(text("ALTER TABLE questions ADD COLUMN IF NOT EXISTS difficulty TEXT NOT NULL DEFAULT 'medium'"))
        c.execute(text('''CREATE TABLE IF NOT EXISTS comprehensive_exams (
            id TEXT PRIMARY KEY,
            member_id BIGINT NOT NULL REFERENCES members(id) ON DELETE CASCADE,
            subject_id INTEGER NOT NULL REFERENCES subjects(id),
            status TEXT NOT NULL DEFAULT 'active',
            question_snapshot TEXT NOT NULL,
            answers_json TEXT NOT NULL DEFAULT '{}',
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            deadline_at TIMESTAMPTZ NOT NULL,
            submitted_at TIMESTAMPTZ,
            score INTEGER,
            total INTEGER NOT NULL,
            result_json TEXT
        )'''))
        c.execute(text('CREATE INDEX IF NOT EXISTS idx_comprehensive_member ON comprehensive_exams(member_id,started_at DESC)'))

def _auth():
    mid=session.get('member_id')
    if not mid:return None
    return int(mid)

def _origin_ok():
    value=request.headers.get('Origin') or request.headers.get('Referer')
    if not value:return False
    a=urlsplit(value);b=urlsplit(request.host_url)
    return (a.scheme,a.netloc)==(b.scheme,b.netloc)

@bp.before_request
def protect():
    if request.method in ('POST','PUT','PATCH','DELETE') and not _origin_ok():
        return jsonify(error='คำขอไม่ผ่านการตรวจสอบต้นทาง'),403

def _load_exam(c,eid,mid,lock=False):
    sql='SELECT * FROM comprehensive_exams WHERE id=:id AND member_id=:mid'
    if lock:sql+=' FOR UPDATE'
    return c.execute(text(sql),{'id':eid,'mid':mid}).mappings().first()

def _finish(c,row,answers=None):
    if row['status']!='active':return json.loads(row['result_json'])
    items=json.loads(row['question_snapshot'])
    saved=json.loads(row['answers_json']) if answers is None else answers
    details=[];score=0
    for i,q in enumerate(items):
        chosen=saved.get(str(q['id']))
        valid=isinstance(chosen,int) and not isinstance(chosen,bool) and 0<=chosen<len(q['options'])
        correct=valid and chosen==q['answer']
        score+=int(correct)
        details.append({'id':q['id'],'number':i+1,'text':q['text'],'options':q['options'],
            'selected':chosen if valid else None,'answer':q['answer'],'correct':bool(correct),
            'explain':q['explain'],'topic':q['topic'],'difficulty':q['difficulty']})
    result={'id':row['id'],'score':score,'total':len(items),'percent':round(100*score/len(items),1),
        'details':details,'subjectId':row['subject_id'],'submittedAt':datetime.now(timezone.utc).isoformat()}
    c.execute(text('''UPDATE comprehensive_exams SET status='submitted',score=:score,
        submitted_at=NOW(),result_json=:result,answers_json=:answers WHERE id=:id'''),
        {'score':score,'result':json.dumps(result,ensure_ascii=False),'answers':json.dumps(saved),'id':row['id']})
    return result

def _public(row):
    return {'id':row['id'],'subjectId':row['subject_id'],'status':row['status'],
        'deadlineAt':row['deadline_at'].isoformat(),'startedAt':row['started_at'].isoformat(),
        'total':row['total']}

@bp.get('/api/v35/catalog')
def catalog():
    with _engine.connect() as c:
        subjects=c.execute(text('''SELECT s.id,s.name,s.code,COUNT(q.id) AS count
            FROM subjects s LEFT JOIN questions q ON q.subject_id=s.id AND q.active=TRUE
            GROUP BY s.id,s.name,s.code ORDER BY s.name''')).mappings().all()
        topics=c.execute(text('''SELECT subject_id,topic,difficulty,COUNT(*) AS count FROM questions
            WHERE active=TRUE GROUP BY subject_id,topic,difficulty ORDER BY topic''')).mappings().all()
    return jsonify(subjects=[dict(r) for r in subjects],topics=[dict(r) for r in topics])

@bp.post('/api/v35/exams')
def start():
    mid=_auth()
    if not mid:return jsonify(error='กรุณาเข้าสู่ระบบสมาชิกก่อนเริ่มสอบ V3.5'),401
    d=request.get_json(silent=True) or {}
    try:
        sid=int(d.get('subjectId'));count=int(d.get('count'));minutes=int(d.get('minutes'))
    except (TypeError,ValueError):return jsonify(error='ข้อมูลการจัดชุดสอบไม่ถูกต้อง'),400
    if not (1<=count<=100 and 1<=minutes<=180):return jsonify(error='จำนวนข้อหรือเวลาสอบไม่ถูกต้อง'),400
    topic=str(d.get('topic','')).strip()[:150]
    difficulty=str(d.get('difficulty','all'))
    if difficulty not in ('all','easy','medium','hard'):return jsonify(error='ระดับความยากไม่ถูกต้อง'),400
    with _engine.begin() as c:
        active=c.execute(text("SELECT id FROM comprehensive_exams WHERE member_id=:mid AND status='active' ORDER BY started_at DESC FOR UPDATE"),{'mid':mid}).mappings().all()
        for old in active:
            row=_load_exam(c,old['id'],mid,True)
            if row:
                if datetime.now(timezone.utc)<row['deadline_at']:
                    return jsonify(error='มีชุดสอบที่กำลังทำอยู่ กรุณาทำให้เสร็จก่อน',activeId=row['id']),409
                _finish(c,row)
        rows=c.execute(text('''SELECT id,text,options,answer,explain,topic,difficulty
            FROM questions WHERE subject_id=:sid AND active=TRUE
            AND (:topic='' OR topic=:topic) AND (:difficulty='all' OR difficulty=:difficulty)'''),
            {'sid':sid,'topic':topic,'difficulty':difficulty}).mappings().all()
        if not rows:return jsonify(error='ไม่พบข้อสอบตามเงื่อนไขที่เลือก'),400
        items=random.SystemRandom().sample(list(rows),min(count,len(rows)))
        snapshot=[]
        for r in items:
            options=json.loads(r['options'])
            if not isinstance(options,list) or not 0<=r['answer']<len(options):continue
            order=list(range(len(options)));random.SystemRandom().shuffle(order)
            snapshot.append({'id':r['id'],'text':r['text'],'options':[options[i] for i in order],
                'answer':order.index(r['answer']),'explain':r['explain'],
                'topic':r['topic'] or 'ทั่วไป','difficulty':r['difficulty']})
        if not snapshot:return jsonify(error='ไม่มีข้อสอบที่ใช้งานได้'),400
        eid=secrets.token_urlsafe(24)
        deadline=datetime.now(timezone.utc)+timedelta(minutes=minutes)
        c.execute(text('''INSERT INTO comprehensive_exams(id,member_id,subject_id,question_snapshot,deadline_at,total)
            VALUES(:id,:mid,:sid,:snapshot,:deadline,:total)'''),
            {'id':eid,'mid':mid,'sid':sid,'snapshot':json.dumps(snapshot,ensure_ascii=False),
             'deadline':deadline,'total':len(snapshot)})
    return jsonify(id=eid,deadlineAt=deadline.isoformat(),total=len(snapshot)),201

@bp.get('/api/v35/exams/active')
def active():
    mid=_auth()
    if not mid:return jsonify(error='กรุณาเข้าสู่ระบบสมาชิก'),401
    with _engine.begin() as c:
        row=c.execute(text("SELECT * FROM comprehensive_exams WHERE member_id=:mid AND status='active' ORDER BY started_at DESC LIMIT 1 FOR UPDATE"),{'mid':mid}).mappings().first()
        if not row:return jsonify(active=False)
        if datetime.now(timezone.utc)>=row['deadline_at']:
            _finish(c,row)
            return jsonify(active=False,expired=True)
        return jsonify(active=True,id=row['id'])

@bp.get('/api/v35/exams/<eid>')
def get_exam(eid):
    mid=_auth()
    if not mid:return jsonify(error='กรุณาเข้าสู่ระบบสมาชิก'),401
    with _engine.begin() as c:
        row=_load_exam(c,eid,mid,True)
        if not row:return jsonify(error='ไม่พบชุดสอบ'),404
        if row['status']=='active' and datetime.now(timezone.utc)>=row['deadline_at']:
            result=_finish(c,row)
            return jsonify({**_public(row),'status':'submitted','result':result})
        if row['status']!='active':return jsonify(**_public(row),result=json.loads(row['result_json']))
        items=json.loads(row['question_snapshot'])
        public=[{k:q[k] for k in ('id','text','options','topic','difficulty')} for q in items]
        return jsonify(**_public(row),questions=public,answers=json.loads(row['answers_json']))

@bp.put('/api/v35/exams/<eid>/answers')
def save_answers(eid):
    mid=_auth()
    if not mid:return jsonify(error='กรุณาเข้าสู่ระบบสมาชิก'),401
    d=request.get_json(silent=True) or {}
    incoming=d.get('answers')
    if not isinstance(incoming,dict) or len(incoming)>100:return jsonify(error='คำตอบไม่ถูกต้อง'),400
    with _engine.begin() as c:
        row=_load_exam(c,eid,mid,True)
        if not row:return jsonify(error='ไม่พบชุดสอบ'),404
        if row['status']!='active':return jsonify(error='ชุดสอบถูกส่งแล้ว'),409
        if datetime.now(timezone.utc)>=row['deadline_at']:
            result=_finish(c,row)
            return jsonify(error='หมดเวลาสอบแล้ว',result=result),409
        items=json.loads(row['question_snapshot']);by_id={str(q['id']):len(q['options']) for q in items}
        if any(k not in by_id or type(v)!=int or not 0<=v<by_id[k] for k,v in incoming.items()):
            return jsonify(error='มีคำตอบไม่ถูกต้อง'),400
        c.execute(text('UPDATE comprehensive_exams SET answers_json=:answers WHERE id=:id'),
            {'answers':json.dumps(incoming),'id':eid})
    return jsonify(ok=True,saved=len(incoming))

@bp.post('/api/v35/exams/<eid>/submit')
def submit(eid):
    mid=_auth()
    if not mid:return jsonify(error='กรุณาเข้าสู่ระบบสมาชิก'),401
    with _engine.begin() as c:
        row=_load_exam(c,eid,mid,True)
        if not row:return jsonify(error='ไม่พบชุดสอบ'),404
        result=_finish(c,row)
    return jsonify(result=result)

@bp.get('/api/v35/history')
def history():
    mid=_auth()
    if not mid:return jsonify(error='กรุณาเข้าสู่ระบบสมาชิก'),401
    with _engine.connect() as c:
        rows=c.execute(text('''SELECT e.id,e.subject_id,s.name AS subject_name,e.score,e.total,e.started_at,
            e.submitted_at,e.result_json FROM comprehensive_exams e JOIN subjects s ON s.id=e.subject_id
            WHERE e.member_id=:mid AND e.status='submitted' ORDER BY e.started_at DESC LIMIT 100'''),{'mid':mid}).mappings().all()
    records=[];by_subject={};by_topic={}
    for r in rows:
        percent=round(100*r['score']/r['total'],1)
        records.append({'id':r['id'],'subjectName':r['subject_name'],'score':r['score'],'total':r['total'],
            'percent':percent,'date':r['submitted_at'].isoformat() if r['submitted_at'] else None})
        s=by_subject.setdefault(r['subject_name'],{'name':r['subject_name'],'score':0,'total':0,'attempts':0})
        s['score']+=r['score'];s['total']+=r['total'];s['attempts']+=1
        for q in json.loads(r['result_json']).get('details',[]):
            key=q['topic'];t=by_topic.setdefault(key,{'name':key,'correct':0,'total':0})
            t['total']+=1;t['correct']+=int(q['correct'])
    return jsonify(attempts=records,subjects=list(by_subject.values()),topics=list(by_topic.values()),
        summary={'attempts':len(rows),'correct':sum(r['score'] for r in rows),
                 'total':sum(r['total'] for r in rows)})

@bp.patch('/api/v35/admin/questions/<int:qid>/metadata')
def metadata(qid):
    if not session.get('admin'):return jsonify(error='ต้องเข้าสู่ระบบผู้ดูแล'),403
    d=request.get_json(silent=True) or {}
    topic=str(d.get('topic','')).strip()
    difficulty=str(d.get('difficulty','medium'))
    if len(topic)>150 or difficulty not in ('easy','medium','hard'):
        return jsonify(error='หัวข้อหรือระดับความยากไม่ถูกต้อง'),400
    with _engine.begin() as c:
        changed=c.execute(text('UPDATE questions SET topic=:topic,difficulty=:difficulty WHERE id=:id'),
            {'topic':topic,'difficulty':difficulty,'id':qid}).rowcount
    if not changed:return jsonify(error='ไม่พบข้อสอบ'),404
    return jsonify(ok=True)
