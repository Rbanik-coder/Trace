import os, re, json, sqlite3, hashlib
from datetime import datetime
from collections import defaultdict, deque
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_file
from werkzeug.utils import secure_filename
from mule_ml import predict as mule_predict, METRICS as MULE_METRICS

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, 'trace.db')
UPLOAD_DIR = os.path.join(BASE, 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)
ALLOWED = {'txt','csv','pdf','png','jpg','jpeg','webp','eml'}
app = Flask(__name__); app.secret_key = os.environ.get('TRACE_SECRET','trace-demo-change-me')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

def init_db():
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS cases(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, victim TEXT, category TEXT, incident_date TEXT, loss REAL, transaction_ref TEXT, description TEXT, status TEXT DEFAULT 'Open', created_at TEXT);
        CREATE TABLE IF NOT EXISTS evidence(id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER, filename TEXT, stored TEXT, kind TEXT, extracted TEXT, sha256 TEXT, created_at TEXT, FOREIGN KEY(case_id) REFERENCES cases(id));
        CREATE TABLE IF NOT EXISTS entities(id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER, kind TEXT, value TEXT, norm TEXT, FOREIGN KEY(case_id) REFERENCES cases(id));
        CREATE TABLE IF NOT EXISTS links(id INTEGER PRIMARY KEY AUTOINCREMENT, source_id INTEGER, target_id INTEGER, strength REAL, reason TEXT, status TEXT DEFAULT 'supported', FOREIGN KEY(source_id) REFERENCES cases(id), FOREIGN KEY(target_id) REFERENCES cases(id));
        CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER, body TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS coordination(id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER, unit TEXT, notice_level TEXT, purpose TEXT, status TEXT DEFAULT 'Pending', created_at TEXT);
        CREATE TABLE IF NOT EXISTS transactions(id INTEGER PRIMARY KEY AUTOINCREMENT, txn_ref TEXT, sender TEXT, receiver TEXT, amount REAL, txn_time TEXT, case_id INTEGER);
        ''')
        # Safe additive migrations for the Phase 2 geospatial USP.
        cols={r['name'] for r in c.execute('PRAGMA table_info(cases)').fetchall()}
        for name,typ in [('latitude','REAL'),('longitude','REAL'),('location_source','TEXT'),('accuracy_m','REAL'),('jurisdiction','TEXT')]:
            if name not in cols: c.execute(f'ALTER TABLE cases ADD COLUMN {name} {typ}')



def mule_features(account, txns):
    incoming=[t for t in txns if t['receiver']==account]; outgoing=[t for t in txns if t['sender']==account]
    counterparties={t['sender'] for t in incoming}|{t['receiver'] for t in outgoing}
    incoming_amount=sum(float(t['amount']) for t in incoming); outgoing_amount=sum(float(t['amount']) for t in outgoing)
    times=[]
    for t in txns:
        if t['receiver']==account or t['sender']==account:
            try: times.append(datetime.fromisoformat(t['txn_time']))
            except Exception: pass
    hours=[]
    for a in incoming:
        try:
            tin=datetime.fromisoformat(a['txn_time'])
            later=[datetime.fromisoformat(o['txn_time']) for o in outgoing if o['txn_time'] and datetime.fromisoformat(o['txn_time'])>=tin]
            if later: hours.append((min(later)-tin).total_seconds()/3600)
        except Exception: pass
    rapid=sum(h<=2 for h in hours)/len(hours) if hours else 0
    night=sum(1 for t in txns if (t['sender']==account or t['receiver']==account) and 0<=int(t['txn_time'][11:13])<5)/max(1,len(times))
    return {'incoming_count':len(incoming),'outgoing_count':len(outgoing),'incoming_amount':incoming_amount,'outgoing_amount':outgoing_amount,'counterparty_count':len(counterparties),'median_hold_hours':float(sorted(hours)[len(hours)//2]) if hours else 240,'rapid_outgoing_ratio':rapid,'night_activity_ratio':night,'fan_in_ratio':len(incoming)/max(1,len(counterparties)),'fan_out_ratio':len(outgoing)/max(1,len(counterparties))}

def mule_analysis():
    with db() as c: txns=[dict(r) for r in c.execute('SELECT * FROM transactions').fetchall()]
    accounts=sorted({t['sender'] for t in txns}|{t['receiver'] for t in txns})
    results=[]
    for a in accounts:
        f=mule_features(a,txns); score,importance=mule_predict(f); signals=[]
        if f['incoming_count']>=5: signals.append('High fan-in: multiple incoming transfers')
        if f['outgoing_count']>=5: signals.append('High fan-out: multiple outgoing transfers')
        if f['rapid_outgoing_ratio']>=.5: signals.append('Rapid pass-through: funds forwarded within two hours')
        if f['counterparty_count']>=8: signals.append('Large counterparty network')
        if f['night_activity_ratio']>=.35: signals.append('Elevated overnight activity')
        results.append({'account':a,'score':score,'band':'High' if score>=70 else 'Medium' if score>=40 else 'Low','features':f,'signals':signals or ['No strong synthetic-demo behaviour signal']})
    return sorted(results,key=lambda x:x['score'],reverse=True),len(txns)

def normalize(s): return re.sub(r'\s+','',str(s or '')).lower()
def extract_entities(text):
    patterns={'UPI ID':r'\b[a-zA-Z0-9._-]{2,}@[a-zA-Z]{2,}\b','Phone':r'(?<!\d)(?:\+91[- ]?)?[6-9]\d{9}(?!\d)','Email':r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b','Transaction ID':r'\b(?:UTR|TXN|REF)[- :]?[A-Z0-9]{6,}\b','URL':r'https?://[^\s,)]+','Account-like ID':r'\b\d{9,18}\b'}
    found=[]
    for kind,pat in patterns.items():
        for value in re.findall(pat,text or '',re.I):
            if kind=='Phone': value=re.sub(r'\D','',value)[-10:]
            found.append((kind,value,normalize(value)))
    return list(dict.fromkeys(found))

def score_case(case, entities, all_cases):
    score=15; reasons=[]
    if float(case['loss'] or 0)>=50000: score+=12; reasons.append('Reported loss is above ₹50,000')
    if len(entities)>=3: score+=12; reasons.append('Multiple extractable identifiers appear in the complaint')
    if any(k=='UPI ID' for k,_,_ in entities): score+=10; reasons.append('UPI handle detected')
    if any(k=='URL' for k,_,_ in entities): score+=10; reasons.append('URL present in submitted evidence')
    if any(k=='Phone' for k,_,_ in entities): score+=6; reasons.append('Phone number detected')
    if len([x for x in all_cases if x['id']!=case['id']])>=1 and entities: score+=8; reasons.append('Potential cross-case overlap requires review')
    return min(score,95), reasons

def case_entities(case_id):
    with db() as c: return c.execute('SELECT kind,value,norm FROM entities WHERE case_id=?',(case_id,)).fetchall()

def refresh_links():
    with db() as c:
        prior={(r['source_id'],r['target_id']):r['status'] for r in c.execute('SELECT source_id,target_id,status FROM links').fetchall()}
        c.execute('DELETE FROM links')
        cases=c.execute('SELECT id FROM cases').fetchall()
        rows=c.execute('SELECT case_id,kind,norm,value FROM entities').fetchall()
        by=defaultdict(list)
        for r in rows: by[(r['kind'],r['norm'])].append(r['case_id'])
        pair=defaultdict(list)
        for (kind,norm),ids in by.items():
            ids=sorted(set(ids))
            for i,a in enumerate(ids):
                for b in ids[i+1:]: pair[(a,b)].append(kind)
        for (a,b),kinds in pair.items():
            # Public Wi-Fi / generic business contacts are deliberately not auto-promoted.
            c.execute('INSERT INTO links(source_id,target_id,strength,reason,status) VALUES(?,?,?,?,?)',(a,b,min(.95,.45+.15*len(kinds)), 'Shared '+', '.join(sorted(set(kinds))), prior.get((a,b), 'needs_review')))

def get_dashboard():
    with db() as c:
        cases=c.execute('SELECT * FROM cases ORDER BY id DESC').fetchall()
        evidence=c.execute('SELECT COUNT(*) n FROM evidence').fetchone()['n']
        links=c.execute('SELECT COUNT(*) n FROM links').fetchone()['n']
        total=c.execute('SELECT COALESCE(SUM(loss),0) n FROM cases').fetchone()['n']
        ent=c.execute('SELECT COUNT(*) n FROM entities').fetchone()['n']
        return cases, {'cases':len(cases),'evidence':evidence,'links':links,'loss':total,'entities':ent}

@app.route('/')
def index():
    cases,stats=get_dashboard()
    case_cards=[]
    with db() as c:
        for x in cases:
            ents=c.execute('SELECT COUNT(*) n FROM entities WHERE case_id=?',(x['id'],)).fetchone()['n']
            ev=c.execute('SELECT COUNT(*) n FROM evidence WHERE case_id=?',(x['id'],)).fetchone()['n']
            score,reasons=score_case(x,case_entities(x['id']),cases)
            case_cards.append(dict(x)|{'entity_count':ents,'evidence_count':ev,'score':score,'reasons':reasons})
    return render_template('index.html',cases=case_cards,stats=stats)

@app.route('/cases/new',methods=['GET','POST'])
def new_case():
    if request.method=='POST':
        f=request.form
        try: loss=float(f.get('loss') or 0)
        except ValueError: flash('Loss must be a number.','error'); return redirect(url_for('new_case'))
        with db() as c:
            cur=c.execute('INSERT INTO cases(title,victim,category,incident_date,loss,transaction_ref,description,created_at,latitude,longitude,location_source,accuracy_m,jurisdiction) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(f.get('title','Untitled incident'),f.get('victim',''),f.get('category','Other'),f.get('incident_date',''),loss,f.get('transaction_ref',''),f.get('description',''),datetime.now().isoformat(timespec='seconds'),float(f['latitude']) if f.get('latitude') else None,float(f['longitude']) if f.get('longitude') else None,f.get('location_source','Not supplied'),float(f['accuracy_m']) if f.get('accuracy_m') else None,f.get('jurisdiction','Unassigned')))
            cid=cur.lastrowid
            for item in extract_entities(' '.join([f.get('victim',''),f.get('transaction_ref',''),f.get('description','')])): c.execute('INSERT INTO entities(case_id,kind,value,norm) VALUES(?,?,?,?)',(cid,*item))
        refresh_links(); flash('Case registered.','success'); return redirect(url_for('case_detail',case_id=cid))
    return render_template('case_form.html')

@app.route('/cases/<int:case_id>')
def case_detail(case_id):
    with db() as c:
        case=c.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
        if not case: return 'Case not found',404
        evidence=c.execute('SELECT * FROM evidence WHERE case_id=? ORDER BY id DESC',(case_id,)).fetchall()
        entities=c.execute('SELECT * FROM entities WHERE case_id=?',(case_id,)).fetchall()
        notes=c.execute('SELECT * FROM notes WHERE case_id=? ORDER BY id DESC',(case_id,)).fetchall()
        links=c.execute('''SELECT l.*, a.title a_title, b.title b_title FROM links l JOIN cases a ON a.id=l.source_id JOIN cases b ON b.id=l.target_id WHERE source_id=? OR target_id=?''',(case_id,case_id)).fetchall()
        cases=c.execute('SELECT * FROM cases').fetchall()
    score,reasons=score_case(case,entities,cases)
    return render_template('case_detail.html',case=case,evidence=evidence,entities=entities,notes=notes,links=links,score=score,reasons=reasons)

@app.route('/cases/<int:case_id>/upload',methods=['POST'])
def upload(case_id):
    file=request.files.get('file'); text_input=request.form.get('evidence_text','')
    if not file and not text_input.strip(): flash('Choose a file or paste evidence text.','error'); return redirect(url_for('case_detail',case_id=case_id))
    filename='Pasted evidence.txt'; stored=''; raw=text_input.encode('utf-8'); extracted=text_input
    if file and file.filename:
        filename=secure_filename(file.filename); ext=filename.rsplit('.',1)[-1].lower() if '.' in filename else ''
        if ext not in ALLOWED: flash('Unsupported file type.','error'); return redirect(url_for('case_detail',case_id=case_id))
        raw=file.read(); stored=f'{datetime.now().strftime("%Y%m%d%H%M%S%f")}_{filename}'
        open(os.path.join(UPLOAD_DIR,stored),'wb').write(raw)
        extracted=raw.decode('utf-8',errors='ignore') if ext in {'txt','csv','eml'} else ''
        if ext in {'pdf','png','jpg','jpeg','webp'}: extracted='File stored. OCR is an optional local integration; add extracted text in the evidence text box for this demo.'
    digest=hashlib.sha256(raw).hexdigest()
    with db() as c:
        c.execute('INSERT INTO evidence(case_id,filename,stored,kind,extracted,sha256,created_at) VALUES(?,?,?,?,?,?,?)',(case_id,filename,stored,'file' if stored else 'text',extracted,digest,datetime.now().isoformat(timespec='seconds')))
        for item in extract_entities(extracted): c.execute('INSERT INTO entities(case_id,kind,value,norm) VALUES(?,?,?,?)',(case_id,*item))
    refresh_links(); flash('Evidence saved and identifiers extracted where supported.','success'); return redirect(url_for('case_detail',case_id=case_id))

@app.route('/cases/<int:case_id>/note',methods=['POST'])
def add_note(case_id):
    body=request.form.get('body','').strip()
    if body:
        with db() as c: c.execute('INSERT INTO notes(case_id,body,created_at) VALUES(?,?,?)',(case_id,body,datetime.now().isoformat(timespec='seconds')))
    return redirect(url_for('case_detail',case_id=case_id))

@app.route('/network')
def network():
    with db() as c:
        cases=c.execute('SELECT id,title FROM cases').fetchall(); links=c.execute('SELECT * FROM links').fetchall()
        nodes=[]
        for x in cases:
            es=c.execute('SELECT kind,value FROM entities WHERE case_id=?',(x['id'],)).fetchall(); nodes.append({'id':x['id'],'label':f"C{x['id']} · {x['title'][:22]}",'entities':[dict(e) for e in es]})
    return render_template('network.html',nodes=nodes,links=[dict(x) for x in links])

@app.route('/reports')
def reports():
    cases,stats=get_dashboard()
    with db() as c: rows=c.execute('SELECT * FROM links ORDER BY strength DESC').fetchall()
    return render_template('reports.html',cases=cases,stats=stats,links=rows)

@app.route('/reports/export')
def export_report():
    with db() as c:
        cases=[dict(x) for x in c.execute('SELECT * FROM cases ORDER BY id')]
        links=[dict(x) for x in c.execute('SELECT * FROM links')]
        evidence=[dict(x) for x in c.execute('SELECT id,case_id,filename,sha256,created_at FROM evidence')]
        entities=[dict(x) for x in c.execute('SELECT case_id,kind,value FROM entities')]
    path=os.path.join(BASE,'trace_investigation_report.json')
    with open(path,'w',encoding='utf-8') as f: json.dump({'generated_at':datetime.now().isoformat(),'notice':'Decision-support demo; not proof of wrongdoing. Human review required.','cases':cases,'evidence':evidence,'entities':entities,'links':links},f,indent=2,ensure_ascii=False)
    return send_file(path,as_attachment=True)

@app.route('/api/search')
def api_search():
    q=request.args.get('q','').lower()
    with db() as c: rows=c.execute('SELECT id,title,victim,category,description FROM cases WHERE lower(title||" "||victim||" "||category||" "||description) LIKE ?',('%'+q+'%',)).fetchall()
    return jsonify([dict(x) for x in rows])

@app.route('/api/copilot',methods=['POST'])
def copilot():
    q=(request.json or {}).get('question','').lower()
    cases,stats=get_dashboard()
    if 'link' in q or 'connect' in q: answer=f"TRACE currently has {stats['links']} candidate cross-case links. Open the Fraud Network Graph and review each shared identifier before drawing conclusions."
    elif 'risk' in q or 'score' in q: answer='Risk scores are transparent heuristic triage signals based on reported loss and detected identifiers. They are not probabilities or findings of guilt.'
    elif 'evidence' in q: answer=f"There are {stats['evidence']} evidence items across {stats['cases']} cases. Each stored file has a SHA-256 hash for integrity tracking."
    else: answer=f"TRACE has {stats['cases']} registered cases, {stats['entities']} extracted identifiers and {stats['links']} candidate links. Try asking about links, evidence or risk scoring. This local copilot does not invent investigative facts."
    return jsonify({'answer':answer})


@app.route('/mule')
def mule_dashboard():
    results,n=mule_analysis()
    return render_template('mule.html',results=results,txn_count=n,metrics=MULE_METRICS)

@app.route('/mule/demo',methods=['POST'])
def mule_demo():
    now=datetime.now().replace(minute=0,second=0,microsecond=0)
    demo=[]
    # Synthetic pass-through account MULE-001: many senders, rapid onward transfers.
    for i in range(9):
        demo.append((f'DEMO-IN-{i}','SRC-'+str(i),'MULE-001',float(12000+i*1700),(now.replace(hour=9)+__import__('datetime').timedelta(minutes=i*4)).isoformat(),None))
    for i in range(8):
        demo.append((f'DEMO-OUT-{i}','MULE-001','DST-'+str(i),float(11000+i*1500),(now.replace(hour=10)+__import__('datetime').timedelta(minutes=i*5)).isoformat(),None))
    # Ordinary account has sparse, slower activity.
    demo += [('DEMO-LEG-1','EMPLOYER-1','NORMAL-001',52000,(now.replace(day=max(1,now.day-1),hour=12)).isoformat(),None),('DEMO-LEG-2','NORMAL-001','RENT-001',18000,(now.replace(hour=18)).isoformat(),None)]
    with db() as c:
        c.execute('DELETE FROM transactions')
        c.executemany('INSERT INTO transactions(txn_ref,sender,receiver,amount,txn_time,case_id) VALUES(?,?,?,?,?,?)',demo)
    flash('Synthetic transaction network loaded. These are fictional records for demonstration.','success')
    return redirect(url_for('mule_dashboard'))

@app.route('/mule/transactions',methods=['POST'])
def add_mule_transaction():
    f=request.form
    try: amount=float(f.get('amount','0')); dt=datetime.fromisoformat(f.get('txn_time',''))
    except Exception: flash('Enter a valid amount and ISO date/time.','error'); return redirect(url_for('mule_dashboard'))
    if amount<=0 or not f.get('sender') or not f.get('receiver'): flash('Sender, receiver and positive amount are required.','error'); return redirect(url_for('mule_dashboard'))
    with db() as c: c.execute('INSERT INTO transactions(txn_ref,sender,receiver,amount,txn_time) VALUES(?,?,?,?,?)',(f.get('txn_ref','MANUAL'),f['sender'].strip(),f['receiver'].strip(),amount,dt.isoformat()))
    flash('Transaction added. Mule-risk analysis refreshed.','success'); return redirect(url_for('mule_dashboard'))

@app.route('/geospatial')
def geospatial():
    with db() as c:
        cases=c.execute("SELECT * FROM cases WHERE latitude IS NOT NULL AND longitude IS NOT NULL ORDER BY id DESC").fetchall()
        requests=c.execute('SELECT * FROM coordination ORDER BY id DESC').fetchall()
    return render_template('geospatial.html',cases=cases,requests=requests)

@app.route('/coordination',methods=['POST'])
def coordination_request():
    f=request.form
    with db() as c:
        c.execute('INSERT INTO coordination(case_id,unit,notice_level,purpose,created_at) VALUES(?,?,?,?,?)',(int(f['case_id']),f.get('unit',''),f.get('notice_level','Hit notice'),f.get('purpose',''),datetime.now().isoformat(timespec='seconds')))
    flash('Coordination request logged for human approval. No agency data was transmitted.','success')
    return redirect(url_for('geospatial'))

@app.route('/coordination/<int:req_id>/<action>',methods=['POST'])
def coordination_action(req_id,action):
    status={'approve':'Approved for authorized follow-up','acknowledge':'Acknowledged','reject':'Declined'}.get(action)
    if not status: return 'Invalid action',400
    with db() as c: c.execute('UPDATE coordination SET status=? WHERE id=?',(status,req_id))
    flash('Coordination status updated. This local demo does not send external notices.','success')
    return redirect(url_for('geospatial'))

@app.route('/links/<int:link_id>/review',methods=['POST'])
def review_link(link_id):
    status=request.form.get('status')
    if status not in {'supported','unverified_association','dismissed'}: return 'Invalid review status',400
    with db() as c: c.execute('UPDATE links SET status=? WHERE id=?',(status,link_id))
    flash('Link review decision saved to the local audit trail.','success')
    return redirect(request.referrer or url_for('network'))

@app.route('/demo/reset',methods=['POST'])
def reset_demo():
    with db() as c:
        c.execute('DELETE FROM notes'); c.execute('DELETE FROM links'); c.execute('DELETE FROM entities'); c.execute('DELETE FROM evidence'); c.execute('DELETE FROM cases')
        samples=[('UPI collect request scam','Aarav Mehta','UPI Fraud','2026-11-18',18500,'TXN-AB7821','Caller shared payment link https://pay-secure.example/collect and asked to approve collect request. Contact: 9876543210. UPI: helpdesk@upi.'),('Fake customer support','Nisha Rao','Impersonation','2026-11-19',42000,'UTR ZX9012AB','Search result led to fake support page https://pay-secure.example/collect. Caller used 9876543210 and UPI helpdesk@upi.'),('Investment group fraud','Kabir Shah','Investment Fraud','2026-11-20',75000,'REF-INV88291','Telegram group promised returns. Payment sent to invest.fast@upi. Phone 9123456780.')]
        for s in samples:
            cur=c.execute('INSERT INTO cases(title,victim,category,incident_date,loss,transaction_ref,description,created_at) VALUES(?,?,?,?,?,?,?,?)',(*s,datetime.now().isoformat(timespec='seconds')))
            for item in extract_entities(' '.join([s[5],s[6]])): c.execute('INSERT INTO entities(case_id,kind,value,norm) VALUES(?,?,?,?)',(cur.lastrowid,*item))
    refresh_links(); flash('Demo dataset loaded.','success'); return redirect(url_for('index'))

if __name__=='__main__':
    init_db(); app.run(debug=True,port=5000)
else: init_db()
