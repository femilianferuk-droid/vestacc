import re
import secrets
import traceback
import hashlib
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, request, redirect, url_for, session, flash, jsonify, g, get_flashed_messages
import psycopg2
import psycopg2.extras
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError

DATABASE_URL = "postgresql://bothost_db_3092f9da4312:yvzBra5xN_j2a_dafFbpHStZAVH7HiMuzJ2iCwDX-5w@node1.pghost.ru:15796/bothost_db_3092f9da4312"
API_ID = 32480523
API_HASH = "147839735c9fa4e83451209e9b55cfc5"
SECRET_KEY = secrets.token_hex(32)
COMMISSION = 0.05

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

def hash_password(password):
    salt = secrets.token_hex(16)
    h = hashlib.sha256((password + salt).encode()).hexdigest()
    return f"{salt}${h}"

def verify_password(password, hashed):
    try:
        salt, h = hashed.split('$')
        return hashlib.sha256((password + salt).encode()).hexdigest() == h
    except:
        return False

def get_db():
    if 'db' not in g:
        g.db = psycopg2.connect(DATABASE_URL)
        g.db.autocommit = True
    return g.db

@app.teardown_appcontext
def close_db(error):
    db = g.pop('db', None)
    if db is not None: db.close()

def init_db():
    db = get_db()
    with db.cursor() as cur:
        cur.execute("CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username VARCHAR(100) UNIQUE NOT NULL, password_hash VARCHAR(255) NOT NULL, balance DECIMAL(10,2) DEFAULT 0.00, is_admin BOOLEAN DEFAULT FALSE, created_at TIMESTAMP DEFAULT NOW())")
        cur.execute("CREATE TABLE IF NOT EXISTS accounts (id SERIAL PRIMARY KEY, seller_id INTEGER REFERENCES users(id), title VARCHAR(200) NOT NULL, origin VARCHAR(100), description TEXT, price DECIMAL(10,2) NOT NULL, session_string TEXT NOT NULL, country VARCHAR(50), has_2fa BOOLEAN DEFAULT FALSE, spamblock BOOLEAN DEFAULT FALSE, chats_count INTEGER DEFAULT 0, channels_count INTEGER DEFAULT 0, groups_count INTEGER DEFAULT 0, is_sold BOOLEAN DEFAULT FALSE, created_at TIMESTAMP DEFAULT NOW())")
        cur.execute("CREATE TABLE IF NOT EXISTS purchases (id SERIAL PRIMARY KEY, buyer_id INTEGER REFERENCES users(id), account_id INTEGER REFERENCES accounts(id), phone_number VARCHAR(20), purchase_date TIMESTAMP DEFAULT NOW(), code_retrieved BOOLEAN DEFAULT FALSE)")
        cur.execute("SELECT COUNT(*) FROM users")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO users (username, password_hash, is_admin, balance) VALUES (%s, %s, TRUE, 999999.00)", ("admin", hash_password("admin123")))
    db.commit()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session: return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

@app.before_request
def load_user():
    g.user = None
    if 'user_id' in session:
        try:
            db = get_db()
            with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("SELECT * FROM users WHERE id = %s", (session['user_id'],))
                g.user = cur.fetchone()
        except: pass

def flash_msgs():
    return ''.join([f'<div style="padding:12px 16px;border-radius:10px;margin-bottom:14px;font-size:14px;background:rgba({("16,185,129" if c=="success" else "239,68,68" if c=="error" else "99,102,241")},0.12);border:1px solid rgba({("16,185,129" if c=="success" else "239,68,68" if c=="error" else "99,102,241")},0.25);color:#{"34d399" if c=="success" else "fca5a5" if c=="error" else "a5b4fc"}">{m}</div>' for c,m in get_flashed_messages(with_categories=True)])

STYLE = '''<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:#080812;color:#e2e8f0;min-height:100vh;overflow-x:hidden}
body::before{content:'';position:fixed;top:0;left:0;right:0;bottom:0;background:radial-gradient(ellipse at 30% 20%,rgba(99,102,241,0.05) 0%,transparent 60%),radial-gradient(ellipse at 70% 80%,rgba(59,130,246,0.03) 0%,transparent 60%);pointer-events:none;z-index:0}
.navbar{background:rgba(8,8,18,0.92);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border-bottom:1px solid rgba(255,255,255,0.06);padding:12px 20px;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:200}
.logo{font-size:20px;font-weight:800;text-decoration:none;letter-spacing:-0.5px}
.logo span{background:linear-gradient(135deg,#6366f1,#3b82f6);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.balance-badge{background:rgba(99,102,241,0.1);border:1px solid rgba(99,102,241,0.2);padding:8px 16px;border-radius:30px;color:#a5b4fc;font-weight:600;font-size:14px}
.burger{width:36px;height:36px;background:transparent;border:none;cursor:pointer;display:flex;flex-direction:column;justify-content:center;gap:5px;padding:6px;z-index:300;position:relative}
.burger span{display:block;height:2px;background:#e2e8f0;border-radius:2px;transition:0.3s}
.burger.open span:nth-child(1){transform:rotate(45deg) translate(5px,5px)}
.burger.open span:nth-child(2){opacity:0}
.burger.open span:nth-child(3){transform:rotate(-45deg) translate(5px,-5px)}
.sidebar{position:fixed;top:0;right:-320px;width:300px;height:100vh;background:rgba(10,10,20,0.98);backdrop-filter:blur(30px);-webkit-backdrop-filter:blur(30px);border-left:1px solid rgba(255,255,255,0.06);z-index:250;transition:0.3s ease;padding:80px 20px 20px;display:flex;flex-direction:column;gap:6px;overflow-y:auto}
.sidebar.open{right:0}
.sidebar a{display:flex;align-items:center;gap:12px;padding:14px 16px;color:#cbd5e1;text-decoration:none;border-radius:12px;font-weight:500;transition:0.2s;font-size:15px}
.sidebar a:hover{background:rgba(99,102,241,0.1);color:#fff}
.sidebar .divider{height:1px;background:rgba(255,255,255,0.06);margin:6px 0}
.overlay{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:240;display:none}
.overlay.show{display:block}
.modal{position:fixed;top:0;left:0;right:0;bottom:0;z-index:300;display:none;align-items:center;justify-content:center}
.modal.show{display:flex}
.modal-bg{position:absolute;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.7)}
.modal-content{position:relative;background:#111118;border:1px solid rgba(255,255,255,0.08);border-radius:20px;padding:28px;max-width:500px;width:90%;max-height:90vh;overflow-y:auto;z-index:1}
.container{max-width:1200px;margin:0 auto;padding:20px 16px;position:relative;z-index:1}
.page-title{font-size:32px;font-weight:900;text-align:center;margin:20px 0 6px;background:linear-gradient(135deg,#e2e8f0,#94a3b8);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.page-sub{text-align:center;color:#64748b;margin-bottom:24px;font-size:15px}
.btn{padding:10px 20px;border:none;border-radius:30px;cursor:pointer;font-size:14px;font-weight:600;text-decoration:none;display:inline-flex;align-items:center;gap:6px;transition:0.3s;font-family:inherit;white-space:nowrap}
.btn-primary{background:linear-gradient(135deg,#6366f1,#4f46e5);color:#fff}
.btn-primary:hover{transform:translateY(-2px);box-shadow:0 8px 25px rgba(99,102,241,0.4)}
.btn-secondary{background:rgba(255,255,255,0.05);color:#e2e8f0;border:1px solid rgba(255,255,255,0.1)}
.btn-secondary:hover{background:rgba(255,255,255,0.1)}
.btn-success{background:linear-gradient(135deg,#10b981,#059669);color:#fff}
.btn-success:hover{transform:translateY(-2px);box-shadow:0 8px 25px rgba(16,185,129,0.4)}
.btn-ghost{background:transparent;color:#94a3b8}
.btn-ghost:hover{background:rgba(255,255,255,0.05);color:#fff}
.btn-sm{padding:8px 14px;font-size:13px}
input,textarea,select{width:100%;padding:14px 16px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:12px;color:#e2e8f0;font-size:15px;outline:none;transition:0.3s;font-family:inherit;margin-bottom:14px}
input:focus,textarea:focus,select:focus{border-color:#6366f1;box-shadow:0 0 20px rgba(99,102,241,0.15)}
::placeholder{color:#475569}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px}
.card{background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:16px;padding:20px;transition:0.3s;position:relative}
.card:hover{border-color:rgba(99,102,241,0.4);transform:translateY(-3px);box-shadow:0 20px 40px rgba(0,0,0,0.4)}
.card-row{display:flex;justify-content:space-between;align-items:start;margin-bottom:14px}
.card-title{font-weight:700;font-size:17px}
.card-seller{font-size:13px;color:#64748b;margin-top:2px}
.price-tag{background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.2);color:#34d399;padding:6px 14px;border-radius:20px;font-weight:700;font-size:15px;white-space:nowrap}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:12px}
.stat-box{text-align:center;padding:10px 6px;background:rgba(0,0,0,0.3);border-radius:10px}
.stat-val{font-size:17px;font-weight:700;color:#818cf8}
.stat-lbl{font-size:10px;color:#64748b;text-transform:uppercase;margin-top:2px}
.tags{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
.tag{padding:4px 10px;border-radius:20px;font-size:12px;font-weight:600}
.tag-yellow{background:rgba(245,158,11,0.15);color:#fbbf24}
.tag-blue{background:rgba(99,102,241,0.15);color:#a5b4fc}
.tag-red{background:rgba(239,68,68,0.15);color:#fca5a5}
.card-actions{display:flex;gap:8px}
.card-actions>*{flex:1}
.filter-bar{text-align:center;margin-bottom:20px}
.filter-btn{background:rgba(99,102,241,0.1);border:1px solid rgba(99,102,241,0.2);color:#a5b4fc;padding:12px 24px;border-radius:30px;cursor:pointer;font-size:14px;font-weight:600;transition:0.3s}
.filter-btn:hover{background:rgba(99,102,241,0.2)}
.filter-drop{display:none;background:rgba(12,12,22,0.95);border:1px solid rgba(255,255,255,0.08);border-radius:16px;padding:20px;margin-top:10px;text-align:left;backdrop-filter:blur(20px)}
.filter-drop.show{display:block}
.filter-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-bottom:14px}
.form-box{max-width:440px;margin:60px auto;background:rgba(12,12,22,0.9);border:1px solid rgba(255,255,255,0.08);border-radius:20px;padding:32px;backdrop-filter:blur(20px)}
.form-box h2{font-size:26px;font-weight:800;text-align:center;margin-bottom:4px;background:linear-gradient(135deg,#6366f1,#818cf8);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.form-box .sub{text-align:center;color:#64748b;margin-bottom:24px;font-size:14px}
.form-group{margin-bottom:16px}
.form-group label{display:block;margin-bottom:6px;font-weight:600;color:#94a3b8;font-size:14px}
.detail-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin:16px 0}
.detail-item{background:rgba(0,0,0,0.2);padding:12px;border-radius:10px}
.detail-lbl{font-size:11px;color:#64748b;text-transform:uppercase;margin-bottom:4px}
.detail-val{font-weight:600}
.code-box{font-size:28px;font-weight:800;letter-spacing:6px;color:#34d399;text-align:center;padding:16px;background:rgba(0,0,0,0.3);border-radius:10px;margin:10px 0}
.purchase-card{background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:16px;padding:20px;margin-bottom:12px}
.empty{text-align:center;padding:60px 20px;color:#64748b}
.empty-icon{font-size:56px;margin-bottom:12px}
table{width:100%;border-collapse:collapse}
th{background:rgba(0,0,0,0.3);padding:10px 14px;text-align:left;font-weight:600;color:#94a3b8;font-size:12px;text-transform:uppercase}
td{padding:10px 14px;border-top:1px solid rgba(255,255,255,0.04)}
.profile-section{max-width:600px;margin:0 auto}
.profile-card{background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:16px;padding:24px;margin-bottom:16px}
.avatar{width:50px;height:50px;background:linear-gradient(135deg,#6366f1,#4f46e5);border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:22px}
.flex{display:flex;align-items:center;gap:12px}
@media(max-width:768px){
.grid{grid-template-columns:1fr}
.page-title{font-size:26px}
.sidebar{width:280px}
}
</style>'''

SCRIPT = '''
<script>
function toggleSidebar(){document.getElementById('sidebar').classList.toggle('open');document.getElementById('overlay').classList.toggle('show');document.getElementById('burger').classList.toggle('open')}
function closeSidebar(){document.getElementById('sidebar').classList.remove('open');document.getElementById('overlay').classList.remove('show');document.getElementById('burger').classList.remove('open')}
function toggleFilter(){document.getElementById('filterDrop').classList.toggle('show')}
function openModal(id){document.getElementById(id).classList.add('show')}
function closeModal(id){document.getElementById(id).classList.remove('show')}
function copyText(t){navigator.clipboard.writeText(t).then(()=>{let e=document.createElement('div');e.style.cssText='position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:linear-gradient(135deg,#6366f1,#4f46e5);color:#fff;padding:12px 24px;border-radius:30px;font-weight:600;z-index:999;box-shadow:0 8px 25px rgba(99,102,241,0.5)';e.textContent='Скопировано!';document.body.appendChild(e);setTimeout(()=>{e.style.opacity='0';e.style.transition='0.3s';setTimeout(()=>e.remove(),300)},2000)})}
function getCode(i){let b=event.target;b.disabled=true;b.textContent='Загрузка...';fetch('/get_code/'+i).then(r=>r.json()).then(d=>{if(d.code){document.getElementById('code-'+i).innerHTML='<div class="code-box">'+d.code+'</div>';b.style.display='none'}else{alert('Ошибка: '+(d.error||'не найдено'))}}).catch(e=>alert('Ошибка')).finally(()=>{b.disabled=false;b.textContent='Получить код'})}
</script>
'''

def navbar():
    if g.user:
        return f'''<div class="navbar">
            <a href="/" class="logo"><span>Vest Accs</span></a>
            <div style="display:flex;align-items:center;gap:12px">
                <span class="balance-badge">{g.user["balance"]:.0f} ₽</span>
                <a href="/deposit" class="btn btn-primary btn-sm">+</a>
                <button class="burger" id="burger" onclick="toggleSidebar()"><span></span><span></span><span></span></button>
            </div>
        </div>
        <div class="overlay" id="overlay" onclick="closeSidebar()"></div>
        <div class="sidebar" id="sidebar">
            <a href="/profile">👤 Профиль</a>
            <a href="/my_purchases">📦 Мои покупки</a>
            <a href="#" onclick="openModal('sellModal');closeSidebar()">📱 Выставить аккаунт</a>
            <div class="divider"></div>
            <a href="/deposit">💰 Пополнить баланс</a>
            <a href="/logout" style="color:#fca5a5">🚪 Выйти</a>
            {f'<div class="divider"></div><a href="/admin">⚙️ Админ-панель</a>' if g.user["is_admin"] else ""}
        </div>'''
    return f'''<div class="navbar">
        <a href="/" class="logo"><span>Vest Accs</span></a>
        <div style="display:flex;gap:8px">
            <a href="/login" class="btn btn-ghost btn-sm">Войти</a>
            <a href="/register" class="btn btn-primary btn-sm">Регистрация</a>
        </div>
    </div>'''

def sell_modal():
    if not g.user: return ''
    extra = ''
    if session.get('verify_phone'):
        extra += '''<form method="POST" action="/profile" style="margin-top:12px;padding:14px;background:rgba(0,0,0,0.2);border-radius:10px"><input type="hidden" name="action" value="confirm_code"><label style="display:block;margin-bottom:6px;color:#94a3b8;font-size:13px">Код из Telegram</label><input type="text" name="code" placeholder="12345" required><button type="submit" class="btn btn-success btn-sm" style="width:100%;margin-top:8px">Подтвердить</button></form>'''
    if session.get('2fa_needed'):
        extra += '''<form method="POST" action="/profile" style="margin-top:12px;padding:14px;background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.2);border-radius:10px"><input type="hidden" name="action" value="confirm_2fa"><label style="display:block;margin-bottom:6px;color:#fbbf24;font-size:13px">Пароль 2FA</label><input type="password" name="password_2fa" required><button type="submit" class="btn btn-sm" style="width:100%;margin-top:8px;background:#f59e0b;color:#000">Подтвердить</button></form>'''
    if session.get('phone_verified'):
        extra += '<div style="margin-top:12px;padding:14px;background:rgba(16,185,129,0.08);border:1px solid rgba(16,185,129,0.2);border-radius:10px;text-align:center"><p style="color:#34d399;font-size:14px">Номер подтвержден!</p><a href="/sell" class="btn btn-primary btn-sm" style="margin-top:8px">Заполнить данные</a></div>'
    
    return f'''<div class="modal" id="sellModal">
        <div class="modal-bg" onclick="closeModal('sellModal')"></div>
        <div class="modal-content">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px"><h3 style="font-size:20px;font-weight:700">📱 Выставить аккаунт</h3><button onclick="closeModal('sellModal')" style="background:transparent;border:none;color:#94a3b8;font-size:24px;cursor:pointer">&times;</button></div>
            <form method="POST" action="/profile">
                <input type="hidden" name="action" value="verify_phone">
                <label style="display:block;margin-bottom:6px;color:#94a3b8;font-size:13px">Номер телефона</label>
                <input type="text" name="phone" placeholder="+79001234567" required>
                <button type="submit" class="btn btn-primary" style="width:100%;justify-content:center">Отправить код</button>
            </form>
            {extra}
        </div>
    </div>'''

@app.route('/')
def index():
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT a.*, u.username as seller_name FROM accounts a JOIN users u ON a.seller_id = u.id WHERE a.is_sold = FALSE ORDER BY a.created_at DESC")
            accounts = cur.fetchall()
        
        cards = ''
        for a in accounts:
            tags = ''
            if a['has_2fa']: tags += '<span class="tag tag-yellow">2FA</span>'
            if a['spamblock']: tags += '<span class="tag tag-red">Спамблок</span>'
            tags += f'<span class="tag tag-blue">{a["country"] or "?"}</span>'
            buy = ''
            if g.user and g.user['id'] != a['seller_id']:
                buy = f'<form action="/buy/{a["id"]}" method="POST" style="flex:1"><button class="btn btn-primary" style="width:100%;justify-content:center">Купить</button></form>'
            cards += f'''<div class="card">
                <div class="card-row"><div><div class="card-title">{a["title"]}</div><div class="card-seller">{a["seller_name"]}</div></div><div class="price-tag">{a["price"]:.0f} ₽</div></div>
                <div class="stats"><div class="stat-box"><div class="stat-val">{a["chats_count"]}</div><div class="stat-lbl">Чаты</div></div><div class="stat-box"><div class="stat-val">{a["channels_count"]}</div><div class="stat-lbl">Каналы</div></div><div class="stat-box"><div class="stat-val">{a["groups_count"]}</div><div class="stat-lbl">Группы</div></div></div>
                <div class="tags">{tags}</div>
                <div class="card-actions"><a href="/account/{a["id"]}" class="btn btn-secondary" style="justify-content:center">Подробнее</a>{buy}</div>
            </div>'''
        if not cards: cards = '<div class="empty"><div class="empty-icon">📭</div><h3>Нет аккаунтов</h3><p>Станьте первым продавцом</p></div>'
        
        return f'''<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Vest Accs</title>{STYLE}</head><body>
            {navbar()}
            {sell_modal() if g.user else ''}
            <div class="container">
                <h1 class="page-title">Маркетплейс Telegram</h1>
                <p class="page-sub">Покупайте и продавайте аккаунты</p>
                {flash_msgs()}
                <div class="filter-bar">
                    <button onclick="toggleFilter()" class="filter-btn">🔍 Фильтры</button>
                    <div class="filter-drop" id="filterDrop">
                        <form action="/filter" method="GET">
                            <div class="filter-grid">
                                <input type="text" name="q" placeholder="Поиск...">
                                <input type="text" name="country" placeholder="Страна...">
                                <input type="text" name="origin" placeholder="Происхождение...">
                                <select name="2fa"><option value="">2FA</option><option value="yes">Есть</option><option value="no">Нет</option></select>
                                <select name="spamblock"><option value="">Спамблок</option><option value="yes">Есть</option><option value="no">Нет</option></select>
                                <input type="number" name="min_chats" placeholder="Мин. чатов">
                            </div>
                            <div style="display:flex;gap:8px;justify-content:center"><button type="submit" class="btn btn-primary btn-sm">Применить</button><a href="/" class="btn btn-secondary btn-sm">Сбросить</a></div>
                        </form>
                    </div>
                </div>
                <div class="grid">{cards}</div>
            </div>
            {SCRIPT}</body></html>'''
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        return f'<h1>Ошибка: {e}</h1>', 500

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if not username or not password:
            flash('Заполните все поля', 'error')
        else:
            try:
                db = get_db()
                with db.cursor() as cur:
                    cur.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s)", (username, hash_password(password)))
                db.commit()
                flash('Регистрация успешна!', 'success')
                return redirect(url_for('login'))
            except psycopg2.IntegrityError:
                db.rollback()
                flash('Пользователь существует', 'error')
    return f'''<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Регистрация</title>{STYLE}</head><body>
        <div class="navbar"><a href="/" class="logo"><span>Vest Accs</span></a></div>
        <div class="form-box"><h2>Регистрация</h2><p class="sub">Создайте аккаунт</p>{flash_msgs()}
            <form method="POST">
                <div class="form-group"><label>Логин</label><input type="text" name="username" required></div>
                <div class="form-group"><label>Пароль</label><input type="password" name="password" required></div>
                <button type="submit" class="btn btn-primary" style="width:100%;justify-content:center;padding:14px">Зарегистрироваться</button>
            </form>
            <p style="text-align:center;margin-top:16px;color:#64748b">Есть аккаунт? <a href="/login" style="color:#818cf8">Войти</a></p>
        </div></body></html>'''

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        try:
            db = get_db()
            with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("SELECT * FROM users WHERE username = %s", (username,))
                user = cur.fetchone()
                if user and verify_password(password, user['password_hash']):
                    session['user_id'] = user['id']
                    session.permanent = True
                    return redirect(url_for('index'))
            flash('Неверный логин или пароль', 'error')
        except Exception as e:
            flash(f'Ошибка: {e}', 'error')
    return f'''<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Вход</title>{STYLE}</head><body>
        <div class="navbar"><a href="/" class="logo"><span>Vest Accs</span></a></div>
        <div class="form-box"><h2>Вход</h2><p class="sub">Войдите в аккаунт</p>{flash_msgs()}
            <form method="POST">
                <div class="form-group"><label>Логин</label><input type="text" name="username" required></div>
                <div class="form-group"><label>Пароль</label><input type="password" name="password" required></div>
                <button type="submit" class="btn btn-primary" style="width:100%;justify-content:center;padding:14px">Войти</button>
            </form>
            <p style="text-align:center;margin-top:16px;color:#64748b">Нет аккаунта? <a href="/register" style="color:#818cf8">Создать</a></p>
        </div></body></html>'''

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/deposit', methods=['GET', 'POST'])
@login_required
def deposit():
    if request.method == 'POST':
        amount = request.form.get('amount', 0, type=float)
        if amount <= 0:
            flash('Сумма должна быть положительной', 'error')
        else:
            db = get_db()
            with db.cursor() as cur:
                cur.execute("UPDATE users SET balance = balance + %s WHERE id = %s", (amount, g.user['id']))
            flash(f'Пополнено на {amount} ₽', 'success')
            return redirect(url_for('index'))
    return f'''<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Пополнение</title>{STYLE}</head><body>
        <div class="navbar"><a href="/" class="logo"><span>Vest Accs</span></a><span class="balance-badge">{g.user["balance"]:.2f} ₽</span></div>
        <div class="form-box"><h2>Пополнение</h2><p class="sub">Баланс: <strong style="color:#34d399">{g.user["balance"]:.2f} ₽</strong></p>{flash_msgs()}
            <form method="POST"><div class="form-group"><label>Сумма</label><input type="number" name="amount" step="0.01" required></div>
                <button type="submit" class="btn btn-success" style="width:100%;justify-content:center;padding:14px">Пополнить</button>
            </form>
        </div></body></html>'''

@app.route('/filter', methods=['GET'])
def filter_accounts():
    try:
        q = request.args.get('q', '').strip()
        country = request.args.get('country', '').strip()
        origin = request.args.get('origin', '').strip()
        fa2 = request.args.get('2fa', '').strip()
        sb = request.args.get('spamblock', '').strip()
        mc = request.args.get('min_chats', type=int)
        db = get_db()
        conds = ["a.is_sold = FALSE"]
        params = []
        if q: conds.append("a.title ILIKE %s"); params.append(f"%{q}%")
        if country: conds.append("a.country ILIKE %s"); params.append(f"%{country}%")
        if origin: conds.append("a.origin ILIKE %s"); params.append(f"%{origin}%")
        if fa2 == 'yes': conds.append("a.has_2fa = TRUE")
        elif fa2 == 'no': conds.append("a.has_2fa = FALSE")
        if sb == 'yes': conds.append("a.spamblock = TRUE")
        elif sb == 'no': conds.append("a.spamblock = FALSE")
        if mc is not None: conds.append("a.chats_count >= %s"); params.append(mc)
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(f"SELECT a.*, u.username as seller_name FROM accounts a JOIN users u ON a.seller_id = u.id WHERE {' AND '.join(conds)} ORDER BY a.created_at DESC", params)
            accounts = cur.fetchall()
        cards = ''
        for a in accounts:
            buy = ''
            if g.user and g.user['id'] != a['seller_id']:
                buy = f'<form action="/buy/{a["id"]}" method="POST" style="flex:1"><button class="btn btn-primary" style="width:100%;justify-content:center">Купить</button></form>'
            cards += f'''<div class="card"><div class="card-row"><div><div class="card-title">{a["title"]}</div><div class="card-seller">{a["seller_name"]}</div></div><div class="price-tag">{a["price"]:.0f} ₽</div></div><div class="stats"><div class="stat-box"><div class="stat-val">{a["chats_count"]}</div><div class="stat-lbl">Чаты</div></div><div class="stat-box"><div class="stat-val">{a["channels_count"]}</div><div class="stat-lbl">Каналы</div></div><div class="stat-box"><div class="stat-val">{a["groups_count"]}</div><div class="stat-lbl">Группы</div></div></div><div class="card-actions"><a href="/account/{a["id"]}" class="btn btn-secondary" style="justify-content:center">Подробнее</a>{buy}</div></div>'''
        if not cards: cards = '<div class="empty"><div class="empty-icon">🔍</div><h3>Ничего не найдено</h3></div>'
        return f'''<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Поиск</title>{STYLE}</head><body>{navbar()}<div class="container"><h1 class="page-title">Результаты</h1><p class="page-sub">Найдено: {len(accounts)}</p><div class="grid">{cards}</div></div></body></html>'''
    except Exception as e:
        return f'<h1>Ошибка: {e}</h1>', 500

@app.route('/account/<int:account_id>')
def account_detail(account_id):
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT a.*, u.username as seller_name FROM accounts a JOIN users u ON a.seller_id = u.id WHERE a.id = %s", (account_id,))
            a = cur.fetchone()
        if not a: flash('Не найден', 'error'); return redirect(url_for('index'))
        buy = ''
        if g.user and g.user['id'] != a['seller_id'] and not a['is_sold']:
            buy = f'<form action="/buy/{a["id"]}" method="POST"><button class="btn btn-primary" style="width:100%;justify-content:center;padding:14px">Купить аккаунт</button></form>'
        desc = f'<div style="background:rgba(0,0,0,0.2);padding:14px;border-radius:10px;margin:14px 0"><div style="font-size:11px;color:#64748b;text-transform:uppercase">Описание</div><p style="margin-top:4px">{a["description"]}</p></div>' if a.get('description') else ''
        return f'''<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>{a["title"]}</title>{STYLE}</head><body>
            <div class="navbar"><a href="/" class="logo"><span>Vest Accs</span></a><a href="/" class="btn btn-secondary btn-sm">← Назад</a></div>
            <div class="container" style="max-width:700px"><div class="card" style="padding:24px"><div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:14px;margin-bottom:16px"><div><h2 style="font-size:24px;font-weight:800">{a["title"]}</h2><p style="color:#64748b">{a["seller_name"]}</p></div><div style="background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.2);padding:12px 18px;border-radius:14px;text-align:center"><div style="font-size:11px;color:#64748b">Цена</div><div style="font-size:22px;font-weight:800;color:#34d399">{a["price"]:.2f} ₽</div></div></div>
            <div class="detail-grid"><div class="detail-item"><div class="detail-lbl">Страна</div><div class="detail-val">{a["country"] or "-"}</div></div><div class="detail-item"><div class="detail-lbl">2FA</div><div class="detail-val">{"Да" if a["has_2fa"] else "Нет"}</div></div><div class="detail-item"><div class="detail-lbl">Спамблок</div><div class="detail-val">{"Есть" if a["spamblock"] else "Нет"}</div></div><div class="detail-item"><div class="detail-lbl">Чаты</div><div class="detail-val">{a["chats_count"]}</div></div><div class="detail-item"><div class="detail-lbl">Каналы</div><div class="detail-val">{a["channels_count"]}</div></div><div class="detail-item"><div class="detail-lbl">Группы</div><div class="detail-val">{a["groups_count"]}</div></div></div>
            {desc}{buy}</div></div></body></html>'''
    except Exception as e:
        return f'<h1>Ошибка: {e}</h1>', 500

@app.route('/buy/<int:account_id>', methods=['POST'])
@login_required
def buy_account(account_id):
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT * FROM accounts WHERE id = %s AND is_sold = FALSE", (account_id,))
            acc = cur.fetchone()
            if not acc: flash('Недоступен', 'error'); return redirect(url_for('index'))
            if g.user['balance'] < acc['price']: flash('Недостаточно средств', 'error'); return redirect(url_for('deposit'))
            seller_earn = acc['price'] * (1 - COMMISSION)
            cur.execute("UPDATE users SET balance = balance - %s WHERE id = %s", (acc['price'], g.user['id']))
            cur.execute("UPDATE users SET balance = balance + %s WHERE id = %s", (seller_earn, acc['seller_id']))
            cur.execute("UPDATE accounts SET is_sold = TRUE WHERE id = %s", (account_id,))
            cur.execute("INSERT INTO purchases (buyer_id, account_id, phone_number) VALUES (%s, %s, %s) RETURNING id", (g.user['id'], account_id, 'Загрузка...'))
            pid = cur.fetchone()['id']
            db.commit()
            phone = extract_phone(acc['session_string'])
            if phone:
                cur.execute("UPDATE purchases SET phone_number = %s WHERE id = %s", (phone, pid))
                db.commit()
            flash('Покупка успешна!', 'success')
            return redirect(url_for('my_purchases'))
    except Exception as e:
        flash(f'Ошибка: {e}', 'error')
        return redirect(url_for('index'))

def extract_phone(ss):
    try:
        c = TelegramClient(StringSession(ss), API_ID, API_HASH); c.connect()
        if c.is_user_authorized(): me = c.get_me(); c.disconnect(); return me.phone or "Скрыт"
        c.disconnect()
    except: pass
    return "Скрыт"

@app.route('/my_purchases')
@login_required
def my_purchases():
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT p.*, a.title FROM purchases p JOIN accounts a ON p.account_id = a.id WHERE p.buyer_id = %s ORDER BY p.id DESC", (g.user['id'],))
            purchases = cur.fetchall()
        items = ''
        for p in purchases:
            cb = ''
            if not p['code_retrieved']:
                cb = f'<button onclick="getCode({p["id"]})" class="btn btn-primary" style="width:100%;justify-content:center">Получить код</button>'
            items += f'''<div class="purchase-card"><h3 style="margin-bottom:6px">{p["title"]}</h3><p style="color:#64748b;font-size:13px;margin-bottom:10px">{p["purchase_date"].strftime("%d.%m.%Y %H:%M") if p["purchase_date"] else ""}</p>
                <div style="background:rgba(0,0,0,0.2);padding:12px;border-radius:10px;margin-bottom:10px">📱 Номер: <strong>{p["phone_number"]}</strong> <button onclick="copyText('{p["phone_number"]}')" class="btn btn-secondary btn-sm" style="margin-left:6px">📋</button></div>
                <div id="code-{p["id"]}"></div>{cb}</div>'''
        if not items: items = '<div class="empty"><div class="empty-icon">🛒</div><h3>Нет покупок</h3><a href="/" class="btn btn-primary btn-sm" style="margin-top:10px">К покупкам</a></div>'
        return f'''<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Покупки</title>{STYLE}</head><body>{navbar()}<div class="container"><h2 style="font-size:26px;font-weight:800;margin-bottom:20px">Мои покупки</h2>{items}</div>{SCRIPT}</body></html>'''
    except Exception as e:
        return f'<h1>Ошибка: {e}</h1>', 500

@app.route('/get_code/<int:pid>')
@login_required
def get_code(pid):
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT p.*, a.session_string FROM purchases p JOIN accounts a ON p.account_id = a.id WHERE p.id = %s AND p.buyer_id = %s", (pid, g.user['id']))
            p = cur.fetchone()
            if not p: return jsonify({'error': 'Не найдена'}), 404
            code = extract_code(p['session_string'])
            if code:
                cur.execute("UPDATE purchases SET code_retrieved = TRUE WHERE id = %s", (pid,))
                db.commit()
                return jsonify({'code': code})
            return jsonify({'error': 'Код не найден'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def extract_code(ss):
    c = None
    try:
        c = TelegramClient(StringSession(ss), API_ID, API_HASH); c.connect()
        if not c.is_user_authorized(): return None
        for d in c.get_dialogs(limit=10):
            try:
                for m in c.get_messages(d, limit=10):
                    if m.message:
                        codes = re.findall(r'\b\d{5}\b', m.message)
                        if codes: return codes[-1]
            except: continue
    except: pass
    finally:
        if c:
            try: c.disconnect()
            except: pass
    return None

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'verify_phone':
            phone = request.form.get('phone', '').strip()
            if not phone.startswith('+'): phone = '+' + phone
            result = send_code(phone)
            if result:
                session['verify_phone'] = phone; session['code_hash'] = result
                flash('Код отправлен!', 'info')
            else: flash('Ошибка отправки', 'error')
        elif action == 'confirm_code':
            code = request.form.get('code', '').strip()
            phone = session.get('verify_phone', ''); code_hash = session.get('code_hash', '')
            if not phone or not code_hash: flash('Сессия истекла', 'error'); return redirect(url_for('profile'))
            try:
                c = TelegramClient(StringSession(), API_ID, API_HASH); c.connect()
                try:
                    c.sign_in(phone=phone, code=code, phone_code_hash=code_hash)
                    session['phone_verified'] = True; session['session_string'] = c.session.save()
                    session.pop('2fa_needed', None); flash('Подтвержден!', 'success')
                except SessionPasswordNeededError:
                    session['2fa_needed'] = True; session['client_temp'] = c.session.save(); flash('Нужен 2FA', 'info')
                except PhoneCodeInvalidError: flash('Неверный код', 'error')
                finally:
                    if not session.get('2fa_needed'): c.disconnect()
            except Exception as e: flash(f'Ошибка: {e}', 'error')
        elif action == 'confirm_2fa':
            pw = request.form.get('password_2fa', '')
            try:
                c = TelegramClient(StringSession(session.get('client_temp', '')), API_ID, API_HASH); c.connect()
                try:
                    c.sign_in(password=pw)
                    session['phone_verified'] = True; session['session_string'] = c.session.save()
                    session.pop('2fa_needed', None); flash('Готово!', 'success')
                except Exception as e: flash(f'Ошибка: {e}', 'error')
                finally: c.disconnect()
            except Exception as e: flash(f'Ошибка: {e}', 'error')
    
    extra = ''
    if session.get('verify_phone'):
        extra += '<form method="POST" style="padding:14px;background:rgba(0,0,0,0.2);border-radius:10px;margin-top:12px"><input type="hidden" name="action" value="confirm_code"><label style="display:block;margin-bottom:6px;color:#94a3b8;font-size:13px">Код из Telegram</label><input type="text" name="code" required><button type="submit" class="btn btn-success btn-sm" style="width:100%;margin-top:8px">Подтвердить</button></form>'
    if session.get('2fa_needed'):
        extra += '<form method="POST" style="padding:14px;background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.2);border-radius:10px;margin-top:12px"><input type="hidden" name="action" value="confirm_2fa"><label style="display:block;margin-bottom:6px;color:#fbbf24;font-size:13px">Пароль 2FA</label><input type="password" name="password_2fa" required><button type="submit" class="btn btn-sm" style="width:100%;margin-top:8px;background:#f59e0b;color:#000">Подтвердить</button></form>'
    if session.get('phone_verified'):
        extra += '<div style="padding:14px;background:rgba(16,185,129,0.08);border:1px solid rgba(16,185,129,0.2);border-radius:10px;margin-top:12px;text-align:center"><p style="color:#34d399">Номер подтвержден!</p><a href="/sell" class="btn btn-primary btn-sm" style="margin-top:8px">Заполнить данные</a></div>'
    
    admin_btn = ''
    if g.user['is_admin']:
        admin_btn = '<a href="/admin" class="btn btn-sm" style="width:100%;justify-content:center;background:#f59e0b;color:#000;margin-top:12px">Админ-панель</a>'
    
    return f'''<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Профиль</title>{STYLE}</head><body>
        {navbar()}
        <div class="container profile-section">
            {flash_msgs()}
            <div class="profile-card"><div class="flex"><div class="avatar">U</div><div><h3>{g.user["username"]}</h3><span class="balance-badge" style="display:inline-block;margin-top:4px">{g.user["balance"]:.2f} ₽</span></div></div></div>
            <div class="profile-card"><h3 style="margin-bottom:16px">📱 Выставить аккаунт</h3>
                <form method="POST"><input type="hidden" name="action" value="verify_phone"><div class="form-group"><label>Номер телефона</label><input type="text" name="phone" placeholder="+79001234567" required></div><button type="submit" class="btn btn-primary" style="width:100%;justify-content:center">Отправить код</button></form>
                {extra}
            </div>
            {admin_btn}
        </div></body></html>'''

def send_code(phone):
    c = None
    try:
        c = TelegramClient(StringSession(), API_ID, API_HASH); c.connect()
        r = c.send_code_request(phone); return r.phone_code_hash
    except: return None
    finally:
        if c:
            try: c.disconnect()
            except: pass

@app.route('/sell', methods=['GET', 'POST'])
@login_required
def sell_account():
    if not session.get('phone_verified'): flash('Подтвердите номер', 'error'); return redirect(url_for('profile'))
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        origin = request.form.get('origin', '').strip()
        desc = request.form.get('description', '').strip()
        price = request.form.get('price', type=float)
        has_2fa = request.form.get('has_2fa') == 'on'
        if not title or not price: flash('Название и цена обязательны', 'error')
        else:
            try:
                ss = session.get('session_string')
                flash('Сбор данных...', 'info')
                ad = gather_data(ss)
                db = get_db()
                with db.cursor() as cur:
                    cur.execute("INSERT INTO accounts (seller_id,title,origin,description,price,session_string,country,has_2fa,spamblock,chats_count,channels_count,groups_count) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (g.user['id'],title,origin,desc,price,ss,ad.get('country',''),ad.get('has_2fa',has_2fa),ad.get('spamblock',False),ad.get('chats_count',0),ad.get('channels_count',0),ad.get('groups_count',0)))
                db.commit()
                for k in ['phone_verified','session_string','verify_phone','code_hash','client_temp','2fa_needed']: session.pop(k, None)
                flash('Аккаунт выставлен!', 'success')
                return redirect(url_for('index'))
            except Exception as e: flash(f'Ошибка: {e}', 'error')
    return f'''<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Продажа</title>{STYLE}</head><body>
        <div class="navbar"><a href="/" class="logo"><span>Vest Accs</span></a><a href="/profile" class="btn btn-secondary btn-sm">← Назад</a></div>
        <div class="form-box" style="max-width:500px"><h2>Выставить аккаунт</h2><p class="sub">Заполните данные</p>{flash_msgs()}
            <form method="POST">
                <div class="form-group"><label>Название *</label><input type="text" name="title" required></div>
                <div class="form-group"><label>Происхождение</label><input type="text" name="origin"></div>
                <div class="form-group"><label>Описание</label><textarea name="description" rows="3"></textarea></div>
                <div class="form-group"><label>Цена (₽) *</label><input type="number" name="price" step="0.01" required></div>
                <label style="display:flex;align-items:center;gap:8px;margin-bottom:16px;cursor:pointer"><input type="checkbox" name="has_2fa" style="width:auto;margin:0"> Есть 2FA</label>
                <button type="submit" class="btn btn-primary" style="width:100%;justify-content:center;padding:14px">Выставить</button>
            </form>
            <p style="text-align:center;color:#64748b;margin-top:12px">Комиссия: 5%</p>
        </div></body></html>'''

def gather_data(ss):
    data = {'country':'','has_2fa':False,'spamblock':False,'chats_count':0,'channels_count':0,'groups_count':0}
    c = None
    try:
        c = TelegramClient(StringSession(ss), API_ID, API_HASH); c.connect()
        if not c.is_user_authorized(): return data
        try: c.get_password_hint(); data['has_2fa'] = True
        except: pass
        for d in c.get_dialogs(limit=100):
            if d.is_channel:
                if hasattr(d.entity,'megagroup') and d.entity.megagroup: data['groups_count'] += 1
                else: data['channels_count'] += 1
            else: data['chats_count'] += 1
    except: pass
    finally:
        if c:
            try: c.disconnect()
            except: pass
    return data

@app.route('/admin', methods=['GET', 'POST'])
@login_required
def admin_panel():
    if not g.user['is_admin']: flash('Доступ запрещен', 'error'); return redirect(url_for('index'))
    try:
        db = get_db()
        if request.method == 'POST':
            uid = request.form.get('user_id', type=int); amount = request.form.get('amount', type=float); action = request.form.get('action')
            if uid and amount:
                with db.cursor() as cur:
                    if action == 'add': cur.execute("UPDATE users SET balance = balance + %s WHERE id = %s", (amount, uid))
                    elif action == 'set': cur.execute("UPDATE users SET balance = %s WHERE id = %s", (amount, uid))
                flash('Баланс обновлен', 'success')
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT id, username, balance, is_admin FROM users ORDER BY id")
            users = cur.fetchall()
        opts = ''.join([f'<option value="{u["id"]}">{u["username"]} ({u["balance"]:.2f} ₽)</option>' for u in users])
        rows = ''.join([f'<tr><td>#{u["id"]}</td><td><strong>{u["username"]}</strong></td><td style="color:#34d399;font-weight:600">{u["balance"]:.2f} ₽</td><td>{"✅" if u["is_admin"] else "—"}</td></tr>' for u in users])
        return f'''<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Админ</title>{STYLE}</head><body>
            {navbar()}
            <div class="container"><h2 style="font-size:26px;font-weight:800;margin-bottom:20px">Админ-панель</h2>{flash_msgs()}
                <div class="profile-card"><h3 style="margin-bottom:16px">Изменить баланс</h3><form method="POST">
                    <div class="form-group"><label>Пользователь</label><select name="user_id" required><option value="">Выберите...</option>{opts}</select></div>
                    <div class="form-group"><label>Сумма</label><input type="number" name="amount" step="0.01" required></div>
                    <div style="display:flex;gap:8px"><button type="submit" name="action" value="add" class="btn btn-success" style="flex:1;justify-content:center">Добавить</button><button type="submit" name="action" value="set" class="btn btn-sm" style="flex:1;justify-content:center;background:#f59e0b;color:#000">Установить</button></div>
                </form></div>
                <div class="profile-card" style="overflow-x:auto"><h3 style="margin-bottom:16px">Пользователи</h3><table><thead><tr><th>ID</th><th>Логин</th><th>Баланс</th><th>Админ</th></tr></thead><tbody>{rows}</tbody></table></div>
            </div></body></html>'''
    except Exception as e:
        return f'<h1>Ошибка: {e}</h1>', 500

if __name__ == '__main__':
    with app.app_context(): init_db()
    print("Vest Accs: http://0.0.0.0:5000 | admin:admin123")
    app.run(debug=True, host='0.0.0.0', port=5000)
