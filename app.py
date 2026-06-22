import re
import secrets
import hashlib
import requests
import asyncio
import json
import sqlite3
import io
import os
import tempfile
from datetime import datetime, timedelta
from functools import wraps
from decimal import Decimal

from flask import Flask, request, redirect, url_for, session, flash, jsonify, g, get_flashed_messages, send_file
import psycopg2
import psycopg2.extras

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError

DATABASE_URL = "postgresql://bothost_db_3092f9da4312:yvzBra5xN_j2a_dafFbpHStZAVH7HiMuzJ2iCwDX-5w@node1.pghost.ru:15796/bothost_db_3092f9da4312"
API_ID = 32480523
API_HASH = "147839735c9fa4e83451209e9b55cfc5"
SECRET_KEY = secrets.token_hex(32)
COMMISSION = Decimal('0.05')
CRYPTO_TOKEN = "499354:AATdkiDyuC1tWd1ro5S5wFw6XcePNUNH5Ph"

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

COUNTRIES = ["Россия","США","Германия","Франция","Италия","Испания","Украина","Беларусь","Казахстан","Турция","Китай","Япония","Южная Корея","Индия","Бразилия","Мексика","Канада","Австралия","Аргентина","Чили","Великобритания","Нидерланды","Бельгия","Швейцария","Австрия","Польша","Чехия","Швеция","Норвегия","Дания","Финляндия","Португалия","Греция","Венгрия","Румыния","Болгария","Сербия","Хорватия","Словакия","Ирландия"]
ORIGINS = ["Авторег","Саморег","Стиллер","Фишинг"]

def detect_country_by_phone(phone):
    phone = re.sub(r'\D','',phone)
    prefixes = {'79':'Россия','73':'Россия','74':'Россия','75':'Россия','77':'Казахстан','380':'Украина','375':'Беларусь','1':'США','44':'Великобритания','49':'Германия','33':'Франция','39':'Италия','34':'Испания','90':'Турция','86':'Китай','48':'Польша'}
    for pref in sorted(prefixes.keys(),key=len,reverse=True):
        if phone.startswith(pref): return prefixes[pref]
    return "Интернациональный"

def hash_password(password):
    salt = secrets.token_hex(16)
    return f"{salt}${hashlib.sha256((password+salt).encode()).hexdigest()}"

def verify_password(password,hashed):
    try:
        salt,h = hashed.split('$')
        return hashlib.sha256((password+salt).encode()).hexdigest() == h
    except: return False

def get_db():
    if 'db' not in g:
        g.db = psycopg2.connect(DATABASE_URL)
        g.db.autocommit = True
    return g.db

@app.teardown_appcontext
def close_db(error):
    db = g.pop('db',None)
    if db is not None: db.close()

def init_db():
    db = psycopg2.connect(DATABASE_URL)
    db.autocommit = True
    with db.cursor() as cur:
        cur.execute("CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY,username VARCHAR(100) UNIQUE NOT NULL,password_hash VARCHAR(255) NOT NULL,balance DECIMAL(10,2) DEFAULT 0.00,is_admin BOOLEAN DEFAULT FALSE,sales_count INTEGER DEFAULT 0,created_at TIMESTAMP DEFAULT NOW())")
        cur.execute("CREATE TABLE IF NOT EXISTS accounts (id SERIAL PRIMARY KEY,seller_id INTEGER REFERENCES users(id),title VARCHAR(200) NOT NULL,origin VARCHAR(100),description TEXT,price DECIMAL(10,2) NOT NULL,session_string TEXT NOT NULL,country VARCHAR(50),has_2fa BOOLEAN DEFAULT FALSE,spamblock BOOLEAN DEFAULT FALSE,is_premium BOOLEAN DEFAULT FALSE,chats_count INTEGER DEFAULT 0,channels_count INTEGER DEFAULT 0,groups_count INTEGER DEFAULT 0,is_sold BOOLEAN DEFAULT FALSE,created_at TIMESTAMP DEFAULT NOW())")
        cur.execute("CREATE TABLE IF NOT EXISTS purchases (id SERIAL PRIMARY KEY,buyer_id INTEGER REFERENCES users(id),account_id INTEGER REFERENCES accounts(id),phone_number VARCHAR(20),purchase_date TIMESTAMP DEFAULT NOW(),code_retrieved BOOLEAN DEFAULT FALSE)")
        cur.execute("CREATE TABLE IF NOT EXISTS balance_history (id SERIAL PRIMARY KEY,user_id INTEGER REFERENCES users(id),amount DECIMAL(10,2),type VARCHAR(50),description TEXT,created_at TIMESTAMP DEFAULT NOW())")
        cur.execute("CREATE TABLE IF NOT EXISTS withdrawals (id SERIAL PRIMARY KEY,user_id INTEGER REFERENCES users(id),amount_rub DECIMAL(10,2),amount_usdt DECIMAL(10,6),address VARCHAR(200),status VARCHAR(20) DEFAULT 'pending',created_at TIMESTAMP DEFAULT NOW())")
        cur.execute("CREATE TABLE IF NOT EXISTS crypto_invoices (id SERIAL PRIMARY KEY,user_id INTEGER REFERENCES users(id),invoice_id VARCHAR(100),amount_rub DECIMAL(10,2),status VARCHAR(20) DEFAULT 'pending',created_at TIMESTAMP DEFAULT NOW())")
        cur.execute("CREATE TABLE IF NOT EXISTS reviews (id SERIAL PRIMARY KEY,buyer_id INTEGER REFERENCES users(id),seller_id INTEGER REFERENCES users(id),account_id INTEGER REFERENCES accounts(id),rating INTEGER DEFAULT 5,text TEXT,created_at TIMESTAMP DEFAULT NOW())")
        try: cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS sales_count INTEGER DEFAULT 0")
        except: pass
        try: cur.execute("ALTER TABLE crypto_invoices ADD COLUMN IF NOT EXISTS pay_url TEXT")
        except: pass
        try: cur.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS is_premium BOOLEAN DEFAULT FALSE")
        except: pass
        try: cur.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS chats_count INTEGER DEFAULT 0")
        except: pass
        try: cur.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS channels_count INTEGER DEFAULT 0")
        except: pass
        try: cur.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS groups_count INTEGER DEFAULT 0")
        except: pass
        try: cur.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS spamblock BOOLEAN DEFAULT FALSE")
        except: pass
        try: cur.execute("ALTER TABLE purchases ADD COLUMN IF NOT EXISTS phone_number VARCHAR(20)")
        except: pass
        try: cur.execute("ALTER TABLE purchases ADD COLUMN IF NOT EXISTS code_retrieved BOOLEAN DEFAULT FALSE")
        except: pass
        cur.execute("SELECT COUNT(*) FROM users WHERE username=%s",("vest",))
        if cur.fetchone()[0]==0: cur.execute("INSERT INTO users (username,password_hash,is_admin,balance) VALUES (%s,%s,TRUE,999999)",("vest",hash_password("55337q")))
    db.close()

init_db()

def get_seller_rating(seller_id):
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT rating FROM reviews WHERE seller_id=%s",(seller_id,))
            ratings = [r['rating'] for r in cur.fetchall()]
            if not ratings: return None,0
            return f"{sum(ratings)/len(ratings):.1f}",len(ratings)
    except: return None,0

def login_required(f):
    @wraps(f)
    def decorated(*args,**kwargs):
        if 'user_id' not in session: return redirect(url_for('login'))
        return f(*args,**kwargs)
    return decorated

@app.before_request
def load_user():
    g.user = None
    if 'user_id' in session:
        try:
            db = get_db()
            with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("SELECT * FROM users WHERE id=%s",(session['user_id'],))
                g.user = cur.fetchone()
        except: pass

def flash_msgs():
    return ''.join([f'<div class="flash {c}">{m}</div>' for c,m in get_flashed_messages(with_categories=True)])

STYLE = '''<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:#0a0a0f;color:#e0e0e0;min-height:100vh;display:flex;flex-direction:column}
::-webkit-scrollbar{width:4px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.1);border-radius:4px}

.nav{background:rgba(10,10,15,0.9);border-bottom:1px solid rgba(255,255,255,0.05);padding:14px 20px;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:100;backdrop-filter:blur(10px)}
.logo{font-size:20px;font-weight:800;text-decoration:none;background:linear-gradient(135deg,#6366f1,#8b5cf6);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.nav-links{display:flex;gap:12px;align-items:center}
.nav-links a{color:#888;text-decoration:none;font-size:13px;font-weight:500;padding:8px 14px;border-radius:8px;transition:0.2s}
.nav-links a:hover{color:#fff;background:rgba(255,255,255,0.03)}
.balance{background:rgba(99,102,241,0.1);color:#a5b4fc;padding:6px 14px;border-radius:20px;font-size:13px;font-weight:600}

.main{flex:1;max-width:900px;margin:0 auto;padding:20px;width:100%}

.flash{padding:12px 16px;border-radius:10px;margin-bottom:12px;font-size:13px;font-weight:500}
.flash.success{background:rgba(16,185,129,0.1);color:#34d399;border:1px solid rgba(16,185,129,0.2)}
.flash.error{background:rgba(239,68,68,0.1);color:#fca5a5;border:1px solid rgba(239,68,68,0.2)}
.flash.info{background:rgba(99,102,241,0.1);color:#a5b4fc;border:1px solid rgba(99,102,241,0.2)}

.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px}
.card{background:#12121a;border:1px solid rgba(255,255,255,0.04);border-radius:14px;padding:16px;transition:0.2s}
.card:hover{border-color:rgba(99,102,241,0.2)}
.card-title{font-size:15px;font-weight:600;color:#fff;text-decoration:none;display:block;margin-bottom:10px}
.card-title:hover{color:#a5b4fc}
.tags{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}
.tag{padding:3px 8px;border-radius:6px;font-size:11px;font-weight:500;background:rgba(255,255,255,0.03);color:#888}
.tag.green{background:rgba(16,185,129,0.1);color:#34d399}
.tag.red{background:rgba(239,68,68,0.1);color:#fca5a5}
.tag.purple{background:rgba(139,92,246,0.1);color:#a78bfa}
.card-footer{display:flex;justify-content:space-between;align-items:center;padding-top:10px;border-top:1px solid rgba(255,255,255,0.04);margin-top:10px}
.price{color:#ffb703;font-weight:700;font-size:15px}
.seller{color:#666;font-size:12px}
.seller strong{color:#999}

.btn{padding:10px 18px;border:none;border-radius:10px;cursor:pointer;font-size:13px;font-weight:600;text-decoration:none;display:inline-flex;align-items:center;justify-content:center;gap:6px;transition:0.2s}
.btn-primary{background:#6366f1;color:#fff}
.btn-primary:hover{background:#5558e6}
.btn-secondary{background:rgba(255,255,255,0.03);color:#ccc;border:1px solid rgba(255,255,255,0.06)}
.btn-secondary:hover{background:rgba(255,255,255,0.06)}
.btn-success{background:#10b981;color:#fff}
.btn-danger{background:rgba(239,68,68,0.15);color:#fca5a5}
.btn-sm{padding:6px 12px;font-size:12px;border-radius:8px}

input,textarea,select{width:100%;padding:12px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:10px;color:#e0e0e0;font-size:13px;outline:none;margin-bottom:12px}
input:focus,textarea:focus,select:focus{border-color:rgba(99,102,241,0.3)}

.auth-page{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
.auth-box{background:#12121a;border:1px solid rgba(255,255,255,0.06);border-radius:20px;padding:36px;width:100%;max-width:380px}
.auth-box h2{font-size:24px;font-weight:700;color:#fff;margin-bottom:8px}
.auth-box p{color:#666;font-size:13px;margin-bottom:24px}

.profile-header{display:flex;align-items:center;gap:16px;margin-bottom:24px}
.avatar{width:56px;height:56px;background:linear-gradient(135deg,#6366f1,#8b5cf6);border-radius:16px;display:flex;align-items:center;justify-content:center;font-size:24px;font-weight:700;color:#fff}
.profile-info h2{font-size:20px;color:#fff}
.profile-info .bal{color:#34d399;font-size:18px;font-weight:700}

.profile-actions{display:flex;flex-direction:column;gap:8px;margin-bottom:24px}
.profile-actions .btn{width:100%;padding:14px;font-size:14px}

.section{background:#12121a;border:1px solid rgba(255,255,255,0.04);border-radius:14px;padding:20px;margin-bottom:16px}
.section h3{font-size:15px;color:#fff;margin-bottom:14px}

.acc-item{display:flex;justify-content:space-between;align-items:center;padding:12px;background:rgba(255,255,255,0.01);border-radius:10px;margin-bottom:8px}
.acc-item .title{font-weight:600;color:#fff}
.acc-item .meta{color:#666;font-size:12px}

.modal{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.7);z-index:200;display:none;align-items:center;justify-content:center}
.modal.show{display:flex}
.modal-content{background:#12121a;border:1px solid rgba(255,255,255,0.06);border-radius:18px;padding:28px;width:90%;max-width:440px;max-height:80vh;overflow-y:auto}

.footer{padding:24px;text-align:center;color:#444;font-size:12px;border-top:1px solid rgba(255,255,255,0.03)}
.footer a{color:#666;text-decoration:none}
.footer a:hover{color:#888}

.sort-bar{display:flex;gap:6px;margin-bottom:16px;flex-wrap:wrap}
.sort-bar a{padding:6px 12px;border-radius:8px;font-size:12px;color:#888;text-decoration:none;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.04)}
.sort-bar a.active{background:rgba(99,102,241,0.1);color:#a5b4fc;border-color:rgba(99,102,241,0.2)}

.filter-wrap{background:#12121a;border:1px solid rgba(255,255,255,0.04);border-radius:14px;padding:16px;margin-bottom:20px}
.filter-toggle{color:#888;font-size:13px;font-weight:500;cursor:pointer;display:flex;justify-content:space-between;align-items:center}
.filter-body{display:none;margin-top:14px}
.filter-body.show{display:block}

.specs{display:flex;flex-direction:column;gap:4px;margin:14px 0}
.spec{display:flex;justify-content:space-between;padding:8px 10px;background:rgba(255,255,255,0.01);border-radius:8px;font-size:13px}
.spec .lbl{color:#666}
.spec .val{color:#ccc;font-weight:500}
</style>'''

SCRIPT = '''<script>
document.addEventListener('click',function(e){
var t=e.target.closest('.filter-toggle');if(t){t.nextElementSibling.classList.toggle('show');return}
var m=e.target.closest('[data-modal]');if(m){document.getElementById(m.dataset.modal).classList.add('show');return}
var c=e.target.closest('.modal-close');if(c){c.closest('.modal').classList.remove('show');return}
if(e.target.classList.contains('modal')){e.target.classList.remove('show');return}
var d=e.target.closest('.btn-delete');if(d){if(confirm('Удалить?')){window.location.href='/delete/'+d.dataset.id};return}
var v=e.target.closest('.btn-valid');if(v){e.preventDefault();var id=v.dataset.id;v.disabled=true;v.textContent='...';fetch('/check_valid/'+id).then(r=>r.json()).then(d=>{if(d.valid){v.className='btn btn-success btn-sm';v.textContent='Валид'}else{v.className='btn btn-danger btn-sm';v.textContent='Невалид'}});return}
var g=e.target.closest('.btn-code');if(g){e.preventDefault();var pid=g.dataset.id;g.disabled=true;g.textContent='...';fetch('/get_code/'+pid).then(r=>r.json()).then(d=>{if(d.code){document.getElementById('code-'+pid).innerHTML='<code style="color:#34d399;">'+d.code+'</code>';g.style.display='none'}else{alert(d.error||'Ошибка');g.disabled=false;g.textContent='Код'}});return}
});
</script>'''

def render(title,content,nav=True):
    n = navbar() if nav else '<div class="nav"><a href="/" class="logo">Vest</a></div>'
    return f'<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>{STYLE}</head><body>{n}<div class="main">{flash_msgs()}{content}</div>{SCRIPT}</body></html>'

def footer():
    return '<div class="footer"><span>© 2026 Vest Accs</span> · <a href="https://t.me/VestAccsSupport">Поддержка</a></div>'

def navbar():
    if g.user:
        al = '<a href="/admin">Админ</a>' if g.user.get("is_admin") else ''
        return f'<div class="nav"><a href="/" class="logo">Vest</a><div class="nav-links"><span class="balance">{g.user["balance"]:.0f} ₽</span><a href="/deposit">+</a><a href="/profile">Профиль</a><a href="/purchases">Покупки</a>{al}</div></div>'
    return '<div class="nav"><a href="/" class="logo">Vest</a><div class="nav-links"><a href="/login">Вход</a><a href="/register">Регистрация</a></div></div>'

def quick_connect(ss):
    try:
        client = TelegramClient(StringSession(ss),API_ID,API_HASH)
        client.connect()
        return client
    except: return None

def extract_phone(ss):
    client = quick_connect(ss)
    if not client: return "Скрыт"
    try:
        if client.is_user_authorized():
            me = client.get_me()
            return me.phone or "Скрыт"
    except: pass
    finally:
        try: client.disconnect()
        except: pass
    return "Скрыт"

def extract_code(ss):
    client = quick_connect(ss)
    if not client: return None
    try:
        if not client.is_user_authorized(): return None
        for d in client.get_dialogs(limit=5):
            try:
                for m in client.get_messages(d,limit=5):
                    if m.message:
                        codes = re.findall(r'\b\d{5}\b',m.message)
                        if codes: return codes[-1]
            except: continue
    finally:
        try: client.disconnect()
        except: pass
    return None

def gather_data(ss):
    data = {'has_2fa':False,'spamblock':False,'is_premium':False,'chats':0,'channels':0,'groups':0}
    client = quick_connect(ss)
    if not client: return data
    try:
        if not client.is_user_authorized(): return data
        try: client.get_password_hint(); data['has_2fa']=True
        except: pass
        try: data['is_premium']=getattr(client.get_me(),'premium',False)
        except: pass
        try:
            for d in client.get_dialogs(limit=50):
                if d.is_channel:
                    if hasattr(d.entity,'megagroup') and d.entity.megagroup: data['groups']+=1
                    else: data['channels']+=1
                else: data['chats']+=1
        except: pass
    finally:
        try: client.disconnect()
        except: pass
    return data

def send_code(phone):
    try:
        client = TelegramClient(StringSession(),API_ID,API_HASH)
        client.connect()
        result = client.send_code_request(phone)
        return result.phone_code_hash,client.session.save(),None
    except Exception as e: return None,None,str(e)
    finally:
        try: client.disconnect()
        except: pass

@app.route('/check_valid/<int:aid>')
def check_valid(aid):
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT session_string FROM accounts WHERE id=%s",(aid,))
            a = cur.fetchone()
        if not a: return jsonify({'valid':False})
        c = quick_connect(a['session_string'])
        v = c and c.is_user_authorized()
        if c:
            try: c.disconnect()
            except: pass
        return jsonify({'valid':v})
    except: return jsonify({'valid':False})

@app.route('/get_code/<int:pid>')
@login_required
def get_code(pid):
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT a.session_string FROM purchases p JOIN accounts a ON p.account_id=a.id WHERE p.id=%s AND p.buyer_id=%s",(pid,g.user['id']))
            p = cur.fetchone()
        if not p: return jsonify({'error':'Не найдено'})
        code = extract_code(p['session_string'])
        if code:
            with db.cursor() as cur: cur.execute("UPDATE purchases SET code_retrieved=TRUE WHERE id=%s",(pid,))
            return jsonify({'code':code})
        return jsonify({'error':'Код не найден'})
    except Exception as e: return jsonify({'error':str(e)})

@app.route('/delete/<int:aid>')
@login_required
def delete_account(aid):
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT * FROM accounts WHERE id=%s AND seller_id=%s AND is_sold=FALSE",(aid,g.user['id']))
        if not cur.fetchone(): flash('Не найдено','error'); return redirect('/profile')
        cur.execute("DELETE FROM accounts WHERE id=%s",(aid,))
    flash('Удалено','success')
    return redirect('/profile')

@app.route('/admin/withdrawals',methods=['POST'])
@login_required
def process_withdrawal():
    if not g.user.get('is_admin'): return redirect('/')
    wid = request.form.get('withdrawal_id',type=int)
    action = request.form.get('action')
    db = get_db()
    with db.cursor() as cur:
        if action=='complete': cur.execute("UPDATE withdrawals SET status='completed' WHERE id=%s",(wid,))
        elif action=='reject':
            cur.execute("SELECT * FROM withdrawals WHERE id=%s",(wid,))
            w = cur.fetchone()
            if w:
                cur.execute("UPDATE users SET balance=balance+%s WHERE id=%s",(w[2],w[1]))
                cur.execute("INSERT INTO balance_history (user_id,amount,type,description) VALUES (%s,%s,%s,%s)",(w[1],w[2],'refund','Возврат'))
                cur.execute("UPDATE withdrawals SET status='rejected' WHERE id=%s",(wid,))
    return redirect('/admin')

def render_cards(accounts):
    cards = ''
    for a in accounts:
        rs,_ = get_seller_rating(a['seller_id'])
        rh = f'<span style="color:#fbbf24;font-size:11px;">★{rs}</span>' if rs else ''
        oc = "green" if a["origin"] in ["Авторег","Саморег"] else ""
        sc = "green" if not a["spamblock"] else "red"
        pc = "purple" if a["is_premium"] else ""
        cards += f'''<div class="card">
        <a href="/account/{a["id"]}" class="card-title">{a["title"]}</a>
        <div class="tags">
            <span class="tag">{a["country"] or "Интер"}</span>
            <span class="tag {oc}">{a["origin"] or "Лог"}</span>
            <span class="tag">{"2FA" if a["has_2fa"] else "Без 2FA"}</span>
            <span class="tag {sc}">{"Спамблок" if a["spamblock"] else "Чистый"}</span>
            <span class="tag {pc}">{"Premium" if a["is_premium"] else "Обычный"}</span>
        </div>
        <div class="card-footer">
            <div class="seller"><strong>{a["seller_name"]}</strong> {rh}</div>
            <div><span class="price">{a["price"]:.0f} ₽</span> <a href="/account/{a["id"]}" class="btn btn-primary btn-sm">Купить</a></div>
        </div></div>'''
    return cards

@app.route('/')
def index():
    page = request.args.get('page',1,type=int)
    sort = request.args.get('sort','newest')
    offset = (page-1)*20
    ob = "a.created_at DESC"
    if sort=='price_asc': ob="a.price ASC"
    elif sort=='price_desc': ob="a.price DESC"
    elif sort=='oldest': ob="a.created_at ASC"
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT COUNT(*) as cnt FROM accounts WHERE is_sold=FALSE")
        total = cur.fetchone()['cnt']
        cur.execute(f"SELECT a.*,u.username as seller_name FROM accounts a JOIN users u ON a.seller_id=u.id WHERE a.is_sold=FALSE ORDER BY {ob} LIMIT 20 OFFSET %s",(offset,))
        accounts = cur.fetchall()
    cards = render_cards(accounts) or '<div style="text-align:center;padding:40px;color:#666;">Нет аккаунтов</div>'
    sb = f'<div class="sort-bar"><a href="/?sort=newest" class="{"active" if sort=="newest" else ""}">Новые</a><a href="/?sort=price_asc" class="{"active" if sort=="price_asc" else ""}">Дешевле</a><a href="/?sort=price_desc" class="{"active" if sort=="price_desc" else ""}">Дороже</a></div>'
    filter_html = f'''<div class="filter-wrap"><div class="filter-toggle">Фильтры <span>▼</span></div><div class="filter-body"><form action="/filter"><input type="text" name="q" placeholder="Поиск..."><input type="hidden" name="sort" value="{sort}"><button class="btn btn-primary" style="width:100%;">Найти</button></form></div></div>'''
    return render("Vest Accs",f'{filter_html}{sb}<div class="grid">{cards}</div>{footer()}')

@app.route('/register',methods=['GET','POST'])
def register():
    if request.method=='POST':
        u = request.form.get('username','').strip()
        p = request.form.get('password','').strip()
        if not u or not p: flash('Заполните поля','error')
        else:
            try:
                db = get_db()
                with db.cursor() as cur: cur.execute("INSERT INTO users (username,password_hash) VALUES (%s,%s)",(u,hash_password(p)))
                flash('Успешно','success'); return redirect('/login')
            except: flash('Пользователь существует','error')
    return render("Регистрация",f'<div class="auth-page"><div class="auth-box"><h2>Регистрация</h2><p>Создайте аккаунт</p><form method="POST"><input type="text" name="username" placeholder="Логин" required><input type="password" name="password" placeholder="Пароль" required><button class="btn btn-primary" style="width:100%;padding:12px;">Создать</button></form><p style="text-align:center;margin-top:16px;color:#666;">Есть аккаунт? <a href="/login" style="color:#818cf8;">Войти</a></p></div></div>{footer()}',False)

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        u = request.form.get('username','').strip()
        p = request.form.get('password','').strip()
        try:
            db = get_db()
            with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("SELECT * FROM users WHERE username=%s",(u,))
                user = cur.fetchone()
                if user and verify_password(p,user['password_hash']): session['user_id']=user['id']; session.permanent=True; return redirect('/')
            flash('Неверные данные','error')
        except Exception as e: flash(str(e),'error')
    return render("Вход",f'<div class="auth-page"><div class="auth-box"><h2>Вход</h2><p>Добро пожаловать</p><form method="POST"><input type="text" name="username" placeholder="Логин" required><input type="password" name="password" placeholder="Пароль" required><button class="btn btn-primary" style="width:100%;padding:12px;">Войти</button></form><p style="text-align:center;margin-top:16px;color:#666;">Нет аккаунта? <a href="/register" style="color:#818cf8;">Создать</a></p></div></div>{footer()}',False)

@app.route('/logout')
def logout(): session.clear(); return redirect('/')

@app.route('/deposit',methods=['GET','POST'])
@login_required
def deposit():
    if request.method=='POST':
        amount = request.form.get('amount',0,type=float)
        if amount<20: flash('Минимум 20 ₽','error')
        else:
            try:
                r = requests.post("https://pay.crypt.bot/api/createInvoice",json={"asset":"USDT","amount":str(round(amount/90,2)),"description":"Vest Accs"},headers={"Crypto-Pay-API-Token":CRYPTO_TOKEN},timeout=10)
                resp = r.json()
                if resp.get('ok'):
                    db = get_db()
                    with db.cursor() as cur: cur.execute("INSERT INTO crypto_invoices (user_id,invoice_id,amount_rub,pay_url) VALUES (%s,%s,%s,%s)",(g.user['id'],str(resp['result']['invoice_id']),amount,resp['result']['pay_url']))
                    return redirect(f'/invoice/{resp["result"]["invoice_id"]}')
                flash('Ошибка','error')
            except Exception as e: flash(str(e),'error')
    return render("Пополнение",f'<div style="max-width:380px;margin:40px auto;"><div class="section"><h3>Пополнение</h3><p style="color:#34d399;font-size:18px;font-weight:700;">{g.user["balance"]:.2f} ₽</p></div><div class="section"><form method="POST"><input type="number" name="amount" step="0.01" min="20" placeholder="Сумма (от 20 ₽)" required><button class="btn btn-primary" style="width:100%;">Пополнить</button></form></div>{footer()}</div>')

@app.route('/invoice/<iid>')
@login_required
def invoice_page(iid):
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT * FROM crypto_invoices WHERE invoice_id=%s AND user_id=%s",(str(iid),g.user['id']))
        inv = cur.fetchone()
    if not inv: flash('Не найден','error'); return redirect('/')
    st = "Ожидает" if inv['status']=='pending' else "Оплачен"
    c = f'<div style="max-width:380px;margin:40px auto;"><div class="section"><h3>Счет</h3><p>Сумма: <strong>{inv["amount_rub"]:.2f} ₽</strong></p><p>Статус: <strong>{st}</strong></p></div>'
    if inv['status']=='pending': c += f'<a href="{inv["pay_url"]}" target="_blank" class="btn btn-primary" style="width:100%;">Оплатить</a>'
    return render("Счет",c+f'{footer()}</div>')

@app.route('/check_invoice/<iid>')
@login_required
def check_invoice(iid):
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT * FROM crypto_invoices WHERE invoice_id=%s AND user_id=%s",(str(iid),g.user['id']))
        inv = cur.fetchone()
    if not inv: return redirect('/')
    if inv['status']=='paid': return redirect(f'/invoice/{iid}')
    try:
        r = requests.get("https://pay.crypt.bot/api/getInvoices",params={"invoice_ids":str(iid)},headers={"Crypto-Pay-API-Token":CRYPTO_TOKEN},timeout=10)
        if r.json().get('ok') and r.json()['result']['items'][0].get('status')=='paid':
            with db.cursor() as cur:
                cur.execute("UPDATE users SET balance=balance+%s WHERE id=%s",(inv['amount_rub'],inv['user_id']))
                cur.execute("INSERT INTO balance_history (user_id,amount,type,description) VALUES (%s,%s,%s,%s)",(inv['user_id'],inv['amount_rub'],'deposit','Пополнение'))
                cur.execute("UPDATE crypto_invoices SET status='paid' WHERE invoice_id=%s",(str(iid),))
            flash('Оплачено','success')
    except: pass
    return redirect(f'/invoice/{iid}')

@app.route('/filter')
def filter_accounts():
    page = request.args.get('page',1,type=int); offset = (page-1)*20
    q = request.args.get('q','').strip(); sort = request.args.get('sort','newest')
    ob = "a.created_at DESC"
    if sort=='price_asc': ob="a.price ASC"
    elif sort=='price_desc': ob="a.price DESC"
    conds = ["a.is_sold=FALSE"]; params = []
    if q: conds.append("a.title ILIKE %s"); params.append(f"%{q}%")
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute(f"SELECT COUNT(*) as cnt FROM accounts a WHERE {' AND '.join(conds)}",params)
        total = cur.fetchone()['cnt']
        cur.execute(f"SELECT a.*,u.username as seller_name FROM accounts a JOIN users u ON a.seller_id=u.id WHERE {' AND '.join(conds)} ORDER BY {ob} LIMIT 20 OFFSET %s",params+[offset])
        accounts = cur.fetchall()
    cards = render_cards(accounts) or '<div style="text-align:center;color:#666;">Ничего не найдено</div>'
    return render("Поиск",f'<h2 style="color:#fff;margin-bottom:12px;">Результаты ({total})</h2><div class="grid">{cards}</div>{footer()}')

@app.route('/account/<int:aid>')
def account_detail(aid):
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT a.*,u.username as seller_name FROM accounts a JOIN users u ON a.seller_id=u.id WHERE a.id=%s",(aid,))
        a = cur.fetchone()
    if not a: flash('Не найден','error'); return redirect('/')
    bb = f'<form action="/buy/{aid}" method="POST"><button class="btn btn-primary" style="width:100%;">Купить за {a["price"]:.0f} ₽</button></form>' if g.user and g.user['id']!=a['seller_id'] and not a['is_sold'] else ''
    cb = f'<button class="btn btn-secondary btn-valid btn-sm" data-id="{aid}" style="margin-right:8px;">Проверить</button>' if not a['is_sold'] else ''
    rs,_ = get_seller_rating(a['seller_id'])
    rh = f'<span style="color:#fbbf24;">★{rs}</span>' if rs else ''
    return render(a["title"],f'''<div style="max-width:500px;margin:0 auto;">
    <div class="section">
        <h2 style="color:#fff;font-size:20px;">{a["title"]}</h2>
        <p style="color:#666;margin-top:4px;">Продавец: <strong>{a["seller_name"]}</strong> {rh}</p>
        <div style="font-size:24px;color:#34d399;font-weight:700;margin:16px 0;">{a["price"]:.2f} ₽</div>
        {cb}{bb}
    </div>
    <div class="section">
        <div class="specs">
            <div class="spec"><span class="lbl">Страна</span><span class="val">{a["country"] or "-"}</span></div>
            <div class="spec"><span class="lbl">Происхождение</span><span class="val">{a["origin"] or "-"}</span></div>
            <div class="spec"><span class="lbl">2FA</span><span class="val">{"Да" if a["has_2fa"] else "Нет"}</span></div>
            <div class="spec"><span class="lbl">Спамблок</span><span class="val">{"Есть" if a["spamblock"] else "Чистый"}</span></div>
            <div class="spec"><span class="lbl">Premium</span><span class="val">{"Да" if a["is_premium"] else "Нет"}</span></div>
            <div class="spec"><span class="lbl">Чатов</span><span class="val">{a["chats_count"]}</span></div>
        </div>
        <p style="color:#888;font-size:13px;margin-top:8px;">{a["description"] or "Описание отсутствует"}</p>
    </div>
    {footer()}</div>''')

@app.route('/buy/<int:aid>',methods=['POST'])
@login_required
def buy_account(aid):
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT * FROM accounts WHERE id=%s AND is_sold=FALSE",(aid,))
        a = cur.fetchone()
        if not a: flash('Недоступен','error'); return redirect('/')
        price = Decimal(str(a['price']))
        balance = Decimal(str(g.user['balance']))
        if balance<price: flash('Недостаточно средств','error'); return redirect('/deposit')
        se = price*(Decimal('1')-COMMISSION)
        cur.execute("UPDATE users SET balance=balance-%s WHERE id=%s",(price,g.user['id']))
        cur.execute("INSERT INTO balance_history (user_id,amount,type,description) VALUES (%s,%s,%s,%s)",(g.user['id'],-price,'purchase',f'Покупка #{aid}'))
        cur.execute("UPDATE users SET balance=balance+%s,sales_count=sales_count+1 WHERE id=%s",(se,a['seller_id']))
        cur.execute("INSERT INTO balance_history (user_id,amount,type,description) VALUES (%s,%s,%s,%s)",(a['seller_id'],se,'sale',f'Продажа #{aid}'))
        cur.execute("UPDATE accounts SET is_sold=TRUE WHERE id=%s",(aid,))
        phone = extract_phone(a['session_string'])
        cur.execute("INSERT INTO purchases (buyer_id,account_id,phone_number) VALUES (%s,%s,%s)",(g.user['id'],aid,phone or 'Скрыт'))
    flash('Успешно!','success')
    return redirect('/purchases')

@app.route('/purchases')
@login_required
def purchases():
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT p.*,a.title FROM purchases p JOIN accounts a ON p.account_id=a.id WHERE p.buyer_id=%s ORDER BY p.id DESC",(g.user['id'],))
        purchases = cur.fetchall()
    items = ''
    for p in purchases:
        items += f'''<div class="acc-item">
        <div><div class="title">{p["title"]}</div><div class="meta">{p["phone_number"] or "Скрыт"} · {p["purchase_date"].strftime("%d.%m.%Y")}</div></div>
        <div><button class="btn btn-sm btn-primary btn-code" data-id="{p["id"]}">Код</button></div>
        <div id="code-{p["id"]}"></div></div>'''
    if not items: items = '<div style="text-align:center;color:#666;padding:40px;">Нет покупок</div>'
    return render("Покупки",f'<h2 style="color:#fff;margin-bottom:16px;">Мои покупки</h2>{items}{footer()}')

@app.route('/profile',methods=['GET','POST'])
@login_required
def profile():
    if request.method=='POST' and request.form.get('action')=='sell':
        phone = request.form.get('phone','').strip()
        if not phone.startswith('+'): phone = '+'+phone
        phash,ss,err = send_code(phone)
        if phash:
            session['v_phone']=phone; session['v_hash']=phash; session['v_ss']=ss
            return redirect('/verify')
        flash(err or 'Ошибка','error')
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT * FROM accounts WHERE seller_id=%s ORDER BY id DESC",(g.user['id'],))
        my_accs = cur.fetchall()
        cur.execute("SELECT COUNT(*) as cnt FROM purchases p JOIN accounts a ON p.account_id=a.id WHERE a.seller_id=%s",(g.user['id'],))
        sales = cur.fetchone()['cnt']
    rs,_ = get_seller_rating(g.user['id'])
    rh = f'<span style="color:#fbbf24;">★{rs}</span>' if rs else ''
    accs_html = ''.join([f'<div class="acc-item"><div><div class="title">{a["title"]}</div><div class="meta">{a["price"]:.0f} ₽ · {"Активен" if not a["is_sold"] else "Продан"}</div></div>{"<button class=\"btn btn-danger btn-sm btn-delete\" data-id=\""+str(a["id"])+"\">×</button>" if not a["is_sold"] else ""}</div>' for a in my_accs]) or '<div style="color:#666;text-align:center;">Нет товаров</div>'
    content = f'''<div class="profile-header"><div class="avatar">{g.user["username"][0].upper()}</div><div class="profile-info"><h2>{g.user["username"]}</h2> {rh}<div class="bal">{g.user["balance"]:.2f} ₽</div></div></div>
    <div class="profile-actions"><button class="btn btn-primary" data-modal="modal-sell">Продать аккаунт</button><a href="/deposit" class="btn btn-secondary">Пополнить</a><a href="/withdraw" class="btn btn-secondary">Вывести</a><a href="/logout" class="btn btn-danger">Выйти</a></div>
    {('<a href="/admin" class="btn btn-secondary" style="width:100%;margin-bottom:16px;">Админ-панель</a>' if g.user.get("is_admin") else '')}
    <div class="section"><h3>Мои товары ({len(my_accs)})</h3>{accs_html}</div>
    <div class="modal" id="modal-sell"><div class="modal-content"><h3 style="color:#fff;margin-bottom:16px;">Продажа</h3><form method="POST"><input type="hidden" name="action" value="sell"><input type="text" name="phone" placeholder="+79001234567" required><button class="btn btn-primary" style="width:100%;">Запросить код</button></form><button class="btn btn-secondary modal-close" style="width:100%;margin-top:8px;">Отмена</button></div></div>
    {footer()}'''
    return render("Профиль",content)

@app.route('/verify',methods=['GET','POST'])
@login_required
def verify():
    phone = session.get('v_phone','')
    if not phone: return redirect('/profile')
    if request.method=='POST':
        code = request.form.get('code','').strip()
        try:
            client = TelegramClient(StringSession(session.get('v_ss','')),API_ID,API_HASH)
            client.connect()
            try:
                client.sign_in(phone=phone,code=code,phone_code_hash=session.get('v_hash',''))
                session['v_done']=True; session['v_session']=client.session.save()
                flash('Подтвержден','success'); return redirect('/sell')
            except SessionPasswordNeededError:
                session['v_2fa']=True; session['v_ss']=client.session.save()
                return redirect('/verify_2fa')
            except PhoneCodeInvalidError: flash('Неверный код','error')
            finally:
                if not session.get('v_2fa'):
                    try: client.disconnect()
                    except: pass
        except Exception as e: flash(str(e),'error')
    return render("Код",f'<div style="max-width:380px;margin:40px auto;"><div class="section"><h3>Код подтверждения</h3><p style="color:#666;">Отправлен на {phone}</p><form method="POST"><input type="text" name="code" placeholder="Код" required><button class="btn btn-primary" style="width:100%;">Подтвердить</button></form></div>{footer()}</div>')

@app.route('/verify_2fa',methods=['GET','POST'])
@login_required
def verify_2fa():
    if not session.get('v_2fa'): return redirect('/profile')
    if request.method=='POST':
        pw = request.form.get('password','')
        try:
            client = TelegramClient(StringSession(session.get('v_ss','')),API_ID,API_HASH)
            client.connect()
            client.sign_in(password=pw)
            session['v_done']=True; session['v_session']=client.session.save(); session.pop('v_2fa',None)
            flash('Успешно','success'); return redirect('/sell')
        except Exception as e: flash(str(e),'error')
    return render("2FA",f'<div style="max-width:380px;margin:40px auto;"><div class="section"><h3>2FA пароль</h3><form method="POST"><input type="password" name="password" placeholder="Пароль" required><button class="btn btn-primary" style="width:100%;">Подтвердить</button></form></div>{footer()}</div>')

@app.route('/sell',methods=['GET','POST'])
@login_required
def sell():
    if not session.get('v_done'): return redirect('/profile')
    if request.method=='POST':
        title = request.form.get('title','').strip()
        price = request.form.get('price',type=float)
        if not title or not price: flash('Заполните','error')
        else:
            try:
                ss = session.get('v_session')
                ad = gather_data(ss)
                db = get_db()
                with db.cursor() as cur:
                    cur.execute("INSERT INTO accounts (seller_id,title,origin,description,price,session_string,country,has_2fa,spamblock,is_premium,chats_count,channels_count,groups_count) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (g.user['id'],title,request.form.get('origin',''),request.form.get('desc',''),Decimal(str(price)),ss,detect_country_by_phone(extract_phone(ss)),session.get('v_2fa',False),ad.get('spamblock',False),ad.get('is_premium',False),ad.get('chats',0),ad.get('channels',0),ad.get('groups',0)))
                for k in ['v_done','v_session','v_phone','v_hash','v_ss','v_2fa']: session.pop(k,None)
                flash('Выставлен!','success'); return redirect('/')
            except Exception as e: flash(str(e),'error')
    return render("Продажа",f'<div style="max-width:380px;margin:40px auto;"><div class="section"><h3>Новый аккаунт</h3><form method="POST"><input type="text" name="title" placeholder="Название" required><select name="origin"><option value="">Происхождение</option>{"".join([f"<option>{o}</option>" for o in ORIGINS])}</select><textarea name="desc" placeholder="Описание"></textarea><input type="number" name="price" placeholder="Цена (₽)" step="0.01" required><button class="btn btn-primary" style="width:100%;">Выставить</button></form></div>{footer()}</div>')

@app.route('/withdraw',methods=['GET','POST'])
@login_required
def withdraw_page():
    if request.method=='POST':
        amount = request.form.get('amount',0,type=float)
        address = request.form.get('address','').strip()
        if amount<50: flash('Минимум 50 ₽','error')
        elif not address: flash('Укажите адрес','error')
        else:
            db = get_db()
            with db.cursor() as cur:
                cur.execute("UPDATE users SET balance=balance-%s WHERE id=%s",(Decimal(str(amount)),g.user['id']))
                cur.execute("INSERT INTO balance_history (user_id,amount,type,description) VALUES (%s,%s,%s,%s)",(g.user['id'],-Decimal(str(amount)),'withdrawal','Вывод'))
                cur.execute("INSERT INTO withdrawals (user_id,amount_rub,amount_usdt,address) VALUES (%s,%s,%s,%s)",(g.user['id'],Decimal(str(amount)),Decimal(str(amount))/Decimal('90'),address))
            flash('Заявка создана','success'); return redirect('/profile')
    return render("Вывод",f'<div style="max-width:380px;margin:40px auto;"><div class="section"><h3>Вывод средств</h3><form method="POST"><input type="number" name="amount" placeholder="Сумма (от 50 ₽)" min="50" required><input type="text" name="address" placeholder="TON адрес" required><button class="btn btn-primary" style="width:100%;">Вывести</button></form></div>{footer()}</div>')

@app.route('/admin',methods=['GET','POST'])
@login_required
def admin():
    if not g.user.get('is_admin'): return redirect('/')
    db = get_db()
    if request.method=='POST':
        uid = request.form.get('user_id',type=int)
        amount = request.form.get('amount',type=float)
        act = request.form.get('action')
        if uid and amount:
            with db.cursor() as cur:
                if act=='add': cur.execute("UPDATE users SET balance=balance+%s WHERE id=%s",(Decimal(str(amount)),uid))
                elif act=='set': cur.execute("UPDATE users SET balance=%s WHERE id=%s",(Decimal(str(amount)),uid))
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT * FROM withdrawals ORDER BY created_at DESC LIMIT 20")
        withdrawals = cur.fetchall()
        cur.execute("SELECT * FROM users ORDER BY id")
        users = cur.fetchall()
    wh = ''.join([f'<tr><td>#{w["id"]}</td><td>{w["amount_rub"]:.0f} ₽</td><td style="color:{"#f59e0b" if w["status"]=="pending" else "#34d399"}">{w["status"]}</td><td><form method="POST" action="/admin/withdrawals"><input type="hidden" name="withdrawal_id" value="{w["id"]}"><button name="action" value="complete" class="btn btn-success btn-sm">✓</button><button name="action" value="reject" class="btn btn-danger btn-sm">✗</button></form></td></tr>' for w in withdrawals]) or '<tr><td colspan="4">Нет заявок</td></tr>'
    uo = ''.join([f'<option value="{u["id"]}">{u["username"]} ({u["balance"]:.0f} ₽)</option>' for u in users])
    return render("Админ",f'''<div class="section"><h3>Баланс</h3><form method="POST"><select name="user_id">{uo}</select><input type="number" name="amount" placeholder="Сумма" required><button name="action" value="add" class="btn btn-success">Добавить</button><button name="action" value="set" class="btn btn-secondary">Установить</button></form></div>
    <div class="section"><h3>Выводы</h3><table style="width:100%;"><thead><tr><th>ID</th><th>Сумма</th><th>Статус</th><th></th></tr></thead><tbody>{wh}</tbody></table></div>{footer()}''')

if __name__=='__main__':
    app.run(debug=True,host='0.0.0.0',port=5000)
