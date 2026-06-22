import re
import secrets
import traceback
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
import telethon.sync
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

COUNTRIES = [
    "Россия", "США", "Германия", "Франция", "Италия", "Испания", "Украина", "Беларусь", "Казахстан", "Турция",
    "Китай", "Япония", "Южная Корея", "Индия", "Бразилия", "Мексика", "Канада", "Австралия", "Аргентина", "Чили",
    "Великобритания", "Нидерланды", "Бельгия", "Швейцария", "Австрия", "Польша", "Чехия", "Швеция", "Норвегия", "Дания",
    "Финляндия", "Португалия", "Греция", "Венгрия", "Румыния", "Болгария", "Сербия", "Хорватия", "Словакия", "Ирландия"
]

ORIGINS = ["Авторег", "Саморег", "Стиллер", "Фишинг"]

def ensure_loop():
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

def detect_country_by_phone(phone):
    phone = re.sub(r'\D', '', phone)
    prefixes = {
        '79': 'Россия', '73': 'Россия', '74': 'Россия', '75': 'Россия',
        '77': 'Казахстан', '380': 'Украина', '375': 'Беларусь',
        '994': 'Азербайджан', '995': 'Грузия', '374': 'Армения',
        '998': 'Узбекистан', '992': 'Таджикистан', '996': 'Кыргызстан',
        '373': 'Молдова', '1': 'США', '44': 'Великобритания',
        '49': 'Германия', '33': 'Франция', '39': 'Италия', '34': 'Испания',
        '90': 'Турция', '86': 'Китай', '48': 'Польша', '971': 'ОАЭ'
    }
    for pref in sorted(prefixes.keys(), key=len, reverse=True):
        if phone.startswith(pref):
            return prefixes[pref]
    return "Интернациональный"

def hash_password(password):
    salt = secrets.token_hex(16)
    return f"{salt}$" + hashlib.sha256((password + salt).encode()).hexdigest()

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
    if db is not None:
        db.close()

def init_db():
    db = psycopg2.connect(DATABASE_URL)
    db.autocommit = True
    with db.cursor() as cur:
        cur.execute("CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username VARCHAR(100) UNIQUE NOT NULL, password_hash VARCHAR(255) NOT NULL, balance DECIMAL(10,2) DEFAULT 0.00, is_admin BOOLEAN DEFAULT FALSE, sales_count INTEGER DEFAULT 0, api_key VARCHAR(64), created_at TIMESTAMP DEFAULT NOW())")
        cur.execute("CREATE TABLE IF NOT EXISTS accounts (id SERIAL PRIMARY KEY, seller_id INTEGER REFERENCES users(id), title VARCHAR(200) NOT NULL, origin VARCHAR(100), description TEXT, price DECIMAL(10,2) NOT NULL, session_string TEXT NOT NULL, country VARCHAR(50), has_2fa BOOLEAN DEFAULT FALSE, spamblock BOOLEAN DEFAULT FALSE, is_premium BOOLEAN DEFAULT FALSE, chats_count INTEGER DEFAULT 0, channels_count INTEGER DEFAULT 0, groups_count INTEGER DEFAULT 0, is_sold BOOLEAN DEFAULT FALSE, created_at TIMESTAMP DEFAULT NOW())")
        cur.execute("CREATE TABLE IF NOT EXISTS purchases (id SERIAL PRIMARY KEY, buyer_id INTEGER REFERENCES users(id), account_id INTEGER REFERENCES accounts(id), phone_number VARCHAR(20), purchase_date TIMESTAMP DEFAULT NOW(), code_retrieved BOOLEAN DEFAULT FALSE)")
        cur.execute("CREATE TABLE IF NOT EXISTS balance_history (id SERIAL PRIMARY KEY, user_id INTEGER REFERENCES users(id), amount DECIMAL(10,2), type VARCHAR(50), description TEXT, created_at TIMESTAMP DEFAULT NOW())")
        cur.execute("CREATE TABLE IF NOT EXISTS withdrawals (id SERIAL PRIMARY KEY, user_id INTEGER REFERENCES users(id), amount_rub DECIMAL(10,2), amount_usdt DECIMAL(10,6), address VARCHAR(200), status VARCHAR(20) DEFAULT 'pending', created_at TIMESTAMP DEFAULT NOW())")
        cur.execute("CREATE TABLE IF NOT EXISTS crypto_invoices (id SERIAL PRIMARY KEY, user_id INTEGER REFERENCES users(id), invoice_id VARCHAR(100), amount_rub DECIMAL(10,2), status VARCHAR(20) DEFAULT 'pending', created_at TIMESTAMP DEFAULT NOW())")
        cur.execute("CREATE TABLE IF NOT EXISTS reviews (id SERIAL PRIMARY KEY, buyer_id INTEGER REFERENCES users(id), seller_id INTEGER REFERENCES users(id), account_id INTEGER REFERENCES accounts(id), rating INTEGER DEFAULT 5, text TEXT, created_at TIMESTAMP DEFAULT NOW())")

        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS sales_count INTEGER DEFAULT 0")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS api_key VARCHAR(64)")
        cur.execute("ALTER TABLE crypto_invoices ADD COLUMN IF NOT EXISTS pay_url TEXT")
        cur.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS is_premium BOOLEAN DEFAULT FALSE")
        cur.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS chats_count INTEGER DEFAULT 0")
        cur.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS channels_count INTEGER DEFAULT 0")
        cur.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS groups_count INTEGER DEFAULT 0")
        cur.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS spamblock BOOLEAN DEFAULT FALSE")
        cur.execute("ALTER TABLE purchases ADD COLUMN IF NOT EXISTS phone_number VARCHAR(20)")
        cur.execute("ALTER TABLE purchases ADD COLUMN IF NOT EXISTS purchase_date TIMESTAMP DEFAULT NOW()")
        cur.execute("ALTER TABLE purchases ADD COLUMN IF NOT EXISTS code_retrieved BOOLEAN DEFAULT FALSE")

        cur.execute("SELECT COUNT(*) FROM users WHERE username = %s", ("vest",))
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO users (username, password_hash, is_admin, balance, sales_count, api_key) VALUES (%s, %s, TRUE, 999999.00, 0, %s)", ("vest", hash_password("55337q"), secrets.token_hex(16)))
        else:
            cur.execute("UPDATE users SET is_admin = TRUE WHERE username = %s", ("vest",))
            cur.execute("UPDATE users SET api_key = %s WHERE username = %s AND api_key IS NULL", (secrets.token_hex(16), "vest"))
    db.close()

try:
    init_db()
except Exception as e:
    print(f"Ошибка миграции БД: {e}")

def get_seller_rating(seller_id):
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT rating FROM reviews WHERE seller_id = %s", (seller_id,))
            explicit = [r['rating'] for r in cur.fetchall()]
            if not explicit:
                return None, 0
            total_stars = sum(explicit)
            total_reviews = len(explicit)
            if total_reviews == 0:
                return None, 0
            return f"{total_stars / total_reviews:.1f}", total_reviews
    except:
        return None, 0

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def api_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
        if not api_key:
            return jsonify({'error': 'API key required'}), 401
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE api_key = %s", (api_key,))
            g.user = cur.fetchone()
        if not g.user:
            return jsonify({'error': 'Invalid API key'}), 401
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
        except:
            pass

def flash_msgs():
    return ''.join([f'<div style="padding:14px 18px;border-radius:14px;margin-bottom:16px;font-size:14px;font-weight:600;background:rgba({("16,185,129" if c=="success" else "239,68,68" if c=="error" else "42,171,238")},0.1);border:1px solid rgba({("16,185,129" if c=="success" else "239,68,68" if c=="error" else "42,171,238")},0.2);color:#{"34d399" if c=="success" else "fca5a5" if c=="error" else "7dd3fc"};animation: slideIn 0.3s ease">{m}</div>' for c,m in get_flashed_messages(with_categories=True)])

STYLE = '''<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
:root {
    --primary: #2AABEE; --primary-light: #7dd3fc; --primary-dark: #1d8ec9;
    --bg: #0a0a10; --bg-secondary: #111118; --bg-card: #16161f; --bg-hover: #1c1c28;
    --border: rgba(42,171,238,0.06); --border-active: rgba(42,171,238,0.15);
    --text: #f1f5f9; --text-secondary: #94a3b8; --text-muted: #64748b;
    --success: #34d399; --warning: #fbbf24; --danger: #fca5a5; --price: #ffb703;
    --radius: 14px; --radius-sm: 10px; --radius-lg: 20px;
}
body.light{--bg:#f8fafc;--bg-secondary:#fff;--bg-card:#fff;--bg-hover:#f1f5f9;--border:rgba(0,0,0,0.06);--border-active:rgba(42,171,238,0.2);--text:#0f172a;--text-secondary:#475569;--text-muted:#94a3b8}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;overflow-x:hidden;display:flex;flex-direction:column;line-height:1.5;transition:background 0.3s,color 0.3s}
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:rgba(128,128,128,0.2);border-radius:10px}
@keyframes slideIn{from{opacity:0;transform:translateY(-10px)}to{opacity:1;transform:translateY(0)}}
@keyframes fadeInUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}
@keyframes gradient{0%{background-position:0% 50%}50%{background-position:100% 50%}100%{background-position:0% 50%}}
.navbar{background:var(--bg-secondary);border-bottom:1px solid var(--border);padding:14px 24px;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:100;backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px)}
.logo{font-size:24px;font-weight:900;text-decoration:none;letter-spacing:-0.8px;background:linear-gradient(135deg,var(--primary),var(--primary-light),var(--primary),var(--primary-light));background-size:300% 100%;-webkit-background-clip:text;-webkit-text-fill-color:transparent;animation:gradient 3s ease infinite}
.balance-badge{background:rgba(42,171,238,0.08);border:1px solid rgba(42,171,238,0.12);padding:8px 16px;border-radius:30px;color:var(--primary-light);font-weight:700;font-size:13px}
.theme-toggle{width:36px;height:36px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);cursor:pointer;border-radius:var(--radius-sm);display:flex;align-items:center;justify-content:center;font-size:16px;transition:0.2s}
.theme-toggle:hover{background:rgba(255,255,255,0.04)}
.burger{width:36px;height:36px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);cursor:pointer;display:flex;flex-direction:column;justify-content:center;align-items:center;gap:4px;border-radius:var(--radius-sm);z-index:102}
.burger span{display:block;width:18px;height:2px;background:var(--text-secondary);border-radius:2px;transition:0.3s}
.burger.open span:nth-child(1){transform:translateY(6px) rotate(45deg);background:var(--primary-light)}
.burger.open span:nth-child(2){opacity:0}
.burger.open span:nth-child(3){transform:translateY(-6px) rotate(-45deg);background:var(--primary-light)}
.sidebar{position:fixed;top:0;right:0;width:250px;height:100vh;background:var(--bg-secondary);border-left:1px solid var(--border);z-index:101;transition:transform 0.35s cubic-bezier(0.4,0,0.2,1);padding:85px 16px 20px;display:flex;flex-direction:column;gap:6px;transform:translateX(100%)}
.sidebar.open{transform:translateX(0)}
.sidebar a{display:flex;align-items:center;gap:10px;padding:12px 14px;color:var(--text-secondary);text-decoration:none;border-radius:var(--radius-sm);font-weight:500;transition:0.2s;font-size:13px;border:1px solid transparent}
.sidebar a:hover{background:rgba(42,171,238,0.06);color:var(--text);border-color:var(--border-active)}
.sidebar .divider{height:1px;background:var(--border);margin:6px 0}
.overlay{position:fixed;top:0;left:0;width:100vw;height:100vh;background:rgba(0,0,0,0.6);backdrop-filter:blur(4px);z-index:99;display:none}
.overlay.show{display:block}
.main-content{flex:1}
.container{max-width:1100px;margin:0 auto;padding:24px 20px;width:100%}
.btn{padding:11px 22px;border:none;border-radius:var(--radius);cursor:pointer;font-size:13px;font-weight:600;text-decoration:none;display:inline-flex;align-items:center;justify-content:center;gap:6px;transition:all 0.2s;font-family:inherit;white-space:nowrap}
.btn-primary{background:linear-gradient(135deg,var(--primary),var(--primary-dark));color:#fff}
.btn-primary:hover{transform:translateY(-1px);box-shadow:0 4px 15px rgba(42,171,238,0.3)}
.btn-secondary{background:rgba(255,255,255,0.02);color:var(--text-secondary);border:1px solid rgba(255,255,255,0.06)}
.btn-secondary:hover{background:rgba(255,255,255,0.04);color:var(--text);border-color:var(--border-active)}
.btn-success{background:#10b981;color:#fff}
.btn-sm{padding:7px 14px;font-size:12px;border-radius:8px}
.btn-danger{background:rgba(239,68,68,0.08);color:var(--danger);border:1px solid rgba(239,68,68,0.2)}
.btn-danger:hover{background:rgba(239,68,68,0.15)}
.btn-ghost{background:transparent;color:var(--text-secondary);border:1px solid transparent}
.btn-ghost:hover{background:rgba(255,255,255,0.02);border-color:rgba(255,255,255,0.08)}
.btn-copy{background:rgba(42,171,238,0.08);color:var(--primary-light);border:1px solid var(--border-active);font-size:11px;padding:6px 12px;border-radius:6px;cursor:pointer;transition:0.2s}
.btn-copy:hover{background:rgba(42,171,238,0.15)}
.btn-copy.copied{background:rgba(16,185,129,0.15);border-color:rgba(16,185,129,0.3);color:var(--success)}
.card{background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius-lg);padding:18px;transition:all 0.25s ease}
.card:hover{border-color:var(--border-active);transform:translateY(-2px);box-shadow:0 8px 30px rgba(0,0,0,0.3)}
.accounts-list{display:flex;flex-direction:column;gap:10px}
.account-card-compact{display:flex;align-items:center;justify-content:space-between;background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);padding:14px 18px;transition:all 0.2s ease;gap:16px}
.account-card-compact:hover{border-color:var(--border-active);background:var(--bg-hover)}
.acc-top{display:flex;flex-direction:column;gap:4px;min-width:0;flex:1}
.acc-title-row{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.acc-title{font-weight:600;font-size:14px;color:var(--text);text-decoration:none}
.acc-title:hover{color:var(--primary-light)}
.acc-seller{font-size:13px;font-weight:600;color:var(--primary-light);white-space:nowrap}
.acc-rating{font-size:11px;color:var(--text-muted)}
.acc-bottom{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.acc-tags{display:flex;gap:4px;flex-wrap:wrap}
.acc-tag{padding:3px 8px;border-radius:20px;font-size:10px;font-weight:600;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.04);color:var(--text-secondary);white-space:nowrap}
.acc-tag.green{background:rgba(16,185,129,0.08);border-color:rgba(16,185,129,0.15);color:var(--success)}
.acc-tag.red{background:rgba(239,68,68,0.08);border-color:rgba(239,68,68,0.15);color:var(--danger)}
.acc-tag.purple{background:rgba(139,92,246,0.08);border-color:rgba(139,92,246,0.15);color:#c084fc}
.acc-right{display:flex;align-items:center;gap:10px;flex-shrink:0}
.acc-price{color:var(--price);font-weight:800;font-size:15px}
input,textarea,select{width:100%;padding:13px 16px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:var(--radius);color:var(--text);font-size:14px;outline:none;margin-bottom:14px;transition:border-color 0.2s;font-family:inherit}
input:focus,textarea:focus,select:focus{border-color:var(--primary)}
.form-box{max-width:440px;margin:40px auto;background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius-lg);padding:32px}
table{width:100%;border-collapse:collapse}
th{padding:10px 14px;text-align:left;color:var(--text-muted);font-size:11px;text-transform:uppercase;font-weight:700;letter-spacing:0.5px}
td{padding:13px 14px;font-size:13px;border-bottom:1px solid var(--border)}
tr:last-child td{border-bottom:none}
.bottom-sheet-backdrop{position:fixed;top:0;left:0;width:100vw;height:100vh;background:rgba(0,0,0,0.6);z-index:200;display:none;backdrop-filter:blur(4px)}
.bottom-sheet-backdrop.active{display:block}
.bottom-sheet{position:fixed;bottom:0;left:0;right:0;background:var(--bg-card);border-top:1px solid rgba(255,255,255,0.06);border-radius:22px 22px 0 0;z-index:201;transform:translateY(100%);transition:transform 0.3s ease;max-height:70vh;display:flex;flex-direction:column}
.bottom-sheet.active{transform:translateY(0)}
.bottom-sheet-header{padding:18px 24px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--border)}
.bottom-sheet-header h3{font-size:17px;font-weight:700}
.bottom-sheet-close{background:transparent;border:none;color:var(--text-muted);font-size:22px;cursor:pointer;line-height:1}
.bottom-sheet-content{padding:16px 24px 24px;overflow-y:auto;flex:1}
.sheet-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:8px}
.sheet-item{padding:11px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:var(--radius-sm);text-align:center;font-size:13px;font-weight:500;color:var(--text-secondary);cursor:pointer;transition:0.2s}
.sheet-item:hover{background:rgba(42,171,238,0.06);color:var(--text)}
.sheet-item.selected{background:linear-gradient(135deg,var(--primary),var(--primary-dark));color:#fff;border-color:transparent}
.modal{position:fixed;top:0;left:0;width:100vw;height:100vh;background:rgba(0,0,0,0.7);backdrop-filter:blur(8px);z-index:300;opacity:0;visibility:hidden;display:flex;align-items:flex-end;justify-content:center;transition:0.3s}
.modal.active{opacity:1;visibility:visible}
.modal-content{background:var(--bg-card);border:1px solid rgba(255,255,255,0.06);border-radius:22px 22px 0 0;padding:28px;width:100%;max-width:520px;max-height:85vh;overflow-y:auto;transform:translateY(100%);transition:transform 0.3s ease}
.modal.active .modal-content{transform:translateY(0)}
@media(min-width:769px){.modal{align-items:center}.modal-content{border-radius:var(--radius-lg);width:92%;transform:scale(0.95)}.modal.active .modal-content{transform:scale(1)}}
.profile-container{max-width:700px;margin:0 auto}
.profile-header{background:linear-gradient(135deg,var(--bg-card),var(--bg-hover));border:1px solid var(--border);border-radius:var(--radius-lg);padding:28px;margin-bottom:24px}
.profile-header h2{font-size:22px;font-weight:800;margin-bottom:4px}
.profile-header .role{font-size:13px;color:var(--text-muted);margin-bottom:8px}
.profile-header .balance{font-size:28px;font-weight:800;color:var(--success);margin-bottom:16px}
.profile-stats{display:flex;gap:12px}
.profile-stats .stat{flex:1;background:rgba(255,255,255,0.02);border:1px solid var(--border);border-radius:var(--radius);padding:14px;text-align:center;cursor:pointer;transition:0.2s}
.profile-stats .stat:hover{background:rgba(42,171,238,0.04);border-color:var(--border-active)}
.stat-value{font-size:18px;font-weight:800;color:var(--text)}
.stat-label{font-size:11px;color:var(--text-muted);font-weight:600;text-transform:uppercase;letter-spacing:0.5px;margin-top:2px}
.section-card{background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius-lg);padding:20px;margin-bottom:20px}
.section-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px}
.section-header h3{font-size:16px;font-weight:700}
.tab-nav{display:flex;gap:4px;background:rgba(255,255,255,0.02);padding:4px;border-radius:var(--radius);margin-bottom:16px}
.tab-btn{flex:1;padding:10px;text-align:center;border-radius:10px;cursor:pointer;font-weight:600;font-size:13px;color:var(--text-muted);background:transparent;border:none;transition:0.2s;font-family:inherit}
.tab-btn.active{background:rgba(42,171,238,0.15);color:var(--primary-light)}
.tab-content{display:none}
.tab-content.active{display:block}
.purchase-card{background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius-lg);padding:22px;margin-bottom:14px;animation:fadeInUp 0.3s ease;cursor:pointer;transition:0.2s}
.purchase-card:hover{border-color:var(--border-active)}
.purchase-card.expanded{border-color:var(--border-active)}
.purchase-title{font-size:18px;font-weight:700;margin-bottom:4px}
.purchase-date{color:var(--text-muted);font-size:12px;margin-bottom:12px}
.purchase-preview{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.purchase-preview .preview-tag{padding:3px 8px;border-radius:20px;font-size:10px;font-weight:600;background:rgba(42,171,238,0.06);border:1px solid var(--border-active);color:var(--primary-light);white-space:nowrap}
.purchase-detail{display:none;margin-top:16px}
.purchase-card.expanded .purchase-detail{display:block}
.purchase-info{display:flex;flex-direction:column;gap:10px;margin-bottom:16px}
.info-block{background:rgba(255,255,255,0.02);border:1px solid var(--border);border-radius:var(--radius);padding:14px}
.info-label{font-size:11px;color:var(--text-muted);font-weight:600;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px}
.info-value{font-size:14px;font-weight:600;word-break:break-all}
.info-value.mono{font-family:monospace;font-size:12px;color:var(--text-secondary)}
.code-section{background:rgba(255,255,255,0.02);border:1px solid var(--border);border-radius:var(--radius);padding:16px;margin-bottom:14px}
.code-box{background:var(--bg);border:1px solid rgba(255,255,255,0.06);border-radius:var(--radius-sm);padding:14px;text-align:center;font-family:monospace;font-size:16px;color:var(--primary-light);margin-top:8px;letter-spacing:2px}
.download-section{background:rgba(255,255,255,0.02);border:1px solid var(--border);border-radius:var(--radius);padding:16px}
.download-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.stars{display:flex;gap:6px;justify-content:center;margin:12px 0}
.star{font-size:28px;cursor:pointer;color:rgba(255,255,255,0.1);transition:0.2s}
.star:hover,.star.active{color:var(--warning)}
.auth-container{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
.auth-card{background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius-lg);padding:36px;width:100%;max-width:400px;animation:fadeInUp 0.5s ease}
.auth-header{text-align:center;margin-bottom:28px}
.auth-header h2{font-size:26px;font-weight:900;margin-bottom:6px;background:linear-gradient(135deg,var(--primary),var(--primary-light));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.filter-bar{max-width:440px;margin:0 auto 24px;background:var(--bg-card);padding:18px;border-radius:var(--radius-lg);border:1px solid var(--border)}
.filter-btn{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);color:var(--text);width:100%;padding:13px;border-radius:var(--radius);cursor:pointer;font-weight:600;font-size:14px;font-family:inherit}
.filter-drop{display:none;margin-top:12px}
.filter-drop.show{display:block}
.sort-buttons{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
.sort-btn{padding:7px 12px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:8px;color:var(--text-secondary);cursor:pointer;font-size:12px;font-weight:600;text-decoration:none;transition:0.2s}
.sort-btn.active,.sort-btn:hover{background:rgba(42,171,238,0.1);border-color:var(--border-active);color:var(--primary-light)}
.custom-select-trigger{width:100%;padding:13px 16px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:var(--radius);color:var(--text-secondary);font-size:14px;cursor:pointer;margin-bottom:14px;display:flex;justify-content:space-between;align-items:center}
.custom-select-trigger::after{content:'▼';font-size:10px;color:var(--text-muted)}
.spec-row{display:flex;justify-content:space-between;align-items:center;padding:11px 14px;background:rgba(255,255,255,0.01);border:1px solid var(--border);border-radius:var(--radius-sm);margin-bottom:5px;font-size:13px}
.spec-lbl{color:var(--text-muted);font-weight:500}
.spec-val{color:var(--text);font-weight:600}
.rating-badge{background:rgba(251,191,36,0.06);border:1px solid rgba(251,191,36,0.15);color:var(--warning);padding:3px 8px;border-radius:20px;font-size:11px;font-weight:700;display:inline-flex;align-items:center;gap:3px}
.support-link{color:var(--primary-light);text-decoration:none;font-weight:600;transition:0.2s}
.support-link:hover{text-decoration:underline}
.footer{background:var(--bg-secondary);border-top:1px solid var(--border);padding:32px 24px;text-align:center;margin-top:auto}
.footer-content{max-width:1100px;margin:0 auto;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:16px}
.footer-brand{font-size:20px;font-weight:900;letter-spacing:-0.5px;background:linear-gradient(135deg,var(--primary),var(--primary-light));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.footer-links{display:flex;gap:24px;align-items:center}
.footer-links a{color:var(--text-secondary);text-decoration:none;font-size:14px;font-weight:500;transition:0.2s}
.footer-links a:hover{color:var(--primary-light)}
.footer-copyright{color:var(--text-muted);font-size:12px;margin-top:12px}
.empty-state{text-align:center;padding:50px 20px}
.empty-state h3{color:var(--text-muted);margin-bottom:8px}
.page-title{font-size:28px;font-weight:900;text-align:center;margin:20px 0 6px}
.page-sub{text-align:center;color:var(--text-muted);margin-bottom:24px;font-size:14px}
.pagination{text-align:center;margin-top:24px;display:flex;justify-content:center;gap:6px;flex-wrap:wrap}
.pagination a,.pagination span{padding:8px 14px;background:rgba(255,255,255,0.02);border-radius:var(--radius-sm);color:var(--text-secondary);text-decoration:none;font-size:13px;font-weight:600;transition:0.2s}
.pagination span.active{background:rgba(42,171,238,0.15);color:var(--primary-light)}
.pagination a:hover{background:rgba(42,171,238,0.08);color:var(--text)}
.api-key-display{background:var(--bg);border:1px solid var(--border-active);border-radius:var(--radius-sm);padding:16px;font-family:monospace;font-size:14px;color:var(--primary-light);text-align:center;word-break:break-all;margin:12px 0}
@media(max-width:768px){.navbar{padding:12px 16px}.logo{font-size:20px}.balance-badge{font-size:11px;padding:6px 12px}.container{padding:16px 12px}.account-card-compact{padding:12px 14px;gap:10px}.acc-title{font-size:13px}.acc-tag{font-size:9px;padding:2px 6px}.acc-price{font-size:14px}.profile-header{padding:20px}.profile-header .balance{font-size:24px}.profile-stats{flex-wrap:wrap}.profile-stats .stat{min-width:80px}.page-title{font-size:22px}.auth-card{padding:24px}.footer{padding:24px 16px}.footer-content{flex-direction:column;text-align:center;gap:12px}.download-grid{grid-template-columns:1fr}}
</style>'''

SCRIPT = '''
<script>
document.body.addEventListener('click', function(e) {
    var burger = e.target.closest('#burger');
    if (burger) { e.preventDefault(); document.getElementById('sidebar').classList.toggle('open'); document.getElementById('overlay').classList.toggle('show'); burger.classList.toggle('open'); return; }
    if (e.target.closest('#overlay')) { document.getElementById('sidebar').classList.remove('open'); document.getElementById('burger').classList.remove('open'); document.getElementById('overlay').classList.remove('show'); return; }
    if (e.target.closest('#themeToggle')) { document.body.classList.toggle('light'); localStorage.setItem('theme', document.body.classList.contains('light') ? 'light' : 'dark'); return; }
    if (e.target.closest('.filter-btn')) { document.getElementById('filterDrop').classList.toggle('show'); return; }
    var tab = e.target.closest('.tab-btn');
    if (tab) { var tabId = tab.getAttribute('data-tab'); var container = tab.closest('.modal-content') || tab.closest('.section-card') || document; container.querySelectorAll('.tab-btn').forEach(function(b){b.classList.remove('active')}); container.querySelectorAll('.tab-content').forEach(function(c){c.classList.remove('active')}); tab.classList.add('active'); var t=document.getElementById(tabId); if(t)t.classList.add('active'); return; }
    var trigger = e.target.closest('.custom-select-trigger');
    if (trigger) { var s=document.getElementById(trigger.getAttribute('data-sheet')); if(s){s.classList.add('active');document.getElementById('sheet-backdrop').classList.add('active')} return; }
    if (e.target.closest('.bottom-sheet-close') || e.target.id === 'sheet-backdrop') { document.querySelectorAll('.bottom-sheet,.bottom-sheet-backdrop').forEach(function(el){el.classList.remove('active')}); return; }
    var winTrigger = e.target.closest('.window-trigger-btn');
    if (winTrigger) { var w=document.getElementById(winTrigger.getAttribute('data-window')); if(w)w.classList.add('active'); return; }
    var closeBtn = e.target.closest('.window-close');
    if (closeBtn) { var m=closeBtn.closest('.modal'); if(m)m.classList.remove('active'); return; }
    if (e.target.classList.contains('modal')) { e.target.classList.remove('active'); return; }
    var sheetItem = e.target.closest('.sheet-item');
    if (sheetItem) {
        var type=sheetItem.getAttribute('data-type'),val=sheetItem.getAttribute('data-value'),hi=document.getElementById(type+'_hidden'),te=document.querySelector('.custom-select-trigger[data-sheet="sheet_'+type+'"] span');
        if (sheetItem.parentElement.classList.contains('multi-select')) { sheetItem.classList.toggle('selected'); var si=sheetItem.parentElement.querySelectorAll('.sheet-item.selected'),vs=Array.from(si).map(function(i){return i.getAttribute('data-value')}); if(hi)hi.value=vs.join(','); if(te)te.textContent=vs.length>0?'Выбрано: '+vs.length:'Выбрать...'; }
        else { sheetItem.parentElement.querySelectorAll('.sheet-item').forEach(function(e){e.classList.remove('selected')}); sheetItem.classList.add('selected'); if(hi)hi.value=val; if(te)te.textContent=sheetItem.textContent; document.querySelectorAll('.bottom-sheet,.bottom-sheet-backdrop').forEach(function(e){e.classList.remove('active')}); }
        return;
    }
    var copyBtn = e.target.closest('.btn-copy');
    if (copyBtn) { var t=copyBtn.getAttribute('data-copy'); navigator.clipboard.writeText(t).then(function(){copyBtn.textContent='Скопировано';copyBtn.classList.add('copied');setTimeout(function(){copyBtn.textContent='Копировать';copyBtn.classList.remove('copied')},2000)}); return; }
    var checkBtn = e.target.closest('.btn-check-valid');
    if (checkBtn) { e.preventDefault(); var aid=checkBtn.getAttribute('data-id'); checkBtn.disabled=true;checkBtn.textContent='Проверка...'; fetch('/check_valid/'+aid).then(function(r){return r.json()}).then(function(d){checkBtn.className=d.valid?'btn btn-success btn-sm':'btn btn-danger btn-sm';checkBtn.textContent=d.valid?'Валид':'Невалид'}).catch(function(){checkBtn.disabled=false;checkBtn.textContent='Проверить'}); return; }
    var deleteBtn = e.target.closest('.btn-delete-acc');
    if (deleteBtn) { e.preventDefault(); if(confirm('Удалить объявление?')){window.location.href='/delete_account/'+deleteBtn.getAttribute('data-id')} return; }
    var getCodeBtn = e.target.closest('.btn-get-code');
    if (getCodeBtn) { e.preventDefault(); var pid=getCodeBtn.getAttribute('data-id'); getCodeBtn.disabled=true;getCodeBtn.textContent='Загрузка...'; fetch('/get_code/'+pid).then(function(r){return r.json()}).then(function(d){if(d.code){var ce=document.getElementById('code-'+pid);if(ce)ce.innerHTML='<div class="code-box">'+d.code+'</div>';getCodeBtn.style.display='none'}else{alert('Ошибка: '+(d.error||'код не найден'));getCodeBtn.disabled=false;getCodeBtn.textContent='Получить код'}}).catch(function(){getCodeBtn.disabled=false;getCodeBtn.textContent='Получить код'}); return; }
    var star = e.target.closest('.star');
    if (star) { var r=parseInt(star.getAttribute('data-rating')),sc=star.parentElement; sc.querySelectorAll('.star').forEach(function(s){s.classList.toggle('active',parseInt(s.getAttribute('data-rating'))<=r)}); var pid=sc.id.replace('review-stars-',''),ri=document.getElementById('review-rating-'+pid); if(ri)ri.value=r; return; }
    var purchaseCard = e.target.closest('.purchase-card');
    if (purchaseCard && !e.target.closest('button') && !e.target.closest('a') && !e.target.closest('.modal')) { purchaseCard.classList.toggle('expanded'); return; }
    var regenBtn = e.target.closest('#regenApiKey');
    if (regenBtn) { e.preventDefault(); if(confirm('Сгенерировать новый API ключ? Старый перестанет работать.')){fetch('/regen_api_key').then(function(r){return r.json()}).then(function(d){if(d.api_key){document.getElementById('apiKeyDisplay').textContent=d.api_key;document.getElementById('apiKeyCopy').setAttribute('data-copy',d.api_key)}else{alert('Ошибка')}})} return; }
});
document.body.addEventListener('input', function(e) {
    var si = e.target.closest('.sheet-search-input');
    if (si) { var v=si.value.toLowerCase(); document.querySelectorAll('#sheet_country .sheet-item').forEach(function(i){i.style.display=i.textContent.toLowerCase().includes(v)?'block':'none'}); }
});
if (localStorage.getItem('theme') === 'light') { document.body.classList.add('light'); }
</script>
'''

FAQ_HTML = '''
<div class="form-box" style="max-width:700px"><h2 style="margin-bottom:6px">FAQ — Частые вопросы</h2><p style="color:var(--text-muted);margin-bottom:20px;font-size:13px">Ответы на популярные вопросы</p><div style="display:flex;flex-direction:column;gap:16px">
<div class="info-block"><div class="info-label">Как купить аккаунт?</div><p style="font-size:13px;color:var(--text-secondary);margin-top:4px">Пополните баланс, выберите аккаунт и нажмите «Купить». После оплаты он появится в «Мои покупки».</p></div>
<div class="info-block"><div class="info-label">Как войти в купленный аккаунт?</div><p style="font-size:13px;color:var(--text-secondary);margin-top:4px">Скачайте сессию Telethon или JSON, используйте код из Telegram. При проблемах — в поддержку.</p></div>
<div class="info-block"><div class="info-label">Как продать аккаунт?</div><p style="font-size:13px;color:var(--text-secondary);margin-top:4px">В боковом меню нажмите «Продать аккаунт», введите номер, подтвердите вход и заполните объявление.</p></div>
<div class="info-block"><div class="info-label">Как вывести средства?</div><p style="font-size:13px;color:var(--text-secondary);margin-top:4px">Минимум 50 ₽, нужна 1 продажа. Укажите адрес TON в разделе «Вывод средств».</p></div>
<div class="info-block"><div class="info-label">Что такое спамблок?</div><p style="font-size:13px;color:var(--text-secondary);margin-top:4px">Ограничение Telegram на отправку сообщений. Аккаунты без спамблока ценятся выше.</p></div>
<div class="info-block"><div class="info-label">Аккаунт не работает — что делать?</div><p style="font-size:13px;color:var(--text-secondary);margin-top:4px">Проверьте валидность перед покупкой. Если уже куплен — <a href="https://t.me/VestAccsSupport" class="support-link" target="_blank">напишите в поддержку</a>.</p></div>
</div></div>'''

RULES_HTML = '''
<div class="form-box" style="max-width:700px"><h2 style="margin-bottom:6px">Правила сервиса</h2><p style="color:var(--text-muted);margin-bottom:20px;font-size:13px">Используя Vest Accs, вы соглашаетесь с правилами</p><div style="display:flex;flex-direction:column;gap:16px">
<div class="info-block"><div class="info-label">1. Запрещённые действия</div><p style="font-size:13px;color:var(--text-secondary);margin-top:4px">Запрещено мошенничество и обман других пользователей. Запрещена продажа нерабочих аккаунтов.</p></div>
<div class="info-block"><div class="info-label">2. Возвраты</div><p style="font-size:13px;color:var(--text-secondary);margin-top:4px">Возврат возможен только если аккаунт не соответствует описанию. Заявки рассматриваются администрацией.</p></div>
<div class="info-block"><div class="info-label">3. Комиссия сервиса</div><p style="font-size:13px;color:var(--text-secondary);margin-top:4px">Комиссия за продажу — 5% от цены. Пополнение без комиссии через Crypto Bot.</p></div>
<div class="info-block"><div class="info-label">4. Вывод средств</div><p style="font-size:13px;color:var(--text-secondary);margin-top:4px">Минимум 50 ₽. Нужна 1 успешная продажа. Выводы обрабатываются администратором.</p></div>
<div class="info-block"><div class="info-label">5. Ответственность</div><p style="font-size:13px;color:var(--text-secondary);margin-top:4px">Администрация не несёт ответственности за действия третьих лиц. Споры решаются с участием администрации.</p></div>
<div class="info-block"><div class="info-label">6. Контакты</div><p style="font-size:13px;color:var(--text-secondary);margin-top:4px">Поддержка: <a href="https://t.me/VestAccsSupport" class="support-link" target="_blank">@VestAccsSupport</a></p></div>
</div></div>'''

API_DOCS_HTML = '''
<div class="form-box" style="max-width:800px"><h2 style="margin-bottom:6px">API Документация</h2><p style="color:var(--text-muted);margin-bottom:20px;font-size:13px">API v2 — программный доступ к маркету</p>
<p style="color:var(--text-muted);margin-bottom:8px;font-size:13px"><strong>Базовый URL:</strong> <code style="background:var(--bg);padding:2px 8px;border-radius:4px;color:var(--primary-light)">https://ваш-домен/api/v2</code></p>
<p style="color:var(--text-muted);margin-bottom:16px;font-size:13px"><strong>Авторизация:</strong> заголовок <code style="background:var(--bg);padding:2px 8px;border-radius:4px;color:var(--primary-light)">X-API-Key: ваш_ключ</code> или параметр <code style="background:var(--bg);padding:2px 8px;border-radius:4px;color:var(--primary-light)">?api_key=ваш_ключ</code></p>
<div style="display:flex;flex-direction:column;gap:16px">
<div class="info-block"><div class="info-label">GET /accounts — Список аккаунтов</div><p style="font-size:13px;color:var(--text-secondary);margin-top:4px">Параметры: <code>page</code>, <code>sort</code> (newest/oldest/price_asc/price_desc/chats), <code>country</code>, <code>origin</code>, <code>premium</code> (yes/no), <code>spamblock</code> (yes/no), <code>min_chats</code></p></div>
<div class="info-block"><div class="info-label">GET /accounts/{id} — Информация об аккаунте</div><p style="font-size:13px;color:var(--text-secondary);margin-top:4px">Возвращает полную информацию об аккаунте.</p></div>
<div class="info-block"><div class="info-label">POST /buy/{id} — Купить аккаунт</div><p style="font-size:13px;color:var(--text-secondary);margin-top:4px">Списывает средства с баланса. Возвращает данные покупки.</p></div>
<div class="info-block"><div class="info-label">GET /purchases — Список покупок</div><p style="font-size:13px;color:var(--text-secondary);margin-top:4px">Возвращает список ваших покупок.</p></div>
<div class="info-block"><div class="info-label">GET /purchases/{id}/code — Получить код</div><p style="font-size:13px;color:var(--text-secondary);margin-top:4px">Возвращает код авторизации из Telegram. Одноразово.</p></div>
<div class="info-block"><div class="info-label">GET /me — Профиль</div><p style="font-size:13px;color:var(--text-secondary);margin-top:4px">Возвращает баланс и статистику профиля.</p></div>
</div></div>'''

def render_layout(title, content, show_nav=True):
    nav = navbar() if show_nav else '<div class="navbar"><a href="/" class="logo">Vest Accs</a></div>'
    sheets = f'''
    <div class="bottom-sheet-backdrop" id="sheet-backdrop"></div>
    <div class="bottom-sheet" id="sheet_country"><div class="bottom-sheet-header"><h3>Выберите страны</h3><button class="bottom-sheet-close">&times;</button></div><div class="bottom-sheet-content"><input type="text" class="sheet-search-input" placeholder="Поиск страны..."><div class="sheet-grid multi-select">{"".join([f'<div class="sheet-item" data-type="country" data-value="{c}">{c}</div>' for c in COUNTRIES])}</div></div></div>
    <div class="bottom-sheet" id="sheet_origin"><div class="bottom-sheet-header"><h3>Происхождение</h3><button class="bottom-sheet-close">&times;</button></div><div class="bottom-sheet-content"><div class="sheet-grid multi-select">{"".join([f'<div class="sheet-item" data-type="origin" data-value="{o}">{o}</div>' for o in ORIGINS])}</div></div></div>
    <div class="bottom-sheet" id="sheet_premium"><div class="bottom-sheet-header"><h3>Telegram Premium</h3><button class="bottom-sheet-close">&times;</button></div><div class="bottom-sheet-content"><div class="sheet-grid"><div class="sheet-item" data-type="premium" data-value="">Не важно</div><div class="sheet-item" data-type="premium" data-value="yes">С Premium</div><div class="sheet-item" data-type="premium" data-value="no">Без Premium</div></div></div></div>
    <div class="bottom-sheet" id="sheet_spamblock"><div class="bottom-sheet-header"><h3>Спамблок</h3><button class="bottom-sheet-close">&times;</button></div><div class="bottom-sheet-content"><div class="sheet-grid"><div class="sheet-item" data-type="spamblock" data-value="">Не важно</div><div class="sheet-item" data-type="spamblock" data-value="yes">Со спамблоком</div><div class="sheet-item" data-type="spamblock" data-value="no">Чистые</div></div></div></div>
    '''
    return f'''<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no"><title>{title}</title>{STYLE}</head><body>{nav}<div class="main-content"><div class="container">{flash_msgs()}{content}</div></div>{sheets}{SCRIPT}</body></html>'''

def footer():
    return '''<div class="footer"><div class="footer-content"><div class="footer-brand">Vest Accs</div><div class="footer-links"><a href="/faq">FAQ</a><a href="/rules">Правила</a><a href="/api-docs">API</a><a href="https://t.me/VestAccsSupport" target="_blank">Поддержка</a></div></div><div class="footer-copyright">© 2026 Vest Accs. Все права защищены.</div></div>'''

def navbar():
    if g.user:
        admin = '<div class="divider"></div><a href="/admin" style="color:var(--primary-light);">Панель администратора</a>' if g.user.get("is_admin") else ''
        return f'''
        <div class="navbar"><a href="/" class="logo">Vest Accs</a><div style="display:flex;align-items:center;gap:10px"><span class="balance-badge">{g.user["balance"]:.0f} ₽</span><button class="theme-toggle" id="themeToggle" title="Сменить тему">☀</button><a href="/deposit" class="btn btn-primary btn-sm">Пополнить</a><button class="burger" id="burger"><span></span><span></span><span></span></button></div></div>
        <div class="overlay" id="overlay"></div><div class="sidebar" id="sidebar"><a href="/profile">Профиль</a><a href="/my_purchases">Мои покупки</a><a href="/deposit">Пополнение</a><a href="#" class="window-trigger-btn" data-window="win-withdraw">Вывод средств</a><a href="#" class="window-trigger-btn" data-window="win-sell">Продать аккаунт</a><a href="#" class="window-trigger-btn" data-window="win-api">API ключ</a><div class="divider"></div><a href="/faq">FAQ</a><a href="/rules">Правила</a><a href="/api-docs">API Документация</a>{admin}</div>'''
    return '<div class="navbar"><a href="/" class="logo">Vest Accs</a><div style="display:flex;gap:8px"><button class="theme-toggle" id="themeToggle" title="Сменить тему">☀</button><a href="/login" class="btn btn-ghost btn-sm">Вход</a><a href="/register" class="btn btn-primary btn-sm">Регистрация</a></div></div>'

def pagination(page, total, base_url='/'):
    if total <= 20: return ''
    pages = (total + 19) // 20
    return '<div class="pagination">' + ''.join([f'<span class="active">{p}</span>' if p == page else f'<a href="{base_url}?page={p}">{p}</a>' for p in range(1, pages + 1)]) + '</div>'

def quick_connect(session_string):
    ensure_loop()
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
                for msg in client.get_messages(dialog, limit=10):
                    if msg.message:
                        codes = re.findall(r'\b\d{5}\b', msg.message)
                        if codes: return codes[-1]
            except: continue
    finally:
        try: client.disconnect()
        except: pass
    return None

def send_verification_code(phone):
    ensure_loop()
    client = None
    try:
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        client.connect()
        result = client.send_code_request(phone)
        return result.phone_code_hash, client.session.save(), None
    except Exception as e:
        return None, None, str(e)
    finally:
        if client:
            try: client.disconnect()
            except: pass

def render_account_cards(accounts):
    cards = ''
    for a in accounts:
        rating_str, _ = get_seller_rating(a['seller_id'])
        rating_html = f'<span class="acc-rating">★ {rating_str}</span>' if rating_str else ''
        origin_class = "green" if a["origin"] in ["Авторег", "Саморег"] else ""
        spam_class = "green" if not a["spamblock"] else "red"
        prem_tag = '<span class="acc-tag purple">Premium</span>' if a["is_premium"] else ''
        cards += f'''
        <div class="account-card-compact">
            <div class="acc-top">
                <div class="acc-title-row">
                    <a href="/account/{a["id"]}" class="acc-title">{a["title"]}</a>
                    <span class="acc-seller">{a["seller_name"]}</span>
                    {rating_html}
                </div>
                <div class="acc-bottom">
                    <div class="acc-tags">
                        <span class="acc-tag">{a["country"] or "Интер"}</span>
                        <span class="acc-tag {origin_class}">{a["origin"] or "—"}</span>
                        <span class="acc-tag">{"2FA" if a["has_2fa"] else "Без 2FA"}</span>
                        <span class="acc-tag {spam_class}">{"Спамблок" if a["spamblock"] else "Чистый"}</span>
                        {prem_tag}
                    </div>
                </div>
            </div>
            <div class="acc-right">
                <span class="acc-price">{a["price"]:.0f} ₽</span>
                <a href="/account/{a["id"]}" class="btn btn-primary btn-sm">Купить</a>
            </div>
        </div>'''
    return cards or '<div class="empty-state"><h3>Нет доступных аккаунтов</h3><p style="color:var(--text-muted)">Станьте первым продавцом</p></div>'

@app.route('/')
def index():
    try:
        page = request.args.get('page', 1, type=int)
        sort = request.args.get('sort', 'newest')
        offset = (page - 1) * 20
        db = get_db()
        order_map = {'price_asc': 'a.price ASC', 'price_desc': 'a.price DESC', 'oldest': 'a.created_at ASC', 'chats': 'a.chats_count DESC'}
        order_by = order_map.get(sort, 'a.created_at DESC')
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM accounts WHERE is_sold = FALSE")
            total = cur.fetchone()['cnt']
            cur.execute(f"SELECT a.*, u.username as seller_name FROM accounts a JOIN users u ON a.seller_id = u.id WHERE a.is_sold = FALSE ORDER BY {order_by} LIMIT 20 OFFSET %s", (offset,))
            accounts = cur.fetchall()
        sort_buttons = ''.join([f'<a href="/?sort={s}" class="sort-btn {"active" if sort==s else ""}">{n}</a>' for s, n in [('newest','Новые'),('oldest','Старые'),('price_asc','Дешевле'),('price_desc','Дороже'),('chats','По чатам')]])
        content = f'''
        <div class="filter-bar"><button class="filter-btn">Фильтры и сортировка</button><div class="filter-drop" id="filterDrop"><div class="sort-buttons">{sort_buttons}</div><form action="/filter" method="GET">
        <input type="text" name="q" placeholder="Поиск по названию..."><div class="custom-select-trigger" data-sheet="sheet_country"><span>Выбрать страны...</span></div><input type="hidden" name="country" id="country_hidden">
        <div class="custom-select-trigger" data-sheet="sheet_origin"><span>Происхождение...</span></div><input type="hidden" name="origin" id="origin_hidden">
        <div class="custom-select-trigger" data-sheet="sheet_premium"><span>Premium: Не важно</span></div><input type="hidden" name="premium" id="premium_hidden">
        <div class="custom-select-trigger" data-sheet="sheet_spamblock"><span>Спамблок: Не важно</span></div><input type="hidden" name="spamblock" id="spamblock_hidden">
        <input type="number" name="min_chats" placeholder="Минимум чатов"><input type="hidden" name="sort" value="{sort}"><button type="submit" class="btn btn-primary" style="width:100%">Найти</button></form></div></div>
        <div class="accounts-list">{render_account_cards(accounts)}</div>{pagination(page, total, f"/?sort={sort}")}{footer()}'''
        return render_layout("Vest Accs", content)
    except Exception as e: return f'<h1>Ошибка: {e}</h1>', 500

@app.route('/faq')
def faq_page():
    content = FAQ_HTML + footer()
    return render_layout("FAQ", content)

@app.route('/rules')
def rules_page():
    content = RULES_HTML + footer()
    return render_layout("Правила", content)

@app.route('/api-docs')
def api_docs_page():
    content = API_DOCS_HTML + footer()
    return render_layout("API Документация", content)

@app.route('/regen_api_key')
@login_required
def regen_api_key():
    new_key = secrets.token_hex(16)
    db = get_db()
    with db.cursor() as cur:
        cur.execute("UPDATE users SET api_key = %s WHERE id = %s", (new_key, g.user['id']))
    return jsonify({'api_key': new_key})

@app.route('/get_code/<int:pid>')
@login_required
def get_code(pid):
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT a.session_string FROM purchases p JOIN accounts a ON p.account_id = a.id WHERE p.id = %s AND p.buyer_id = %s", (pid, g.user['id']))
            p = cur.fetchone()
        if not p: return jsonify({'error': 'Не найдено'})
        code = extract_code_from_session(p['session_string'])
        if code:
            return jsonify({'code': code})
        return jsonify({'error': 'Код не найден в диалогах'})
    except Exception as e: return jsonify({'error': str(e)})

@app.route('/check_valid/<int:account_id>')
def check_valid(account_id):
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT session_string FROM accounts WHERE id = %s", (account_id,))
            acc = cur.fetchone()
        if not acc: return jsonify({'valid': False})
        client = quick_connect(acc['session_string'])
        valid = client and client.is_user_authorized()
        try: client.disconnect()
        except: pass
        return jsonify({'valid': valid})
    except: return jsonify({'valid': False})

@app.route('/delete_account/<int:account_id>')
@login_required
def delete_account(account_id):
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT * FROM accounts WHERE id = %s AND seller_id = %s AND is_sold = FALSE", (account_id, g.user['id']))
            if not cur.fetchone(): flash('Не найдено', 'error'); return redirect(url_for('profile'))
            cur.execute("DELETE FROM accounts WHERE id = %s", (account_id,))
        db.commit()
        flash('Удалено', 'success')
    except Exception as e: flash(f'Ошибка: {e}', 'error')
    return redirect(url_for('profile'))

@app.route('/admin/withdrawals', methods=['POST'])
@login_required
def process_withdrawal():
    if not g.user.get('is_admin'): flash('Доступ запрещен', 'error'); return redirect(url_for('index'))
    wid, action = request.form.get('withdrawal_id', type=int), request.form.get('action')
    try:
        db = get_db()
        with db.cursor() as cur:
            if action == 'complete': cur.execute("UPDATE withdrawals SET status = 'completed' WHERE id = %s", (wid,)); flash('Выполнен', 'success')
            elif action == 'reject':
                cur.execute("SELECT * FROM withdrawals WHERE id = %s", (wid,)); w = cur.fetchone()
                if w: cur.execute("UPDATE users SET balance = balance + %s WHERE id = %s", (w[2], w[1])); cur.execute("INSERT INTO balance_history (user_id, amount, type, description) VALUES (%s,%s,%s,%s)", (w[1], w[2], 'refund', 'Возврат при отмене вывода')); cur.execute("UPDATE withdrawals SET status = 'rejected' WHERE id = %s", (wid,)); flash('Отклонен', 'success')
    except Exception as e: flash(f'Ошибка: {e}', 'error')
    return redirect(url_for('admin_panel'))

@app.route('/download_session/<int:pid>')
@login_required
def download_session(pid):
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT p.phone_number, a.session_string FROM purchases p JOIN accounts a ON p.account_id = a.id WHERE p.id = %s AND p.buyer_id = %s", (pid, g.user['id']))
            p = cur.fetchone()
        if not p: return "Файл не найден", 404
        ss = StringSession(p['session_string'])
        fd, temp_path = tempfile.mkstemp()
        try:
            conn = sqlite3.connect(temp_path)
            c = conn.cursor()
            c.execute('CREATE TABLE IF NOT EXISTS sessions (dc_id INTEGER PRIMARY KEY, server_address TEXT, port INTEGER, auth_key BLOB, takeout_id INTEGER)')
            auth_key_bytes = sqlite3.Binary(ss.auth_key) if ss.auth_key else b''
            c.execute('INSERT INTO sessions VALUES (?, ?, ?, ?, ?)', (ss.dc_id, ss.server_address, ss.port, auth_key_bytes, 0))
            conn.commit()
            conn.close()
            return send_file(temp_path, as_attachment=True, download_name=f"{p['phone_number'] or pid}.session", mimetype='application/octet-stream')
        finally:
            try: os.close(fd); os.remove(temp_path)
            except: pass
    except Exception as e: return f"Ошибка генерации: {e}", 500

@app.route('/download_json/<int:pid>')
@login_required
def download_json(pid):
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT p.phone_number, a.title, a.origin, a.country, a.session_string FROM purchases p JOIN accounts a ON p.account_id = a.id WHERE p.id = %s AND p.buyer_id = %s", (pid, g.user['id']))
            p = cur.fetchone()
        if not p: return "Файл не найден", 404
        ss = StringSession(p['session_string'])
        config = {"phone": p['phone_number'], "api_id": API_ID, "api_hash": API_HASH, "country": p['country'], "origin": p['origin'], "app_title": p['title'], "dc_id": ss.dc_id, "server_address": ss.server_address, "port": ss.port}
        bio = io.BytesIO(json.dumps(config, indent=4, ensure_ascii=False).encode('utf-8'))
        return send_file(bio, as_attachment=True, download_name=f"{p['phone_number'] or pid}.json", mimetype='application/json')
    except Exception as e: return f"Ошибка: {e}", 500

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        u, p = request.form.get('username', '').strip(), request.form.get('password', '').strip()
        if not u or not p: flash('Заполните все поля', 'error')
        else:
            try:
                db = get_db()
                with db.cursor() as cur: cur.execute("INSERT INTO users (username, password_hash, api_key) VALUES (%s, %s, %s)", (u, hash_password(p), secrets.token_hex(16)))
                db.commit(); flash('Регистрация успешна', 'success'); return redirect(url_for('login'))
            except psycopg2.IntegrityError: db.rollback(); flash('Пользователь существует', 'error')
    content = f'''<div class="auth-container"><div class="auth-card"><div class="auth-header"><h2>Регистрация</h2><p style="color:var(--text-muted);font-size:13px">Создайте аккаунт для покупки и продажи</p></div><form method="POST"><label style="display:block;margin-bottom:6px;color:var(--text-secondary);font-size:13px;font-weight:600">Логин</label><input type="text" name="username" required placeholder="Придумайте логин"><label style="display:block;margin-bottom:6px;color:var(--text-secondary);font-size:13px;font-weight:600">Пароль</label><input type="password" name="password" required placeholder="Придумайте пароль"><button type="submit" class="btn btn-primary" style="width:100%;padding:13px;font-size:14px">Создать аккаунт</button></form><p style="text-align:center;margin-top:16px;color:var(--text-muted);font-size:13px">Уже есть аккаунт? <a href="/login" style="color:var(--primary-light);font-weight:600">Войти</a></p></div></div>{footer()}'''
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
                if user and verify_password(p, user['password_hash']):
                    session['user_id'] = user['id']; session.permanent = True
                    if not user['api_key']:
                        with db.cursor() as cu: cu.execute("UPDATE users SET api_key = %s WHERE id = %s", (secrets.token_hex(16), user['id']))
                    return redirect(url_for('index'))
            flash('Неверный логин или пароль', 'error')
        except Exception as e: flash(f'Ошибка: {e}', 'error')
    content = f'''<div class="auth-container"><div class="auth-card"><div class="auth-header"><h2>Вход</h2><p style="color:var(--text-muted);font-size:13px">Добро пожаловать обратно</p></div><form method="POST"><label style="display:block;margin-bottom:6px;color:var(--text-secondary);font-size:13px;font-weight:600">Логин</label><input type="text" name="username" required placeholder="Введите логин"><label style="display:block;margin-bottom:6px;color:var(--text-secondary);font-size:13px;font-weight:600">Пароль</label><input type="password" name="password" required placeholder="Введите пароль"><button type="submit" class="btn btn-primary" style="width:100%;padding:13px;font-size:14px">Войти</button></form><p style="text-align:center;margin-top:16px;color:var(--text-muted);font-size:13px">Нет аккаунта? <a href="/register" style="color:var(--primary-light);font-weight:600">Создать</a></p></div></div>{footer()}'''
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
                data = {"asset": "USDT", "amount": str(round(amount / 90, 2)), "description": "Пополнение Vest Accs", "allow_comments": False, "allow_anonymous": False}
                r = requests.post("https://pay.crypt.bot/api/createInvoice", json=data, headers=headers, timeout=10)
                resp = r.json()
                if resp.get('ok'):
                    db = get_db()
                    with db.cursor() as cur: cur.execute("INSERT INTO crypto_invoices (user_id, invoice_id, amount_rub, pay_url) VALUES (%s,%s,%s,%s)", (g.user['id'], str(resp['result']['invoice_id']), amount, resp['result']['pay_url']))
                    return redirect(url_for('invoice_page', invoice_id=resp['result']['invoice_id']))
                flash('Ошибка создания счета', 'error')
            except Exception as e: flash(f'Ошибка: {e}', 'error')
    content = f'''<div class="form-box"><h2 style="margin-bottom:6px">Пополнение баланса</h2><p style="color:var(--text-muted);margin-bottom:20px;font-size:13px">Текущий баланс: <strong style="color:var(--success)">{g.user["balance"]:.2f} ₽</strong></p><form method="POST"><label style="display:block;margin-bottom:6px;color:var(--text-secondary);font-size:13px;font-weight:600">Сумма пополнения (от 20 ₽)</label><input type="number" name="amount" step="0.01" min="20" required placeholder="Например: 500"><button type="submit" class="btn btn-success" style="width:100%;padding:13px">Пополнить через Crypto Bot</button></form></div>{footer()}'''
    return render_layout("Пополнение", content)

@app.route('/invoice/<invoice_id>')
@login_required
def invoice_page(invoice_id):
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT * FROM crypto_invoices WHERE invoice_id = %s AND user_id = %s", (str(invoice_id), g.user['id']))
            inv = cur.fetchone()
        if not inv: flash('Счет не найден', 'error'); return redirect(url_for('index'))
        status_map = {'pending': ('Ожидает оплаты', '#f59e0b'), 'paid': ('Оплачен', '#34d399')}
        stext, scolor = status_map.get(inv['status'], ('Отменен', '#ef4444'))
        content = f'''<div class="form-box" style="max-width:480px"><h2>Счет #{inv['invoice_id']}</h2><p style="color:var(--text-muted);font-size:13px;margin-bottom:16px">Пополнение баланса</p><div style="background:rgba(255,255,255,0.02);border:1px solid var(--border);border-radius:var(--radius);padding:16px;margin-bottom:16px"><div style="display:flex;justify-content:space-between;margin-bottom:10px"><span style="color:var(--text-muted)">Сумма</span><strong>{inv['amount_rub']:.2f} ₽</strong></div><div style="display:flex;justify-content:space-between;margin-bottom:10px"><span style="color:var(--text-muted)">Статус</span><strong style="color:{scolor}">{stext}</strong></div><div style="display:flex;justify-content:space-between"><span style="color:var(--text-muted)">Дата</span><span style="color:var(--text-secondary);font-size:13px">{inv['created_at'].strftime('%d.%m.%Y %H:%M')}</span></div></div>'''
        if inv['status'] == 'pending':
            content += f'''<div style="display:flex;flex-direction:column;gap:10px"><a href="{inv['pay_url']}" target="_blank" class="btn btn-primary" style="width:100%">Перейти к оплате</a><a href="/check_invoice/{inv['invoice_id']}" class="btn btn-secondary" style="width:100%">Проверить оплату</a></div>'''
        else: content += f'<a href="/" class="btn btn-secondary" style="width:100%">На главную</a>'
        content += f'</div>{footer()}'
        return render_layout(f"Счет #{inv['invoice_id']}", content)
    except Exception as e: return f'<h1>Ошибка: {e}</h1>', 500

@app.route('/check_invoice/<invoice_id>')
@login_required
def check_invoice(invoice_id):
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT * FROM crypto_invoices WHERE invoice_id = %s AND user_id = %s", (str(invoice_id), g.user['id']))
            inv = cur.fetchone()
        if not inv: flash('Счет не найден', 'error'); return redirect(url_for('index'))
        if inv['status'] == 'paid': flash('Счет уже оплачен', 'success'); return redirect(url_for('invoice_page', invoice_id=invoice_id))
        r = requests.get("https://pay.crypt.bot/api/getInvoices", params={"invoice_ids": str(invoice_id)}, headers={"Crypto-Pay-API-Token": CRYPTO_TOKEN}, timeout=10)
        resp = r.json()
        if resp.get('ok') and resp.get('result', {}).get('items'):
            if resp['result']['items'][0].get('status') == 'paid':
                with db.cursor() as cur:
                    cur.execute("SELECT status FROM crypto_invoices WHERE invoice_id = %s FOR UPDATE", (str(invoice_id),))
                    if cur.fetchone()[0] == 'pending':
                        cur.execute("UPDATE users SET balance = balance + %s WHERE id = %s", (inv['amount_rub'], inv['user_id']))
                        cur.execute("INSERT INTO balance_history (user_id, amount, type, description) VALUES (%s,%s,%s,%s)", (inv['user_id'], inv['amount_rub'], 'deposit', 'Пополнение'))
                        cur.execute("UPDATE crypto_invoices SET status = 'paid' WHERE invoice_id = %s", (str(invoice_id),))
                flash('Оплата подтверждена!', 'success')
            else: flash('Оплата еще не поступила', 'info')
        return redirect(url_for('invoice_page', invoice_id=invoice_id))
    except Exception as e: flash(f'Ошибка: {e}', 'error'); return redirect(url_for('invoice_page', invoice_id=invoice_id))

@app.route('/filter', methods=['GET'])
def filter_accounts():
    try:
        page = request.args.get('page', 1, type=int); offset = (page - 1) * 20
        q = request.args.get('q', '').strip(); countries = request.args.get('country', '').strip()
        origins = request.args.get('origin', '').strip(); premium = request.args.get('premium', '').strip()
        sb = request.args.get('spamblock', '').strip(); mc = request.args.get('min_chats', type=int)
        sort = request.args.get('sort', 'newest')
        order_map = {'price_asc': 'a.price ASC', 'price_desc': 'a.price DESC', 'oldest': 'a.created_at ASC', 'chats': 'a.chats_count DESC'}
        order_by = order_map.get(sort, 'a.created_at DESC')
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
            cur.execute(f"SELECT a.*, u.username as seller_name FROM accounts a JOIN users u ON a.seller_id = u.id WHERE {where} ORDER BY {order_by} LIMIT 20 OFFSET %s", params + [offset])
            accounts = cur.fetchall()
        cards = render_account_cards(accounts) or '<div class="empty-state"><h3>Ничего не найдено</h3></div>'
        qs = "&".join([f"{k}={v}" for k,v in request.args.items() if k != "page"])
        content = f'<h1 class="page-title">Результаты</h1><p class="page-sub">Найдено: {total}</p><div class="accounts-list">{cards}</div>{pagination(page, total, "/filter?" + qs)}{footer()}'
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
        buy_btn = f'<form action="/buy/{a["id"]}" method="POST"><button type="submit" class="btn btn-primary" style="width:100%">Купить за {a["price"]:.0f} ₽</button></form>' if g.user and g.user['id'] != a['seller_id'] and not a['is_sold'] else ''
        check_btn = f'<button class="btn btn-secondary btn-check-valid" data-id="{a["id"]}" style="width:100%">Проверить на валид</button>' if not a['is_sold'] else ''
        rating_str, _ = get_seller_rating(a['seller_id'])
        rating_html = f'<span class="rating-badge">★ {rating_str}</span>' if rating_str else ''
        content = f'''<div style="max-width:600px;margin:0 auto"><div class="card" style="padding:24px"><div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:12px;margin-bottom:20px"><div><h2 style="font-size:22px;font-weight:800">{a["title"]}</h2><p style="color:var(--text-muted);font-size:13px;margin-top:4px">Продавец: <strong style="color:var(--primary-light)">{a["seller_name"]}</strong> {rating_html}</p></div><div style="background:rgba(16,185,129,0.06);border:1px solid rgba(16,185,129,0.15);padding:10px 20px;border-radius:var(--radius);text-align:center"><div style="font-size:20px;font-weight:900;color:var(--success)">{a["price"]:.2f} ₽</div></div></div><div style="display:flex;flex-direction:column;gap:8px;margin-bottom:16px">{check_btn}{buy_btn}</div><div style="display:flex;flex-direction:column;margin-bottom:14px"><div class="spec-row"><span class="spec-lbl">Страна</span><span class="spec-val" style="color:var(--primary-light)">{a["country"] or "-"}</span></div><div class="spec-row"><span class="spec-lbl">Происхождение</span><span class="spec-val" style="color:var(--success)">{a["origin"] or "-"}</span></div><div class="spec-row"><span class="spec-lbl">2FA</span><span class="spec-val">{"Да" if a["has_2fa"] else "Нет"}</span></div><div class="spec-row"><span class="spec-lbl">Спамблок</span><span class="spec-val">{"Есть" if a["spamblock"] else "Чистый"}</span></div><div class="spec-row"><span class="spec-lbl">Premium</span><span class="spec-val">{"Да" if a["is_premium"] else "Нет"}</span></div><div class="spec-row"><span class="spec-lbl">Диалогов</span><span class="spec-val">{a["chats_count"]}</span></div><div class="spec-row"><span class="spec-lbl">Каналов</span><span class="spec-val">{a["channels_count"]}</span></div></div><div style="background:rgba(255,255,255,0.01);border:1px solid var(--border);border-radius:var(--radius);padding:14px"><p style="font-size:13px;color:var(--text-secondary)">{a["description"] or "Описание отсутствует."}</p></div></div></div>{footer()}'''
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
            price = Decimal(str(acc['price']))
            if Decimal(str(g.user['balance'])) < price: flash('Недостаточно средств', 'error'); return redirect(url_for('deposit'))
            seller_earn = price * (Decimal('1') - COMMISSION)
            cur.execute("UPDATE users SET balance = balance - %s WHERE id = %s", (price, g.user['id']))
            cur.execute("INSERT INTO balance_history (user_id, amount, type, description) VALUES (%s,%s,%s,%s)", (g.user['id'], -price, 'purchase', f'Покупка #{account_id}'))
            cur.execute("UPDATE users SET balance = balance + %s, sales_count = sales_count + 1 WHERE id = %s", (seller_earn, acc['seller_id']))
            cur.execute("INSERT INTO balance_history (user_id, amount, type, description) VALUES (%s,%s,%s,%s)", (acc['seller_id'], seller_earn, 'sale', f'Продажа #{account_id}'))
            cur.execute("UPDATE accounts SET is_sold = TRUE WHERE id = %s", (account_id,))
            cur.execute("INSERT INTO purchases (buyer_id, account_id, phone_number) VALUES (%s,%s,%s) RETURNING id", (g.user['id'], account_id, 'Загрузка...'))
            pid = cur.fetchone()['id']
        db.commit()
        phone = extract_phone_from_session(acc['session_string'])
        if phone:
            with db.cursor() as cur: cur.execute("UPDATE purchases SET phone_number = %s WHERE id = %s", (phone, pid))
        db.commit()
        flash('Покупка успешна!', 'success')
        return redirect(url_for('my_purchases'))
    except Exception as e: flash(f'Ошибка: {e}', 'error'); return redirect(url_for('index'))

@app.route('/my_purchases')
@login_required
def my_purchases():
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT p.*, a.title, a.session_string, a.seller_id FROM purchases p JOIN accounts a ON p.account_id = a.id WHERE p.buyer_id = %s ORDER BY p.id DESC", (g.user['id'],))
            purchases = cur.fetchall()
        items = ''
        for p in purchases:
            ss = StringSession(p['session_string'])
            dc_id = str(ss.dc_id) if ss.dc_id else '—'
            auth_key_str = str(ss.auth_key) if ss.auth_key else '—'
            auth_key_short = (auth_key_str[:25] + '...') if len(auth_key_str) > 25 else auth_key_str
            cb = f'<button class="btn btn-primary btn-get-code" data-id="{p["id"]}" style="width:100%">Получить код</button>' if not p['code_retrieved'] else '<div class="code-box" style="margin-top:0">Код уже получен</div>'
            review_btn = f'<button class="btn btn-secondary window-trigger-btn" data-window="win-review-{p["id"]}" style="width:100%;margin-top:8px">Оставить отзыв</button>' if p['seller_id'] != g.user['id'] else ''
            items += f'''
            <div class="purchase-card"><div class="purchase-title">{p["title"]}</div><div class="purchase-date">{p["purchase_date"].strftime("%d.%m.%Y %H:%M") if p["purchase_date"] else ""}</div>
            <div class="purchase-preview"><span class="preview-tag">📱 {p["phone_number"]}</span><span class="preview-tag">DC {dc_id}</span><span style="font-size:11px;color:var(--text-muted)">Нажмите для деталей</span></div>
            <div class="purchase-detail"><div class="purchase-info">
            <div class="info-block"><div class="info-label">Номер телефона</div><div class="info-value">{p["phone_number"]}</div><button class="btn-copy" data-copy="{p["phone_number"]}" style="margin-top:8px">Копировать</button></div>
            <div class="info-block"><div class="info-label">DC ID</div><div class="info-value">{dc_id}</div><button class="btn-copy" data-copy="{dc_id}" style="margin-top:8px">Копировать</button></div>
            <div class="info-block"><div class="info-label">AUTH KEY</div><div class="info-value mono">{auth_key_short}</div><button class="btn-copy" data-copy="{auth_key_str}" style="margin-top:8px">Копировать</button></div></div>
            <div class="code-section"><div class="info-label" style="margin-bottom:4px">Войти по коду в Telegram</div>{cb}<div id="code-{p["id"]}"></div></div>
            <div class="download-section"><div class="info-label" style="text-align:center;margin-bottom:10px">Скачать сессию</div><div class="download-grid"><a href="/download_session/{p["id"]}" class="btn btn-secondary btn-sm" style="width:100%">Telethon .session</a><a href="/download_json/{p["id"]}" class="btn btn-secondary btn-sm" style="width:100%">JSON конфиг</a></div></div>
            {review_btn}<p style="text-align:center;margin-top:12px;font-size:12px;color:var(--text-muted)">Проблемы? <a href="https://t.me/VestAccsSupport" class="support-link" target="_blank">Напишите в поддержку</a></p></div></div>
            <div class="modal" id="win-review-{p["id"]}"><div class="modal-content"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px"><h3>Оставить отзыв</h3><button class="window-close" style="background:transparent;border:none;color:var(--text-muted);font-size:22px;cursor:pointer">&times;</button></div><form method="POST" action="/review/{p["id"]}"><p style="text-align:center;color:var(--text-muted);margin-bottom:8px">Оцените продавца</p><div class="stars" id="review-stars-{p["id"]}"><span class="star" data-rating="1">★</span><span class="star" data-rating="2">★</span><span class="star" data-rating="3">★</span><span class="star" data-rating="4">★</span><span class="star active" data-rating="5">★</span></div><input type="hidden" name="rating" value="5" id="review-rating-{p["id"]}"><textarea name="text" rows="3" placeholder="Ваш отзыв (необязательно)"></textarea><button type="submit" class="btn btn-primary" style="width:100%">Отправить отзыв</button></form></div></div>'''
        if not items: items = '<div class="empty-state"><h3>Нет покупок</h3><a href="/" class="btn btn-primary btn-sm" style="margin-top:8px">К покупкам</a></div>'
        content = f'<h2 style="font-size:22px;font-weight:800;margin-bottom:18px">Мои покупки</h2>{items}{footer()}'
        return render_layout("Мои покупки", content)
    except Exception as e: return f'<h1>Ошибка: {e}</h1>', 500

@app.route('/review/<int:purchase_id>', methods=['POST'])
@login_required
def leave_review(purchase_id):
    try:
        rating = request.form.get('rating', 5, type=int)
        text = request.form.get('text', '').strip()
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT p.*, a.seller_id, a.id as account_id FROM purchases p JOIN accounts a ON p.account_id = a.id WHERE p.id = %s AND p.buyer_id = %s", (purchase_id, g.user['id']))
            p = cur.fetchone()
        if not p: flash('Покупка не найдена', 'error'); return redirect(url_for('my_purchases'))
        with db.cursor() as cur:
            cur.execute("SELECT id FROM reviews WHERE buyer_id = %s AND account_id = %s", (g.user['id'], p['account_id']))
            if cur.fetchone(): flash('Вы уже оставили отзыв', 'error'); return redirect(url_for('my_purchases'))
            cur.execute("INSERT INTO reviews (buyer_id, seller_id, account_id, rating, text) VALUES (%s,%s,%s,%s,%s)", (g.user['id'], p['seller_id'], p['account_id'], rating, text))
        db.commit()
        flash('Отзыв отправлен!', 'success')
    except Exception as e: flash(f'Ошибка: {e}', 'error')
    return redirect(url_for('my_purchases'))

@app.route('/profile', methods=['GET'])
@login_required
def profile():
    if session.get('verify_phone') or session.get('2fa_needed'): return redirect(url_for('verify_code_page'))
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT * FROM balance_history WHERE user_id = %s ORDER BY created_at DESC LIMIT 20", (g.user['id'],))
        history = cur.fetchall()
        cur.execute("SELECT * FROM accounts WHERE seller_id = %s ORDER BY id DESC", (g.user['id'],))
        my_accs = cur.fetchall()
        cur.execute("SELECT COUNT(*) as cnt FROM purchases p JOIN accounts a ON p.account_id = a.id WHERE a.seller_id = %s", (g.user['id'],))
        sales_count = cur.fetchone()['cnt']
        cur.execute("SELECT COALESCE(SUM(amount),0) as total FROM balance_history WHERE user_id = %s AND type = 'sale'", (g.user['id'],))
        total_earned = cur.fetchone()['total']
        cur.execute("SELECT id, username, balance FROM users ORDER BY id")
        all_users = cur.fetchall()

    hist_html = ''.join([f'<tr><td>{h["created_at"].strftime("%d.%m %H:%M")}</td><td style="color:{"var(--success)" if h["amount"]>0 else "var(--danger)"}">{"+" if h["amount"]>0 else ""}{h["amount"]:.2f} ₽</td><td>{h["description"]}</td></tr>' for h in history]) or '<tr><td colspan="3" style="text-align:center;color:var(--text-muted);padding:20px">Нет операций</td></tr>'
    accs_html = ''.join([f'''<div style="background:rgba(255,255,255,0.01);border:1px solid var(--border);border-radius:var(--radius);padding:14px;margin-bottom:8px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px"><div><span style="color:var(--text-muted);font-size:11px">#{a["id"]}</span> <strong>{a["title"]}</strong></div><div style="display:flex;align-items:center;gap:12px"><span style="font-weight:800;color:var(--price)">{a["price"]:.0f} ₽</span><span style="font-size:11px;color:{"var(--success)" if not a["is_sold"] else "var(--danger)"}">{"Активен" if not a["is_sold"] else "Продан"}</span>{f'<button class="btn btn-danger btn-sm btn-delete-acc" data-id="{a["id"]}">Удалить</button>' if not a['is_sold'] else ''}</div></div>''' for a in my_accs]) or '<div style="text-align:center;color:var(--text-muted);padding:20px">Нет товаров</div>'
    rating_str, total_reviews = get_seller_rating(g.user['id'])
    user_opts = ''.join([f'<option value="{u["id"]}">{u["username"]} ({u["balance"]:.2f} ₽)</option>' for u in all_users])
    api_key = g.user.get('api_key') or secrets.token_hex(16)

    content = f'''
    <div class="profile-container">
        <div class="profile-header"><h2>{g.user["username"]}</h2><div class="role">{"Администратор" if g.user["is_admin"] else "Пользователь"} {f'<span class="rating-badge">★ {rating_str}</span>' if rating_str else ''}</div><div class="balance">{g.user["balance"]:.2f} ₽</div>
        <div class="profile-stats"><div class="stat"><div class="stat-value">{len(my_accs)}</div><div class="stat-label">Товаров</div></div><div class="stat"><div class="stat-value">{sales_count}</div><div class="stat-label">Продаж</div></div><div class="stat window-trigger-btn" data-window="win-stats"><div class="stat-value">→</div><div class="stat-label">Статистика</div></div></div></div>
        <div class="section-card"><div class="section-header"><h3>Мои объявления</h3></div>{accs_html}</div>
        <div class="section-card"><div class="section-header"><h3>История транзакций</h3></div><div style="overflow-x:auto"><table><thead><tr><th>Дата</th><th>Сумма</th><th>Описание</th></tr></thead><tbody>{hist_html}</tbody></table></div></div>
        {f'<div class="section-card"><div class="section-header"><h3>Администрирование</h3></div><div class="tab-nav"><button class="tab-btn active" data-tab="admin-balance">Баланс</button><button class="tab-btn" data-tab="admin-withdrawals">Выводы</button></div><div id="admin-balance" class="tab-content active"><form method="POST" action="/admin"><select name="user_id" style="background:#000;color:#fff;padding:12px;border:1px solid var(--border);width:100%;border-radius:var(--radius);margin-bottom:12px" required><option value="">Выберите пользователя</option>{user_opts}</select><input type="number" name="amount" step="0.01" required placeholder="Сумма"><div style="display:flex;gap:8px"><button type="submit" name="balance_action" value="add" class="btn btn-success" style="flex:1">Добавить</button><button type="submit" name="balance_action" value="set" class="btn" style="flex:1;background:var(--warning);color:#000;font-weight:700">Установить</button></div></form></div><div id="admin-withdrawals" class="tab-content">{get_withdrawals_html(db)}</div></div>' if g.user["is_admin"] else ''}
    </div>
    <div class="modal" id="win-stats"><div class="modal-content"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px"><h3>Детальная статистика</h3><button class="window-close" style="background:transparent;border:none;color:var(--text-muted);font-size:22px;cursor:pointer">&times;</button></div><div style="display:flex;flex-direction:column;gap:12px"><div class="spec-row"><span class="spec-lbl">Всего продаж</span><span class="spec-val">{sales_count}</span></div><div class="spec-row"><span class="spec-lbl">Заработано</span><span class="spec-val" style="color:var(--success)">{total_earned:.2f} ₽</span></div><div class="spec-row"><span class="spec-lbl">Рейтинг</span><span class="spec-val">★ {rating_str or "—"} ({total_reviews} отзывов)</span></div><div class="spec-row"><span class="spec-lbl">Активных товаров</span><span class="spec-val">{len([a for a in my_accs if not a["is_sold"]])}</span></div><div class="spec-row"><span class="spec-lbl">Баланс</span><span class="spec-val" style="color:var(--primary-light)">{g.user["balance"]:.2f} ₽</span></div></div></div></div>
    <div class="modal" id="win-sell"><div class="modal-content"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px"><h3>Продать аккаунт</h3><button class="window-close" style="background:transparent;border:none;color:var(--text-muted);font-size:22px;cursor:pointer">&times;</button></div><form method="POST"><input type="hidden" name="action" value="verify_phone"><label style="display:block;margin-bottom:6px;color:var(--text-muted);font-size:13px;font-weight:600">Номер телефона аккаунта</label><input type="text" name="phone" placeholder="+79001234567" required><button type="submit" class="btn btn-primary" style="width:100%">Запросить код в Telegram</button></form></div></div>
    <div class="modal" id="win-withdraw"><div class="modal-content"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px"><h3>Вывод средств</h3><button class="window-close" style="background:transparent;border:none;color:var(--text-muted);font-size:22px;cursor:pointer">&times;</button></div><form method="POST" action="/withdraw"><label style="display:block;margin-bottom:6px;color:var(--text-muted);font-size:13px;font-weight:600">Сумма (минимум 50 ₽)</label><input type="number" name="amount_rub" step="0.01" min="50" required placeholder="Например: 500"><label style="display:block;margin-bottom:6px;color:var(--text-muted);font-size:13px;font-weight:600">Адрес TON кошелька</label><input type="text" name="address" placeholder="EQD..." required><button type="submit" class="btn btn-primary" style="width:100%">Заказать вывод</button></form></div></div>
    <div class="modal" id="win-api"><div class="modal-content"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px"><h3>API ключ</h3><button class="window-close" style="background:transparent;border:none;color:var(--text-muted);font-size:22px;cursor:pointer">&times;</button></div><p style="color:var(--text-muted);font-size:13px;margin-bottom:8px">Ваш персональный API ключ для программного доступа:</p><div class="api-key-display" id="apiKeyDisplay">{api_key}</div><button class="btn-copy" data-copy="{api_key}" style="width:100%;margin-bottom:8px">Копировать ключ</button><button class="btn btn-secondary" id="regenApiKey" style="width:100%;margin-bottom:12px">Сгенерировать новый ключ</button><a href="/api-docs" class="btn btn-primary btn-sm" style="width:100%">Документация API</a></div></div>
    {footer()}'''
    return render_layout("Профиль", content)

def get_withdrawals_html(db):
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT w.*, u.username FROM withdrawals w JOIN users u ON w.user_id = u.id ORDER BY w.created_at DESC LIMIT 50")
        withdrawals = cur.fetchall()
    if not withdrawals: return '<div style="text-align:center;color:var(--text-muted);padding:20px">Нет заявок</div>'
    html = '<div style="overflow-x:auto"><table><thead><tr><th>ID</th><th>Пользователь</th><th>RUB</th><th>USDT</th><th>Статус</th><th>Действия</th></tr></thead><tbody>'
    for w in withdrawals:
        stext = 'Выполнен' if w['status']=='completed' else 'Отклонен' if w['status']=='rejected' else 'Ожидает'
        scolor = 'var(--success)' if w['status']=='completed' else 'var(--danger)' if w['status']=='rejected' else 'var(--warning)'
        actions = f'<form method="POST" action="/admin/withdrawals" style="display:inline"><input type="hidden" name="withdrawal_id" value="{w["id"]}"><button type="submit" name="action" value="complete" class="btn btn-success btn-sm">Выполнить</button> <button type="submit" name="action" value="reject" class="btn btn-danger btn-sm">Отклонить</button></form>' if w['status']=='pending' else ''
        html += f'<tr><td>#{w["id"]}</td><td>{w["username"]}</td><td>{w["amount_rub"]:.2f} ₽</td><td>{w["amount_usdt"]:.6f}</td><td style="color:{scolor}">{stext}</td><td>{actions}</td></tr>'
    return html + '</tbody></table></div>'

@app.route('/profile', methods=['POST'])
@login_required
def profile_post():
    action = request.form.get('action')
    if action == 'verify_phone':
        phone = request.form.get('phone', '').strip()
        if not phone.startswith('+'): phone = '+' + phone
        result, temp_ss, error_msg = send_verification_code(phone)
        if result:
            session['verify_phone'] = phone; session['code_hash'] = result; session['client_temp'] = temp_ss
            flash('Код отправлен', 'success'); return redirect(url_for('verify_code_page'))
        else: flash(f'Ошибка отправки: {error_msg}', 'error')
    return redirect(url_for('profile'))

@app.route('/profile/verify', methods=['GET', 'POST'])
@login_required
def verify_code_page():
    ensure_loop()
    phone = session.get('verify_phone', '')
    if not phone and not session.get('2fa_needed'): return redirect(url_for('profile'))
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'confirm_code':
            code = request.form.get('code', '').strip()
            try:
                client = TelegramClient(StringSession(session.get('client_temp','')), API_ID, API_HASH)
                client.connect()
                try:
                    client.sign_in(phone=phone, code=code, phone_code_hash=session.get('code_hash',''))
                    session['phone_verified'] = True; session['session_string'] = client.session.save(); session['has_2fa'] = False
                    session.pop('2fa_needed', None); flash('Номер подтвержден', 'success'); return redirect(url_for('sell_account'))
                except SessionPasswordNeededError:
                    session['2fa_needed'] = True; session['has_2fa'] = True; session['client_temp'] = client.session.save()
                    flash('Требуется пароль 2FA', 'info')
                except PhoneCodeInvalidError: flash('Неверный код', 'error')
                finally:
                    if not session.get('2fa_needed'):
                        try: client.disconnect()
                        except: pass
            except Exception as e: flash(f'Ошибка: {e}', 'error')
        elif action == 'confirm_2fa':
            pw = request.form.get('password_2fa', '')
            try:
                client = TelegramClient(StringSession(session.get('client_temp','')), API_ID, API_HASH)
                client.connect()
                try:
                    client.sign_in(password=pw)
                    session['phone_verified'] = True; session['session_string'] = client.session.save()
                    session.pop('2fa_needed', None); session.pop('client_temp', None)
                    flash('Авторизация пройдена', 'success'); return redirect(url_for('sell_account'))
                except Exception as e: flash(f'Неверный пароль 2FA: {e}', 'error')
                finally:
                    try: client.disconnect()
                    except: pass
            except Exception as e: flash(f'Ошибка: {e}', 'error')
        elif action == 'cancel':
            for k in ['phone_verified','session_string','verify_phone','code_hash','client_temp','2fa_needed','has_2fa']: session.pop(k, None)
            flash('Отменено', 'info'); return redirect(url_for('profile'))

    form_body = '''<h2>Защита 2FA</h2><p style="color:var(--warning);margin-bottom:16px">Затребован облачный пароль</p><form method="POST"><input type="hidden" name="action" value="confirm_2fa"><label style="display:block;margin-bottom:6px;color:var(--text-muted);font-size:13px;font-weight:600">Пароль 2FA</label><input type="password" name="password_2fa" required><button type="submit" class="btn" style="width:100%;background:var(--warning);color:#000;margin-bottom:8px">Подтвердить</button><button type="submit" name="action" value="cancel" class="btn btn-secondary" style="width:100%">Отмена</button></form>''' if session.get('2fa_needed') else f'''<h2>Проверка кода</h2><p style="color:var(--text-muted);margin-bottom:16px">Код отправлен на {phone}</p><form method="POST"><input type="hidden" name="action" value="confirm_code"><label style="display:block;margin-bottom:6px;color:var(--text-muted);font-size:13px;font-weight:600">Код из Telegram</label><input type="text" name="code" required placeholder="5-значный код"><button type="submit" class="btn btn-success" style="width:100%;margin-bottom:8px">Подтвердить</button><button type="submit" name="action" value="cancel" class="btn btn-secondary" style="width:100%">Отмена</button></form>'''
    content = f'<div class="form-box">{form_body}</div>{footer()}'
    return render_layout("Подтверждение", content)

@app.route('/sell', methods=['GET', 'POST'])
@login_required
def sell_account():
    if not session.get('phone_verified'): flash('Сначала подтвердите номер', 'error'); return redirect(url_for('profile'))
    if request.method == 'POST':
        title = request.form.get('title', '').strip(); origin = request.form.get('origin', '').strip()
        desc = request.form.get('description', '').strip(); price = request.form.get('price', type=float)
        if not title or not price: flash('Название и цена обязательны', 'error')
        else:
            try:
                ss = session.get('session_string')
                geo_country = detect_country_by_phone(extract_phone_from_session(ss))
                has_2fa = session.get('has_2fa', False)
                ad = gather_account_data(ss)
                db = get_db()
                with db.cursor() as cur:
                    cur.execute("INSERT INTO accounts (seller_id,title,origin,description,price,session_string,country,has_2fa,spamblock,is_premium,chats_count,channels_count,groups_count) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (g.user['id'],title,origin,desc,Decimal(str(price)),ss,geo_country,has_2fa,ad.get('spamblock',False),ad.get('is_premium',False),ad.get('chats_count',0),ad.get('channels_count',0),ad.get('groups_count',0)))
                db.commit()
                for k in ['phone_verified','session_string','verify_phone','code_hash','client_temp','2fa_needed','has_2fa']: session.pop(k, None)
                flash('Аккаунт выставлен на продажу', 'success'); return redirect(url_for('index'))
            except Exception as e: flash(f'Ошибка: {e}', 'error')
    content = f'''<div class="form-box"><h2 style="margin-bottom:6px">Выставить аккаунт</h2><p style="color:var(--text-muted);margin-bottom:20px;font-size:13px">Заполните данные объявления</p><form method="POST"><label style="display:block;margin-bottom:6px;color:var(--text-muted);font-size:13px;font-weight:600">Название *</label><input type="text" name="title" required><label style="display:block;margin-bottom:6px;color:var(--text-muted);font-size:13px;font-weight:600">Происхождение</label><select name="origin"><option value="">Выберите...</option>{"".join([f'<option value="{o}">{o}</option>' for o in ORIGINS])}</select><label style="display:block;margin-bottom:6px;color:var(--text-muted);font-size:13px;font-weight:600">Описание</label><textarea name="description" rows="3"></textarea><label style="display:block;margin-bottom:6px;color:var(--text-muted);font-size:13px;font-weight:600">Цена (₽) *</label><input type="number" name="price" step="0.01" required><p style="color:var(--text-muted);font-size:11px;margin-bottom:14px;text-align:center">2FA, Premium и статистика определятся автоматически</p><button type="submit" class="btn btn-primary" style="width:100%">Выставить на маркет</button></form></div>{footer()}'''
    return render_layout("Продажа", content)

@app.route('/withdraw', methods=['POST'])
@login_required
def withdraw():
    amount_rub = request.form.get('amount_rub', 0, type=float); address = request.form.get('address', '').strip()
    if amount_rub < 50: flash('Минимум 50 ₽', 'error'); return redirect(url_for('profile'))
    if g.user['balance'] < amount_rub: flash('Недостаточно средств', 'error'); return redirect(url_for('profile'))
    if g.user.get('sales_count', 0) < 1: flash('Нужна минимум 1 продажа', 'error'); return redirect(url_for('profile'))
    if not address: flash('Укажите адрес TON', 'error'); return redirect(url_for('profile'))
    try:
        amount_usdt = Decimal(str(amount_rub)) / Decimal('90')
        db = get_db()
        with db.cursor() as cur:
            cur.execute("UPDATE users SET balance = balance - %s WHERE id = %s", (Decimal(str(amount_rub)), g.user['id']))
            cur.execute("INSERT INTO balance_history (user_id, amount, type, description) VALUES (%s,%s,%s,%s)", (g.user['id'], -Decimal(str(amount_rub)), 'withdrawal', 'Вывод средств'))
            cur.execute("INSERT INTO withdrawals (user_id, amount_rub, amount_usdt, address) VALUES (%s,%s,%s,%s)", (g.user['id'], Decimal(str(amount_rub)), amount_usdt, address))
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
            uid = request.form.get('user_id', type=int); amount = request.form.get('amount', type=float); act = request.form.get('balance_action')
            if uid and amount:
                with db.cursor() as cur:
                    if act == 'add': cur.execute("UPDATE users SET balance = balance + %s WHERE id = %s", (Decimal(str(amount)), uid))
                    elif act == 'set': cur.execute("UPDATE users SET balance = %s WHERE id = %s", (Decimal(str(amount)), uid))
                flash('Баланс обновлен', 'success')
        return redirect(url_for('profile'))
    except Exception as e: return f'<h1>Ошибка: {e}</h1>', 500

# ============ API v2 ============

@app.route('/api/v2/me')
@api_required
def api_me():
    return jsonify({
        'id': g.user['id'],
        'username': g.user['username'],
        'balance': float(g.user['balance']),
        'sales_count': g.user['sales_count']
    })

@app.route('/api/v2/accounts')
@api_required
def api_accounts():
    page = request.args.get('page', 1, type=int)
    sort = request.args.get('sort', 'newest')
    country = request.args.get('country', '').strip()
    origin = request.args.get('origin', '').strip()
    premium = request.args.get('premium', '').strip()
    spamblock = request.args.get('spamblock', '').strip()
    min_chats = request.args.get('min_chats', type=int)
    q = request.args.get('q', '').strip()

    order_map = {'price_asc': 'a.price ASC', 'price_desc': 'a.price DESC', 'oldest': 'a.created_at ASC', 'chats': 'a.chats_count DESC'}
    order_by = order_map.get(sort, 'a.created_at DESC')
    offset = (page - 1) * 20

    conds = ["a.is_sold = FALSE"]; params = []
    if q: conds.append("a.title ILIKE %s"); params.append(f"%{q}%")
    if country: conds.append("a.country = %s"); params.append(country)
    if origin: conds.append("a.origin = %s"); params.append(origin)
    if premium == 'yes': conds.append("a.is_premium = TRUE")
    elif premium == 'no': conds.append("a.is_premium = FALSE")
    if spamblock == 'yes': conds.append("a.spamblock = TRUE")
    elif spamblock == 'no': conds.append("a.spamblock = FALSE")
    if min_chats is not None: conds.append("a.chats_count >= %s"); params.append(min_chats)
    where = ' AND '.join(conds)

    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute(f"SELECT COUNT(*) as cnt FROM accounts a WHERE {where}", params)
        total = cur.fetchone()['cnt']
        cur.execute(f"SELECT a.id, a.title, a.origin, a.price, a.country, a.has_2fa, a.spamblock, a.is_premium, a.chats_count, u.username as seller_name FROM accounts a JOIN users u ON a.seller_id = u.id WHERE {where} ORDER BY {order_by} LIMIT 20 OFFSET %s", params + [offset])
        accounts = [dict(r) for r in cur.fetchall()]

    return jsonify({'total': total, 'page': page, 'accounts': accounts})

@app.route('/api/v2/accounts/<int:account_id>')
@api_required
def api_account_detail(account_id):
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT a.id, a.title, a.origin, a.description, a.price, a.country, a.has_2fa, a.spamblock, a.is_premium, a.chats_count, a.channels_count, a.groups_count, u.username as seller_name FROM accounts a JOIN users u ON a.seller_id = u.id WHERE a.id = %s AND a.is_sold = FALSE", (account_id,))
        acc = cur.fetchone()
    if not acc: return jsonify({'error': 'Not found'}), 404
    rating_str, _ = get_seller_rating(acc['seller_name'])
    acc = dict(acc)
    acc['seller_rating'] = rating_str
    return jsonify(acc)

@app.route('/api/v2/buy/<int:account_id>', methods=['POST'])
@api_required
def api_buy(account_id):
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT * FROM accounts WHERE id = %s AND is_sold = FALSE", (account_id,))
            acc = cur.fetchone()
            if not acc: return jsonify({'error': 'Account not available'}), 400
            price = Decimal(str(acc['price']))
            if Decimal(str(g.user['balance'])) < price: return jsonify({'error': 'Insufficient balance'}), 400
            seller_earn = price * (Decimal('1') - COMMISSION)
            cur.execute("UPDATE users SET balance = balance - %s WHERE id = %s", (price, g.user['id']))
            cur.execute("INSERT INTO balance_history (user_id, amount, type, description) VALUES (%s,%s,%s,%s)", (g.user['id'], -price, 'purchase', f'API покупка #{account_id}'))
            cur.execute("UPDATE users SET balance = balance + %s, sales_count = sales_count + 1 WHERE id = %s", (seller_earn, acc['seller_id']))
            cur.execute("INSERT INTO balance_history (user_id, amount, type, description) VALUES (%s,%s,%s,%s)", (acc['seller_id'], seller_earn, 'sale', f'API продажа #{account_id}'))
            cur.execute("UPDATE accounts SET is_sold = TRUE WHERE id = %s", (account_id,))
            cur.execute("INSERT INTO purchases (buyer_id, account_id, phone_number) VALUES (%s,%s,%s) RETURNING id", (g.user['id'], account_id, 'Загрузка...'))
            pid = cur.fetchone()['id']
        db.commit()
        phone = extract_phone_from_session(acc['session_string'])
        if phone:
            with db.cursor() as cur: cur.execute("UPDATE purchases SET phone_number = %s WHERE id = %s", (phone, pid))
        db.commit()
        return jsonify({'success': True, 'purchase_id': pid, 'phone': phone or 'Loading...'})
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/v2/purchases')
@api_required
def api_purchases():
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT p.id, p.phone_number, p.purchase_date, p.code_retrieved, a.title FROM purchases p JOIN accounts a ON p.account_id = a.id WHERE p.buyer_id = %s ORDER BY p.id DESC", (g.user['id'],))
        purchases = [dict(r) for r in cur.fetchall()]
    return jsonify(purchases)

@app.route('/api/v2/purchases/<int:pid>/code')
@api_required
def api_get_code(pid):
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT a.session_string FROM purchases p JOIN accounts a ON p.account_id = a.id WHERE p.id = %s AND p.buyer_id = %s", (pid, g.user['id']))
            p = cur.fetchone()
        if not p: return jsonify({'error': 'Not found'}), 404
        code = extract_code_from_session(p['session_string'])
        if code: return jsonify({'code': code})
        return jsonify({'error': 'Code not found'}), 404
    except Exception as e: return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
