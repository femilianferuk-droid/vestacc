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
        cur.execute("""CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username VARCHAR(100) UNIQUE NOT NULL, password_hash VARCHAR(255) NOT NULL, balance DECIMAL(10,2) DEFAULT 0.00, is_admin BOOLEAN DEFAULT FALSE, created_at TIMESTAMP DEFAULT NOW())""")
        cur.execute("""CREATE TABLE IF NOT EXISTS accounts (id SERIAL PRIMARY KEY, seller_id INTEGER REFERENCES users(id), title VARCHAR(200) NOT NULL, origin VARCHAR(100), description TEXT, price DECIMAL(10,2) NOT NULL, session_string TEXT NOT NULL, country VARCHAR(50), has_2fa BOOLEAN DEFAULT FALSE, spamblock BOOLEAN DEFAULT FALSE, chats_count INTEGER DEFAULT 0, channels_count INTEGER DEFAULT 0, groups_count INTEGER DEFAULT 0, is_sold BOOLEAN DEFAULT FALSE, created_at TIMESTAMP DEFAULT NOW())""")
        cur.execute("""CREATE TABLE IF NOT EXISTS purchases (id SERIAL PRIMARY KEY, buyer_id INTEGER REFERENCES users(id), account_id INTEGER REFERENCES accounts(id), phone_number VARCHAR(20), purchase_date TIMESTAMP DEFAULT NOW(), code_retrieved BOOLEAN DEFAULT FALSE)""")
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
    return ''.join([f'<div style="padding:12px 18px;border-radius:10px;margin-bottom:16px;font-weight:500;background:rgba({("16,185,129" if c=="success" else "239,68,68" if c=="error" else "59,130,246")},0.15);border:1px solid rgba({("16,185,129" if c=="success" else "239,68,68" if c=="error" else "59,130,246")},0.3);color:#{"10b981" if c=="success" else "ef4444" if c=="error" else "3b82f6"}">{m}</div>' for c,m in get_flashed_messages(with_categories=True)])

def navbar():
    if g.user:
        return f'''<div style="background:rgba(10,10,25,0.95);backdrop-filter:blur(20px);border-bottom:1px solid rgba(59,130,246,0.3);padding:14px 24px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;position:sticky;top:0;z-index:100;box-shadow:0 4px 20px rgba(0,0,0,0.5)">
            <a href="/" style="font-size:24px;font-weight:900;text-decoration:none;background:linear-gradient(135deg,#3b82f6,#8b5cf6,#3b82f6);background-size:200% 200%;-webkit-background-clip:text;-webkit-text-fill-color:transparent;animation:shimmer 3s ease infinite">⚡ Vest Accs</a>
            <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
                <span style="background:rgba(59,130,246,0.15);border:1px solid rgba(59,130,246,0.4);border-radius:50px;padding:8px 18px;font-weight:700;color:#60a5fa;font-size:15px;box-shadow:0 0 15px rgba(59,130,246,0.2)">💰 {g.user["balance"]:.2f} ₽</span>
                <a href="/deposit" style="width:38px;height:38px;background:linear-gradient(135deg,#3b82f6,#2563eb);color:#fff;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;text-decoration:none;font-size:22px;font-weight:700;box-shadow:0 4px 15px rgba(59,130,246,0.4);transition:all 0.3s;animation:pulse 2s infinite" onmouseover="this.style.transform='scale(1.1)'" onmouseout="this.style.transform='scale(1)'">+</a>
                <a href="/my_purchases" style="padding:10px 20px;background:rgba(59,130,246,0.1);color:#93c5fd;border:1px solid rgba(59,130,246,0.3);border-radius:50px;text-decoration:none;font-size:14px;font-weight:600;transition:all 0.3s" onmouseover="this.style.background='rgba(59,130,246,0.2)';this.style.boxShadow='0 0 20px rgba(59,130,246,0.3)'" onmouseout="this.style.background='rgba(59,130,246,0.1)';this.style.boxShadow='none'">📦 Покупки</a>
                <a href="/logout" style="padding:10px 20px;background:rgba(239,68,68,0.1);color:#fca5a5;border:1px solid rgba(239,68,68,0.3);border-radius:50px;text-decoration:none;font-size:14px;font-weight:600;transition:all 0.3s" onmouseover="this.style.background='rgba(239,68,68,0.2)';this.style.boxShadow='0 0 20px rgba(239,68,68,0.3)'" onmouseout="this.style.background='rgba(239,68,68,0.1)';this.style.boxShadow='none'">🚪 Выйти</a>
            </div></div>'''
    return f'''<div style="background:rgba(10,10,25,0.95);backdrop-filter:blur(20px);border-bottom:1px solid rgba(59,130,246,0.3);padding:14px 24px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;position:sticky;top:0;z-index:100;box-shadow:0 4px 20px rgba(0,0,0,0.5)">
        <a href="/" style="font-size:24px;font-weight:900;text-decoration:none;background:linear-gradient(135deg,#3b82f6,#8b5cf6,#3b82f6);background-size:200% 200%;-webkit-background-clip:text;-webkit-text-fill-color:transparent;animation:shimmer 3s ease infinite">⚡ Vest Accs</a>
        <div style="display:flex;align-items:center;gap:10px">
            <a href="/login" style="padding:10px 20px;color:#93c5fd;border:1px solid rgba(59,130,246,0.4);border-radius:50px;text-decoration:none;font-size:14px;font-weight:600;transition:all 0.3s" onmouseover="this.style.background='rgba(59,130,246,0.2)';this.style.boxShadow='0 0 20px rgba(59,130,246,0.4)'" onmouseout="this.style.background='transparent';this.style.boxShadow='none'">Войти</a>
            <a href="/register" style="padding:10px 20px;background:linear-gradient(135deg,#3b82f6,#2563eb);color:#fff;border-radius:50px;text-decoration:none;font-size:14px;font-weight:600;box-shadow:0 4px 15px rgba(59,130,246,0.4);transition:all 0.3s;animation:pulse 2s infinite" onmouseover="this.style.transform='translateY(-2px)';this.style.boxShadow='0 8px 25px rgba(59,130,246,0.6)'" onmouseout="this.style.transform='translateY(0)';this.style.boxShadow='0 4px 15px rgba(59,130,246,0.4)'">Регистрация</a>
        </div></div>'''

STYLE = '''
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
body{font-family:'Inter',-apple-system,BlinkMacSystemFont,sans-serif;background:linear-gradient(135deg,#0a0a1a 0%,#0f0f2e 50%,#0a0a1a 100%);color:#e0e7ff;min-height:100vh;margin:0;overflow-x:hidden}
body::before{content:'';position:fixed;top:0;left:0;right:0;bottom:0;background:radial-gradient(ellipse at 20% 50%,rgba(59,130,246,0.08) 0%,transparent 50%),radial-gradient(ellipse at 80% 20%,rgba(139,92,246,0.06) 0%,transparent 50%),radial-gradient(ellipse at 50% 80%,rgba(37,99,235,0.04) 0%,transparent 50%);pointer-events:none;z-index:0}
@keyframes shimmer{0%,100%{background-position:0% 50%}50%{background-position:100% 50%}}
@keyframes pulse{0%,100%{box-shadow:0 4px 15px rgba(59,130,246,0.4)}50%{box-shadow:0 4px 25px rgba(59,130,246,0.7)}}
@keyframes float{0%,100%{transform:translateY(0)}50%{transform:translateY(-10px)}}
input,textarea,select{width:100%;padding:14px;background:rgba(0,0,0,0.4);border:1px solid rgba(59,130,246,0.3);border-radius:10px;color:#e0e7ff;font-size:15px;outline:none;transition:all 0.3s;font-family:inherit;margin-bottom:16px}
input:focus,textarea:focus,select:focus{border-color:#3b82f6;box-shadow:0 0 20px rgba(59,130,246,0.3)}
input::placeholder,textarea::placeholder{color:#64748b}
</style>
'''

SCRIPT = '''
<script>
function copyText(t){navigator.clipboard.writeText(t).then(()=>{let e=document.createElement('div');e.style.cssText='position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:linear-gradient(135deg,#3b82f6,#2563eb);color:#fff;padding:12px 24px;border-radius:50px;font-weight:600;z-index:999;box-shadow:0 8px 25px rgba(59,130,246,0.5);animation:float 0.5s ease';e.textContent='✓ Скопировано!';document.body.appendChild(e);setTimeout(()=>{e.style.opacity='0';e.style.transition='opacity 0.3s';setTimeout(()=>e.remove(),300)},2000)})}
function getCode(i){let b=event.target;b.disabled=true;b.textContent='⏳ Загрузка...';fetch('/get_code/'+i).then(r=>r.json()).then(d=>{if(d.code){document.getElementById('code-'+i).innerHTML='<div style="font-size:32px;font-weight:800;letter-spacing:8px;color:#60a5fa;text-align:center;padding:20px;background:rgba(0,0,0,0.4);border-radius:10px;margin:12px 0;border:1px solid rgba(59,130,246,0.3);box-shadow:0 0 20px rgba(59,130,246,0.2)">'+d.code+'</div>';b.style.display='none'}else{alert('Ошибка: '+(d.error||'не найдено'))}}).catch(e=>alert('Ошибка')).finally(()=>{b.disabled=false;b.textContent='📨 Получить код'})}
</script>
'''

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
            if a['has_2fa']: tags += '<span style="padding:4px 10px;border-radius:50px;font-size:12px;font-weight:600;background:rgba(245,158,11,0.2);color:#fbbf24">🔐 2FA</span>'
            if a['spamblock']: tags += '<span style="padding:4px 10px;border-radius:50px;font-size:12px;font-weight:600;background:rgba(239,68,68,0.2);color:#fca5a5">🚫 Спамблок</span>'
            tags += f'<span style="padding:4px 10px;border-radius:50px;font-size:12px;font-weight:600;background:rgba(59,130,246,0.15);color:#93c5fd">🌍 {a["country"] or "?"}</span>'
            buy = ''
            if g.user and g.user['id'] != a['seller_id']:
                buy = f'<form action="/buy/{a["id"]}" method="POST" style="flex:1"><button style="width:100%;padding:10px 20px;border:none;border-radius:50px;background:linear-gradient(135deg,#3b82f6,#2563eb);color:#fff;font-size:14px;font-weight:600;cursor:pointer;box-shadow:0 4px 15px rgba(59,130,246,0.3);transition:all 0.3s;animation:pulse 2s infinite" onmouseover="this.style.transform=\'translateY(-2px)\';this.style.boxShadow=\'0 8px 25px rgba(59,130,246,0.5)\'" onmouseout="this.style.transform=\'translateY(0)\';this.style.boxShadow=\'0 4px 15px rgba(59,130,246,0.3)\'">🛒 Купить</button></form>'
            cards += f'''<div style="background:rgba(15,15,30,0.8);border:1px solid rgba(59,130,246,0.2);border-radius:16px;padding:24px;transition:all 0.4s;backdrop-filter:blur(10px);position:relative;overflow:hidden" onmouseover="this.style.borderColor='rgba(59,130,246,0.6)';this.style.transform='translateY(-5px)';this.style.boxShadow='0 15px 40px rgba(0,0,0,0.6),0 0 30px rgba(59,130,246,0.2)'" onmouseout="this.style.borderColor='rgba(59,130,246,0.2)';this.style.transform='translateY(0)';this.style.boxShadow='none'">
                <div style="position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,#3b82f6,#8b5cf6,#3b82f6);background-size:200% 200%;animation:shimmer 3s ease infinite;opacity:0;transition:opacity 0.4s" onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0'"></div>
                <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:16px">
                    <div><div style="font-size:18px;font-weight:700;color:#e0e7ff">{a["title"]}</div><div style="font-size:13px;color:#64748b;margin-top:4px">👤 {a["seller_name"]}</div></div>
                    <div style="background:linear-gradient(135deg,rgba(59,130,246,0.2),rgba(37,99,235,0.2));border:1px solid rgba(59,130,246,0.4);color:#60a5fa;padding:8px 16px;border-radius:50px;font-weight:700;font-size:16px;box-shadow:0 0 15px rgba(59,130,246,0.15)">{a["price"]:.0f} ₽</div>
                </div>
                <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px">
                    <div style="text-align:center;padding:10px;background:rgba(0,0,0,0.3);border-radius:10px;border:1px solid rgba(59,130,246,0.15)"><div style="font-size:18px;font-weight:700;color:#3b82f6">{a["chats_count"]}</div><div style="font-size:11px;color:#64748b">💬 Чаты</div></div>
                    <div style="text-align:center;padding:10px;background:rgba(0,0,0,0.3);border-radius:10px;border:1px solid rgba(59,130,246,0.15)"><div style="font-size:18px;font-weight:700;color:#8b5cf6">{a["channels_count"]}</div><div style="font-size:11px;color:#64748b">📢 Каналы</div></div>
                    <div style="text-align:center;padding:10px;background:rgba(0,0,0,0.3);border-radius:10px;border:1px solid rgba(59,130,246,0.15)"><div style="font-size:18px;font-weight:700;color:#60a5fa">{a["groups_count"]}</div><div style="font-size:11px;color:#64748b">👥 Группы</div></div>
                </div>
                <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">{tags}</div>
                <div style="display:flex;gap:8px">
                    <a href="/account/{a["id"]}" style="flex:1;padding:10px 20px;background:rgba(59,130,246,0.1);color:#93c5fd;border:1px solid rgba(59,130,246,0.3);border-radius:50px;text-decoration:none;font-size:14px;font-weight:600;text-align:center;transition:all 0.3s" onmouseover="this.style.background='rgba(59,130,246,0.2)';this.style.boxShadow='0 0 20px rgba(59,130,246,0.3)'" onmouseout="this.style.background='rgba(59,130,246,0.1)';this.style.boxShadow='none'">📋 Подробнее</a>
                    {buy}
                </div></div>'''
        
        if not cards: cards = '<div style="text-align:center;padding:60px;color:#64748b"><div style="font-size:64px;margin-bottom:16px">📭</div><h3 style="color:#93c5fd">Нет доступных аккаунтов</h3><p>Станьте первым продавцом!</p></div>'
        
        profile_btn = ''
        if g.user: profile_btn = '<a href="/profile" style="display:block;width:100%;max-width:500px;margin:40px auto;padding:16px;background:rgba(59,130,246,0.1);border:1px solid rgba(59,130,246,0.3);border-radius:16px;color:#93c5fd;text-align:center;text-decoration:none;font-weight:600;font-size:16px;transition:all 0.3s" onmouseover="this.style.background=\'rgba(59,130,246,0.2)\';this.style.boxShadow=\'0 0 30px rgba(59,130,246,0.3)\'" onmouseout="this.style.background=\'rgba(59,130,246,0.1)\';this.style.boxShadow=\'none\'">👤 Профиль и продажа аккаунтов</a>'
        
        return f'''<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Vest Accs - Маркетплейс</title>{STYLE}</head><body style="position:relative;z-index:1">
            {navbar()}
            <div style="max-width:1200px;margin:0 auto;padding:24px 16px;position:relative;z-index:1">
                <h1 style="text-align:center;font-size:42px;font-weight:900;margin-bottom:8px;background:linear-gradient(135deg,#3b82f6,#8b5cf6,#3b82f6);background-size:200% 200%;-webkit-background-clip:text;-webkit-text-fill-color:transparent;animation:shimmer 3s ease infinite">Маркетплейс Telegram аккаунтов</h1>
                <p style="text-align:center;color:#64748b;margin-bottom:32px;font-size:16px">Покупайте и продавайте проверенные аккаунты Telegram</p>
                {flash_msgs()}
                <div style="text-align:center;margin-bottom:24px">
                    <button onclick="document.getElementById('fp').style.display=document.getElementById('fp').style.display=='block'?'none':'block'" style="background:rgba(59,130,246,0.15);border:1px solid rgba(59,130,246,0.4);color:#93c5fd;padding:14px 32px;border-radius:50px;cursor:pointer;font-size:15px;font-weight:600;transition:all 0.3s" onmouseover="this.style.background='rgba(59,130,246,0.25)';this.style.boxShadow='0 0 30px rgba(59,130,246,0.3)'" onmouseout="this.style.background='rgba(59,130,246,0.15)';this.style.boxShadow='none'">🔍 Фильтры и поиск</button>
                    <div id="fp" style="display:none;background:rgba(15,15,30,0.9);border:1px solid rgba(59,130,246,0.3);border-radius:16px;padding:24px;margin-top:12px;text-align:left;backdrop-filter:blur(10px)">
                        <form action="/filter" method="GET">
                            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:16px">
                                <input type="text" name="q" placeholder="🔎 Поиск по заголовку...">
                                <input type="text" name="country" placeholder="🌍 Страна...">
                                <input type="text" name="origin" placeholder="📋 Происхождение...">
                                <select name="2fa"><option value="">🔐 2FA (любой)</option><option value="yes">✅ Есть</option><option value="no">❌ Нет</option></select>
                                <select name="spamblock"><option value="">🚫 Спамблок</option><option value="yes">⚠️ Есть</option><option value="no">✅ Нет</option></select>
                                <input type="number" name="min_chats" placeholder="💬 Мин. чатов...">
                            </div>
                            <div style="display:flex;gap:10px;justify-content:center">
                                <button type="submit" style="padding:10px 24px;background:linear-gradient(135deg,#3b82f6,#2563eb);color:#fff;border:none;border-radius:50px;cursor:pointer;font-size:14px;font-weight:600;box-shadow:0 4px 15px rgba(59,130,246,0.4);transition:all 0.3s" onmouseover="this.style.transform='translateY(-2px)';this.style.boxShadow='0 8px 25px rgba(59,130,246,0.6)'" onmouseout="this.style.transform='translateY(0)';this.style.boxShadow='0 4px 15px rgba(59,130,246,0.4)'">🔍 Применить</button>
                                <a href="/" style="padding:10px 24px;background:rgba(59,130,246,0.1);color:#93c5fd;border:1px solid rgba(59,130,246,0.3);border-radius:50px;text-decoration:none;font-size:14px;font-weight:600;transition:all 0.3s" onmouseover="this.style.background='rgba(59,130,246,0.2)'" onmouseout="this.style.background='rgba(59,130,246,0.1)'">↺ Сбросить</a>
                            </div>
                        </form>
                    </div>
                </div>
                <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:20px">{cards}</div>
                {profile_btn}
            </div>
            {SCRIPT}</body></html>'''
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        return f'<h1 style="color:#ef4444">Ошибка: {e}</h1>', 500

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
                flash('Регистрация успешна! Войдите.', 'success')
                return redirect(url_for('login'))
            except psycopg2.IntegrityError:
                db.rollback()
                flash('Пользователь уже существует', 'error')
            except Exception as e:
                flash(f'Ошибка: {e}', 'error')
    return f'''<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Регистрация - Vest Accs</title>{STYLE}</head><body style="position:relative;z-index:1">
        <div style="background:rgba(10,10,25,0.95);border-bottom:1px solid rgba(59,130,246,0.3);padding:14px 24px"><a href="/" style="font-size:24px;font-weight:900;text-decoration:none;background:linear-gradient(135deg,#3b82f6,#8b5cf6,#3b82f6);background-size:200% 200%;-webkit-background-clip:text;-webkit-text-fill-color:transparent;animation:shimmer 3s ease infinite">⚡ Vest Accs</a></div>
        <div style="max-width:420px;margin:80px auto;background:rgba(15,15,30,0.9);border:1px solid rgba(59,130,246,0.3);border-radius:20px;padding:40px;backdrop-filter:blur(10px);box-shadow:0 20px 60px rgba(0,0,0,0.5),0 0 30px rgba(59,130,246,0.1)">
            <h2 style="font-size:30px;font-weight:900;text-align:center;margin-bottom:8px;background:linear-gradient(135deg,#3b82f6,#8b5cf6,#3b82f6);background-size:200% 200%;-webkit-background-clip:text;-webkit-text-fill-color:transparent;animation:shimmer 3s ease infinite">Присоединяйтесь</h2>
            <p style="text-align:center;color:#64748b;margin-bottom:32px">Создайте аккаунт для покупки и продажи</p>
            {flash_msgs()}
            <form method="POST">
                <label style="display:block;margin-bottom:8px;font-weight:600;color:#93c5fd;font-size:14px">👤 Логин</label>
                <input type="text" name="username" placeholder="Придумайте логин" required>
                <label style="display:block;margin-bottom:8px;font-weight:600;color:#93c5fd;font-size:14px">🔒 Пароль</label>
                <input type="password" name="password" placeholder="Придумайте пароль" required>
                <button type="submit" style="width:100%;padding:14px;background:linear-gradient(135deg,#3b82f6,#2563eb);color:#fff;border:none;border-radius:50px;cursor:pointer;font-size:16px;font-weight:700;box-shadow:0 4px 15px rgba(59,130,246,0.4);transition:all 0.3s;animation:pulse 2s infinite;margin-top:8px" onmouseover="this.style.transform='translateY(-2px)';this.style.boxShadow='0 8px 25px rgba(59,130,246,0.6)'" onmouseout="this.style.transform='translateY(0)';this.style.boxShadow='0 4px 15px rgba(59,130,246,0.4)'">✨ Зарегистрироваться</button>
            </form>
            <p style="text-align:center;margin-top:20px;color:#64748b">Уже есть аккаунт? <a href="/login" style="color:#3b82f6;font-weight:600;text-decoration:none">Войти</a></p>
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
    return f'''<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Вход - Vest Accs</title>{STYLE}</head><body style="position:relative;z-index:1">
        <div style="background:rgba(10,10,25,0.95);border-bottom:1px solid rgba(59,130,246,0.3);padding:14px 24px"><a href="/" style="font-size:24px;font-weight:900;text-decoration:none;background:linear-gradient(135deg,#3b82f6,#8b5cf6,#3b82f6);background-size:200% 200%;-webkit-background-clip:text;-webkit-text-fill-color:transparent;animation:shimmer 3s ease infinite">⚡ Vest Accs</a></div>
        <div style="max-width:420px;margin:80px auto;background:rgba(15,15,30,0.9);border:1px solid rgba(59,130,246,0.3);border-radius:20px;padding:40px;backdrop-filter:blur(10px);box-shadow:0 20px 60px rgba(0,0,0,0.5),0 0 30px rgba(59,130,246,0.1)">
            <h2 style="font-size:30px;font-weight:900;text-align:center;margin-bottom:8px;background:linear-gradient(135deg,#3b82f6,#8b5cf6,#3b82f6);background-size:200% 200%;-webkit-background-clip:text;-webkit-text-fill-color:transparent;animation:shimmer 3s ease infinite">С возвращением</h2>
            <p style="text-align:center;color:#64748b;margin-bottom:32px">Войдите в свой аккаунт</p>
            {flash_msgs()}
            <form method="POST">
                <label style="display:block;margin-bottom:8px;font-weight:600;color:#93c5fd;font-size:14px">👤 Логин</label>
                <input type="text" name="username" placeholder="Введите логин" required>
                <label style="display:block;margin-bottom:8px;font-weight:600;color:#93c5fd;font-size:14px">🔒 Пароль</label>
                <input type="password" name="password" placeholder="Введите пароль" required>
                <button type="submit" style="width:100%;padding:14px;background:linear-gradient(135deg,#3b82f6,#2563eb);color:#fff;border:none;border-radius:50px;cursor:pointer;font-size:16px;font-weight:700;box-shadow:0 4px 15px rgba(59,130,246,0.4);transition:all 0.3s;animation:pulse 2s infinite;margin-top:8px" onmouseover="this.style.transform='translateY(-2px)';this.style.boxShadow='0 8px 25px rgba(59,130,246,0.6)'" onmouseout="this.style.transform='translateY(0)';this.style.boxShadow='0 4px 15px rgba(59,130,246,0.4)'">🚀 Войти</button>
            </form>
            <p style="text-align:center;margin-top:20px;color:#64748b">Нет аккаунта? <a href="/register" style="color:#3b82f6;font-weight:600;text-decoration:none">Создать</a></p>
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
            flash(f'Баланс пополнен на {amount} ₽', 'success')
            return redirect(url_for('index'))
    return f'''<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Пополнение - Vest Accs</title>{STYLE}</head><body style="position:relative;z-index:1">
        <div style="background:rgba(10,10,25,0.95);border-bottom:1px solid rgba(59,130,246,0.3);padding:14px 24px;display:flex;justify-content:space-between;align-items:center">
            <a href="/" style="font-size:24px;font-weight:900;text-decoration:none;background:linear-gradient(135deg,#3b82f6,#8b5cf6,#3b82f6);background-size:200% 200%;-webkit-background-clip:text;-webkit-text-fill-color:transparent;animation:shimmer 3s ease infinite">⚡ Vest Accs</a>
            <span style="background:rgba(59,130,246,0.15);border:1px solid rgba(59,130,246,0.4);border-radius:50px;padding:8px 18px;font-weight:700;color:#60a5fa">💰 {g.user["balance"]:.2f} ₽</span>
        </div>
        <div style="max-width:420px;margin:80px auto;background:rgba(15,15,30,0.9);border:1px solid rgba(59,130,246,0.3);border-radius:20px;padding:40px;backdrop-filter:blur(10px);box-shadow:0 20px 60px rgba(0,0,0,0.5),0 0 30px rgba(59,130,246,0.1)">
            <h2 style="font-size:30px;font-weight:900;text-align:center;margin-bottom:8px;background:linear-gradient(135deg,#3b82f6,#8b5cf6,#3b82f6);background-size:200% 200%;-webkit-background-clip:text;-webkit-text-fill-color:transparent;animation:shimmer 3s ease infinite">Пополнение баланса</h2>
            <p style="text-align:center;color:#64748b;margin-bottom:32px">Текущий баланс: <strong style="color:#60a5fa;font-size:18px">{g.user["balance"]:.2f} ₽</strong></p>
            {flash_msgs()}
            <form method="POST">
                <label style="display:block;margin-bottom:8px;font-weight:600;color:#93c5fd;font-size:14px">💰 Сумма пополнения</label>
                <input type="number" name="amount" placeholder="1000" step="0.01" required>
                <button type="submit" style="width:100%;padding:14px;background:linear-gradient(135deg,#10b981,#059669);color:#fff;border:none;border-radius:50px;cursor:pointer;font-size:16px;font-weight:700;box-shadow:0 4px 15px rgba(16,185,129,0.4);transition:all 0.3s" onmouseover="this.style.transform='translateY(-2px)';this.style.boxShadow='0 8px 25px rgba(16,185,129,0.6)'" onmouseout="this.style.transform='translateY(0)';this.style.boxShadow='0 4px 15px rgba(16,185,129,0.4)'">💎 Пополнить</button>
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
            tags = ''
            if a['has_2fa']: tags += '<span style="padding:4px 10px;border-radius:50px;font-size:12px;font-weight:600;background:rgba(245,158,11,0.2);color:#fbbf24">🔐 2FA</span>'
            tags += f'<span style="padding:4px 10px;border-radius:50px;font-size:12px;font-weight:600;background:rgba(59,130,246,0.15);color:#93c5fd">🌍 {a["country"] or "?"}</span>'
            buy = ''
            if g.user and g.user['id'] != a['seller_id']:
                buy = f'<form action="/buy/{a["id"]}" method="POST" style="flex:1"><button style="width:100%;padding:10px 20px;border:none;border-radius:50px;background:linear-gradient(135deg,#3b82f6,#2563eb);color:#fff;font-size:14px;font-weight:600;cursor:pointer;box-shadow:0 4px 15px rgba(59,130,246,0.3);animation:pulse 2s infinite">🛒 Купить</button></form>'
            cards += f'''<div style="background:rgba(15,15,30,0.8);border:1px solid rgba(59,130,246,0.2);border-radius:16px;padding:24px">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:16px">
                    <div><div style="font-size:18px;font-weight:700">{a["title"]}</div><div style="font-size:13px;color:#64748b">👤 {a["seller_name"]}</div></div>
                    <div style="background:rgba(59,130,246,0.2);border:1px solid rgba(59,130,246,0.4);color:#60a5fa;padding:8px 16px;border-radius:50px;font-weight:700;font-size:16px">{a["price"]:.0f} ₽</div>
                </div>
                <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px">
                    <div style="text-align:center;padding:10px;background:rgba(0,0,0,0.3);border-radius:10px"><div style="font-size:18px;font-weight:700;color:#3b82f6">{a["chats_count"]}</div><div style="font-size:11px;color:#64748b">💬 Чаты</div></div>
                    <div style="text-align:center;padding:10px;background:rgba(0,0,0,0.3);border-radius:10px"><div style="font-size:18px;font-weight:700;color:#8b5cf6">{a["channels_count"]}</div><div style="font-size:11px;color:#64748b">📢 Каналы</div></div>
                    <div style="text-align:center;padding:10px;background:rgba(0,0,0,0.3);border-radius:10px"><div style="font-size:18px;font-weight:700;color:#60a5fa">{a["groups_count"]}</div><div style="font-size:11px;color:#64748b">👥 Группы</div></div>
                </div>
                <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">{tags}</div>
                <div style="display:flex;gap:8px">
                    <a href="/account/{a["id"]}" style="flex:1;padding:10px 20px;background:rgba(59,130,246,0.1);color:#93c5fd;border:1px solid rgba(59,130,246,0.3);border-radius:50px;text-decoration:none;font-size:14px;font-weight:600;text-align:center">📋 Подробнее</a>
                    {buy}
                </div></div>'''
        if not cards: cards = '<div style="text-align:center;padding:60px;color:#64748b"><div style="font-size:64px;margin-bottom:16px">🔍</div><h3>Ничего не найдено</h3><p>Попробуйте изменить фильтры</p></div>'
        
        profile_btn = ''
        if g.user: profile_btn = '<a href="/profile" style="display:block;width:100%;max-width:500px;margin:40px auto;padding:16px;background:rgba(59,130,246,0.1);border:1px solid rgba(59,130,246,0.3);border-radius:16px;color:#93c5fd;text-align:center;text-decoration:none;font-weight:600;font-size:16px">👤 Профиль и продажа</a>'
        
        return f'''<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Поиск - Vest Accs</title>{STYLE}</head><body style="position:relative;z-index:1">
            {navbar()}
            <div style="max-width:1200px;margin:0 auto;padding:24px 16px">
                <h1 style="text-align:center;font-size:42px;font-weight:900;margin-bottom:8px;background:linear-gradient(135deg,#3b82f6,#8b5cf6,#3b82f6);background-size:200% 200%;-webkit-background-clip:text;-webkit-text-fill-color:transparent;animation:shimmer 3s ease infinite">Результаты поиска</h1>
                <p style="text-align:center;color:#64748b;margin-bottom:32px">Найдено аккаунтов: {len(accounts)}</p>
                {flash_msgs()}
                <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:20px">{cards}</div>
                {profile_btn}
            </div>
            {SCRIPT}</body></html>'''
    except Exception as e:
        print(f"Error: {e}")
        return f'<h1>Ошибка: {e}</h1>', 500

@app.route('/account/<int:account_id>')
def account_detail(account_id):
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT a.*, u.username as seller_name FROM accounts a JOIN users u ON a.seller_id = u.id WHERE a.id = %s", (account_id,))
            a = cur.fetchone()
        if not a:
            flash('Аккаунт не найден', 'error')
            return redirect(url_for('index'))
        
        buy = ''
        if g.user and g.user['id'] != a['seller_id'] and not a['is_sold']:
            buy = f'<form action="/buy/{a["id"]}" method="POST"><button style="width:100%;padding:14px;background:linear-gradient(135deg,#3b82f6,#2563eb);color:#fff;border:none;border-radius:50px;cursor:pointer;font-size:16px;font-weight:700;box-shadow:0 4px 15px rgba(59,130,246,0.4);animation:pulse 2s infinite">🛒 Купить аккаунт</button></form>'
        
        desc = ''
        if a.get('description'):
            desc = f'<div style="background:rgba(0,0,0,0.3);padding:16px;border-radius:10px;margin:16px 0"><div style="font-size:12px;color:#64748b;text-transform:uppercase">📝 Описание</div><p style="margin-top:4px">{a["description"]}</p></div>'
        
        return f'''<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>{a["title"]} - Vest Accs</title>{STYLE}</head><body style="position:relative;z-index:1">
            <div style="background:rgba(10,10,25,0.95);border-bottom:1px solid rgba(59,130,246,0.3);padding:14px 24px;display:flex;justify-content:space-between;align-items:center">
                <a href="/" style="font-size:24px;font-weight:900;text-decoration:none;background:linear-gradient(135deg,#3b82f6,#8b5cf6,#3b82f6);background-size:200% 200%;-webkit-background-clip:text;-webkit-text-fill-color:transparent;animation:shimmer 3s ease infinite">⚡ Vest Accs</a>
                <a href="/" style="padding:10px 20px;background:rgba(59,130,246,0.1);color:#93c5fd;border:1px solid rgba(59,130,246,0.3);border-radius:50px;text-decoration:none;font-size:14px;font-weight:600">← Назад</a>
            </div>
            <div style="max-width:700px;margin:0 auto;padding:24px 16px">
                <div style="background:rgba(15,15,30,0.8);border:1px solid rgba(59,130,246,0.2);border-radius:16px;padding:28px">
                    <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:16px;margin-bottom:20px">
                        <div><h2 style="font-size:26px;font-weight:800;margin:0">{a["title"]}</h2><p style="color:#64748b;margin:4px 0 0 0">👤 {a["seller_name"]}</p></div>
                        <div style="background:linear-gradient(135deg,rgba(59,130,246,0.2),rgba(37,99,235,0.2));border:1px solid rgba(59,130,246,0.4);padding:14px 20px;border-radius:12px;text-align:center">
                            <div style="font-size:12px;color:#64748b">Цена</div>
                            <div style="font-size:24px;font-weight:800;color:#60a5fa">{a["price"]:.2f} ₽</div>
                        </div>
                    </div>
                    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin:20px 0">
                        <div style="background:rgba(0,0,0,0.3);padding:14px;border-radius:10px"><div style="font-size:12px;color:#64748b">🌍 Страна</div><div style="font-weight:600;margin-top:2px">{a["country"] or "-"}</div></div>
                        <div style="background:rgba(0,0,0,0.3);padding:14px;border-radius:10px"><div style="font-size:12px;color:#64748b">📋 Происхождение</div><div style="font-weight:600;margin-top:2px">{a["origin"] or "-"}</div></div>
                        <div style="background:rgba(0,0,0,0.3);padding:14px;border-radius:10px"><div style="font-size:12px;color:#64748b">🔐 2FA</div><div style="font-weight:600;margin-top:2px">{"✅ Да" if a["has_2fa"] else "❌ Нет"}</div></div>
                        <div style="background:rgba(0,0,0,0.3);padding:14px;border-radius:10px"><div style="font-size:12px;color:#64748b">🚫 Спамблок</div><div style="font-weight:600;margin-top:2px">{"⚠️ Есть" if a["spamblock"] else "✅ Нет"}</div></div>
                        <div style="background:rgba(0,0,0,0.3);padding:14px;border-radius:10px"><div style="font-size:12px;color:#64748b">💬 Чаты</div><div style="font-weight:600;margin-top:2px">{a["chats_count"]}</div></div>
                        <div style="background:rgba(0,0,0,0.3);padding:14px;border-radius:10px"><div style="font-size:12px;color:#64748b">📢 Каналы</div><div style="font-weight:600;margin-top:2px">{a["channels_count"]}</div></div>
                        <div style="background:rgba(0,0,0,0.3);padding:14px;border-radius:10px"><div style="font-size:12px;color:#64748b">👥 Группы</div><div style="font-weight:600;margin-top:2px">{a["groups_count"]}</div></div>
                    </div>
                    {desc}
                    <div style="display:flex;gap:10px">{buy}</div>
                </div>
            </div></body></html>'''
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
            if not acc:
                flash('Аккаунт недоступен', 'error')
                return redirect(url_for('index'))
            if g.user['balance'] < acc['price']:
                flash('Недостаточно средств', 'error')
                return redirect(url_for('deposit'))
            seller_earn = acc['price'] * (1 - COMMISSION)
            cur.execute("UPDATE users SET balance = balance - %s WHERE id = %s", (acc['price'], g.user['id']))
            cur.execute("UPDATE users SET balance = balance + %s WHERE id = %s", (seller_earn, acc['seller_id']))
            cur.execute("UPDATE accounts SET is_sold = TRUE WHERE id = %s", (account_id,))
            cur.execute("INSERT INTO purchases (buyer_id, account_id, phone_number) VALUES (%s, %s, %s) RETURNING id", (g.user['id'], account_id, 'Загрузка...'))
            purchase = cur.fetchone()
            db.commit()
            phone = extract_phone(acc['session_string'])
            if phone:
                cur.execute("UPDATE purchases SET phone_number = %s WHERE id = %s", (phone, purchase['id']))
                db.commit()
            flash('Покупка успешна! Перейдите в "Мои покупки" для получения кода.', 'success')
            return redirect(url_for('my_purchases'))
    except Exception as e:
        flash(f'Ошибка: {e}', 'error')
        return redirect(url_for('index'))

def extract_phone(session_string):
    try:
        client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
        client.connect()
        if client.is_user_authorized():
            me = client.get_me()
            phone = me.phone if me.phone else "Скрыт"
            client.disconnect()
            return phone
        client.disconnect()
    except: pass
    return "Скрыт"

@app.route('/my_purchases')
@login_required
def my_purchases():
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT p.*, a.title FROM purchases p JOIN accounts a ON p.account_id = a.id WHERE p.buyer_id = %s ORDER BY p.purchase_date DESC", (g.user['id'],))
            purchases = cur.fetchall()
        
        items = ''
        for p in purchases:
            cb = ''
            if not p['code_retrieved']:
                cb = f'<button onclick="getCode({p["id"]})" style="width:100%;padding:12px;background:linear-gradient(135deg,#3b82f6,#2563eb);color:#fff;border:none;border-radius:50px;cursor:pointer;font-size:14px;font-weight:600;box-shadow:0 4px 15px rgba(59,130,246,0.3);animation:pulse 2s infinite">📨 Получить код</button>'
            items += f'''<div style="background:rgba(15,15,30,0.8);border:1px solid rgba(59,130,246,0.2);border-radius:16px;padding:20px;margin-bottom:14px">
                <h3 style="font-size:18px;margin:0 0 8px 0">{p["title"]}</h3>
                <p style="color:#64748b;margin:0 0 12px 0">📅 {p["purchase_date"].strftime("%d.%m.%Y %H:%M")}</p>
                <div style="background:rgba(0,0,0,0.3);padding:14px;border-radius:10px;margin-bottom:12px">
                    📱 Номер: <strong>{p["phone_number"]}</strong>
                    <button onclick="copyText('{p["phone_number"]}')" style="margin-left:8px;padding:4px 10px;background:rgba(59,130,246,0.1);color:#93c5fd;border:1px solid rgba(59,130,246,0.3);border-radius:50px;cursor:pointer;font-size:12px">📋</button>
                </div>
                <div id="code-{p["id"]}"></div>
                {cb}
            </div>'''
        if not items: items = '<div style="text-align:center;padding:60px;color:#64748b"><div style="font-size:64px;margin-bottom:16px">🛒</div><h3>Нет покупок</h3><p>Купите свой первый аккаунт!</p><a href="/" style="display:inline-block;margin-top:12px;padding:10px 20px;background:linear-gradient(135deg,#3b82f6,#2563eb);color:#fff;border-radius:50px;text-decoration:none;font-weight:600">🔍 Смотреть аккаунты</a></div>'
        
        return f'''<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Мои покупки - Vest Accs</title>{STYLE}</head><body style="position:relative;z-index:1">
            {navbar()}
            <div style="max-width:1200px;margin:0 auto;padding:24px 16px"><h2 style="font-size:28px;font-weight:800;margin-bottom:24px">📦 Мои покупки</h2>{items}</div>
            {SCRIPT}</body></html>'''
    except Exception as e:
        return f'<h1>Ошибка: {e}</h1>', 500

@app.route('/get_code/<int:purchase_id>')
@login_required
def get_code(purchase_id):
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT p.*, a.session_string FROM purchases p JOIN accounts a ON p.account_id = a.id WHERE p.id = %s AND p.buyer_id = %s", (purchase_id, g.user['id']))
            purchase = cur.fetchone()
            if not purchase: return jsonify({'error': 'Покупка не найдена'}), 404
            code = extract_code(purchase['session_string'])
            if code:
                cur.execute("UPDATE purchases SET code_retrieved = TRUE WHERE id = %s", (purchase_id,))
                db.commit()
                return jsonify({'code': code})
            return jsonify({'error': 'Код не найден'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def extract_code(session_string):
    client = None
    try:
        client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
        client.connect()
        if not client.is_user_authorized(): return None
        dialogs = client.get_dialogs(limit=10)
        for dialog in dialogs:
            try:
                messages = client.get_messages(dialog, limit=10)
                for msg in messages:
                    if msg.message:
                        codes = re.findall(r'\b\d{5}\b', msg.message)
                        if codes: return codes[-1]
            except: continue
    except: pass
    finally:
        if client:
            try: client.disconnect()
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
                session['verify_phone'] = phone
                session['code_hash'] = result
                flash('Код отправлен в Telegram. Проверьте сообщения.', 'info')
            else: flash('Ошибка отправки кода', 'error')
        elif action == 'confirm_code':
            code = request.form.get('code', '').strip()
            phone = session.get('verify_phone', '')
            code_hash = session.get('code_hash', '')
            if not phone or not code_hash:
                flash('Сессия истекла', 'error')
                return redirect(url_for('profile'))
            try:
                client = TelegramClient(StringSession(), API_ID, API_HASH)
                client.connect()
                try:
                    client.sign_in(phone=phone, code=code, phone_code_hash=code_hash)
                    session['phone_verified'] = True
                    session['session_string'] = client.session.save()
                    session.pop('2fa_needed', None)
                    flash('Телефон подтвержден!', 'success')
                except SessionPasswordNeededError:
                    session['2fa_needed'] = True
                    session['client_temp'] = client.session.save()
                    flash('Требуется пароль 2FA', 'info')
                except PhoneCodeInvalidError:
                    flash('Неверный код', 'error')
                finally:
                    if not session.get('2fa_needed'): client.disconnect()
            except Exception as e:
                flash(f'Ошибка: {e}', 'error')
        elif action == 'confirm_2fa':
            password = request.form.get('password_2fa', '')
            try:
                client = TelegramClient(StringSession(session.get('client_temp', '')), API_ID, API_HASH)
                client.connect()
                try:
                    client.sign_in(password=password)
                    session['phone_verified'] = True
                    session['session_string'] = client.session.save()
                    session.pop('2fa_needed', None)
                    flash('2FA подтвержден!', 'success')
                except Exception as e: flash(f'Ошибка: {e}', 'error')
                finally: client.disconnect()
            except Exception as e: flash(f'Ошибка: {e}', 'error')
    
    extra = ''
    if session.get('verify_phone'):
        extra += '<form method="POST" style="padding:16px;background:rgba(0,0,0,0.3);border-radius:10px;margin-bottom:16px"><input type="hidden" name="action" value="confirm_code"><label style="display:block;margin-bottom:8px;font-weight:600;color:#93c5fd">Шаг 2: Код из Telegram</label><input type="text" name="code" required><button type="submit" style="width:100%;padding:12px;background:linear-gradient(135deg,#10b981,#059669);color:#fff;border:none;border-radius:50px;cursor:pointer;font-weight:600;margin-top:8px">✅ Подтвердить</button></form>'
    if session.get('2fa_needed'):
        extra += '<form method="POST" style="padding:16px;background:rgba(245,158,11,0.1);border:1px solid rgba(245,158,11,0.3);border-radius:10px;margin-bottom:16px"><input type="hidden" name="action" value="confirm_2fa"><label style="display:block;margin-bottom:8px;font-weight:600;color:#fbbf24">Шаг 3: Пароль 2FA</label><input type="password" name="password_2fa" required><button type="submit" style="width:100%;padding:12px;background:#f59e0b;color:#000;border:none;border-radius:50px;cursor:pointer;font-weight:600;margin-top:8px">🔐 Подтвердить 2FA</button></form>'
    if session.get('phone_verified'):
        extra += '<div style="padding:16px;background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.3);border-radius:10px;text-align:center"><p style="color:#10b981;font-weight:600">✅ Номер подтвержден!</p><a href="/sell" style="display:inline-block;padding:10px 20px;background:linear-gradient(135deg,#3b82f6,#2563eb);color:#fff;border-radius:50px;text-decoration:none;font-weight:600;margin-top:8px">📝 Заполнить данные аккаунта</a></div>'
    
    admin_btn = ''
    if g.user['is_admin']:
        admin_btn = '<a href="/admin" style="display:block;width:100%;padding:12px;background:#f59e0b;color:#000;border-radius:50px;text-decoration:none;font-weight:600;text-align:center;margin-top:16px">⚙️ Админ-панель</a>'
    
    return f'''<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Профиль - Vest Accs</title>{STYLE}</head><body style="position:relative;z-index:1">
        {navbar()}
        <div style="max-width:600px;margin:0 auto;padding:24px 16px">
            {flash_msgs()}
            <div style="background:rgba(15,15,30,0.8);border:1px solid rgba(59,130,246,0.2);border-radius:16px;padding:28px;margin-bottom:20px">
                <div style="display:flex;align-items:center;gap:14px">
                    <div style="width:55px;height:55px;background:linear-gradient(135deg,#3b82f6,#8b5cf6);border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:26px">👤</div>
                    <div><h3 style="margin:0">{g.user["username"]}</h3><span style="background:rgba(59,130,246,0.15);border:1px solid rgba(59,130,246,0.4);border-radius:50px;padding:8px 18px;font-weight:700;color:#60a5fa;display:inline-block;margin-top:4px">💰 {g.user["balance"]:.2f} ₽</span></div>
                </div>
            </div>
            <div style="background:rgba(15,15,30,0.8);border:1px solid rgba(59,130,246,0.2);border-radius:16px;padding:28px">
                <h3 style="margin-bottom:20px">📱 Выставить аккаунт на продажу</h3>
                <form method="POST" style="margin-bottom:20px">
                    <input type="hidden" name="action" value="verify_phone">
                    <label style="display:block;margin-bottom:8px;font-weight:600;color:#93c5fd">Шаг 1: Номер телефона</label>
                    <input type="text" name="phone" placeholder="+79001234567" required>
                    <button type="submit" style="width:100%;padding:12px;background:linear-gradient(135deg,#3b82f6,#2563eb);color:#fff;border:none;border-radius:50px;cursor:pointer;font-weight:600;margin-top:8px;box-shadow:0 4px 15px rgba(59,130,246,0.4);animation:pulse 2s infinite">📤 Отправить код</button>
                </form>
                {extra}
            </div>
            {admin_btn}
        </div></body></html>'''

def send_code(phone):
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

@app.route('/sell', methods=['GET', 'POST'])
@login_required
def sell_account():
    if not session.get('phone_verified'):
        flash('Сначала подтвердите номер телефона', 'error')
        return redirect(url_for('profile'))
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        origin = request.form.get('origin', '').strip()
        description = request.form.get('description', '').strip()
        price = request.form.get('price', type=float)
        has_2fa = request.form.get('has_2fa') == 'on'
        if not title or not price:
            flash('Название и цена обязательны', 'error')
        else:
            try:
                session_string = session.get('session_string')
                flash('Собираем данные аккаунта...', 'info')
                adata = gather_data(session_string)
                db = get_db()
                with db.cursor() as cur:
                    cur.execute("INSERT INTO accounts (seller_id,title,origin,description,price,session_string,country,has_2fa,spamblock,chats_count,channels_count,groups_count) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (g.user['id'],title,origin,description,price,session_string,adata.get('country',''),adata.get('has_2fa',has_2fa),adata.get('spamblock',False),adata.get('chats_count',0),adata.get('channels_count',0),adata.get('groups_count',0)))
                db.commit()
                for k in ['phone_verified','session_string','verify_phone','code_hash','client_temp','2fa_needed']:
                    session.pop(k, None)
                flash('Аккаунт успешно выставлен на продажу!', 'success')
                return redirect(url_for('index'))
            except Exception as e: flash(f'Ошибка: {e}', 'error')
    
    return f'''<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Продажа - Vest Accs</title>{STYLE}</head><body style="position:relative;z-index:1">
        <div style="background:rgba(10,10,25,0.95);border-bottom:1px solid rgba(59,130,246,0.3);padding:14px 24px;display:flex;justify-content:space-between;align-items:center">
            <a href="/" style="font-size:24px;font-weight:900;text-decoration:none;background:linear-gradient(135deg,#3b82f6,#8b5cf6,#3b82f6);background-size:200% 200%;-webkit-background-clip:text;-webkit-text-fill-color:transparent;animation:shimmer 3s ease infinite">⚡ Vest Accs</a>
            <a href="/profile" style="padding:10px 20px;background:rgba(59,130,246,0.1);color:#93c5fd;border:1px solid rgba(59,130,246,0.3);border-radius:50px;text-decoration:none;font-size:14px;font-weight:600">← Назад</a>
        </div>
        <div style="max-width:550px;margin:60px auto;background:rgba(15,15,30,0.9);border:1px solid rgba(59,130,246,0.3);border-radius:20px;padding:40px;backdrop-filter:blur(10px);box-shadow:0 20px 60px rgba(0,0,0,0.5)">
            <h2 style="font-size:30px;font-weight:900;text-align:center;margin-bottom:8px;background:linear-gradient(135deg,#3b82f6,#8b5cf6,#3b82f6);background-size:200% 200%;-webkit-background-clip:text;-webkit-text-fill-color:transparent;animation:shimmer 3s ease infinite">📱 Выставить аккаунт</h2>
            <p style="text-align:center;color:#64748b;margin-bottom:32px">Заполните данные аккаунта</p>
            {flash_msgs()}
            <form method="POST">
                <label style="display:block;margin-bottom:8px;font-weight:600;color:#93c5fd">📛 Название *</label>
                <input type="text" name="title" placeholder="Например: Премиум аккаунт" required>
                <label style="display:block;margin-bottom:8px;font-weight:600;color:#93c5fd">📋 Происхождение</label>
                <input type="text" name="origin" placeholder="Парсинг / Регистрация">
                <label style="display:block;margin-bottom:8px;font-weight:600;color:#93c5fd">📝 Описание</label>
                <textarea name="description" rows="4" placeholder="Опишите аккаунт..."></textarea>
                <label style="display:block;margin-bottom:8px;font-weight:600;color:#93c5fd">💎 Цена (₽) *</label>
                <input type="number" name="price" placeholder="1000" step="0.01" required>
                <label style="display:flex;align-items:center;gap:8px;margin-bottom:16px;cursor:pointer"><input type="checkbox" name="has_2fa" style="width:auto;margin:0"> 🔐 Есть 2FA</label>
                <button type="submit" style="width:100%;padding:14px;background:linear-gradient(135deg,#3b82f6,#2563eb);color:#fff;border:none;border-radius:50px;cursor:pointer;font-size:16px;font-weight:700;box-shadow:0 4px 15px rgba(59,130,246,0.4);animation:pulse 2s infinite">🚀 Выставить на продажу</button>
            </form>
            <p style="text-align:center;color:#64748b;margin-top:16px">💡 Комиссия платформы: 5%</p>
        </div></body></html>'''

def gather_data(session_string):
    data = {'country':'','has_2fa':False,'spamblock':False,'chats_count':0,'channels_count':0,'groups_count':0}
    client = None
    try:
        client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
        client.connect()
        if not client.is_user_authorized(): return data
        try:
            client.get_password_hint()
            data['has_2fa'] = True
        except: pass
        dialogs = client.get_dialogs(limit=100)
        for d in dialogs:
            if d.is_channel:
                if hasattr(d.entity,'megagroup') and d.entity.megagroup: data['groups_count'] += 1
                else: data['channels_count'] += 1
            else: data['chats_count'] += 1
    except: pass
    finally:
        if client:
            try: client.disconnect()
            except: pass
    return data

@app.route('/admin', methods=['GET', 'POST'])
@login_required
def admin_panel():
    if not g.user['is_admin']:
        flash('Доступ запрещен', 'error')
        return redirect(url_for('index'))
    try:
        db = get_db()
        if request.method == 'POST':
            uid = request.form.get('user_id', type=int)
            amount = request.form.get('amount', type=float)
            action = request.form.get('action')
            if uid and amount:
                with db.cursor() as cur:
                    if action == 'add': cur.execute("UPDATE users SET balance = balance + %s WHERE id = %s", (amount, uid))
                    elif action == 'set': cur.execute("UPDATE users SET balance = %s WHERE id = %s", (amount, uid))
                flash('Баланс обновлен', 'success')
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT id, username, balance, is_admin FROM users ORDER BY id")
            users = cur.fetchall()
        
        opts = ''.join([f'<option value="{u["id"]}">{u["username"]} ({u["balance"]:.2f} ₽)</option>' for u in users])
        rows = ''.join([f'<tr><td style="padding:12px 16px;border-top:1px solid rgba(59,130,246,0.2)">#{u["id"]}</td><td style="padding:12px 16px;border-top:1px solid rgba(59,130,246,0.2)"><strong>{u["username"]}</strong></td><td style="padding:12px 16px;border-top:1px solid rgba(59,130,246,0.2);color:#60a5fa;font-weight:600">{u["balance"]:.2f} ₽</td><td style="padding:12px 16px;border-top:1px solid rgba(59,130,246,0.2)">{"✅" if u["is_admin"] else "—"}</td></tr>' for u in users])
        
        return f'''<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Админ - Vest Accs</title>{STYLE}</head><body style="position:relative;z-index:1">
            {navbar()}
            <div style="max-width:1200px;margin:0 auto;padding:24px 16px">
                <h2 style="font-size:28px;font-weight:800;margin-bottom:24px">⚙️ Админ-панель</h2>
                {flash_msgs()}
                <div style="background:rgba(15,15,30,0.8);border:1px solid rgba(59,130,246,0.2);border-radius:16px;padding:28px;margin-bottom:20px">
                    <h3 style="margin-bottom:20px">💳 Изменить баланс пользователя</h3>
                    <form method="POST">
                        <label style="display:block;margin-bottom:8px;font-weight:600;color:#93c5fd">👤 Пользователь</label>
                        <select name="user_id" required><option value="">Выберите...</option>{opts}</select>
                        <label style="display:block;margin-bottom:8px;font-weight:600;color:#93c5fd">💰 Сумма</label>
                        <input type="number" name="amount" placeholder="1000" step="0.01" required>
                        <div style="display:flex;gap:10px;margin-top:16px">
                            <button type="submit" name="action" value="add" style="flex:1;padding:12px;background:linear-gradient(135deg,#10b981,#059669);color:#fff;border:none;border-radius:50px;cursor:pointer;font-weight:600">➕ Добавить</button>
                            <button type="submit" name="action" value="set" style="flex:1;padding:12px;background:#f59e0b;color:#000;border:none;border-radius:50px;cursor:pointer;font-weight:600">📌 Установить</button>
                        </div>
                    </form>
                </div>
                <div style="background:rgba(15,15,30,0.8);border:1px solid rgba(59,130,246,0.2);border-radius:16px;overflow-x:auto">
                    <h3 style="padding:20px;margin:0">👥 Все пользователи</h3>
                    <table style="width:100%;border-collapse:collapse"><thead><tr><th style="background:rgba(0,0,0,0.3);padding:12px 16px;text-align:left;font-weight:600;color:#93c5fd;font-size:13px;text-transform:uppercase">ID</th><th style="background:rgba(0,0,0,0.3);padding:12px 16px;text-align:left;font-weight:600;color:#93c5fd;font-size:13px;text-transform:uppercase">Логин</th><th style="background:rgba(0,0,0,0.3);padding:12px 16px;text-align:left;font-weight:600;color:#93c5fd;font-size:13px;text-transform:uppercase">Баланс</th><th style="background:rgba(0,0,0,0.3);padding:12px 16px;text-align:left;font-weight:600;color:#93c5fd;font-size:13px;text-transform:uppercase">Админ</th></tr></thead><tbody>{rows}</tbody></table>
                </div>
            </div></body></html>'''
    except Exception as e:
        return f'<h1>Ошибка: {e}</h1>', 500

if __name__ == '__main__':
    with app.app_context():
        init_db()
    print("=" * 50)
    print("Vest Accs - Маркетплейс Telegram аккаунтов")
    print("Сервер: http://0.0.0.0:5000")
    print("Админ: admin / admin123")
    print("=" * 50)
    app.run(debug=True, host='0.0.0.0', port=5000)
