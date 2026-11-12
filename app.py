           'status,created_at AS "createdAt" FROM documents')
    params = {}
    if status != "all":
        sql += " WHERE status=:status"
        params["status"] = status
    sql += " ORDER BY created_at DESC,id DESC"
    rows = fetchall(sql, params)
    for row in rows:
        if row["createdAt"] is not None:
            row["createdAt"] = row["createdAt"].isoformat(sep=" ")
    return jsonify(rows)

@app.post("/api/submissions")
def submit():
    uploaded = request.files.get("file")
    title = request.form.get("title", "").strip()[:140]
    description = request.form.get("description", "").strip()[:2000]
    try:
        sid = int(request.form.get("subjectId", 0))
        year = int(request.form.get("year", 0))
    except (ValueError, TypeError):
        return jsonify(error="ข้อมูลไม่ถูกต้อง"), 400
    typ = request.form.get("type", "")
    if (not title or not description or year not in range(1, 5)
            or typ not in ("แนวข้อสอบ", "สรุปบทเรียน", "แบบฝึกหัด")
            or not uploaded or not request.form.get("rights")):
        return jsonify(error="กรอกข้อมูลและยืนยันสิทธิ์ให้ครบ"), 400
    if not fetchone("SELECT 1 FROM subjects WHERE id=:id", {"id": sid}):
        return jsonify(error="ไม่พบรายวิชา"), 400
    header = uploaded.stream.read(5)
    uploaded.stream.seek(0)
    if header != b"%PDF-" or not (uploaded.filename or "").lower().endswith(".pdf"):
        return jsonify(error="รองรับเฉพาะไฟล์ PDF"), 400
    file_id = uuid.uuid4().hex
    filename = file_id + ".pdf"
    try:
        r2.upload_fileobj(uploaded.stream, R2_BUCKET, filename,
                          ExtraArgs={"ContentType": "application/pdf"})
    except (ClientError, BotoCoreError, OSError):
        app.logger.exception("R2 upload failed")
        return jsonify(error="ไม่สามารถบันทึกไฟล์ PDF ได้ กรุณาลองใหม่"), 502
    try:
        execute("""INSERT INTO documents(id,title,subject_id,year,type,description,filename)
                   VALUES (:id,:title,:sid,:year,:type,:description,:filename)""",
                {"id": file_id, "title": title, "sid": sid, "year": year,
                 "type": typ, "description": description, "filename": filename})
    except Exception:
        app.logger.exception("Document metadata insert failed")
        try:
            r2.delete_object(Bucket=R2_BUCKET, Key=filename)
        except Exception:
            app.logger.exception("R2 rollback delete failed")
        return jsonify(error="ไม่สามารถบันทึกข้อมูลเอกสารได้"), 500
    return jsonify(ok=True, status="pending"), 201

@app.get("/api/documents/<doc_id>/file")
def file(doc_id):
    row = fetchone("SELECT filename,status FROM documents WHERE id=:id", {"id": doc_id})
    if not row or (row["status"] != "approved" and not admin()):
        abort(404)
    try:
        obj = r2.get_object(Bucket=R2_BUCKET, Key=row["filename"])
        body = obj["Body"].read()
    except (ClientError, BotoCoreError, OSError):
        app.logger.exception("R2 download failed")
        return jsonify(error="ไม่สามารถอ่านไฟล์ PDF ได้"), 502
    return send_file(io.BytesIO(body), mimetype="application/pdf",
                     as_attachment=False, download_name=row["filename"])

@app.post("/api/documents/<doc_id>/status")
def change_status(doc_id):
    if not admin():
        return forbidden()
    status = (request.get_json(silent=True) or {}).get("status")
    if status not in ("approved", "rejected"):
        return jsonify(error="สถานะไม่ถูกต้อง"), 400
    count = execute("UPDATE documents SET status=:status WHERE id=:id",
                    {"status": status, "id": doc_id})
    if not count:
        return jsonify(error="ไม่พบเอกสาร"), 404
    return jsonify(ok=True)

@app.get("/api/questions")
def questions():
    rows = fetchall("SELECT id,subject_id,text,options FROM questions")
    return jsonify([{"id": row["id"], "subjectId": row["subject_id"],
                     "text": row["text"], "options": json.loads(row["options"])}
                    for row in rows])

@app.post("/api/quiz/grade")
def grade():
    answers = (request.get_json(silent=True) or {}).get("answers", {})
    if not isinstance(answers, dict):
        return jsonify(error="รูปแบบคำตอบไม่ถูกต้อง"), 400
    result = []
    for key, value in list(answers.items())[:100]:
        try:
            qid = int(key)
        except (TypeError, ValueError):
            continue
        question = fetchone("SELECT id,answer,explain FROM questions WHERE id=:id", {"id": qid})
        if question:
            result.append({"id": question["id"], "correct": value == question["answer"],
                           "answer": question["answer"], "explain": question["explain"]})
    return jsonify(results=result, score=sum(x["correct"] for x in result), total=len(result))

@app.errorhandler(413)
def too_big(error):
    return jsonify(error="ไฟล์มีขนาดเกิน 10 MB"), 413

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--init-db", action="store_true")
    parser.add_argument("--setup-admin", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    if args.init_db:
        init()
        print("Database initialized.")
    elif args.setup_admin:
        username = input("Admin username: ").strip()
        password = getpass.getpass("Admin password: ")
        if not username or len(password) < 12:
            raise SystemExit("Username required; password must be at least 12 characters")
        salt = secrets.token_hex(16)
        with engine.begin() as c:
            c.execute(text("""INSERT INTO admins(username,salt,password_hash)
                VALUES (:u,:s,:h) ON CONFLICT (username) DO UPDATE SET
                salt=EXCLUDED.salt,password_hash=EXCLUDED.password_hash"""),
                {"u": username, "s": salt, "h": hashpw(password, salt)})
        print("Admin configured.")
    else:
        app.run(host=args.host, port=args.port, debug=False)
