import os
import re
import secrets
import traceback
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, render_template_string, request, redirect, url_for, session, flash, jsonify, g
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
import psycopg2.extras
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError

# --- Конфигурация ---
DATABASE_URL = "postgresql://bothost_db_3092f9da4312:yvzBra5xN_j2a_dafFbpHStZAVH7HiMuzJ2iCwDX-5w@node1.pghost.ru:15796/bothost_db_3092f9da4312"
API_ID = 32480523
API_HASH = "147839735c9fa4e83451209e9b55cfc5"
SECRET_KEY = secrets.token_hex(32)
COMMISSION = 0.05

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

# --- Работа с БД ---
def get_db():
    if 'db' not in g:
        g.db = psycopg2.connect(DATABASE_URL)
        g.db.autocommit = True
    return g.db

@app.teardown_appcontext
def close_db(error):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    db = get_db()
    with db.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(100) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                balance DECIMAL(10,2) DEFAULT 0.00,
                is_admin BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id SERIAL PRIMARY KEY,
                seller_id INTEGER REFERENCES users(id),
                title VARCHAR(200) NOT NULL,
                origin VARCHAR(100),
                description TEXT,
                price DECIMAL(10,2) NOT NULL,
                session_string TEXT NOT NULL,
                country VARCHAR(50),
                has_2fa BOOLEAN DEFAULT FALSE,
                spamblock BOOLEAN DEFAULT FALSE,
                chats_count INTEGER DEFAULT 0,
                channels_count INTEGER DEFAULT 0,
                groups_count INTEGER DEFAULT 0,
                is_sold BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS purchases (
                id SERIAL PRIMARY KEY,
                buyer_id INTEGER REFERENCES users(id),
                account_id INTEGER REFERENCES accounts(id),
                phone_number VARCHAR(20),
                purchase_date TIMESTAMP DEFAULT NOW(),
                code_retrieved BOOLEAN DEFAULT FALSE
            );
        """)
        cur.execute("SELECT COUNT(*) FROM users")
        if cur.fetchone()[0] == 0:
            cur.execute(
                "INSERT INTO users (username, password_hash, is_admin, balance) VALUES (%s, %s, TRUE, 999999.00)",
                ("admin", generate_password_hash("admin123"))
            )
    db.commit()

# --- Аутентификация ---
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

@app.before_request
def load_user():
    g.user = None
    if 'user_id' in session:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE id = %s", (session['user_id'],))
            g.user = cur.fetchone()

# --- HTML шаблоны (чистый CSS в style) ---
def base_page(title, content, extra_head=''):
    return f'''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - Vest Accs</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        :root {{
            --bg: #0a0a0f;
            --bg2: #13131a;
            --card: #1a1a24;
            --hover: #22222d;
            --accent: #8b5cf6;
            --accent2: #7c3aed;
            --green: #10b981;
            --red: #ef4444;
            --yellow: #f59e0b;
            --text: #e2e8f0;
            --text2: #94a3b8;
            --border: #2d2d3a;
            --radius: 16px;
            --radius2: 10px;
            --shadow: 0 8px 32px rgba(0,0,0,0.4);
        }}
        
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
            line-height: 1.6;
            background-image: 
                radial-gradient(ellipse at 20% 50%, rgba(139,92,246,0.06) 0%, transparent 50%),
                radial-gradient(ellipse at 80% 20%, rgba(16,185,129,0.04) 0%, transparent 50%);
        }}
        
        .navbar {{
            background: rgba(19,19,26,0.85);
            backdrop-filter: blur(20px);
            border-bottom: 1px solid var(--border);
            padding: 14px 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            position: sticky;
            top: 0;
            z-index: 100;
            gap: 16px;
            flex-wrap: wrap;
        }}
        
        .logo {{
            display: flex;
            align-items: center;
            gap: 8px;
            text-decoration: none;
            font-size: 22px;
            font-weight: 800;
            background: linear-gradient(135deg, var(--accent), #a78bfa);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        
        .nav-right {{
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
        }}
        
        .balance {{
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 50px;
            padding: 8px 18px;
            font-weight: 700;
            color: var(--green);
            font-size: 15px;
            white-space: nowrap;
        }}
        
        .btn {{
            padding: 10px 20px;
            border: none;
            border-radius: 50px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            transition: all 0.3s;
            white-space: nowrap;
        }}
        
        .btn:hover {{
            transform: translateY(-2px);
        }}
        
        .btn-primary {{
            background: linear-gradient(135deg, var(--accent), var(--accent2));
            color: #fff;
            box-shadow: 0 4px 15px rgba(139,92,246,0.3);
        }}
        
        .btn-primary:hover {{
            box-shadow: 0 8px 25px rgba(139,92,246,0.5);
        }}
        
        .btn-secondary {{
            background: var(--card);
            color: var(--text);
            border: 1px solid var(--border);
        }}
        
        .btn-secondary:hover {{
            background: var(--hover);
            border-color: #4d4d5a;
        }}
        
        .btn-success {{
            background: linear-gradient(135deg, var(--green), #34d399);
            color: #fff;
            box-shadow: 0 4px 15px rgba(16,185,129,0.3);
        }}
        
        .btn-success:hover {{
            box-shadow: 0 8px 25px rgba(16,185,129,0.5);
        }}
        
        .btn-add {{
            width: 38px;
            height: 38px;
            padding: 0;
            border-radius: 50%;
            justify-content: center;
            font-size: 22px;
            font-weight: bold;
        }}
        
        .btn-ghost {{
            background: transparent;
            color: var(--text);
        }}
        
        .btn-ghost:hover {{
            background: var(--card);
        }}
        
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 24px 16px;
        }}
        
        .page-title {{
            text-align: center;
            font-size: 32px;
            font-weight: 900;
            margin-bottom: 8px;
            background: linear-gradient(135deg, #e2e8f0, #cbd5e1);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        
        .page-subtitle {{
            text-align: center;
            color: var(--text2);
            margin-bottom: 32px;
        }}
        
        .filter-center {{
            text-align: center;
            margin-bottom: 24px;
        }}
        
        .filter-btn {{
            background: var(--card);
            border: 1px solid var(--border);
            color: var(--text);
            padding: 14px 28px;
            border-radius: 50px;
            cursor: pointer;
            font-size: 15px;
            font-weight: 600;
            transition: all 0.3s;
        }}
        
        .filter-btn:hover {{
            border-color: var(--accent);
            box-shadow: 0 0 20px rgba(139,92,246,0.2);
        }}
        
        .filter-panel {{
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 20px;
            margin-top: 12px;
            display: none;
            text-align: left;
        }}
        
        .filter-panel.active {{
            display: block;
        }}
        
        .filter-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 10px;
            margin-bottom: 16px;
        }}
        
        .filter-actions {{
            display: flex;
            gap: 10px;
            justify-content: center;
        }}
        
        input, textarea, select {{
            width: 100%;
            padding: 12px 16px;
            background: var(--bg);
            border: 1px solid var(--border);
            border-radius: var(--radius2);
            color: var(--text);
            font-size: 14px;
            font-family: inherit;
            transition: all 0.3s;
        }}
        
        input:focus, textarea:focus, select:focus {{
            outline: none;
            border-color: var(--accent);
            box-shadow: 0 0 0 3px rgba(139,92,246,0.2);
        }}
        
        select {{
            cursor: pointer;
            appearance: none;
            background-image: url("data:image/svg+xml,%3Csvg width='12' height='8' viewBox='0 0 12 8' fill='none' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M1 1.5L6 6.5L11 1.5' stroke='%2394a3b8' stroke-width='1.5' stroke-linecap='round'/%3E%3C/svg%3E");
            background-repeat: no-repeat;
            background-position: right 14px center;
            padding-right: 40px;
        }}
        
        .accounts-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
            gap: 20px;
        }}
        
        .account-card {{
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 20px;
            transition: all 0.3s;
            position: relative;
            overflow: hidden;
        }}
        
        .account-card:hover {{
            border-color: var(--accent);
            box-shadow: var(--shadow), 0 0 20px rgba(139,92,246,0.15);
            transform: translateY(-4px);
        }}
        
        .card-top {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 16px;
        }}
        
        .card-title {{
            font-size: 18px;
            font-weight: 700;
        }}
        
        .card-seller {{
            font-size: 13px;
            color: var(--text2);
        }}
        
        .card-price {{
            background: rgba(16,185,129,0.15);
            border: 1px solid rgba(16,185,129,0.3);
            color: var(--green);
            padding: 8px 16px;
            border-radius: 50px;
            font-weight: 700;
            font-size: 16px;
        }}
        
        .card-stats {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 8px;
            margin-bottom: 12px;
        }}
        
        .stat {{
            text-align: center;
            padding: 10px;
            background: var(--bg);
            border-radius: var(--radius2);
        }}
        
        .stat-num {{
            font-size: 18px;
            font-weight: 700;
            color: var(--accent);
        }}
        
        .stat-label {{
            font-size: 11px;
            color: var(--text2);
            text-transform: uppercase;
        }}
        
        .card-tags {{
            display: flex;
            gap: 6px;
            flex-wrap: wrap;
            margin-bottom: 12px;
        }}
        
        .tag {{
            padding: 4px 10px;
            border-radius: 50px;
            font-size: 12px;
            font-weight: 600;
        }}
        
        .tag-green {{
            background: rgba(16,185,129,0.2);
            color: var(--green);
        }}
        
        .tag-yellow {{
            background: rgba(245,158,11,0.2);
            color: var(--yellow);
        }}
        
        .tag-default {{
            background: var(--bg);
            color: var(--text2);
        }}
        
        .card-btns {{
            display: flex;
            gap: 8px;
        }}
        
        .card-btns .btn, .card-btns form {{
            flex: 1;
        }}
        
        .card-btns .btn {{
            justify-content: center;
        }}
        
        .profile-btn {{
            display: block;
            width: 100%;
            max-width: 500px;
            margin: 40px auto;
            padding: 16px;
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            color: var(--text);
            text-align: center;
            text-decoration: none;
            font-weight: 600;
            font-size: 16px;
            transition: all 0.3s;
        }}
        
        .profile-btn:hover {{
            border-color: var(--accent);
            box-shadow: 0 0 20px rgba(139,92,246,0.2);
        }}
        
        .form-box {{
            max-width: 420px;
            margin: 60px auto;
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 36px;
            box-shadow: var(--shadow);
        }}
        
        .form-box h2 {{
            font-size: 26px;
            font-weight: 800;
            text-align: center;
            margin-bottom: 6px;
            background: linear-gradient(135deg, var(--accent), #a78bfa);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        
        .form-box .sub {{
            text-align: center;
            color: var(--text2);
            margin-bottom: 24px;
            font-size: 14px;
        }}
        
        .form-group {{
            margin-bottom: 16px;
        }}
        
        .form-group label {{
            display: block;
            margin-bottom: 6px;
            font-weight: 600;
            color: var(--text2);
            font-size: 14px;
        }}
        
        .detail-card {{
            max-width: 700px;
            margin: 0 auto;
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 28px;
        }}
        
        .detail-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 14px;
            margin: 20px 0;
        }}
        
        .detail-item {{
            background: var(--bg);
            padding: 14px;
            border-radius: var(--radius2);
        }}
        
        .detail-label {{
            font-size: 12px;
            text-transform: uppercase;
            color: var(--text2);
            margin-bottom: 2px;
        }}
        
        .detail-val {{
            font-weight: 600;
        }}
        
        .alert {{
            padding: 12px 18px;
            border-radius: var(--radius2);
            margin-bottom: 16px;
            font-weight: 500;
        }}
        
        .alert-success {{
            background: rgba(16,185,129,0.15);
            border: 1px solid rgba(16,185,129,0.3);
            color: var(--green);
        }}
        
        .alert-error {{
            background: rgba(239,68,68,0.15);
            border: 1px solid rgba(239,68,68,0.3);
            color: var(--red);
        }}
        
        .alert-info {{
            background: rgba(59,130,246,0.15);
            border: 1px solid rgba(59,130,246,0.3);
            color: #3b82f6;
        }}
        
        .code-box {{
            font-size: 30px;
            font-weight: 800;
            letter-spacing: 6px;
            color: var(--green);
            text-align: center;
            padding: 18px;
            background: var(--bg);
            border-radius: var(--radius2);
            margin: 12px 0;
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        
        th {{
            background: var(--bg);
            padding: 12px 16px;
            text-align: left;
            font-weight: 600;
            color: var(--text2);
            font-size: 13px;
            text-transform: uppercase;
        }}
        
        td {{
            padding: 12px 16px;
            border-top: 1px solid var(--border);
        }}
        
        .purchase-card {{
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 20px;
            margin-bottom: 14px;
        }}
        
        @media (max-width: 768px) {{
            .navbar {{
                padding: 10px 14px;
            }}
            
            .accounts-grid {{
                grid-template-columns: 1fr;
            }}
            
            .filter-grid {{
                grid-template-columns: 1fr;
            }}
            
            .page-title {{
                font-size: 24px;
            }}
            
            .form-box {{
                margin: 20px 10px;
                padding: 24px;
            }}
            
            .card-btns {{
                flex-direction: column;
            }}
            
            .profile-btn {{
                max-width: 100%;
                margin: 24px 10px;
            }}
        }}
    </style>
    {extra_head}
</head>
<body>
    {content}
    <script>
        function toggleFilters() {{
            document.getElementById('filterPanel').classList.toggle('active');
        }}
        
        function copyText(text) {{
            navigator.clipboard.writeText(text).then(() => {{
                var t = document.createElement('div');
                t.style.cssText = 'position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#10b981;color:#fff;padding:10px 20px;border-radius:50px;font-weight:600;z-index:999;';
                t.textContent = '✓ Скопировано!';
                document.body.appendChild(t);
                setTimeout(function(){{ t.remove(); }}, 2000);
            }});
        }}
        
        function getCode(id) {{
            var btn = event.target;
            btn.disabled = true;
            btn.textContent = 'Загрузка...';
            fetch('/get_code/' + id)
                .then(function(r) {{ return r.json(); }})
                .then(function(d) {{
                    if (d.code) {{
                        document.getElementById('code-' + id).innerHTML = '<div class="code-box">' + d.code + '</div>';
                        btn.style.display = 'none';
                    }} else {{
                        alert('Ошибка: ' + (d.error || 'не найдено'));
                    }}
                }})
                .catch(function(e) {{ alert('Ошибка'); }})
                .finally(function() {{
                    btn.disabled = false;
                    btn.textContent = '📨 Получить код';
                }});
        }}
    </script>
</body>
</html>'''

# --- Шаблоны страниц ---
def index_page(accounts):
    navbar = ''
    if g.user:
        navbar = f'''
        <div class="navbar">
            <a href="/" class="logo">⚡ Vest Accs</a>
            <div class="nav-right">
                <span class="balance">💰 {g.user['balance']:.2f} ₽</span>
                <a href="/deposit" class="btn btn-add btn-success">+</a>
                <a href="/my_purchases" class="btn btn-ghost">📦 Покупки</a>
                <a href="/logout" class="btn btn-ghost">🚪</a>
            </div>
        </div>'''
    else:
        navbar = '''
        <div class="navbar">
            <a href="/" class="logo">⚡ Vest Accs</a>
            <div class="nav-right">
                <a href="/login" class="btn btn-ghost">Войти</a>
                <a href="/register" class="btn btn-primary">Регистрация</a>
            </div>
        </div>'''
    
    alerts = ''
    for cat, msg in get_flashed_messages(with_categories=True):
        alerts += f'<div class="alert alert-{cat}">{msg}</div>'
    
    cards = ''
    for a in accounts:
        tags = ''
        if a['has_2fa']:
            tags += '<span class="tag tag-yellow">🔐 2FA</span>'
        if a['spamblock']:
            tags += '<span class="tag tag-yellow">🚫 Спамблок</span>'
        tags += f'<span class="tag tag-default">🌍 {a["country"] or "?"}</span>'
        
        buy_btn = ''
        if g.user and g.user['id'] != a['seller_id']:
            buy_btn = f'<form action="/buy/{a["id"]}" method="POST" style="flex:1;"><button type="submit" class="btn btn-success" style="width:100%;justify-content:center;">🛒 Купить</button></form>'
        
        cards += f'''
        <div class="account-card">
            <div class="card-top">
                <div>
                    <div class="card-title">{a['title']}</div>
                    <div class="card-seller">👤 {a['seller_name']}</div>
                </div>
                <div class="card-price">{a['price']:.0f} ₽</div>
            </div>
            <div class="card-stats">
                <div class="stat"><div class="stat-num">{a['chats_count']}</div><div class="stat-label">Чаты</div></div>
                <div class="stat"><div class="stat-num">{a['channels_count']}</div><div class="stat-label">Каналы</div></div>
                <div class="stat"><div class="stat-num">{a['groups_count']}</div><div class="stat-label">Группы</div></div>
            </div>
            <div class="card-tags">{tags}</div>
            <div class="card-btns">
                <a href="/account/{a['id']}" class="btn btn-secondary" style="flex:1;justify-content:center;">📋 Детали</a>
                {buy_btn}
            </div>
        </div>'''
    
    if not accounts:
        cards = '<div style="text-align:center;grid-column:1/-1;padding:60px 20px;color:var(--text2);"><div style="font-size:64px;">📭</div><h3>Нет аккаунтов</h3></div>'
    
    profile_link = ''
    if g.user:
        profile_link = '<a href="/profile" class="profile-btn">👤 Профиль и продажа аккаунтов</a>'
    
    content = f'''
    {navbar}
    <div class="container">
        <h1 class="page-title">Маркетплейс Telegram аккаунтов</h1>
        <p class="page-subtitle">Покупайте и продавайте проверенные аккаунты</p>
        {alerts}
        <div class="filter-center">
            <button onclick="toggleFilters()" class="filter-btn">🔍 Фильтры и поиск</button>
            <div id="filterPanel" class="filter-panel">
                <form action="/filter" method="GET">
                    <div class="filter-grid">
                        <input type="text" name="q" placeholder="🔎 Поиск по заголовку...">
                        <input type="text" name="country" placeholder="🌍 Страна...">
                        <input type="text" name="origin" placeholder="📋 Происхождение...">
                        <select name="2fa"><option value="">🔐 2FA (любой)</option><option value="yes">✅ Есть</option><option value="no">❌ Нет</option></select>
                        <select name="spamblock"><option value="">🚫 Спамблок (любой)</option><option value="yes">⚠️ Есть</option><option value="no">✅ Нет</option></select>
                        <input type="number" name="min_chats" placeholder="💬 Мин. чатов...">
                    </div>
                    <div class="filter-actions">
                        <button type="submit" class="btn btn-primary">🔍 Применить</button>
                        <a href="/" class="btn btn-secondary">↺ Сбросить</a>
                    </div>
                </form>
            </div>
        </div>
        <div class="accounts-grid">{cards}</div>
        {profile_link}
    </div>'''
    return base_page('Главная', content)

def login_page():
    alerts = ''
    for cat, msg in get_flashed_messages(with_categories=True):
        alerts += f'<div class="alert alert-{cat}">{msg}</div>'
    
    content = f'''
    <div class="navbar"><a href="/" class="logo">⚡ Vest Accs</a></div>
    <div class="form-box">
        <h2>С возвращением</h2>
        <p class="sub">Войдите в свой аккаунт</p>
        {alerts}
        <form method="POST">
            <div class="form-group"><label>👤 Логин</label><input type="text" name="username" placeholder="Введите логин" required></div>
            <div class="form-group"><label>🔒 Пароль</label><input type="password" name="password" placeholder="Введите пароль" required></div>
            <button type="submit" class="btn btn-primary" style="width:100%;justify-content:center;padding:12px;">🚀 Войти</button>
        </form>
        <p style="text-align:center;margin-top:16px;color:var(--text2);">Нет аккаунта? <a href="/register" style="color:var(--accent);">Создать</a></p>
    </div>'''
    return base_page('Вход', content)

def register_page():
    alerts = ''
    for cat, msg in get_flashed_messages(with_categories=True):
        alerts += f'<div class="alert alert-{cat}">{msg}</div>'
    
    content = f'''
    <div class="navbar"><a href="/" class="logo">⚡ Vest Accs</a></div>
    <div class="form-box">
        <h2>Присоединяйтесь</h2>
        <p class="sub">Создайте аккаунт</p>
        {alerts}
        <form method="POST">
            <div class="form-group"><label>👤 Логин</label><input type="text" name="username" placeholder="Придумайте логин" required></div>
            <div class="form-group"><label>🔒 Пароль</label><input type="password" name="password" placeholder="Придумайте пароль" required></div>
            <button type="submit" class="btn btn-primary" style="width:100%;justify-content:center;padding:12px;">✨ Зарегистрироваться</button>
        </form>
        <p style="text-align:center;margin-top:16px;color:var(--text2);">Есть аккаунт? <a href="/login" style="color:var(--accent);">Войти</a></p>
    </div>'''
    return base_page('Регистрация', content)

def account_detail_page(account):
    buy_form = ''
    if g.user and g.user['id'] != account['seller_id'] and not account['is_sold']:
        buy_form = f'<form action="/buy/{account["id"]}" method="POST"><button type="submit" class="btn btn-success" style="width:100%;justify-content:center;">🛒 Купить аккаунт</button></form>'
    
    content = f'''
    <div class="navbar">
        <a href="/" class="logo">⚡ Vest Accs</a>
        <div class="nav-right"><a href="/" class="btn btn-secondary">← Назад</a></div>
    </div>
    <div class="container">
        <div class="detail-card">
            <div style="display:flex;justify-content:space-between;align-items:start;flex-wrap:wrap;gap:16px;">
                <div>
                    <h2 style="font-size:26px;font-weight:800;">{account['title']}</h2>
                    <p style="color:var(--text2);">👤 {account['seller_name']}</p>
                </div>
                <div style="background:rgba(16,185,129,0.15);border:1px solid rgba(16,185,129,0.3);padding:14px 20px;border-radius:12px;text-align:center;">
                    <div style="font-size:12px;color:var(--text2);">Цена</div>
                    <div style="font-size:24px;font-weight:800;color:var(--green);">{account['price']:.2f} ₽</div>
                </div>
            </div>
            <div class="detail-grid">
                <div class="detail-item"><div class="detail-label">🌍 Страна</div><div class="detail-val">{account['country'] or '-'}</div></div>
                <div class="detail-item"><div class="detail-label">📋 Происхождение</div><div class="detail-val">{account['origin'] or '-'}</div></div>
                <div class="detail-item"><div class="detail-label">🔐 2FA</div><div class="detail-val">{'✅ Да' if account['has_2fa'] else '❌ Нет'}</div></div>
                <div class="detail-item"><div class="detail-label">🚫 Спамблок</div><div class="detail-val">{'⚠️ Есть' if account['spamblock'] else '✅ Нет'}</div></div>
                <div class="detail-item"><div class="detail-label">💬 Чаты</div><div class="detail-val">{account['chats_count']}</div></div>
                <div class="detail-item"><div class="detail-label">📢 Каналы</div><div class="detail-val">{account['channels_count']}</div></div>
                <div class="detail-item"><div class="detail-label">👥 Группы</div><div class="detail-val">{account['groups_count']}</div></div>
            </div>
            {f'<div style="background:var(--bg);padding:16px;border-radius:10px;margin:16px 0;"><div class="detail-label">📝 Описание</div><p>{account["description"]}</p></div>' if account.get('description') else ''}
            <div style="display:flex;gap:10px;flex-wrap:wrap;">{buy_form}</div>
        </div>
    </div>'''
    return base_page(account['title'], content)

def profile_page():
    alerts = ''
    for cat, msg in get_flashed_messages(with_categories=True):
        alerts += f'<div class="alert alert-{cat}">{msg}</div>'
    
    extra = ''
    if session.get('verify_phone'):
        extra += '''
        <form method="POST" style="padding:16px;background:var(--bg);border-radius:10px;margin-bottom:16px;">
            <input type="hidden" name="action" value="confirm_code">
            <div class="form-group"><label>Шаг 2: Код из Telegram</label><input type="text" name="code" placeholder="12345" required></div>
            <button type="submit" class="btn btn-success" style="width:100%;justify-content:center;">✅ Подтвердить</button>
        </form>'''
    
    if session.get('2fa_needed'):
        extra += '''
        <form method="POST" style="padding:16px;background:rgba(245,158,11,0.1);border:1px solid rgba(245,158,11,0.3);border-radius:10px;margin-bottom:16px;">
            <input type="hidden" name="action" value="confirm_2fa">
            <div class="form-group"><label>Шаг 3: Пароль 2FA</label><input type="password" name="password_2fa" placeholder="Пароль" required></div>
            <button type="submit" class="btn" style="width:100%;justify-content:center;background:var(--yellow);color:#000;">🔐 Подтвердить</button>
        </form>'''
    
    if session.get('phone_verified'):
        extra += '''
        <div style="padding:16px;background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.3);border-radius:10px;text-align:center;">
            <p style="color:var(--green);font-weight:600;margin-bottom:10px;">✅ Номер подтвержден!</p>
            <a href="/sell" class="btn btn-primary">📝 Заполнить данные</a>
        </div>'''
    
    admin_btn = ''
    if g.user and g.user['is_admin']:
        admin_btn = '<a href="/admin" class="btn" style="width:100%;justify-content:center;background:var(--yellow);color:#000;margin-top:16px;">⚙️ Админ-панель</a>'
    
    content = f'''
    <div class="navbar">
        <a href="/" class="logo">⚡ Vest Accs</a>
        <div class="nav-right">
            <span class="balance">💰 {g.user["balance"]:.2f} ₽</span>
            <a href="/deposit" class="btn btn-add btn-success">+</a>
        </div>
    </div>
    <div class="container" style="max-width:600px;">
        {alerts}
        <div style="background:var(--card);border:1px solid var(--border);border-radius:16px;padding:28px;margin-bottom:20px;">
            <div style="display:flex;align-items:center;gap:14px;margin-bottom:20px;">
                <div style="width:55px;height:55px;background:linear-gradient(135deg,var(--accent),#a78bfa);border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:26px;">👤</div>
                <div><h3>{g.user['username']}</h3><span class="balance" style="display:inline-flex;margin-top:4px;">{g.user['balance']:.2f} ₽</span></div>
            </div>
        </div>
        <div style="background:var(--card);border:1px solid var(--border);border-radius:16px;padding:28px;">
            <h3 style="font-size:18px;margin-bottom:20px;">📱 Выставить аккаунт на продажу</h3>
            <form method="POST" style="margin-bottom:20px;">
                <input type="hidden" name="action" value="verify_phone">
                <div class="form-group"><label>Шаг 1: Номер телефона</label><input type="text" name="phone" placeholder="+79001234567" required></div>
                <button type="submit" class="btn btn-primary" style="width:100%;justify-content:center;">📤 Отправить код</button>
            </form>
            {extra}
        </div>
        {admin_btn}
    </div>'''
    return base_page('Профиль', content)

def sell_page():
    content = f'''
    <div class="navbar">
        <a href="/" class="logo">⚡ Vest Accs</a>
        <div class="nav-right"><a href="/profile" class="btn btn-secondary">← Профиль</a></div>
    </div>
    <div class="form-box" style="max-width:550px;">
        <h2>📱 Выставить аккаунт</h2>
        <p class="sub">Заполните данные</p>
        <form method="POST">
            <div class="form-group"><label>📛 Название *</label><input type="text" name="title" placeholder="Премиум аккаунт" required></div>
            <div class="form-group"><label>📋 Происхождение</label><input type="text" name="origin" placeholder="Парсинг / Регистрация"></div>
            <div class="form-group"><label>📝 Описание</label><textarea name="description" rows="3" placeholder="Подробности..."></textarea></div>
            <div class="form-group"><label>💎 Цена (₽) *</label><input type="number" name="price" placeholder="1000" step="0.01" required></div>
            <div class="form-group"><label style="display:flex;align-items:center;gap:6px;cursor:pointer;"><input type="checkbox" name="has_2fa" style="width:auto;"> 🔐 Есть 2FA</label></div>
            <button type="submit" class="btn btn-primary" style="width:100%;justify-content:center;padding:14px;">🚀 Выставить</button>
        </form>
        <p style="text-align:center;color:var(--text2);margin-top:12px;">💡 Комиссия: 5%</p>
    </div>'''
    return base_page('Продажа', content)

def purchases_page(purchases):
    items = ''
    for p in purchases:
        code_block = f'<div id="code-{p["id"]}"></div>'
        code_btn = ''
        if not p['code_retrieved']:
            code_btn = f'<button onclick="getCode({p["id"]})" class="btn btn-primary" style="width:100%;justify-content:center;">📨 Получить код</button>'
        
        items += f'''
        <div class="purchase-card">
            <h3 style="font-size:18px;">{p['title']}</h3>
            <p style="color:var(--text2);">📅 {p['purchase_date'].strftime('%d.%m.%Y %H:%M')}</p>
            <div style="background:var(--bg);padding:14px;border-radius:10px;margin:12px 0;">
                <span>📱 Номер: <strong>{p['phone_number']}</strong></span>
                <button onclick="copyText('{p['phone_number']}')" class="btn btn-secondary" style="padding:4px 10px;font-size:12px;margin-left:8px;">📋</button>
            </div>
            {code_block}
            {code_btn}
        </div>'''
    
    if not purchases:
        items = '<div style="text-align:center;padding:60px 20px;color:var(--text2);"><div style="font-size:64px;">🛒</div><h3>Нет покупок</h3><a href="/" class="btn btn-primary" style="margin-top:12px;">🔍 К покупкам</a></div>'
    
    content = f'''
    <div class="navbar">
        <a href="/" class="logo">⚡ Vest Accs</a>
        <div class="nav-right">
            <span class="balance">💰 {g.user["balance"]:.2f} ₽</span>
            <a href="/deposit" class="btn btn-add btn-success">+</a>
        </div>
    </div>
    <div class="container"><h2 style="font-size:28px;font-weight:800;margin-bottom:20px;">📦 Мои покупки</h2>{items}</div>'''
    return base_page('Покупки', content)

def deposit_page():
    content = f'''
    <div class="navbar">
        <a href="/" class="logo">⚡ Vest Accs</a>
        <div class="nav-right"><span class="balance">💰 {g.user["balance"]:.2f} ₽</span></div>
    </div>
    <div class="form-box">
        <h2>Пополнение</h2>
        <p class="sub">Текущий баланс: <strong style="color:var(--green);">{g.user['balance']:.2f} ₽</strong></p>
        <form method="POST">
            <div class="form-group"><label>💰 Сумма</label><input type="number" name="amount" placeholder="1000" step="0.01" required></div>
            <button type="submit" class="btn btn-success" style="width:100%;justify-content:center;padding:12px;">💎 Пополнить</button>
        </form>
    </div>'''
    return base_page('Пополнение', content)

def admin_page(users):
    alerts = ''
    for cat, msg in get_flashed_messages(with_categories=True):
        alerts += f'<div class="alert alert-{cat}">{msg}</div>'
    
    user_rows = ''
    for u in users:
        user_rows += f'<tr><td>#{u["id"]}</td><td><strong>{u["username"]}</strong></td><td style="color:var(--green);font-weight:600;">{u["balance"]:.2f} ₽</td><td>{"✅" if u["is_admin"] else "—"}</td></tr>'
    
    user_options = ''
    for u in users:
        user_options += f'<option value="{u["id"]}">{u["username"]} ({u["balance"]:.2f} ₽)</option>'
    
    content = f'''
    <div class="navbar">
        <a href="/" class="logo">⚡ Vest Accs</a>
        <div class="nav-right"><a href="/profile" class="btn btn-secondary">← Профиль</a></div>
    </div>
    <div class="container">
        <h2 style="font-size:28px;font-weight:800;margin-bottom:24px;">⚙️ Админ-панель</h2>
        {alerts}
        <div style="background:var(--card);border:1px solid var(--border);border-radius:16px;padding:28px;margin-bottom:20px;">
            <h3>💳 Изменить баланс</h3>
            <form method="POST">
                <div class="form-group"><label>👤 Пользователь</label><select name="user_id" required><option value="">Выберите...</option>{user_options}</select></div>
                <div class="form-group"><label>💰 Сумма</label><input type="number" name="amount" placeholder="1000" step="0.01" required></div>
                <div style="display:flex;gap:10px;">
                    <button type="submit" name="action" value="add" class="btn btn-success" style="flex:1;justify-content:center;">➕ Добавить</button>
                    <button type="submit" name="action" value="set" class="btn" style="flex:1;justify-content:center;background:var(--yellow);color:#000;">📌 Установить</button>
                </div>
            </form>
        </div>
        <div style="background:var(--card);border:1px solid var(--border);border-radius:16px;overflow-x:auto;">
            <h3 style="padding:20px;">👥 Пользователи</h3>
            <table>
                <tr><th>ID</th><th>Логин</th><th>Баланс</th><th>Админ</th></tr>
                {user_rows}
            </table>
        </div>
    </div>'''
    return base_page('Админ', content)

# --- Маршруты ---
@app.route('/')
def index():
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("""
            SELECT a.*, u.username as seller_name FROM accounts a
            JOIN users u ON a.seller_id = u.id
            WHERE a.is_sold = FALSE ORDER BY a.created_at DESC
        """)
        accounts = cur.fetchall()
    return index_page(accounts)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if not username or not password:
            flash('Заполните все поля', 'error')
            return register_page()
        db = get_db()
        try:
            with db.cursor() as cur:
                cur.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s)", (username, generate_password_hash(password)))
            db.commit()
            flash('Регистрация успешна!', 'success')
            return redirect(url_for('login'))
        except psycopg2.IntegrityError:
            db.rollback()
            flash('Пользователь существует', 'error')
    return register_page()

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE username = %s", (username,))
            user = cur.fetchone()
            if user and check_password_hash(user['password_hash'], password):
                session['user_id'] = user['id']
                session.permanent = True
                return redirect(url_for('index'))
        flash('Неверный логин или пароль', 'error')
    return login_page()

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
    return deposit_page()

@app.route('/filter', methods=['GET'])
def filter_accounts():
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
    return index_page(accounts)

@app.route('/account/<int:account_id>')
def account_detail(account_id):
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT a.*, u.username as seller_name FROM accounts a JOIN users u ON a.seller_id = u.id WHERE a.id = %s", (account_id,))
        account = cur.fetchone()
    if not account:
        flash('Аккаунт не найден', 'error')
        return redirect(url_for('index'))
    return account_detail_page(account)

@app.route('/buy/<int:account_id>', methods=['POST'])
@login_required
def buy_account(account_id):
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT * FROM accounts WHERE id = %s AND is_sold = FALSE", (account_id,))
        account = cur.fetchone()
        if not account:
            flash('Аккаунт недоступен', 'error')
            return redirect(url_for('index'))
        if g.user['balance'] < account['price']:
            flash('Недостаточно средств', 'error')
            return redirect(url_for('deposit'))
        
        seller_earn = account['price'] * (1 - COMMISSION)
        cur.execute("UPDATE users SET balance = balance - %s WHERE id = %s", (account['price'], g.user['id']))
        cur.execute("UPDATE users SET balance = balance + %s WHERE id = %s", (seller_earn, account['seller_id']))
        cur.execute("UPDATE accounts SET is_sold = TRUE WHERE id = %s", (account_id,))
        cur.execute("INSERT INTO purchases (buyer_id, account_id, phone_number) VALUES (%s, %s, %s) RETURNING id", (g.user['id'], account_id, 'Загрузка...'))
        purchase = cur.fetchone()
        db.commit()
        
        phone = extract_phone(account['session_string'])
        if phone:
            cur.execute("UPDATE purchases SET phone_number = %s WHERE id = %s", (phone, purchase['id']))
            db.commit()
        
        flash('Покупка успешна!', 'success')
        return redirect(url_for('my_purchases'))

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
    except:
        pass
    return "Скрыт"

@app.route('/my_purchases')
@login_required
def my_purchases():
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT p.*, a.title FROM purchases p JOIN accounts a ON p.account_id = a.id WHERE p.buyer_id = %s ORDER BY p.purchase_date DESC", (g.user['id'],))
        purchases = cur.fetchall()
    return purchases_page(purchases)

@app.route('/get_code/<int:purchase_id>')
@login_required
def get_code(purchase_id):
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT p.*, a.session_string FROM purchases p JOIN accounts a ON p.account_id = a.id WHERE p.id = %s AND p.buyer_id = %s", (purchase_id, g.user['id']))
        purchase = cur.fetchone()
        if not purchase:
            return jsonify({'error': 'Не найдена'}), 404
        
        code = extract_code(purchase['session_string'])
        if code:
            cur.execute("UPDATE purchases SET code_retrieved = TRUE WHERE id = %s", (purchase_id,))
            db.commit()
            return jsonify({'code': code})
        return jsonify({'error': 'Код не найден'}), 404

def extract_code(session_string):
    client = None
    try:
        client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
        client.connect()
        if not client.is_user_authorized():
            return None
        dialogs = client.get_dialogs(limit=10)
        for dialog in dialogs:
            try:
                messages = client.get_messages(dialog, limit=10)
                for msg in messages:
                    if msg.message:
                        codes = re.findall(r'\b\d{5}\b', msg.message)
                        if codes:
                            return codes[-1]
            except:
                continue
        return None
    except:
        return None
    finally:
        if client:
            try: client.disconnect()
            except: pass

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
                flash('Код отправлен!', 'info')
            else:
                flash('Ошибка отправки', 'error')
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
                    flash('Подтвержден!', 'success')
                except SessionPasswordNeededError:
                    session['2fa_needed'] = True
                    session['client_temp'] = client.session.save()
                    flash('Нужен пароль 2FA', 'info')
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
                    flash('Готово!', 'success')
                except Exception as e:
                    flash(f'Ошибка: {e}', 'error')
                finally:
                    client.disconnect()
            except Exception as e:
                flash(f'Ошибка: {e}', 'error')
    return profile_page()

def send_code(phone):
    client = None
    try:
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        client.connect()
        result = client.send_code_request(phone)
        return result.phone_code_hash
    except:
        return None
    finally:
        if client:
            try: client.disconnect()
            except: pass

@app.route('/sell', methods=['GET', 'POST'])
@login_required
def sell_account():
    if not session.get('phone_verified'):
        flash('Сначала подтвердите номер', 'error')
        return redirect(url_for('profile'))
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        origin = request.form.get('origin', '').strip()
        description = request.form.get('description', '').strip()
        price = request.form.get('price', type=float)
        has_2fa = request.form.get('has_2fa') == 'on'
        if not title or not price:
            flash('Название и цена обязательны', 'error')
            return sell_page()
        
        session_string = session.get('session_string')
        flash('Сбор данных...', 'info')
        adata = gather_data(session_string)
        
        db = get_db()
        with db.cursor() as cur:
            cur.execute("INSERT INTO accounts (seller_id, title, origin, description, price, session_string, country, has_2fa, spamblock, chats_count, channels_count, groups_count) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (g.user['id'], title, origin, description, price, session_string, adata.get('country',''), adata.get('has_2fa',has_2fa), adata.get('spamblock',False), adata.get('chats_count',0), adata.get('channels_count',0), adata.get('groups_count',0)))
        db.commit()
        
        for k in ['phone_verified','session_string','verify_phone','code_hash','client_temp','2fa_needed']:
            session.pop(k, None)
        flash('Выставлен!', 'success')
        return redirect(url_for('index'))
    return sell_page()

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
    return admin_page(users)

if __name__ == '__main__':
    with app.app_context():
        try:
            init_db()
            print("✓ БД готова")
        except Exception as e:
            print(f"✗ Ошибка БД: {e}")
    print("http://0.0.0.0:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)
