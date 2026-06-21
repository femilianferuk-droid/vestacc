import re
import secrets
import traceback
import hashlib
import requests
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
CRYPTO_TOKEN = "499354:AATdkiDyuC1tWd1ro5S5wFw6XcePNUNH5Ph"

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

COUNTRIES = [
    "Россия", "США", "Германия", "Франция", "Италия", "Испания", "Украина", "Беларусь", "Казахстан", "Турция",
    "Китай", "Япония", "Южная Корея", "Индия", "Бразилия", "Мексика", "Канада", "Австралия", "Аргентина", "Чили",
    "Великобритания", "Нидерланды", "Бельгия", "Швейцария", "Австрия", "Польша", "Чехия", "Швеция", "Норвегия", "Дания",
    "Финляндия", "Португалия", "Греция", "Венгрия", "Румыния", "Болгария", "Сербия", "Хорватия", "Словакия", "Ирландия",
    "ОАЭ", "Саудовская Аравия", "Катар", "Израиль", "Египет", "ЮАР", "Нигерия", "Кения", "Марокко", "Тунис",
    "Таиланд", "Вьетнам", "Индонезия", "Малайзия", "Филиппины", "Сингапур", "Пакистан", "Бангладеш", "Шри-Ланка", "Мьянма",
    "Колумбия", "Перу", "Венесуэла", "Эквадор", "Боливия", "Уругвай", "Парагвай", "Куба", "Доминикана", "Панама",
    "Новая Зеландия", "Грузия", "Армения", "Азербайджан", "Узбекистан", "Таджикистан", "Кыргызстан", "Туркменистан", "Монголия", "Непал",
    "Исландия", "Люксембург", "Мальта", "Кипр", "Эстония", "Латвия", "Литва", "Словения", "Молдова", "Албания",
    "Ирак", "Иран", "Сирия", "Иордания", "Ливан", "Кувейт", "Бахрейн", "Оман", "Йемен", "Афганистан"
]

ORIGINS = ["Авторег", "Саморег", "Стиллер", "Фишинг"]

def hash_password(password):
    salt = secrets.token_hex(16)
    return f"{salt}${hashlib.sha256((password + salt).encode()).hexdigest()}"

def verify_password(password, hashed):
    try:
        salt, h = hashed.split('$')
        return hashlib.sha256((password + salt).encode()).hexdigest() == h
    except: return False

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
    db = psycopg2.connect(DATABASE_URL)
    db.autocommit = True
    with db.cursor() as cur:
        cur.execute("CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username VARCHAR(100) UNIQUE NOT NULL, password_hash VARCHAR(255) NOT NULL, balance DECIMAL(10,2) DEFAULT 0.00, is_admin BOOLEAN DEFAULT FALSE, sales_count INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT NOW())")
        cur.execute("CREATE TABLE IF NOT EXISTS accounts (id SERIAL PRIMARY KEY, seller_id INTEGER REFERENCES users(id), title VARCHAR(200) NOT NULL, origin VARCHAR(100), description TEXT, price DECIMAL(10,2) NOT NULL, session_string TEXT NOT NULL, country VARCHAR(50), has_2fa BOOLEAN DEFAULT FALSE, spamblock BOOLEAN DEFAULT FALSE, is_premium BOOLEAN DEFAULT FALSE, chats_count INTEGER DEFAULT 0, channels_count INTEGER DEFAULT 0, groups_count INTEGER DEFAULT 0, is_sold BOOLEAN DEFAULT FALSE, created_at TIMESTAMP DEFAULT NOW())")
        cur.execute("CREATE TABLE IF NOT EXISTS purchases (id SERIAL PRIMARY KEY, buyer_id INTEGER REFERENCES users(id), account_id INTEGER REFERENCES accounts(id), phone_number VARCHAR(20), purchase_date TIMESTAMP DEFAULT NOW(), code_retrieved BOOLEAN DEFAULT FALSE)")
        cur.execute("CREATE TABLE IF NOT EXISTS balance_history (id SERIAL PRIMARY KEY, user_id INTEGER REFERENCES users(id), amount DECIMAL(10,2), type VARCHAR(50), description TEXT, created_at TIMESTAMP DEFAULT NOW())")
        cur.execute("CREATE TABLE IF NOT EXISTS withdrawals (id SERIAL PRIMARY KEY, user_id INTEGER REFERENCES users(id), amount_rub DECIMAL(10,2), amount_usdt DECIMAL(10,6), address VARCHAR(200), status VARCHAR(20) DEFAULT 'pending', created_at TIMESTAMP DEFAULT NOW())")
        cur.execute("CREATE TABLE IF NOT EXISTS crypto_invoices (id SERIAL PRIMARY KEY, user_id INTEGER REFERENCES users(id), invoice_id VARCHAR(100), amount_rub DECIMAL(10,2), status VARCHAR(20) DEFAULT 'pending', created_at TIMESTAMP DEFAULT NOW())")
        
        # Обновление существующей структуры под хранение URL ссылки
        cur.execute("ALTER TABLE crypto_invoices ADD COLUMN IF NOT EXISTS pay_url TEXT")
        
        cur.execute("SELECT COUNT(*) FROM users")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO users (username, password_hash, is_admin, balance, sales_count) VALUES (%s, %s, TRUE, 999999.00, 0)", ("admin", hash_password("vest55337q")))
    db.close()

try:
    init_db()
except Exception as e:
    print(f"Ошибка миграции БД: {e}")

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
@import url('https://fonts.googleapis.com/css2?family=Inter:wght=300;400;500;600;700;800;900&display=swap');
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:#080812;color:#e2e8f0;min-height:100vh;overflow-x:hidden}
.navbar{background:rgba(8,8,18,0.92);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border-bottom:1px solid rgba(255,255,255,0.06);padding:12px 20px;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:200}
.logo{font-size:20px;font-weight:800;text-decoration:none;color:#a5b4fc;letter-spacing:-0.5px}
.balance-badge{background:rgba(99,102,241,0.1);border:1px solid rgba(99,102,241,0.2);padding:8px 16px;border-radius:30px;color:#a5b4fc;font-weight:600;font-size:14px}
.burger{width:36px;height:36px;background:transparent;border:none;cursor:pointer;display:flex;flex-direction:column;justify-content:center;align-items:center;gap:5px;padding:6px;z-index:300;position:relative;border-radius:8px}
.burger:hover{background:rgba(255,255,255,0.05)}
.burger span{display:block;width:20px;height:2px;background:#e2e8f0;border-radius:2px;transition:0.3s}
.burger.open span:nth-child(1){transform:rotate(45deg) translate(5px,5px)}
.burger.open span:nth-child(2){opacity:0}
.burger.open span:nth-child(3){transform:rotate(-45deg) translate(5px,-5px)}
.sidebar{position:fixed;top:0;right:-280px;width:260px;height:100vh;background:rgba(10,10,20,0.98);backdrop-filter:blur(30px);-webkit-backdrop-filter:blur(30px);border-left:1px solid rgba(255,255,255,0.06);z-index:250;transition:0.3s ease;padding:70px 16px 16px;display:flex;flex-direction:column;gap:4px;overflow-y:auto}
.sidebar.open{right:0 !important}
.sidebar a{display:flex;align-items:center;gap:10px;padding:12px 14px;color:#cbd5e1;text-decoration:none;border-radius:10px;font-weight:500;transition:0.2s;font-size:14px}
.sidebar a:hover{background:rgba(99,102,241,0.1);color:#fff}
.sidebar .divider{height:1px;background:rgba(255,255,255,0.06);margin:4px 0}
.overlay{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:240;display:none}
.overlay.show{display:block !important}
.modal{position:fixed;top:0;left:0;right:0;bottom:0;z-index:300;display:none;align-items:center;justify-content:center}
.modal.show{display:flex}
.modal-bg{position:absolute;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.7)}
.modal-content{position:relative;background:#111118;border:1px solid rgba(255,255,255,0.08);border-radius:20px;padding:24px;max-width:460px;width:90%;max-height:85vh;overflow-y:auto;z-index:1}
.container{max-width:1200px;margin:0 auto;padding:20px 16px;position:relative;z-index:1}
.page-title{font-size:32px;font-weight:900;text-align:center;margin:20px 0 6px;background:linear-gradient(135deg,#e2e8f0,#94a3b8);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.page-sub{text-align:center;color:#64748b;margin-bottom:24px;font-size:15px}
.btn{padding:10px 20px;border:none;border-radius:30px;cursor:pointer;font-size:14px;font-weight:600;text-decoration:none;display:inline-flex;align-items:center;gap:6px;transition:0.3s;font-family:inherit;white-space:nowrap}
.btn-primary{background:linear-gradient(135deg,#6366f1,#4f46e5);color:#fff; text-align:center}
.btn-primary:hover{transform:translateY(-2px);box-shadow:0 8px 25px rgba(99,102,241,0.4)}
.btn-secondary{background:rgba(255,255,255,0.05);color:#e2e8f0;border:1px solid rgba(255,255,255,0.1)}
.btn-secondary:hover{background:rgba(255,255,255,0.1)}
.btn-success{background:linear-gradient(135deg,#10b981,#059669);color:#fff}
.btn-success:hover{transform:translateY(-2px);box-shadow:0 8px 25px rgba(16,185,129,0.4)}
.btn-ghost{background:transparent;color:#94a3b8}
.btn-ghost:hover{background:rgba(255,255,255,0.05);color:#fff}
.btn-sm{padding:7px 12px;font-size:13px}
.btn-red{background:rgba(239,68,68,0.15);color:#fca5a5;border:1px solid rgba(239,68,68,0.3)}
input,textarea,select{width:100%;padding:12px 14px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:10px;color:#e2e8f0;font-size:14px;outline:none;transition:0.3s;font-family:inherit;margin-bottom:12px}
input:focus,textarea:focus,select:focus{border-color:#6366f1;box-shadow:0 0 20px rgba(99,102,241,0.15)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
.card{background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:14px;padding:18px;transition:0.3s}
.card:hover{border-color:rgba(99,102,241,0.4);transform:translateY(-2px);box-shadow:0 15px 30px rgba(0,0,0,0.3)}
.card-row{display:flex;justify-content:space-between;align-items:start;margin-bottom:12px}
.card-title{font-weight:700;font-size:16px}
.card-seller{font-size:12px;color:#64748b;margin-top:2px}
.price-tag{background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.2);color:#34d399;padding:5px 12px;border-radius:18px;font-weight:700;font-size:14px}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:5px;margin-bottom:10px}
.stat-box{text-align:center;padding:8px 4px;background:rgba(0,0,0,0.3);border-radius:8px}
.stat-val{font-size:15px;font-weight:700;color:#818cf8}
.stat-lbl{font-size:10px;color:#64748b;text-transform:uppercase;margin-top:1px}
.tags{display:flex;gap:5px;flex-wrap:wrap;margin-bottom:10px}
.tag{padding:3px 8px;border-radius:16px;font-size:11px;font-weight:600}
.tag-yellow{background:rgba(245,158,11,0.15);color:#fbbf24}
.tag-blue{background:rgba(99,102,241,0.15);color:#a5b4fc}
.tag-red{background:rgba(239,68,68,0.15);color:#fca5a5}
.tag-green{background:rgba(16,185,129,0.15);color:#34d399}
.tag-purple{background:rgba(168,85,247,0.15);color:#c084fc}
.card-actions{display:flex;gap:6px}
.card-actions>*{flex:1}
.filter-bar{text-align:center;margin-bottom:20px}
.filter-btn{background:rgba(99,102,241,0.1);border:1px solid rgba(99,102,241,0.2);color:#a5b4fc;padding:10px 20px;border-radius:30px;cursor:pointer;font-size:14px;font-weight:600;transition:0.3s}
.filter-btn:hover{background:rgba(99,102,241,0.2)}
.filter-drop{display:none;background:rgba(12,12,22,0.95);border:1px solid rgba(255,255,255,0.08);border-radius:14px;padding:18px;margin-top:10px;text-align:left;backdrop-filter:blur(20px)}
.filter-drop.show{display:block}
.filter-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin-bottom:12px}
.multiselect{position:relative}
.multiselect-trigger{width:100%;padding:12px 14px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:10px;color:#e2e8f0;font-size:14px;cursor:pointer;text-align:left;margin-bottom:0}
.multiselect-drop{display:none;position:absolute;top:100%;left:0;right:0;background:#111118;border:1px solid rgba(255,255,255,0.08);border-radius:10px;max-height:220px;overflow-y:auto;z-index:50;margin-top:4px}
.multiselect-drop.show{display:block}
.multiselect-search{padding:8px;position:sticky;top:0;background:#111118;z-index:1}
.multiselect-search input{width:100%;padding:8px;margin:0;font-size:13px}
.multiselect-item{padding:8px 14px;cursor:pointer;display:flex;align-items:center;gap:8px;transition:0.2s;font-size:13px}
.multiselect-item:hover{background:rgba(99,102,241,0.1)}
.multiselect-item input[type="checkbox"]{width:auto;margin:0;accent-color:#6366f1}
.selected-tags{display:flex;flex-wrap:wrap;gap:3px;margin-top:5px}
.selected-tag{background:rgba(99,102,241,0.2);color:#a5b4fc;padding:2px 7px;border-radius:16px;font-size:11px;display:flex;align-items:center;gap:3px}
.selected-tag .remove{cursor:pointer;font-size:12px}
.form-box{max-width:420px;margin:50px auto;background:rgba(12,12,22,0.9);border:1px solid rgba(255,255,255,0.08);border-radius:18px;padding:28px;backdrop-filter:blur(20px)}
.form-box h2{font-size:24px;font-weight:800;text-align:center;margin-bottom:4px;background:linear-gradient(135deg,#6366f1,#818cf8);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.form-box .sub{text-align:center;color:#64748b;margin-bottom:20px;font-size:13px}
.form-group{margin-bottom:14px}
.form-group label{display:block;margin-bottom:5px;font-weight:600;color:#94a3b8;font-size:13px}
.detail-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin:14px 0}
.detail-item{background:rgba(0,0,0,0.2);padding:10px;border-radius:8px}
.detail-lbl{font-size:10px;color:#64748b;text-transform:uppercase;margin-bottom:3px}
.detail-val{font-weight:600;font-size:14px}
.code-box{font-size:26px;font-weight:800;letter-spacing:5px;color:#34d399;text-align:center;padding:14px;background:rgba(0,0,0,0.3);border-radius:8px;margin:8px 0}
.purchase-card{background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:14px;padding:18px;margin-bottom:10px}
.empty{text-align:center;padding:50px 20px;color:#64748b}
table{width:100%;border-collapse:collapse}
th{background:rgba(0,0,0,0.3);padding:8px 12px;text-align:left;font-weight:600;color:#94a3b8;font-size:11px;text-transform:uppercase}
td{padding:8px 12px;border-top:1px solid rgba(255,255,255,0.04);font-size:13px}
.profile-section{max-width:550px;margin:0 auto}
.profile-card{background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:14px;padding:20px;margin-bottom:14px}
.avatar{width:44px;height:44px;background:linear-gradient(135deg,#6366f1,#4f46e5);border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:20px}
.flex{display:flex;align-items:center;gap:10px}
.pagination{display:flex;justify-content:center;gap:6px;margin-top:24px;flex-wrap:wrap}
.pagination a,.pagination span{padding:8px 14px;border-radius:8px;text-decoration:none;font-weight:600;font-size:13px}
.pagination a{background:rgba(255,255,255,0.05);color:#e2e8f0;border:1px solid rgba(255,255,255,0.1)}
.pagination a:hover{background:rgba(99,102,241,0.2);border-color:#6366f1}
.pagination .active{background:#6366f1;color:#fff}
.footer{text-align:center;padding:24px 20px;color:#64748b;font-size:12px;border-top:1px solid rgba(255,255,255,0.04);margin-top:40px}
.footer a{color:#a5b4fc;text-decoration:none}
@media(max-width:768px){.grid{grid-template-columns:1fr}.page-title{font-size:24px}.sidebar{width:240px}.filter-grid{grid-template-columns:1fr}}
</style>'''

SCRIPT = '''
<script>
function toggleSidebar(){var s=document.getElementById('sidebar');var o=document.getElementById('overlay');var b=document.getElementById('burger');if(s)s.classList.toggle('open');if(o)o.classList.toggle('show');if(b)b.classList.toggle('open')}
function closeSidebar(){var s=document.getElementById('sidebar');var o=document.getElementById('overlay');var b=document.getElementById('burger');if(s)s.classList.remove('open');if(o)o.classList.remove('show');if(b)b.classList.remove('open')}
function toggleFilter(){document.getElementById('filterDrop').classList.toggle('show')}
function openModal(id){document.getElementById(id).classList.add('show')}
function closeModal(id){document.getElementById(id).classList.remove('show')}
function copyText(t){navigator.clipboard.writeText(t).then(function(){var e=document.createElement('div');e.style.cssText='position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:linear-gradient(135deg,#6366f1,#4f46e5);color:#fff;padding:10px 20px;border-radius:30px;font-weight:600;z-index:999;box-shadow:0 8px 25px rgba(99,102,241,0.5)';e.textContent='Скопировано!';document.body.appendChild(e);setTimeout(function(){e.style.opacity='0';e.style.transition='0.3s';setTimeout(function(){e.remove()},300)},2000)})}
function getCode(i){var b=event.target;b.disabled=true;b.textContent='Загрузка...';fetch('/get_code/'+i).then(function(r){return r.json()}).then(function(d){if(d.code){document.getElementById('code-'+i).innerHTML='<div class="code-box">'+d.code+'</div>';b.style.display='none'}else{alert('Ошибка: '+(d.error||'не найдено'))}}).catch(function(e){alert('Ошибка')}).finally(function(){b.disabled=false;b.textContent='Получить код'})}
function toggleMulti(id){document.getElementById(id).classList.toggle('show')}
function filterMulti(id){var s=document.getElementById(id+'_search').value.toLowerCase();document.querySelectorAll('#'+id+' .multiselect-item').forEach(function(i){i.style.display=i.textContent.toLowerCase().includes(s)?'flex':'none'})}
function updateSelected(id,hiddenId){var cbs=document.querySelectorAll('#'+id+' input[type=checkbox]:checked');var vals=Array.from(cbs).map(function(c){return c.value});document.getElementById(hiddenId).value=vals.join(',');var tags=document.getElementById(id+'_tags');if(tags){tags.innerHTML=vals.map(function(v){return '<span class="selected-tag">'+v+'<span class="remove" onclick="this.parentElement.remove();updateSelected(\''+id+'\',\''+hiddenId+'\')">x</span></span>'}).join('')}}
document.addEventListener('click',function(e){if(!e.target.closest('.multiselect')){document.querySelectorAll('.multiselect-drop.show').forEach(function(d){d.classList.remove('show')})}})
</script>
'''

def render_layout(title, content, show_nav=True):
    nav = navbar() if show_nav else '<div class="navbar"><a href="/" class="logo">Vest Accs</a></div>'
    s_modal = sell_modal() if (show_nav and g.user) else ''
    w_modal = withdraw_modal() if (show_nav and g.user) else ''
    return f'''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0">
    <title>{title}</title>
    {STYLE}
</head>
<body>
    {nav}
    {s_modal}
    {w_modal}
    <div class="container">
        {flash_msgs()}
        {content}
    </div>
    <div class="footer">Vest Accs 2026 | <a href="https://t.me/VestAccsSupport">@VestAccsSupport</a></div>
    {SCRIPT}
</body>
</html>'''

def multiselect_html(id, options, selected=''):
    opts = ''
    sel_list = selected.split(',') if selected else []
    for o in options:
        chk = 'checked' if o in sel_list else ''
        opts += f'<div class="multiselect-item"><input type="checkbox" value="{o}" {chk} onchange="updateSelected(\'{id}\',\'{id}_hidden\')">{o}</div>'
    tags = ''.join([f'<span class="selected-tag">{s}<span class="remove" onclick="this.parentElement.remove();updateSelected(\'{id}\',\'{id}_hidden\')">x</span></span>' for s in sel_list])
    return f'<div class="multiselect"><div class="multiselect-trigger" onclick="toggleMulti(\'{id}_drop\')">Выбрать...</div><div class="multiselect-drop" id="{id}_drop"><div class="multiselect-search"><input type="text" id="{id}_search" placeholder="Поиск..." oninput="filterMulti(\'{id}_drop\')"></div>{opts}</div><div class="selected-tags" id="{id}_tags">{tags}</div><input type="hidden" name="{id}" id="{id}_hidden" value="{selected}"></div>'

def navbar():
    if g.user:
        admin_link = '<div class="divider"></div><a href="/admin">Админ-панель</a>' if g.user["is_admin"] else ''
        return f'<div class="navbar"><a href="/" class="logo">Vest Accs</a><div style="display:flex;align-items:center;gap:10px"><span class="balance-badge">{g.user["balance"]:.0f} ₽</span><a href="/deposit" class="btn btn-primary btn-sm">+</a><button class="burger" id="burger" onclick="toggleSidebar()"><span></span><span></span><span></span></button></div></div><div class="overlay" id="overlay" onclick="closeSidebar()"></div><div class="sidebar" id="sidebar"><a href="/profile">Профиль</a><a href="/my_purchases">Мои покупки</a><a href="#" onclick="openModal(\'sellModal\');closeSidebar()">Выставить аккаунт</a><a href="#" onclick="openModal(\'withdrawModal\');closeSidebar()">Вывод средств</a><div class="divider"></div><a href="/deposit">Пополнить баланс</a><a href="/logout" style="color:#fca5a5">Выйти</a>{admin_link}</div>'
    return '<div class="navbar"><a href="/" class="logo">Vest Accs</a><div style="display:flex;gap:8px"><a href="/login" class="btn btn-ghost btn-sm">Войти</a><a href="/register" class="btn btn-primary btn-sm">Регистрация</a></div></div>'

def sell_modal():
    if not g.user: return ''
    extra = ''
    if session.get('verify_phone'):
        extra += '<form method="POST" action="/profile" style="margin-top:10px;padding:12px;background:rgba(0,0,0,0.2);border-radius:8px"><input type="hidden" name="action" value="confirm_code"><label style="display:block;margin-bottom:5px;color:#94a3b8;font-size:12px">Код из Telegram</label><input type="text" name="code" required><button type="submit" class="btn btn-success btn-sm" style="width:100%;margin-top:6px">Подтвердить</button></form>'
    if session.get('2fa_needed'):
        extra += '<form method="POST" action="/profile" style="margin-top:10px;padding:12px;background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.2);border-radius:8px"><input type="hidden" name="action" value="confirm_2fa"><label style="display:block;margin-bottom:5px;color:#fbbf24;font-size:12px">Пароль 2FA</label><input type="password" name="password_2fa" required><button type="submit" class="btn btn-sm" style="width:100%;margin-top:6px;background:#f59e0b;color:#000">Подтвердить</button></form>'
    if session.get('phone_verified'):
        extra += '<div style="margin-top:10px;padding:12px;background:rgba(16,185,129,0.08);border:1px solid rgba(16,185,129,0.2);border-radius:8px;text-align:center"><p style="color:#34d399;font-size:13px">Номер подтвержден!</p><a href="/sell" class="btn btn-primary btn-sm" style="margin-top:6px">Заполнить данные</a></div>'
    return f'<div class="modal" id="sellModal"><div class="modal-bg" onclick="closeModal(\'sellModal\')"></div><div class="modal-content"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px"><h3 style="font-size:18px;font-weight:700">Выставить аккаунт</h3><button onclick="closeModal(\'sellModal\')" style="background:transparent;border:none;color:#94a3b8;font-size:22px;cursor:pointer">&times;</button></div><form method="POST" action="/profile"><input type="hidden" name="action" value="verify_phone"><label style="display:block;margin-bottom:5px;color:#94a3b8;font-size:12px">Номер телефона</label><input type="text" name="phone" placeholder="+79001234567" required><button type="submit" class="btn btn-primary" style="width:100%;justify-content:center">Отправить код</button></form>{extra}</div></div>'

def withdraw_modal():
    if not g.user: return ''
    can = g.user['balance'] >= 50 and g.user.get('sales_count', 0) >= 1
    c = f'<form method="POST" action="/withdraw"><div class="form-group"><label>Сумма (₽)</label><input type="number" name="amount_rub" step="0.01" max="{g.user["balance"]}" placeholder="Минимум 50 ₽" required></div><p style="color:#64748b;font-size:12px;margin-bottom:12px">Курс: 1 USDT = 90 ₽ | ~<span id="uc">0.00</span> USDT</p><div class="form-group"><label>Адрес TON</label><input type="text" name="address" placeholder="UQ..." required></div><button type="submit" class="btn btn-primary" style="width:100%;justify-content:center">Отправить</button></form><script>document.querySelector("[name=amount_rub]").oninput=function(){{document.getElementById("uc").textContent=(this.value/90).toFixed(6)}}</script>' if can else '<p style="color:#fca5a5;text-align:center;font-size:13px">Нужно: баланс от 50 ₽ и 1 продажа</p>'
    return f'<div class="modal" id="withdrawModal"><div class="modal-bg" onclick="closeModal(\'withdrawModal\')"></div><div class="modal-content"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px"><h3 style="font-size:18px;font-weight:700">Вывод средств</h3><button onclick="closeModal(\'withdrawModal\')" style="background:transparent;border:none;color:#94a3b8;font-size:22px;cursor:pointer">&times;</button></div><p style="color:#64748b;margin-bottom:12px;font-size:13px">Баланс: <strong style="color:#34d399">{g.user["balance"]:.2f} ₽</strong> | Продаж: <strong style="color:#a5b4fc">{g.user.get("sales_count",0)}</strong></p>{c}</div></div>'

def pagination(page, total, base_url='/'):
    if total <= 20: return ''
    pages = (total + 19) // 20
    return '<div class="pagination">' + ''.join([f'<span class="active">{p}</span>' if p == page else f'<a href="{base_url}?page={p}">{p}</a>' for p in range(1, pages + 1)]) + '</div>'

def quick_connect(session_string):
    client = None
    try:
        client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
        client.connect()
        return client
    except:
        if client:
            try: client.disconnect()
            except: pass
        return None

def gather_account_data(session_string):
    data = {'country': '', 'has_2fa': False, 'spamblock': False, 'is_premium': False, 'chats_count': 0, 'channels_count': 0, 'groups_count': 0}
    client = quick_connect(session_string)
    if not client: return data
    try:
        if not client.is_user_authorized(): return data
        try: client.get_password_hint(); data['has_2fa'] = True
        except: pass
        try: me = client.get_me(); data['is_premium'] = getattr(me, 'premium', False)
        except: pass
        try:
            dialogs = client.get_dialogs(limit=50)
            for d in dialogs:
                if d.is_channel:
                    if hasattr(d.entity, 'megagroup') and d.entity.megagroup: data['groups_count'] += 1
                    else: data['channels_count'] += 1
                else: data['chats_count'] += 1
        except: pass
    finally:
        try: client.disconnect()
        except: pass
    return data

def extract_phone_from_session(session_string):
    client = quick_connect(session_string)
    if not client: return "Скрыт"
    try:
        if client.is_user_authorized(): me = client.get_me(); return me.phone if me.phone else "Скрыт"
    finally:
        try: client.disconnect()
        except: pass
    return "Скрыт"

def extract_code_from_session(session_string):
    client = quick_connect(session_string)
    if not client: return None
    try:
        if not client.is_user_authorized(): return None
        for dialog in client.get_dialogs(limit=5):
            try:
                for msg in client.get_messages(dialog, limit=5):
                    if msg.message:
                        codes = re.findall(r'\b\d{5}\b', msg.message)
                        if codes: return codes[-1]
            except: continue
    finally:
        try: client.disconnect()
        except: pass
    return None

def send_verification_code(phone):
    client = None
    try:
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        client.connect()
        result = client.send_code_request(phone)
        return result.phone_code_hash
    except: return None
    finally:
        if client:
            try: client.disconnect()
            except: pass

@app.route('/')
def index():
    try:
        page = request.args.get('page', 1, type=int)
        offset = (page - 1) * 20
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM accounts WHERE is_sold = FALSE")
            total = cur.fetchone()['cnt']
            cur.execute("SELECT a.*, u.username as seller_name FROM accounts a JOIN users u ON a.seller_id = u.id WHERE a.is_sold = FALSE ORDER BY a.created_at DESC LIMIT 20 OFFSET %s", (offset,))
            accounts = cur.fetchall()
        cards = ''
        for a in accounts:
            tags = ''
            if a['has_2fa']: tags += '<span class="tag tag-yellow">2FA</span>'
            if a['spamblock']: tags += '<span class="tag tag-red">Спамблок</span>'
            if a['is_premium']: tags += '<span class="tag tag-purple">Premium</span>'
            tags += f'<span class="tag tag-blue">{a["country"] or "?"}</span><span class="tag tag-green">{a["origin"] or "?"}</span>'
            buy = f'<form action="/buy/{a["id"]}" method="POST" style="flex:1"><button class="btn btn-primary btn-sm" style="width:100%;justify-content:center">Купить</button></form>' if g.user and g.user['id'] != a['seller_id'] else ''
            cards += f'<div class="card"><div class="card-row"><div><div class="card-title">{a["title"]}</div><div class="card-seller">{a["seller_name"]}</div></div><div class="price-tag">{a["price"]:.0f} ₽</div></div><div class="stats"><div class="stat-box"><div class="stat-val">{a["chats_count"]}</div><div class="stat-lbl">Чаты</div></div><div class="stat-box"><div class="stat-val">{a["channels_count"]}</div><div class="stat-lbl">Каналы</div></div><div class="stat-box"><div class="stat-val">{a["groups_count"]}</div><div class="stat-lbl">Группы</div></div></div><div class="tags">{tags}</div><div class="card-actions"><a href="/account/{a["id"]}" class="btn btn-secondary btn-sm" style="justify-content:center">Подробнее</a>{buy}</div></div>'
        if not cards: cards = '<div class="empty"><h3>Нет аккаунтов</h3></div>'
        
        content = f'''<h1 class="page-title">Маркетплейс Telegram</h1><p class="page-sub">Покупайте и продавайте аккаунты</p><div class="filter-bar"><button onclick="toggleFilter()" class="filter-btn">Фильтры</button><div class="filter-drop" id="filterDrop"><form action="/filter" method="GET"><div class="filter-grid"><input type="text" name="q" placeholder="Поиск...">{multiselect_html("country", COUNTRIES)}{multiselect_html("origin", ORIGINS)}<select name="premium"><option value="">Premium</option><option value="yes">Есть</option><option value="no">Нет</option></select><select name="spamblock"><option value="">Спамблок</option><option value="yes">Есть</option><option value="no">Нет</option></select><input type="number" name="min_chats" placeholder="Мин. чатов"></div><div style="display:flex;gap:6px;justify-content:center"><button type="submit" class="btn btn-primary btn-sm">Применить</button><a href="/" class="btn btn-secondary btn-sm">Сбросить</a></div></form></div></div><div class="grid">{cards}</div>{pagination(page, total)}'''
        return render_layout("Vest Accs", content)
    except Exception as e:
        return f'<h1>Ошибка: {e}</h1>', 500

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        u, p = request.form.get('username', '').strip(), request.form.get('password', '').strip()
        if not u or not p: flash('Заполните все поля', 'error')
        else:
            try:
                db = get_db()
                with db.cursor() as cur: cur.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s)", (u, hash_password(p)))
                db.commit(); flash('Регистрация успешна!', 'success'); return redirect(url_for('login'))
            except psycopg2.IntegrityError: db.rollback(); flash('Пользователь существует', 'error')
    
    content = f'''<div class="form-box"><h2>Регистрация</h2><p class="sub">Создайте аккаунт</p><form method="POST"><div class="form-group"><label>Логин</label><input type="text" name="username" required></div><div class="form-group"><label>Пароль</label><input type="password" name="password" required></div><button type="submit" class="btn btn-primary" style="width:100%;justify-content:center;padding:12px">Зарегистрироваться</button></form><p style="text-align:center;margin-top:14px;color:#64748b;font-size:13px">Есть аккаунт? <a href="/login" style="color:#818cf8">Войти</a></p></div>'''
    return render_layout("Регистрация", content, show_nav=False)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u, p = request.form.get('username', '').strip(), request.form.get('password', '').strip()
        try:
            db = get_db()
            with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("SELECT * FROM users WHERE username = %s", (u,))
                user = cur.fetchone()
                if user and verify_password(p, user['password_hash']): session['user_id'] = user['id']; session.permanent = True; return redirect(url_for('index'))
            flash('Неверный логин или пароль', 'error')
        except Exception as e: flash(f'Ошибка: {e}', 'error')
        
    content = f'''<div class="form-box"><h2>Вход</h2><p class="sub">Войдите в аккаунт</p><form method="POST"><div class="form-group"><label>Логин</label><input type="text" name="username" required></div><div class="form-group"><label>Пароль</label><input type="password" name="password" required></div><button type="submit" class="btn btn-primary" style="width:100%;justify-content:center;padding:12px">Войти</button></form><p style="text-align:center;margin-top:14px;color:#64748b;font-size:13px">Нет аккаунта? <a href="/register" style="color:#818cf8">Создать</a></p></div>'''
    return render_layout("Вход", content, show_nav=False)

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('index'))

@app.route('/deposit', methods=['GET', 'POST'])
@login_required
def deposit():
    if request.method == 'POST':
        amount = request.form.get('amount', 0, type=float)
        if amount < 20: flash('Минимум 20 ₽', 'error')
        else:
            try:
                headers = {"Crypto-Pay-API-Token": CRYPTO_TOKEN}
                data = {
                    "asset": "USDT",
                    "amount": str(round(amount / 90, 2)),
                    "description": "Пополнение Vest Accs",
                    "allow_comments": False,
                    "allow_anonymous": False
                }
                r = requests.post("https://pay.crypt.bot/api/createInvoice", json=data, headers=headers, timeout=10)
                resp = r.json()
                if resp.get('ok'):
                    invoice_id = resp['result']['invoice_id']
                    pay_url = resp['result']['pay_url']
                    db = get_db()
                    with db.cursor() as cur: 
                        cur.execute("INSERT INTO crypto_invoices (user_id, invoice_id, amount_rub, pay_url) VALUES (%s,%s,%s,%s)", (g.user['id'], str(invoice_id), amount, pay_url))
                    return redirect(url_for('invoice_page', invoice_id=invoice_id))
                flash(f'Ошибка создания счета: {resp.get("error",{}).get("name","Неизвестная ошибка")}', 'error')
            except Exception as e: flash(f'Ошибка: {e}', 'error')
            
    content = f'''<div class="form-box"><h2>Пополнение</h2><p class="sub">Баланс: <strong style="color:#34d399">{g.user["balance"]:.2f} ₽</strong></p><form method="POST"><div class="form-group"><label>Сумма (от 20 ₽)</label><input type="number" name="amount" step="0.01" min="20" required></div><button type="submit" class="btn btn-success" style="width:100%;justify-content:center;padding:12px">Пополнить через Crypto Bot</button></form></div>'''
    return render_layout("Пополнение баланса", content)

@app.route('/invoice/<invoice_id>')
@login_required
def invoice_page(invoice_id):
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT * FROM crypto_invoices WHERE invoice_id = %s AND user_id = %s", (str(invoice_id), g.user['id']))
            inv = cur.fetchone()
        if not inv:
            flash('Счет не найден', 'error')
            return redirect(url_for('index'))
        
        status_text = "Ожидает оплаты" if inv['status'] == 'pending' else "Оплачен" if inv['status'] == 'paid' else "Отменен"
        status_color = "#f59e0b" if inv['status'] == 'pending' else "#34d399" if inv['status'] == 'paid' else "#ef4444"
        
        content = f'''
        <div class="form-box" style="max-width:480px; margin: 40px auto;">
            <h2>Счет #{inv['invoice_id']}</h2>
            <p class="sub">Пополнение баланса</p>
            
            <div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.06); padding:20px; border-radius:14px; margin-bottom:20px;">
                <div style="display:flex; justify-content:space-between; margin-bottom:10px;">
                    <span style="color:#64748b;">Сумма к оплате:</span>
                    <strong style="color:#fff; font-size:16px;">{inv['amount_rub']:.2f} ₽</strong>
                </div>
                <div style="display:flex; justify-content:space-between; margin-bottom:10px;">
                    <span style="color:#64748b;">Статус:</span>
                    <strong style="color:{status_color};">{status_text}</strong>
                </div>
                <div style="display:flex; justify-content:space-between;">
                    <span style="color:#64748b;">Дата:</span>
                    <span style="color:#94a3b8;">{inv['created_at'].strftime('%d.%m.%Y %H:%M')}</span>
                </div>
            </div>
        '''
        if inv['status'] == 'pending':
            content += f'''
            <div style="display:flex; flex-direction:column; gap:10px;">
                <a href="{inv['pay_url']}" target="_blank" class="btn btn-primary" style="justify-content:center; padding:12px; font-size:15px;">Перейти к оплате</a>
                <a href="/check_invoice/{inv['invoice_id']}" class="btn btn-secondary" style="justify-content:center; padding:12px; font-size:15px;">Проверить оплату</a>
            </div>
            '''
        else:
            content += f'''<a href="/" class="btn btn-secondary" style="width:100%; justify-content:center; padding:12px;">На главную</a>'''
        content += '</div>'
        return render_layout(f"Счет #{inv['invoice_id']}", content)
    except Exception as e:
        return f'<h1>Ошибка: {e}</h1>', 500

@app.route('/check_invoice/<invoice_id>')
@login_required
def check_invoice(invoice_id):
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT * FROM crypto_invoices WHERE invoice_id = %s AND user_id = %s", (str(invoice_id), g.user['id']))
            inv = cur.fetchone()
        if not inv:
            flash('Счет не найден', 'error')
            return redirect(url_for('index'))
        
        if inv['status'] == 'paid':
            flash('Счет уже оплачен!', 'success')
            return redirect(url_for('invoice_page', invoice_id=invoice_id))
            
        headers = {"Crypto-Pay-API-Token": CRYPTO_TOKEN}
        r = requests.get("https://pay.crypt.bot/api/getInvoices", params={"invoice_ids": str(invoice_id)}, headers=headers, timeout=10)
        resp = r.json()
        
        if resp.get('ok') and resp.get('result', {}).get('items'):
            remote_inv = resp['result']['items'][0]
            if remote_inv.get('status') == 'paid':
                with db.cursor() as cur:
                    cur.execute("SELECT status FROM crypto_invoices WHERE invoice_id = %s FOR UPDATE", (str(invoice_id),))
                    if cur.fetchone()[0] == 'pending':
                        cur.execute("UPDATE users SET balance = balance + %s WHERE id = %s", (inv['amount_rub'], inv['user_id']))
                        cur.execute("INSERT INTO balance_history (user_id, amount, type, description) VALUES (%s,%s,%s,%s)", (inv['user_id'], inv['amount_rub'], 'deposit', 'Пополнение'))
                        cur.execute("UPDATE crypto_invoices SET status = 'paid' WHERE invoice_id = %s", (str(invoice_id),))
                flash('Оплата подтверждена! Баланс пополнен.', 'success')
            else:
                flash('Оплата еще не поступила. Попробуйте еще раз через минуту.', 'info')
        else:
            flash('Не удалось проверить статус. Попробуйте позже.', 'error')
            
        return redirect(url_for('invoice_page', invoice_id=invoice_id))
    except Exception as e:
        flash(f'Ошибка проверки: {e}', 'error')
        return redirect(url_for('invoice_page', invoice_id=invoice_id))

@app.route('/crypto_callback', methods=['POST'])
def crypto_callback():
    try:
        data = request.json
        if data.get('status') == 'paid':
            db = get_db()
            with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("SELECT * FROM crypto_invoices WHERE invoice_id = %s AND status = 'pending'", (str(data['invoice_id']),))
                inv = cur.fetchone()
                if inv:
                    cur.execute("UPDATE users SET balance = balance + %s WHERE id = %s", (inv['amount_rub'], inv['user_id']))
                    cur.execute("INSERT INTO balance_history (user_id, amount, type, description) VALUES (%s,%s,%s,%s)", (inv['user_id'], inv['amount_rub'], 'deposit', 'Пополнение'))
                    cur.execute("UPDATE crypto_invoices SET status = 'paid' WHERE invoice_id = %s", (str(data['invoice_id']),))
        return jsonify({'ok': True})
    except: return jsonify({'ok': False})

@app.route('/filter', methods=['GET'])
def filter_accounts():
    try:
        page = request.args.get('page', 1, type=int); offset = (page - 1) * 20
        q = request.args.get('q', '').strip(); countries = request.args.get('country', '').strip()
        origins = request.args.get('origin', '').strip(); premium = request.args.get('premium', '').strip()
        sb = request.args.get('spamblock', '').strip(); mc = request.args.get('min_chats', type=int)
        db = get_db(); conds = ["a.is_sold = FALSE"]; params = []
        if q: conds.append("a.title ILIKE %s"); params.append(f"%{q}%")
        if countries:
            clist = [c.strip() for c in countries.split(',') if c.strip()]
            if clist: conds.append(f"({' OR '.join(['a.country = %s']*len(clist))})"); params.extend(clist)
        if origins:
            olist = [o.strip() for o in origins.split(',') if o.strip()]
            if olist: conds.append(f"({' OR '.join(['a.origin = %s']*len(olist))})"); params.extend(olist)
        if premium == 'yes': conds.append("a.is_premium = TRUE")
        elif premium == 'no': conds.append("a.is_premium = FALSE")
        if sb == 'yes': conds.append("a.spamblock = TRUE")
        elif sb == 'no': conds.append("a.spamblock = FALSE")
        if mc is not None: conds.append("a.chats_count >= %s"); params.append(mc)
        where = ' AND '.join(conds)
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(f"SELECT COUNT(*) as cnt FROM accounts a WHERE {where}", params)
            total = cur.fetchone()['cnt']
            cur.execute(f"SELECT a.*, u.username as seller_name FROM accounts a JOIN users u ON a.seller_id = u.id WHERE {where} ORDER BY a.created_at DESC LIMIT 20 OFFSET %s", params + [offset])
            accounts = cur.fetchall()
        cards = ''.join([f'<div class="card"><div class="card-row"><div><div class="card-title">{a["title"]}</div><div class="card-seller">{a["seller_name"]}</div></div><div class="price-tag">{a["price"]:.0f} ₽</div></div><div class="card-actions"><a href="/account/{a["id"]}" class="btn btn-secondary btn-sm" style="justify-content:center">Подробнее</a>' + (f'<form action="/buy/{a["id"]}" method="POST" style="flex:1"><button class="btn btn-primary btn-sm" style="width:100%;justify-content:center">Купить</button></form>' if g.user and g.user['id'] != a['seller_id'] else '') + '</div></div>' for a in accounts])
        if not cards: cards = '<div class="empty"><h3>Ничего не найдено</h3></div>'
        
        content = f'''<h1 class="page-title">Результаты</h1><p class="page-sub">Найдено: {total}</p><div class="grid">{cards}</div>{pagination(page, total, "/filter?" + "&".join([f"{k}={v}" for k,v in request.args.items() if k != "page"]))}'''
        return render_layout("Результаты поиска", content)
    except Exception as e: return f'<h1>Ошибка: {e}</h1>', 500

@app.route('/account/<int:account_id>')
def account_detail(account_id):
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT a.*, u.username as seller_name FROM accounts a JOIN users u ON a.seller_id = u.id WHERE a.id = %s", (account_id,))
            a = cur.fetchone()
        if not a: flash('Не найден', 'error'); return redirect(url_for('index'))
        buy = f'<form action="/buy/{a["id"]}" method="POST"><button class="btn btn-primary" style="width:100%;justify-content:center;padding:12px">Купить аккаунт</button></form>' if g.user and g.user['id'] != a['seller_id'] and not a['is_sold'] else ''
        desc = f'<div style="background:rgba(0,0,0,0.2);padding:12px;border-radius:8px;margin:12px 0"><div style="font-size:10px;color:#64748b;text-transform:uppercase">Описание</div><p style="margin-top:4px;font-size:14px">{a["description"]}</p></div>' if a.get('description') else ''
        
        content = f'''<div style="max-width:650px;margin:0 auto;"><div class="card" style="padding:20px"><div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:12px;margin-bottom:14px"><div><h2 style="font-size:22px;font-weight:800">{a["title"]}</h2><p style="color:#64748b;font-size:13px">{a["seller_name"]}</p></div><div style="background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.2);padding:10px 16px;border-radius:12px;text-align:center"><div style="font-size:10px;color:#64748b">Цена</div><div style="font-size:20px;font-weight:800;color:#34d399">{a["price"]:.2f} ₽</div></div></div><div class="detail-grid"><div class="detail-item"><div class="detail-lbl">Страна</div><div class="detail-val">{a["country"] or "-"}</div></div><div class="detail-item"><div class="detail-lbl">Происхождение</div><div class="detail-val">{a["origin"] or "-"}</div></div><div class="detail-item"><div class="detail-lbl">2FA</div><div class="detail-val">{"Да" if a["has_2fa"] else "Нет"}</div></div><div class="detail-item"><div class="detail-lbl">Спамблок</div><div class="detail-val">{"Есть" if a["spamblock"] else "Нет"}</div></div><div class="detail-item"><div class="detail-lbl">Premium</div><div class="detail-val">{"Да" if a["is_premium"] else "Нет"}</div></div><div class="detail-item"><div class="detail-lbl">Чаты</div><div class="detail-val">{a["chats_count"]}</div></div><div class="detail-item"><div class="detail-lbl">Каналы</div><div class="detail-val">{a["channels_count"]}</div></div><div class="detail-item"><div class="detail-lbl">Группы</div><div class="detail-val">{a["groups_count"]}</div></div></div>{desc}{buy}</div></div>'''
        return render_layout(a["title"], content)
    except Exception as e: return f'<h1>Ошибка: {e}</h1>', 500

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
            cur.execute("INSERT INTO balance_history (user_id, amount, type, description) VALUES (%s,%s,%s,%s)", (g.user['id'], -acc['price'], 'purchase', f'Покупка #{account_id}'))
            cur.execute("UPDATE users SET balance = balance + %s, sales_count = sales_count + 1 WHERE id = %s", (seller_earn, acc['seller_id']))
            cur.execute("INSERT INTO balance_history (user_id, amount, type, description) VALUES (%s,%s,%s,%s)", (acc['seller_id'], seller_earn, 'sale', f'Продажа #{account_id}'))
            cur.execute("UPDATE accounts SET is_sold = TRUE WHERE id = %s", (account_id,))
            cur.execute("INSERT INTO purchases (buyer_id, account_id, phone_number) VALUES (%s,%s,%s) RETURNING id", (g.user['id'], account_id, 'Загрузка...'))
            pid = cur.fetchone()['id']
            db.commit()
            phone = extract_phone_from_session(acc['session_string'])
            if phone: cur.execute("UPDATE purchases SET phone_number = %s WHERE id = %s", (phone, pid)); db.commit()
            flash('Покупка успешна!', 'success')
            return redirect(url_for('my_purchases'))
    except Exception as e: flash(f'Ошибка: {e}', 'error'); return redirect(url_for('index'))

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
            cb = f'<button onclick="getCode({p["id"]})" class="btn btn-primary btn-sm" style="width:100%;justify-content:center">Получить код</button>' if not p['code_retrieved'] else ''
            items += f'<div class="purchase-card"><h3 style="margin-bottom:5px;font-size:16px">{p["title"]}</h3><p style="color:#64748b;font-size:12px;margin-bottom:8px">{p["purchase_date"].strftime("%d.%m.%Y %H:%M") if p["purchase_date"] else ""}</p><div style="background:rgba(0,0,0,0.2);padding:10px;border-radius:8px;margin-bottom:8px;font-size:13px">Номер: <strong>{p["phone_number"]}</strong> <button onclick="copyText(\'{p["phone_number"]}\')" class="btn btn-secondary btn-sm" style="margin-left:4px;padding:2px 8px;font-size:11px">Копировать</button></div><div id="code-{p["id"]}"></div>{cb}</div>'
        if not items: items = '<div class="empty"><h3>Нет покупок</h3><a href="/" class="btn btn-primary btn-sm" style="margin-top:8px">К покупкам</a></div>'
        
        content = f'''<h2 style="font-size:24px;font-weight:800;margin-bottom:18px">Мои покупки</h2>{items}'''
        return render_layout("Мои покупки", content)
    except Exception as e: return f'<h1>Ошибка: {e}</h1>', 500

@app.route('/get_code/<int:pid>')
@login_required
def get_code(pid):
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT p.*, a.session_string FROM purchases p JOIN accounts a ON p.account_id = a.id WHERE p.id = %s AND p.buyer_id = %s", (pid, g.user['id']))
            p = cur.fetchone()
            if not p: return jsonify({'error': 'Не найдена'}), 404
            code = extract_code_from_session(p['session_string'])
            if code:
                cur.execute("UPDATE purchases SET code_retrieved = TRUE WHERE id = %s", (pid,)); db.commit()
                return jsonify({'code': code})
            return jsonify({'error': 'Код не найден'}), 404
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    extra = ''
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'verify_phone':
            phone = request.form.get('phone', '').strip()
            if not phone.startswith('+'): phone = '+' + phone
            result = send_verification_code(phone)
            if result: session['verify_phone'] = phone; session['code_hash'] = result; flash('Код отправлен!', 'info')
            else: flash('Ошибка отправки', 'error')
        elif action == 'confirm_code':
            code = request.form.get('code', '').strip()
            phone = session.get('verify_phone', ''); code_hash = session.get('code_hash', '')
            if not phone or not code_hash: flash('Сессия истекла', 'error'); return redirect(url_for('profile'))
            try:
                client = TelegramClient(StringSession(), API_ID, API_HASH); client.connect()
                try:
                    client.sign_in(phone=phone, code=code, phone_code_hash=code_hash)
                    session['phone_verified'] = True; session['session_string'] = client.session.save()
                    session.pop('2fa_needed', None); flash('Подтвержден!', 'success')
                except SessionPasswordNeededError: session['2fa_needed'] = True; session['client_temp'] = client.session.save(); flash('Нужен 2FA', 'info')
                except PhoneCodeInvalidError: flash('Неверный код', 'error')
                finally:
                    if not session.get('2fa_needed'):
                        try: client.disconnect()
                        except: pass
            except Exception as e: flash(f'Ошибка: {e}', 'error')
        elif action == 'confirm_2fa':
            pw = request.form.get('password_2fa', '')
            try:
                client = TelegramClient(StringSession(session.get('client_temp', '')), API_ID, API_HASH); client.connect()
                try:
                    client.sign_in(password=pw)
                    session['phone_verified'] = True; session['session_string'] = client.session.save()
                    session.pop('2fa_needed', None); flash('Готово!', 'success')
                except Exception as e: flash(f'Ошибка: {e}', 'error')
                finally:
                    try: client.disconnect()
                    except: pass
            except Exception as e: flash(f'Ошибка: {e}', 'error')
    
    if session.get('verify_phone'):
        extra += '<form method="POST" style="padding:12px;background:rgba(0,0,0,0.2);border-radius:8px;margin-top:10px"><input type="hidden" name="action" value="confirm_code"><label style="display:block;margin-bottom:5px;color:#94a3b8;font-size:12px">Код из Telegram</label><input type="text" name="code" required><button type="submit" class="btn btn-success btn-sm" style="width:100%;margin-top:6px">Подтвердить</button></form>'
    if session.get('2fa_needed'):
        extra += '<form method="POST" style="padding:12px;background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.2);border-radius:8px;margin-top:10px"><input type="hidden" name="action" value="confirm_2fa"><label style="display:block;margin-bottom:5px;color:#fbbf24;font-size:12px">Пароль 2FA</label><input type="password" name="password_2fa" required><button type="submit" class="btn btn-sm" style="width:100%;margin-top:6px;background:#f59e0b;color:#000">Подтвердить</button></form>'
    if session.get('phone_verified'):
        extra += '<div style="padding:12px;background:rgba(16,185,129,0.08);border:1px solid rgba(16,185,129,0.2);border-radius:8px;margin-top:10px;text-align:center"><p style="color:#34d399;font-size:13px">Номер подтвержден!</p><a href="/sell" class="btn btn-primary btn-sm" style="margin-top:6px">Заполнить данные</a></div>'
    
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT * FROM balance_history WHERE user_id = %s ORDER BY created_at DESC LIMIT 20", (g.user['id'],))
        history = cur.fetchall()
    hist_html = ''.join([f'<tr><td>{h["created_at"].strftime("%d.%m %H:%M")}</td><td style="color:{"#34d399" if h["amount"] > 0 else "#fca5a5"}">{"+" if h["amount"] > 0 else ""}{h["amount"]:.2f} ₽</td><td style="color:#94a3b8;font-size:12px">{h["description"]}</td></tr>' for h in history]) or '<tr><td colspan="3" style="text-align:center;color:#64748b;font-size:13px">Нет операций</td></tr>'
    
    content = f'''<div class="profile-section"><div class="profile-card"><div class="flex"><div class="avatar">U</div><div><h3 style="font-size:18px">{g.user["username"]}</h3><span class="balance-badge" style="display:inline-block;margin-top:4px">{g.user["balance"]:.2f} ₽</span><span style="margin-left:8px;color:#64748b;font-size:12px">Продаж: {g.user.get("sales_count",0)}</span></div></div></div><div class="profile-card"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px"><h3 style="font-size:16px">Продажа аккаунта</h3><button onclick="openModal(\'sellModal\')" class="btn btn-primary btn-sm">Выставить</button></div>{extra if extra else '<p style="color:#64748b;font-size:12px">Нажмите "Выставить" чтобы начать</p>'}</div><div class="profile-card"><h3 style="margin-bottom:14px;font-size:16px">История баланса</h3><div style="overflow-x:auto"><table><thead><tr><th>Дата</th><th>Сумма</th><th>Описание</th></tr></thead><tbody>{hist_html}</tbody></table></div></div></div>'''
    return render_layout("Профиль", content)

@app.route('/sell', methods=['GET', 'POST'])
@login_required
def sell_account():
    if not session.get('phone_verified'): flash('Подтвердите номер', 'error'); return redirect(url_for('profile'))
    if request.method == 'POST':
        title = request.form.get('title', '').strip(); origin = request.form.get('origin', '').strip()
        desc = request.form.get('description', '').strip(); price = request.form.get('price', type=float)
        has_2fa = request.form.get('has_2fa') == 'on'; is_premium = request.form.get('is_premium') == 'on'
        if not title or not price: flash('Название и цена обязательны', 'error')
        else:
            try:
                ss = session.get('session_string')
                flash('Сбор данных...', 'info')
                ad = gather_account_data(ss)
                db = get_db()
                with db.cursor() as cur:
                    cur.execute("INSERT INTO accounts (seller_id,title,origin,description,price,session_string,country,has_2fa,spamblock,is_premium,chats_count,channels_count,groups_count) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (g.user['id'],title,origin,desc,price,ss,ad.get('country',''),ad.get('has_2fa',has_2fa),ad.get('spamblock',False),ad.get('is_premium',is_premium),ad.get('chats_count',0),ad.get('channels_count',0),ad.get('groups_count',0)))
                db.commit()
                for k in ['phone_verified','session_string','verify_phone','code_hash','client_temp','2fa_needed']: session.pop(k, None)
                flash('Аккаунт выставлен!', 'success'); return redirect(url_for('index'))
            except Exception as e: flash(f'Ошибка: {e}', 'error')
            
    content = f'''<div class="form-box" style="max-width:460px"><h2>Выставить аккаунт</h2><p class="sub">Заполните данные</p><form method="POST"><div class="form-group"><label>Название *</label><input type="text" name="title" required></div><div class="form-group"><label>Происхождение</label><select name="origin"><option value="">Выберите...</option>{"".join([f'<option value="{o}">{o}</option>' for o in ORIGINS])}</select></div><div class="form-group"><label>Описание</label><textarea name="description" rows="3"></textarea></div><div class="form-group"><label>Цена (₽) *</label><input type="number" name="price" step="0.01" required></div><label style="display:flex;align-items:center;gap:6px;margin-bottom:6px;cursor:pointer;font-size:14px"><input type="checkbox" name="has_2fa" style="width:auto;margin:0"> 2FA</label><label style="display:flex;align-items:center;gap:6px;margin-bottom:14px;cursor:pointer;font-size:14px"><input type="checkbox" name="is_premium" style="width:auto;margin:0"> Premium</label><button type="submit" class="btn btn-primary" style="width:100%;justify-content:center;padding:12px">Выставить</button></form><p style="text-align:center;color:#64748b;margin-top:10px;font-size:12px">Комиссия: 5%</p></div>'''
    return render_layout("Выставить аккаунт", content)

@app.route('/withdraw', methods=['POST'])
@login_required
def withdraw():
    amount_rub = request.form.get('amount_rub', 0, type=float); address = request.form.get('address', '').strip()
    if amount_rub < 50: flash('Минимум 50 ₽', 'error'); return redirect(url_for('profile'))
    if g.user['balance'] < amount_rub: flash('Недостаточно средств', 'error'); return redirect(url_for('profile'))
    if g.user.get('sales_count', 0) < 1: flash('Нужна 1 продажа', 'error'); return redirect(url_for('profile'))
    if not address: flash('Укажите адрес TON', 'error'); return redirect(url_for('profile'))
    try:
        amount_usdt = amount_rub / 90
        db = get_db()
        with db.cursor() as cur:
            cur.execute("UPDATE users SET balance = balance - %s WHERE id = %s", (amount_rub, g.user['id']))
            cur.execute("INSERT INTO balance_history (user_id, amount, type, description) VALUES (%s,%s,%s,%s)", (g.user['id'], -amount_rub, 'withdrawal', 'Вывод средств'))
            cur.execute("INSERT INTO withdrawals (user_id, amount_rub, amount_usdt, address) VALUES (%s,%s,%s,%s)", (g.user['id'], amount_rub, amount_usdt, address))
        db.commit()
        flash(f'Заявка создана: {amount_rub} ₽ ({amount_usdt:.6f} USDT)', 'success')
    except Exception as e: flash(f'Ошибка: {e}', 'error')
    return redirect(url_for('profile'))

@app.route('/admin', methods=['GET', 'POST'])
@login_required
def admin_panel():
    if not g.user['is_admin']: flash('Доступ запрещен', 'error'); return redirect(url_for('index'))
    try:
        db = get_db()
        if request.method == 'POST':
            action = request.form.get('action'); wid = request.form.get('withdrawal_id', type=int)
            if action in ['approve', 'reject'] and wid:
                status = 'approved' if action == 'approve' else 'rejected'
                with db.cursor() as cur: cur.execute("UPDATE withdrawals SET status = %s WHERE id = %s", (status, wid))
                flash(f'Заявка {status}', 'success')
            else:
                uid = request.form.get('user_id', type=int); amount = request.form.get('amount', type=float); act = request.form.get('balance_action')
                if uid and amount:
                    with db.cursor() as cur:
                        if act == 'add': cur.execute("UPDATE users SET balance = balance + %s WHERE id = %s", (amount, uid))
                        elif act == 'set': cur.execute("UPDATE users SET balance = %s WHERE id = %s", (amount, uid))
                    flash('Баланс обновлен', 'success')
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT id, username, balance, sales_count, is_admin FROM users ORDER BY id"); users = cur.fetchall()
            cur.execute("SELECT w.*, u.username FROM withdrawals w JOIN users u ON w.user_id = u.id ORDER BY w.created_at DESC"); withdrawals = cur.fetchall()
        opts = ''.join([f'<option value="{u["id"]}">{u["username"]} ({u["balance"]:.2f} ₽)</option>' for u in users])
        rows = ''.join([f'<tr><td>#{u["id"]}</td><td><strong>{u["username"]}</strong></td><td style="color:#34d399;font-weight:600">{u["balance"]:.2f} ₽</td><td>{u["sales_count"]}</td><td>{"Да" if u["is_admin"] else "-"}</td></tr>' for u in users])
        w_rows = ''
        for w in withdrawals:
            sc = '#f59e0b' if w['status'] == 'pending' else '#34d399' if w['status'] == 'approved' else '#ef4444'
            st = 'Ожидает' if w['status'] == 'pending' else 'Одобрено' if w['status'] == 'approved' else 'Отклонено'
            btns = f'<form method="POST" style="display:inline"><input type="hidden" name="withdrawal_id" value="{w["id"]}"><button type="submit" name="action" value="approve" class="btn btn-success btn-sm" style="margin-right:3px">OK</button><button type="submit" name="action" value="reject" class="btn btn-red btn-sm">X</button></form>' if w['status'] == 'pending' else ''
            w_rows += f'<tr><td>#{w["id"]}</td><td>{w["username"]}</td><td>{w["amount_rub"]:.2f} ₽</td><td>{w["amount_usdt"]:.6f}</td><td style="font-size:11px;word-break:break-all">{w["address"]}</td><td style="color:{sc}">{st}</td><td>{w["created_at"].strftime("%d.%m %H:%M")}</td><td>{btns}</td></tr>'
        if not w_rows: w_rows = '<tr><td colspan="8" style="text-align:center;color:#64748b;font-size:13px">Нет заявок</td></tr>'
        
        content = f'''<h2 style="font-size:24px;font-weight:800;margin-bottom:18px">Админ-панель</h2><div class="profile-card"><h3 style="margin-bottom:14px;font-size:16px">Баланс</h3><form method="POST"><div class="form-group"><label>Пользователь</label><select name="user_id" required><option value="">Выберите...</option>{opts}</select></div><div class="form-group"><label>Сумма</label><input type="number" name="amount" step="0.01" required></div><div style="display:flex;gap:6px"><button type="submit" name="balance_action" value="add" class="btn btn-success btn-sm" style="flex:1;justify-content:center">Добавить</button><button type="submit" name="balance_action" value="set" class="btn btn-sm" style="flex:1;justify-content:center;background:#f59e0b;color:#000">Установить</button></div></form></div><div class="profile-card" style="overflow-x:auto"><h3 style="margin-bottom:14px;font-size:16px">Пользователи</h3><table><thead><tr><th>ID</th><th>Логин</th><th>Баланс</th><th>Продаж</th><th>Админ</th></tr></thead><tbody>{rows}</tbody></table></div><div class="profile-card" style="overflow-x:auto"><h3 style="margin-bottom:14px;font-size:16px">Выводы</h3><table><thead><tr><th>ID</th><th>User</th><th>RUB</th><th>USDT</th><th>Адрес</th><th>Статус</th><th>Дата</th><th></th></tr></thead><tbody>{w_rows}</tbody></table></div>'''
        return render_layout("Админ-панель", content)
    except Exception as e: return f'<h1>Ошибка: {e}</h1>', 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
