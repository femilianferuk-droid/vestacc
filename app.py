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
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:#0a0a0f;color:#e0e0e0;min-height:100vh;display:flex;flex-direction:column}
::-webkit-scrollbar{width:4px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.1);border-radius:4px}
@keyframes gradient{0%{background-position:0% 50%}50%{background-position:100% 50%}100%{background-position:0% 50%}}

.nav{background:rgba(10,10,15,0.95);border-bottom:1px solid rgba(255,255,255,0.05);padding:16px 24px;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:100;backdrop-filter:blur(12px)}
.logo{font-size:22px;font-weight:900;text-decoration:none;background:linear-gradient(90deg,#6366f1,#8b5cf6,#a78bfa,#6366f1);background-size:300% 100%;-webkit-background-clip:text;-webkit-text-fill-color:transparent;animation:gradient 4s ease infinite}
.nav-right{display:flex;align-items:center;gap:16px}
.nav-right a{color:#888;text-decoration:none;font-size:13px;font-weight:500;transition:0.2s}
.nav-right a:hover{color:#fff}
.balance-badge{background:rgba(99,102,241,0.1);color:#a5b4fc;padding:8px 16px;border-radius:20px;font-size:13px;font-weight:600}
.btn{padding:10px 20px;border:none;border-radius:10px;cursor:pointer;font-size:13px;font-weight:600;text-decoration:none;display:inline-flex;align-items:center;justify-content:center;gap:6px;transition:0.2s}
.btn-primary{background:#6366f1;color:#fff}
.btn-primary:hover{background:#5558e6}
.btn-secondary{background:rgba(255,255,255,0.04);color:#ccc;border:1px solid rgba(255,255,255,0.08)}
.btn-secondary:hover{background:rgba(255,255,255,0.08)}
.btn-success{background:#10b981;color:#fff}
.btn-danger{background:rgba(239,68,68,0.15);color:#fca5a5}
.btn-danger:hover{background:rgba(239,68,68,0.25)}
.btn-sm{padding:6px 12px;font-size:12px;border-radius:8px}
.btn-outline{background:transparent;color:#888;border:1px solid rgba(255,255,255,0.08)}
.btn-outline:hover{color:#fff;border-color:rgba(255,255,255,0.2)}

.main{flex:1;max-width:1100px;margin:0 auto;padding:24px 20px;width:100%}

.flash{padding:12px 16px;border-radius:10px;margin-bottom:12px;font-size:13px;font-weight:500}
.flash.success{background:rgba(16,185,129,0.1);color:#34d399;border:1px solid rgba(16,185,129,0.2)}
.flash.error{background:rgba(239,68,68,0.1);color:#fca5a5;border:1px solid rgba(239,68,68,0.2)}
.flash.info{background:rgba(99,102,241,0.1);color:#a5b4fc;border:1px solid rgba(99,102,241,0.2)}

.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}
.card{background:#12121a;border:1px solid rgba(255,255,255,0.04);border-radius:16px;padding:20px;transition:0.2s;display:flex;flex-direction:column;justify-content:space-between}
.card:hover{border-color:rgba(99,102,241,0.2);transform:translateY(-2px)}
.card-title{font-size:16px;font-weight:700;color:#fff;text-decoration:none;display:block;margin-bottom:12px}
.card-title:hover{color:#a5b4fc}
.tags{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
.tag{padding:4px 10px;border-radius:6px;font-size:11px;font-weight:600;background:rgba(255,255,255,0.03);color:#888}
.tag.green{background:rgba(16,185,129,0.1);color:#34d399}
.tag.red{background:rgba(239,68,68,0.1);color:#fca5a5}
.tag.purple{background:rgba(139,92,246,0.1);color:#a78bfa}
.card-footer{display:flex;justify-content:space-between;align-items:center;padding-top:14px;border-top:1px solid rgba(255,255,255,0.04);margin-top:auto}
.price{color:#ffb703;font-weight:800;font-size:16px}
.seller-info{color:#666;font-size:12px}
.seller-info strong{color:#999}
.rating{color:#fbbf24;font-size:11px;font-weight:600}

.auth-page{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
.auth-box{background:#12121a;border:1px solid rgba(255,255,255,0.06);border-radius:20px;padding:40px;width:100%;max-width:400px}
.auth-box h2{font-size:28px;font-weight:800;margin-bottom:8px;background:linear-gradient(135deg,#6366f1,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.auth-box p{color:#666;font-size:14px;margin-bottom:28px}

input,textarea,select{width:100%;padding:12px 14px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:10px;color:#e0e0e0;font-size:13px;outline:none;margin-bottom:12px;transition:border-color 0.2s}
input:focus,textarea:focus,select:focus{border-color:rgba(99,102,241,0.4)}
label{display:block;margin-bottom:6px;color:#888;font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px}

.profile-header{display:flex;align-items:center;gap:20px;margin-bottom:28px;background:#12121a;border:1px solid rgba(255,255,255,0.04);border-radius:20px;padding:28px}
.avatar{width:72px;height:72px;background:linear-gradient(135deg,#6366f1,#8b5cf6);border-radius:20px;display:flex;align-items:center;justify-content:center;font-size:28px;font-weight:800;color:#fff}
.profile-info h2{font-size:22px;font-weight:800;color:#fff}
.profile-info .role{color:#666;font-size:13px;margin-top:2px}
.profile-info .bal{color:#34d399;font-size:22px;font-weight:800;margin-top:6px}

.profile-actions{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:24px}
.profile-actions .btn{padding:14px;font-size:14px}

.section{background:#12121a;border:1px solid rgba(255,255,255,0.04);border-radius:16px;padding:24px;margin-bottom:20px}
.section h3{font-size:16px;font-weight:700;color:#fff;margin-bottom:16px}

.acc-item{display:flex;justify-content:space-between;align-items:center;padding:14px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.03);border-radius:12px;margin-bottom:8px;transition:0.2s}
.acc-item:hover{border-color:rgba(255,255,255,0.08)}
.acc-item .acc-title{font-weight:600;color:#fff;font-size:14px}
.acc-item .acc-meta{color:#666;font-size:12px;margin-top:2px}

.purchase-card{background:#12121a;border:1px solid rgba(255,255,255,0.04);border-radius:14px;padding:20px;margin-bottom:12px}
.purchase-card h3{color:#fff;font-size:16px;margin-bottom:8px}

.modal{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.7);z-index:200;display:none;align-items:center;justify-content:center;backdrop-filter:blur(4px)}
.modal.show{display:flex}
.modal-content{background:#12121a;border:1px solid rgba(255,255,255,0.06);border-radius:20px;padding:32px;width:90%;max-width:460px;max-height:80vh;overflow-y:auto}

.sort-bar{display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap}
.sort-bar a{padding:8px 16px;border-radius:10px;font-size:12px;font-weight:600;color:#888;text-decoration:none;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.04);transition:0.2s}
.sort-bar a.active,.sort-bar a:hover{background:rgba(99,102,241,0.1);color:#a5b4fc;border-color:rgba(99,102,241,0.2)}

.filter-wrap{background:#12121a;border:1px solid rgba(255,255,255,0.04);border-radius:14px;padding:18px;margin-bottom:20px}
.filter-toggle{color:#ccc;font-size:14px;font-weight:600;cursor:pointer;display:flex;justify-content:space-between;align-items:center;user-select:none}
.filter-body{display:none;margin-top:16px}
.filter-body.show{display:block}

.specs{display:flex;flex-direction:column;gap:6px;margin:16px 0}
.spec{display:flex;justify-content:space-between;padding:10px 12px;background:rgba(255,255,255,0.02);border-radius:10px;font-size:13px}
.spec .lbl{color:#666;font-weight:500}
.spec .val{color:#ccc;font-weight:600}

.footer{padding:24px;text-align:center;color:#444;font-size:13px;border-top:1px solid rgba(255,255,255,0.03);margin-top:auto}
.footer a{color:#666;text-decoration:none;font-weight:500}
.footer a:hover{color:#888}
.footer-brand{font-size:15px;font-weight:700;color:#555;margin-bottom:4px}

table{width:100%;border-collapse:collapse}
th{padding:10px 12px;text-align:left;color:#666;font-size:11px;text-transform:uppercase;font-weight:700;border-bottom:1px solid rgba(255,255,255,0.04)}
td{padding:10px 12px;font-size:13px;border-bottom:1px solid rgba(255,255,255,0.02)}
</style>'''

SCRIPT = '''<script>
document.addEventListener('click',function(e){
var t=e.target.closest('.filter-toggle');if(t){t.nextElementSibling.classList.toggle('show');return}
var m=e.target.closest('[data-modal]');if(m){document.getElementById(m.dataset.modal).classList.add('show');return}
var c=e.target.closest('.modal-close');if(c){c.closest('.modal').classList.remove('show');return}
if(e.target.classList.contains('modal')){e.target.classList.remove('show');return}
var d=e.target.closest('.btn-delete');if(d){if(confirm('Удалить объявление?')){window.location.href='/delete/'+d.dataset.id};return}
var v=e.target.closest('.btn-valid');if(v){e.preventDefault();var id=v.dataset.id;v.disabled=true;v.textContent='Проверка...';fetch('/check_valid/'+id).then(r=>r.json()).then(d=>{if(d.valid){v.className='btn btn-success btn-sm';v.textContent='Валид'}else{v.className='btn btn-danger btn-sm';v.textContent='Невалид'}});return}
var g=e.target.closest('.btn-code');if(g){e.preventDefault();var pid=g.dataset.id;g.disabled=true;g.textContent='...';fetch('/get_code/'+pid).then(r=>r.json()).then(d=>{if(d.code){document.getElementById('code-'+pid).innerHTML='<div style="color:#34d399;font-weight:700;font-size:18px;">'+d.code+'</div>';g.style.display='none'}else{alert(d.error||'Ошибка');g.disabled=false;g.textContent='Получить код'}});return}
});
</script>'''

def render(title,content,nav=True):
    n = navbar() if nav else '<div class="nav"><a href="/" class="logo">Vest Accs</a></div>'
    return f'<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1"><title>{title} - Vest Accs</title>{STYLE}</head><body>{n}<div class="main">{flash_msgs()}{content}</div>{SCRIPT}</body></html>'

def footer():
    return '<div class="footer"><div class="footer-brand">© 2026 Vest Accs</div><a href="https://t.me/VestAccsSupport">Поддержка</a> · Все права защищены</div>'

def navbar():
    if g.user:
        al = '<a href="/admin">Админ</a>' if g.user.get("is_admin") else ''
        return f'<div class="nav"><a href="/" class="logo">Vest Accs</a><div class="nav-right"><span class="balance-badge">{g.user["balance"]:.0f} ₽</span><a href="/deposit">Пополнить</a><a href="/profile">Профиль</a><a href="/purchases">Покупки</a>{al}</div></div>'
    return '<div class="nav"><a href="/" class="logo">Vest Accs</a><div class="nav-right"><a href="/login">Вход</a><a href="/register" class="btn btn-primary btn-sm">Регистрация</a></div></div>'

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

def send_code_sync(phone):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        client = TelegramClient(StringSession(),API_ID,API_HASH,loop=loop)
        client.connect()
        result = loop.run_until_complete(client.send_code_request(phone))
        return result.phone_code_hash,client.session.save(),None
    except Exception as e: return None,None,str(e)
    finally:
        try: client.disconnect()
        except: pass
        loop.close()

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
    flash('Объявление удалено','success')
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
        rh = f'<span class="rating">★{rs}</span>' if rs else ''
        oc = "green" if a["origin"] in ["Авторег","Саморег"] else ""
        sc = "green" if not a["spamblock"] else "red"
        pc = "purple" if a["is_premium"] else ""
        cards += f'''<div class="card">
        <div><a href="/account/{a["id"]}" class="card-title">{a["title"]}</a>
        <div class="tags">
            <span class="tag">{a["country"] or "Интер"}</span>
            <span class="tag">{a["chats_count"]} чатов</span>
            <span class="tag {oc}">{a["origin"] or "Лог"}</span>
            <span class="tag">{"2FA" if a["has_2fa"] else "Без 2FA"}</span>
            <span class="tag {sc}">{"Спамблок" if a["spamblock"] else "Чистый"}</span>
            <span class="tag {pc}">{"Premium" if a["is_premium"] else "Обычный"}</span>
        </div></div>
        <div class="card-footer">
            <div class="seller-info"><strong>{a["seller_name"]}</strong> {rh}</div>
            <div style="display:flex;align-items:center;gap:10px;">
                <span class="price">{a["price"]:.0f} ₽</span>
                <a href="/account/{a["id"]}" class="btn btn-primary btn-sm">Купить</a>
            </div>
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
    elif sort=='chats': ob="a.chats_count DESC"
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT COUNT(*) as cnt FROM accounts WHERE is_sold=FALSE")
        total = cur.fetchone()['cnt']
        cur.execute(f"SELECT a.*,u.username as seller_name FROM accounts a JOIN users u ON a.seller_id=u.id WHERE a.is_sold=FALSE ORDER BY {ob} LIMIT 20 OFFSET %s",(offset,))
        accounts = cur.fetchall()
    cards = render_cards(accounts) or '<div style="text-align:center;padding:60px 20px;color:#666;"><h3>Нет доступных аккаунтов</h3><p style="margin-top:8px;">Станьте первым продавцом</p></div>'
    sb = f'<div class="sort-bar"><a href="/?sort=newest" class="{"active" if sort=="newest" else ""}">Новые</a><a href="/?sort=oldest" class="{"active" if sort=="oldest" else ""}">Старые</a><a href="/?sort=price_asc" class="{"active" if sort=="price_asc" else ""}">Дешевле</a><a href="/?sort=price_desc" class="{"active" if sort=="price_desc" else ""}">Дороже</a><a href="/?sort=chats" class="{"active" if sort=="chats" else ""}">По чатам</a></div>'
    filter_html = f'''<div class="filter-wrap"><div class="filter-toggle">Фильтры <span>▼</span></div><div class="filter-body"><form action="/filter"><input type="text" name="q" placeholder="Поиск по названию..."><input type="hidden" name="sort" value="{sort}"><button class="btn btn-primary" style="width:100%;">Применить</button></form></div></div>'''
    pag = ''
    if total>20:
        pages = (total+19)//20
        pag = '<div style="text-align:center;margin-top:20px;display:flex;gap:6px;justify-content:center;">'+''.join([f'<span style="padding:8px 14px;background:rgba(99,102,241,0.2);border-radius:8px;font-weight:600;">{p}</span>' if p==page else f'<a href="/?page={p}&sort={sort}" style="padding:8px 14px;background:rgba(255,255,255,0.03);border-radius:8px;color:#888;text-decoration:none;">{p}</a>' for p in range(1,pages+1)])+'</div>'
    return render("Главная",f'{filter_html}{sb}<div class="grid">{cards}</div>{pag}{footer()}')

@app.route('/register',methods=['GET','POST'])
def register():
    if request.method=='POST':
        u = request.form.get('username','').strip()
        p = request.form.get('password','').strip()
        if not u or not p: flash('Заполните все поля','error')
        else:
            try:
                db = get_db()
                with db.cursor() as cur: cur.execute("INSERT INTO users (username,password_hash) VALUES (%s,%s)",(u,hash_password(p)))
                flash('Регистрация успешна','success'); return redirect('/login')
            except: flash('Пользователь уже существует','error')
    return render("Регистрация",f'<div class="auth-page"><div class="auth-box"><h2>Регистрация</h2><p>Создайте аккаунт для покупки и продажи</p><form method="POST"><label>Логин</label><input type="text" name="username" placeholder="Придумайте логин" required><label>Пароль</label><input type="password" name="password" placeholder="Придумайте пароль" required><button class="btn btn-primary" style="width:100%;padding:14px;font-size:14px;">Создать аккаунт</button></form><p style="text-align:center;margin-top:20px;color:#666;">Есть аккаунт? <a href="/login" style="color:#818cf8;font-weight:600;">Войти</a></p></div></div>{footer()}',False)

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
            flash('Неверный логин или пароль','error')
        except Exception as e: flash(str(e),'error')
    return render("Вход",f'<div class="auth-page"><div class="auth-box"><h2>Вход</h2><p>Добро пожаловать обратно</p><form method="POST"><label>Логин</label><input type="text" name="username" placeholder="Введите логин" required><label>Пароль</label><input type="password" name="password" placeholder="Введите пароль" required><button class="btn btn-primary" style="width:100%;padding:14px;font-size:14px;">Войти</button></form><p style="text-align:center;margin-top:20px;color:#666;">Нет аккаунта? <a href="/register" style="color:#818cf8;font-weight:600;">Создать</a></p></div></div>{footer()}',False)

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
                flash('Ошибка создания счета','error')
            except Exception as e: flash(str(e),'error')
    return render("Пополнение",f'<div style="max-width:420px;margin:40px auto;"><div class="section"><h3>Пополнение баланса</h3><p style="color:#34d399;font-size:24px;font-weight:800;">{g.user["balance"]:.2f} ₽</p></div><div class="section"><form method="POST"><label>Сумма пополнения</label><input type="number" name="amount" step="0.01" min="20" placeholder="От 20 ₽" required><button class="btn btn-primary" style="width:100%;padding:14px;">Пополнить через Crypto Bot</button></form></div>{footer()}</div>')

@app.route('/invoice/<iid>')
@login_required
def invoice_page(iid):
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT * FROM crypto_invoices WHERE invoice_id=%s AND user_id=%s",(str(iid),g.user['id']))
        inv = cur.fetchone()
    if not inv: flash('Счет не найден','error'); return redirect('/')
    st = "Ожидает оплаты" if inv['status']=='pending' else "Оплачен"
    sc = "#f59e0b" if inv['status']=='pending' else "#34d399"
    c = f'<div style="max-width:420px;margin:40px auto;"><div class="section"><h3>Счет #{inv["invoice_id"]}</h3><div style="display:flex;justify-content:space-between;margin:12px 0;"><span>Сумма:</span><strong>{inv["amount_rub"]:.2f} ₽</strong></div><div style="display:flex;justify-content:space-between;"><span>Статус:</span><strong style="color:{sc};">{st}</strong></div></div>'
    if inv['status']=='pending': c += f'<a href="{inv["pay_url"]}" target="_blank" class="btn btn-primary" style="width:100%;padding:14px;">Перейти к оплате</a><a href="/check_invoice/{iid}" class="btn btn-secondary" style="width:100%;margin-top:8px;">Проверить оплату</a>'
    else: c += '<a href="/" class="btn btn-secondary" style="width:100%;">На главную</a>'
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
            flash('Баланс пополнен','success')
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
    cards = render_cards(accounts) or '<div style="text-align:center;color:#666;padding:40px;">Ничего не найдено</div>'
    return render("Поиск",f'<h2 style="color:#fff;margin-bottom:16px;">Результаты поиска ({total})</h2><div class="grid">{cards}</div>{footer()}')

@app.route('/account/<int:aid>')
def account_detail(aid):
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT a.*,u.username as seller_name FROM accounts a JOIN users u ON a.seller_id=u.id WHERE a.id=%s",(aid,))
        a = cur.fetchone()
    if not a: flash('Не найден','error'); return redirect('/')
    bb = f'<form action="/buy/{aid}" method="POST"><button class="btn btn-primary" style="width:100%;padding:14px;">Купить аккаунт</button></form>' if g.user and g.user['id']!=a['seller_id'] and not a['is_sold'] else ''
    cb = f'<button class="btn btn-secondary btn-valid btn-sm" data-id="{aid}">Проверить на валид</button>' if not a['is_sold'] else ''
    rs,_ = get_seller_rating(a['seller_id'])
    rh = f'<span class="rating">★{rs}</span>' if rs else ''
    return render(a["title"],f'''<div style="max-width:560px;margin:0 auto;">
    <div class="section">
        <h2 style="color:#fff;font-size:22px;margin-bottom:8px;">{a["title"]}</h2>
        <p style="color:#666;">Продавец: <strong>{a["seller_name"]}</strong> {rh}</p>
        <div style="font-size:28px;color:#34d399;font-weight:800;margin:20px 0;">{a["price"]:.2f} ₽</div>
        <div style="display:flex;gap:8px;">{cb}{bb}</div>
    </div>
    <div class="section">
        <div class="specs">
            <div class="spec"><span class="lbl">Страна</span><span class="val">{a["country"] or "-"}</span></div>
            <div class="spec"><span class="lbl">Происхождение</span><span class="val">{a["origin"] or "-"}</span></div>
            <div class="spec"><span class="lbl">2FA защита</span><span class="val">{"Да" if a["has_2fa"] else "Нет"}</span></div>
            <div class="spec"><span class="lbl">Спамблок</span><span class="val">{"Есть" if a["spamblock"] else "Чистый"}</span></div>
            <div class="spec"><span class="lbl">Premium</span><span class="val">{"Да" if a["is_premium"] else "Нет"}</span></div>
            <div class="spec"><span class="lbl">Диалогов</span><span class="val">{a["chats_count"]}</span></div>
            <div class="spec"><span class="lbl">Каналов</span><span class="val">{a["channels_count"]}</span></div>
        </div>
        <p style="color:#888;font-size:13px;margin-top:12px;">{a["description"] or "Описание отсутствует"}</p>
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
    flash('Покупка успешна','success')
    return redirect('/purchases')

@app.route('/purchases')
@login_required
def purchases():
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT p.*,a.title,a.session_string FROM purchases p JOIN accounts a ON p.account_id=a.id WHERE p.buyer_id=%s ORDER BY p.id DESC",(g.user['id'],))
        purchases = cur.fetchall()
    items = ''
    for p in purchases:
        items += f'''<div class="purchase-card">
        <h3>{p["title"]}</h3>
        <p style="color:#666;font-size:12px;">{p["purchase_date"].strftime("%d.%m.%Y %H:%M")}</p>
        <div style="background:rgba(255,255,255,0.02);padding:12px;border-radius:10px;margin:12px 0;">
            <div style="display:flex;justify-content:space-between;"><span style="color:#666;">Номер:</span><strong>{p["phone_number"] or "Скрыт"}</strong></div>
        </div>
        <button class="btn btn-primary btn-sm btn-code" data-id="{p["id"]}">Получить код</button>
        <div id="code-{p["id"]}" style="margin-top:8px;"></div>
        <div style="display:flex;gap:8px;margin-top:12px;">
            <a href="/download_session/{p["id"]}" class="btn btn-secondary btn-sm">Telethon</a>
            <a href="/download_json/{p["id"]}" class="btn btn-secondary btn-sm">JSON</a>
        </div></div>'''
    if not items: items = '<div style="text-align:center;color:#666;padding:40px;">Нет покупок</div>'
    return render("Покупки",f'<h2 style="color:#fff;font-size:22px;margin-bottom:20px;">Мои покупки</h2>{items}{footer()}')

@app.route('/profile',methods=['GET','POST'])
@login_required
def profile():
    if request.method=='POST' and request.form.get('action')=='sell':
        phone = request.form.get('phone','').strip()
        if not phone.startswith('+'): phone = '+'+phone
        phash,ss,err = send_code_sync(phone)
        if phash:
            session['v_phone']=phone; session['v_hash']=phash; session['v_ss']=ss
            return redirect('/verify')
        flash(err or 'Ошибка отправки кода','error')
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT * FROM accounts WHERE seller_id=%s ORDER BY id DESC",(g.user['id'],))
        my_accs = cur.fetchall()
        cur.execute("SELECT COUNT(*) as cnt FROM purchases p JOIN accounts a ON p.account_id=a.id WHERE a.seller_id=%s",(g.user['id'],))
        sales = cur.fetchone()['cnt']
    rs,_ = get_seller_rating(g.user['id'])
    rh = f'<span class="rating" style="font-size:14px;">★{rs}</span>' if rs else ''
    accs_html = ''.join([f'<div class="acc-item"><div><div class="acc-title">{a["title"]}</div><div class="acc-meta">{a["price"]:.0f} ₽ · {"Активен" if not a["is_sold"] else "Продан"}</div></div>{"<button class=\"btn btn-danger btn-sm btn-delete\" data-id=\""+str(a["id"])+"\">Удалить</button>" if not a["is_sold"] else ""}</div>' for a in my_accs]) or '<div style="color:#666;text-align:center;padding:20px;">Нет товаров</div>'
    content = f'''<div class="profile-header"><div class="avatar">{g.user["username"][0].upper()}</div><div class="profile-info"><h2>{g.user["username"]}</h2><div class="role">{"Администратор" if g.user.get("is_admin") else "Пользователь"} {rh}</div><div class="bal">{g.user["balance"]:.2f} ₽</div></div></div>
    <div class="profile-actions"><button class="btn btn-primary" data-modal="modal-sell">Продать аккаунт</button><a href="/deposit" class="btn btn-success">Пополнить</a><button class="btn btn-secondary" data-modal="modal-withdraw">Вывести</button><a href="/logout" class="btn btn-danger">Выйти</a></div>
    {('<a href="/admin" class="btn btn-outline" style="width:100%;margin-bottom:20px;">Панель администратора</a>' if g.user.get("is_admin") else '')}
    <div class="section"><h3>Мои товары ({len(my_accs)})</h3>{accs_html}</div>
    <div class="modal" id="modal-sell"><div class="modal-content"><h3 style="color:#fff;margin-bottom:16px;">Новый аккаунт</h3><form method="POST"><input type="hidden" name="action" value="sell"><label>Номер телефона</label><input type="text" name="phone" placeholder="+79001234567" required><button class="btn btn-primary" style="width:100%;">Запросить код</button></form><button class="btn btn-secondary modal-close" style="width:100%;margin-top:8px;">Отмена</button></div></div>
    <div class="modal" id="modal-withdraw"><div class="modal-content"><h3 style="color:#fff;margin-bottom:16px;">Вывод средств</h3><form method="POST" action="/withdraw"><label>Сумма</label><input type="number" name="amount" placeholder="От 50 ₽" min="50" required><label>TON адрес</label><input type="text" name="address" placeholder="EQD..." required><button class="btn btn-primary" style="width:100%;">Вывести</button></form><button class="btn btn-secondary modal-close" style="width:100%;margin-top:8px;">Отмена</button></div></div>
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
                flash('Номер подтвержден','success'); return redirect('/sell')
            except SessionPasswordNeededError:
                session['v_2fa']=True; session['v_ss']=client.session.save()
                return redirect('/verify_2fa')
            except PhoneCodeInvalidError: flash('Неверный код','error')
            finally:
                if not session.get('v_2fa'):
                    try: client.disconnect()
                    except: pass
        except Exception as e: flash(str(e),'error')
    return render("Код",f'<div style="max-width:400px;margin:40px auto;"><div class="section"><h3>Код подтверждения</h3><p style="color:#666;">Отправлен на {phone}</p><form method="POST"><label>Код из Telegram</label><input type="text" name="code" placeholder="5-значный код" required><button class="btn btn-primary" style="width:100%;">Подтвердить</button></form></div>{footer()}</div>')

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
    return render("2FA",f'<div style="max-width:400px;margin:40px auto;"><div class="section"><h3>2FA пароль</h3><p style="color:#fbbf24;">Требуется облачный пароль</p><form method="POST"><label>Пароль</label><input type="password" name="password" placeholder="Ваш пароль" required><button class="btn btn-primary" style="width:100%;">Подтвердить</button></form></div>{footer()}</div>')

@app.route('/sell',methods=['GET','POST'])
@login_required
def sell():
    if not session.get('v_done'): return redirect('/profile')
    if request.method=='POST':
        title = request.form.get('title','').strip()
        price = request.form.get('price',type=float)
        if not title or not price: flash('Заполните обязательные поля','error')
        else:
            try:
                ss = session.get('v_session')
                ad = gather_data(ss)
                db = get_db()
                with db.cursor() as cur:
                    cur.execute("INSERT INTO accounts (seller_id,title,origin,description,price,session_string,country,has_2fa,spamblock,is_premium,chats_count,channels_count,groups_count) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (g.user['id'],title,request.form.get('origin',''),request.form.get('desc',''),Decimal(str(price)),ss,detect_country_by_phone(extract_phone(ss)),session.get('v_2fa',False),ad.get('spamblock',False),ad.get('is_premium',False),ad.get('chats',0),ad.get('channels',0),ad.get('groups',0)))
                for k in ['v_done','v_session','v_phone','v_hash','v_ss','v_2fa']: session.pop(k,None)
                flash('Аккаунт выставлен на продажу','success'); return redirect('/')
            except Exception as e: flash(str(e),'error')
    return render("Продажа",f'<div style="max-width:420px;margin:40px auto;"><div class="section"><h3>Выставить аккаунт</h3><form method="POST"><label>Название *</label><input type="text" name="title" required><label>Происхождение</label><select name="origin"><option value="">Выберите...</option>{"".join([f"<option>{o}</option>" for o in ORIGINS])}</select><label>Описание</label><textarea name="desc" rows="3"></textarea><label>Цена (₽) *</label><input type="number" name="price" step="0.01" required><button class="btn btn-primary" style="width:100%;padding:14px;">Выставить на маркет</button></form></div>{footer()}</div>')

@app.route('/withdraw',methods=['POST'])
@login_required
def withdraw():
    amount = request.form.get('amount',0,type=float)
    address = request.form.get('address','').strip()
    if amount<50: flash('Минимум 50 ₽','error')
    elif not address: flash('Укажите адрес','error')
    elif g.user['balance']<amount: flash('Недостаточно средств','error')
    else:
        db = get_db()
        with db.cursor() as cur:
            cur.execute("UPDATE users SET balance=balance-%s WHERE id=%s",(Decimal(str(amount)),g.user['id']))
            cur.execute("INSERT INTO balance_history (user_id,amount,type,description) VALUES (%s,%s,%s,%s)",(g.user['id'],-Decimal(str(amount)),'withdrawal','Вывод'))
            cur.execute("INSERT INTO withdrawals (user_id,amount_rub,amount_usdt,address) VALUES (%s,%s,%s,%s)",(g.user['id'],Decimal(str(amount)),Decimal(str(amount))/Decimal('90'),address))
        flash('Заявка на вывод создана','success')
    return redirect('/profile')

@app.route('/admin',methods=['GET','POST'])
@login_required
def admin():
    if not g.user.get('is_admin'): return redirect('/')
    db = get_db()
    if request.method=='POST':
        uid = request.form.get('user_id',type=int)
        amt = request.form.get('amount',type=float)
        act = request.form.get('action')
        if uid and amt:
            with db.cursor() as cur:
                if act=='add': cur.execute("UPDATE users SET balance=balance+%s WHERE id=%s",(Decimal(str(amt)),uid))
                elif act=='set': cur.execute("UPDATE users SET balance=%s WHERE id=%s",(Decimal(str(amt)),uid))
            flash('Баланс обновлен','success')
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT w.*,u.username FROM withdrawals w JOIN users u ON w.user_id=u.id ORDER BY w.created_at DESC LIMIT 20")
        withdrawals = cur.fetchall()
        cur.execute("SELECT * FROM users ORDER BY id")
        users = cur.fetchall()
    wh = ''.join([f'<tr><td>#{w["id"]}</td><td>{w["username"]}</td><td>{w["amount_rub"]:.0f} ₽</td><td style="color:{"#f59e0b" if w["status"]=="pending" else "#34d399" if w["status"]=="completed" else "#ef4444"}">{w["status"]}</td><td><form method="POST" action="/admin/withdrawals"><input type="hidden" name="withdrawal_id" value="{w["id"]}"><button name="action" value="complete" class="btn btn-success btn-sm">✓</button><button name="action" value="reject" class="btn btn-danger btn-sm">✗</button></form></td></tr>' for w in withdrawals]) or '<tr><td colspan="5">Нет заявок</td></tr>'
    uo = ''.join([f'<option value="{u["id"]}">{u["username"]} ({u["balance"]:.0f} ₽)</option>' for u in users])
    return render("Админ",f'''<div class="section"><h3>Управление балансом</h3><form method="POST"><label>Пользователь</label><select name="user_id">{uo}</select><label>Сумма</label><input type="number" name="amount" step="0.01" required><div style="display:flex;gap:8px;"><button name="action" value="add" class="btn btn-success" style="flex:1;">Добавить</button><button name="action" value="set" class="btn btn-secondary" style="flex:1;">Установить</button></div></form></div>
    <div class="section"><h3>Заявки на вывод</h3><table><thead><tr><th>ID</th><th>Пользователь</th><th>Сумма</th><th>Статус</th><th></th></tr></thead><tbody>{wh}</tbody></table></div>{footer()}''')

@app.route('/download_session/<int:pid>')
@login_required
def download_session(pid):
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT p.*,a.session_string FROM purchases p JOIN accounts a ON p.account_id=a.id WHERE p.id=%s AND p.buyer_id=%s",(pid,g.user['id']))
        p = cur.fetchone()
    if not p: return "Не найден",404
    ss = StringSession(p['session_string'])
    fd,tp = tempfile.mkstemp()
    try:
        conn = sqlite3.connect(tp); c = conn.cursor()
        c.execute('CREATE TABLE sessions (dc_id INTEGER PRIMARY KEY,server_address TEXT,port INTEGER,auth_key BLOB)')
        c.execute('INSERT INTO sessions VALUES (?,?,?,?)',(ss.dc_id,ss.server_address,ss.port,ss.auth_key))
        conn.commit(); conn.close()
        return send_file(tp,as_attachment=True,download_name=f"{p['phone_number'] or pid}.session")
    finally:
        try: os.close(fd); os.remove(tp)
        except: pass

@app.route('/download_json/<int:pid>')
@login_required
def download_json(pid):
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT p.*,a.title,a.origin,a.country FROM purchases p JOIN accounts a ON p.account_id=a.id WHERE p.id=%s AND p.buyer_id=%s",(pid,g.user['id']))
        p = cur.fetchone()
    if not p: return "Не найден",404
    config = {"phone":p['phone_number'],"api_id":API_ID,"api_hash":API_HASH,"country":p['country'],"origin":p['origin'],"title":p['title']}
    bio = io.BytesIO(json.dumps(config,indent=4,ensure_ascii=False).encode('utf-8'))
    return send_file(bio,as_attachment=True,download_name=f"{p['phone_number'] or pid}.json",mimetype='application/json')

if __name__=='__main__':
    app.run(debug=True,host='0.0.0.0',port=5000)
