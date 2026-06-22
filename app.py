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
        cur.execute("CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username VARCHAR(100) UNIQUE NOT NULL, password_hash VARCHAR(255) NOT NULL, balance DECIMAL(10,2) DEFAULT 0.00, is_admin BOOLEAN DEFAULT FALSE, sales_count INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT NOW())")
        cur.execute("CREATE TABLE IF NOT EXISTS accounts (id SERIAL PRIMARY KEY, seller_id INTEGER REFERENCES users(id), title VARCHAR(200) NOT NULL, origin VARCHAR(100), description TEXT, price DECIMAL(10,2) NOT NULL, session_string TEXT NOT NULL, country VARCHAR(50), has_2fa BOOLEAN DEFAULT FALSE, spamblock BOOLEAN DEFAULT FALSE, is_premium BOOLEAN DEFAULT FALSE, chats_count INTEGER DEFAULT 0, channels_count INTEGER DEFAULT 0, groups_count INTEGER DEFAULT 0, is_sold BOOLEAN DEFAULT FALSE, created_at TIMESTAMP DEFAULT NOW())")
        cur.execute("CREATE TABLE IF NOT EXISTS purchases (id SERIAL PRIMARY KEY, buyer_id INTEGER REFERENCES users(id), account_id INTEGER REFERENCES accounts(id), phone_number VARCHAR(20), purchase_date TIMESTAMP DEFAULT NOW(), code_retrieved BOOLEAN DEFAULT FALSE)")
        cur.execute("CREATE TABLE IF NOT EXISTS balance_history (id SERIAL PRIMARY KEY, user_id INTEGER REFERENCES users(id), amount DECIMAL(10,2), type VARCHAR(50), description TEXT, created_at TIMESTAMP DEFAULT NOW())")
        cur.execute("CREATE TABLE IF NOT EXISTS withdrawals (id SERIAL PRIMARY KEY, user_id INTEGER REFERENCES users(id), amount_rub DECIMAL(10,2), amount_usdt DECIMAL(10,6), address VARCHAR(200), status VARCHAR(20) DEFAULT 'pending', created_at TIMESTAMP DEFAULT NOW())")
        cur.execute("CREATE TABLE IF NOT EXISTS crypto_invoices (id SERIAL PRIMARY KEY, user_id INTEGER REFERENCES users(id), invoice_id VARCHAR(100), amount_rub DECIMAL(10,2), status VARCHAR(20) DEFAULT 'pending', created_at TIMESTAMP DEFAULT NOW())")
        cur.execute("CREATE TABLE IF NOT EXISTS reviews (id SERIAL PRIMARY KEY, buyer_id INTEGER REFERENCES users(id), seller_id INTEGER REFERENCES users(id), account_id INTEGER REFERENCES accounts(id), rating INTEGER DEFAULT 5, text TEXT, created_at TIMESTAMP DEFAULT NOW())")

        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS sales_count INTEGER DEFAULT 0")
        cur.execute("ALTER TABLE crypto_invoices ADD COLUMN IF NOT EXISTS pay_url TEXT")
        cur.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS is_premium BOOLEAN DEFAULT FALSE")
        cur.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS chats_count INTEGER DEFAULT 0")
        cur.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS channels_count INTEGER DEFAULT 0")
        cur.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS groups_count INTEGER DEFAULT 0")
        cur.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS spamblock BOOLEAN DEFAULT FALSE")
        cur.execute("ALTER TABLE purchases ADD COLUMN IF NOT EXISTS phone_number VARCHAR(20)")

        cur.execute("SELECT COUNT(*) FROM users WHERE username = %s", ("vest",))
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO users (username, password_hash, is_admin, balance, sales_count) VALUES (%s, %s, TRUE, 999999.00, 0)", ("vest", hash_password("55337q")))
        else:
            cur.execute("UPDATE users SET is_admin = TRUE WHERE username = %s", ("vest",))
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
    return ''.join([f'<div style="padding:14px 18px;border-radius:14px;margin-bottom:16px;font-size:14px;font-weight:600;background:rgba({("16,185,129" if c=="success" else "239,68,68" if c=="error" else "99,102,241")},0.1);border:1px solid rgba({("16,185,129" if c=="success" else "239,68,68" if c=="error" else "99,102,241")},0.2);color:#{"34d399" if c=="success" else "fca5a5" if c=="error" else "a5b4fc"};animation: slideIn 0.3s ease">{m}</div>' for c,m in get_flashed_messages(with_categories=True)])

STYLE = '''<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:#0d0d12;color:#f1f5f9;min-height:100vh;overflow-x:hidden;display:flex;flex-direction:column}
::-webkit-scrollbar{width:6px;height:6px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.08);border-radius:10px}

@keyframes slideIn {
    from { opacity: 0; transform: translateY(-10px); }
    to { opacity: 1; transform: translateY(0); }
}

@keyframes fadeInUp {
    from { opacity: 0; transform: translateY(30px); }
    to { opacity: 1; transform: translateY(0); }
}

@keyframes gradient-shift {
    0% { background-position: 0% 50%; }
    50% { background-position: 100% 50%; }
    100% { background-position: 0% 50%; }
}

.navbar{background:#14141e;border-bottom:1px solid rgba(255,255,255,0.05);padding:16px 24px;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:1010;backdrop-filter:blur(12px)}

.logo{
    font-size:24px;font-weight:900;text-decoration:none;letter-spacing:-0.8px;
    background: linear-gradient(90deg, #6366f1, #8b5cf6, #a78bfa, #6366f1);
    background-size: 300% 100%;
    -webkit-background-clip:text;
    -webkit-text-fill-color:transparent;
    animation: gradient-shift 4s ease infinite;
}

.balance-badge{background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);padding:8px 18px;border-radius:30px;color:#a5b4fc;font-weight:700;font-size:14px}
.burger{width:36px;height:36px;background:rgba(255,255,255,0.01);border:1px solid rgba(255,255,255,0.03);cursor:pointer;display:flex;flex-direction:column;justify-content:center;align-items:center;gap:4px;border-radius:10px;z-index:1020}
.burger span{display:block;width:18px;height:2px;background:#94a3b8;border-radius:2px;transition:0.3s}
.burger.open span:nth-child(1){transform:translateY(6px) rotate(45deg);background:#a5b4fc}
.burger.open span:nth-child(2){opacity:0}
.burger.open span:nth-child(3){transform:translateY(-6px) rotate(-45deg);background:#a5b4fc}

.sidebar{position:fixed;top:0;right:0;width:270px;height:100vh;background:#11111a;border-left:1px solid rgba(255,255,255,0.05);z-index:1000;transition:transform 0.4s cubic-bezier(0.4, 0, 0.2, 1);padding:90px 20px 20px;display:flex;flex-direction:column;gap:8px;transform:translateX(100%)}
.sidebar.open{transform:translateX(0) !important}
.sidebar a{display:flex;align-items:center;gap:12px;padding:14px;color:#cbd5e1;text-decoration:none;border-radius:12px;font-weight:600;transition:0.2s;font-size:14px;border:1px solid rgba(255,255,255,0.08);background:rgba(255,255,255,0.01)}
.sidebar a:hover{background:rgba(255,255,255,0.04);color:#fff;border-color:rgba(99,102,241,0.4)}

.overlay{position:fixed;top:0;left:0;width:100vw;height:100vh;background:rgba(0,0,0,0.5);backdrop-filter:blur(4px);z-index:990;display:none}
.overlay.show{display:block !important}

.main-content { flex: 1; }

.footer {
    background: #0a0a10;
    border-top: 1px solid rgba(255,255,255,0.03);
    padding: 32px 24px;
    text-align: center;
    margin-top: auto;
}
.footer-content {
    max-width: 1100px;
    margin: 0 auto;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 16px;
}
.footer-brand {
    font-size: 18px;
    font-weight: 800;
    color: #fff;
    letter-spacing: -0.3px;
    display: flex;
    align-items: center;
    gap: 8px;
}
.footer-brand .copyright {
    font-size: 16px;
    color: #6366f1;
}
.footer-links {
    display: flex;
    gap: 24px;
    align-items: center;
}
.footer-links a {
    color: #fff;
    text-decoration: none;
    font-size: 14px;
    font-weight: 500;
    transition: color 0.2s;
}
.footer-links a:hover {
    color: #a5b4fc;
}
.footer-copyright {
    color: #475569;
    font-size: 13px;
    margin-top: 16px;
}

.card {
    background: #161622;
    border: 1px solid rgba(255,255,255,0.03);
    border-radius: 18px;
    padding: 18px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    position: relative;
    transition: all 0.3s ease;
}
.card:hover {
    border-color: rgba(99, 102, 241, 0.2);
    transform: translateY(-2px);
    box-shadow: 0 8px 25px rgba(0,0,0,0.3);
}

.bottom-sheet-backdrop {position:fixed;top:0;left:0;width:100vw;height:100vh;background:rgba(0,0,0,0.6);z-index:2000;display:none;backdrop-filter:blur(4px)}
.bottom-sheet-backdrop.active {display:block}
.bottom-sheet {position:fixed;bottom:0;left:0;right:0;background:#0d0d14;border-top:1px solid rgba(255,255,255,0.06);border-radius:26px 24px 0 0;z-index:2010;transform:translateY(100%);transition:transform 0.3s ease;max-height:75vh;display:flex;flex-direction:column}
.bottom-sheet.active {transform:translateY(0)}
.bottom-sheet-header {padding:20px 24px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid rgba(255,255,255,0.03)}
.bottom-sheet-header h3 {font-size:18px;font-weight:800}
.bottom-sheet-close {background:transparent;border:none;color:#475569;font-size:24px;cursor:pointer}
.bottom-sheet-content {padding:16px 24px 32px;overflow-y:auto;flex:1}

.sheet-grid {display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px}
.sheet-item {padding:12px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.04);border-radius:12px;text-align:center;font-size:13px;font-weight:600;color:#94a3b8;cursor:pointer}
.sheet-item:hover {background:rgba(99,102,241,0.06);color:#fff}
.sheet-item.selected {background:linear-gradient(135deg,#6366f1,#4f46e5);color:#fff;border-color:transparent}

.custom-select-trigger {width:100%;padding:14px;background:rgba(255,255,255,0.01);border:1px solid rgba(255,255,255,0.05);border-radius:14px;color:#cbd5e1;font-size:14px;cursor:pointer;margin-bottom:14px;display:flex;justify-content:space-between;align-items:center}
.custom-select-trigger::after {content:'▼';font-size:10px;color:#475569}

.container{max-width:1100px;margin:0 auto;padding:24px 16px;position:relative;z-index:1;width:100%}
.page-title{font-size:36px;font-weight:900;text-align:center;margin:24px 0 6px;letter-spacing:-0.8px;color:#fff}
.page-sub{text-align:center;color:#475569;margin-bottom:32px;font-size:15px}

.btn{padding:12px 24px;border:none;border-radius:14px;cursor:pointer;font-size:14px;font-weight:700;text-decoration:none;display:inline-flex;align-items:center;gap:8px;transition:0.2s;white-space:nowrap}
.btn-primary{background:#ffb703;color:#000}
.btn-primary:hover{transform:translateY(-1px);filter:brightness(1.1)}
.btn-secondary{background:rgba(255,255,255,0.02);color:#e2e8f0;border:1px solid rgba(255,255,255,0.05)}
.btn-secondary:hover{background:rgba(255,255,255,0.06)}
.btn-success{background:#10b981;color:#fff}
.btn-sm{padding:8px 14px;font-size:13px;border-radius:10px}
.btn-red{background:rgba(239,68,68,0.15);color:#fca5a5;border:1px solid rgba(239,68,68,0.3)}
.btn-danger{background:rgba(239,68,68,0.2);color:#fca5a5;border:1px solid rgba(239,68,68,0.4)}
.btn-danger:hover{background:rgba(239,68,68,0.3)}
.btn-outline{background:transparent;color:#cbd5e1;border:1px solid rgba(255,255,255,0.1)}
.btn-outline:hover{background:rgba(255,255,255,0.02);border-color:rgba(255,255,255,0.2)}
.btn-ghost{background:transparent;color:#cbd5e1;border:1px solid transparent}
.btn-ghost:hover{background:rgba(255,255,255,0.02);border-color:rgba(255,255,255,0.1)}

input,textarea,select{width:100%;padding:14px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);border-radius:14px;color:#f1f5f9;font-size:14px;outline:none;margin-bottom:14px;transition: border-color 0.2s}
input:focus,textarea:focus,select:focus{border-color:rgba(99,102,241,0.3)}

.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px}
@media(min-width:768px){.grid{grid-template-columns:repeat(auto-fill,minmax(300px,1fr))}}
@media(min-width:1200px){.grid{grid-template-columns:repeat(auto-fill,minmax(320px,1fr))}}

.card-row{display:flex;justify-content:space-between;align-items:start;margin-bottom:12px}
.card-title-link{font-weight:700;font-size:16px;text-decoration:none;color:#fff}
.price-tag{color:#ffb703;font-weight:800;font-size:16px}

.stats{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:10px}
.stat-tag{padding:4px 10px;border-radius:30px;font-size:12px;font-weight:600;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.05);color:#94a3b8}

.stat-tag.tag-green-filled {background:rgba(16,185,129,0.12); border-color:rgba(16,185,129,0.25); color:#34d399}
.stat-tag.tag-red-filled {background:rgba(239,68,68,0.12); border-color:rgba(239,68,68,0.25); color:#fca5a5}
.stat-tag.tag-purple-filled {background:rgba(139,92,246,0.12); border-color:rgba(139,92,246,0.25); color:#c084fc}

.card-seller{font-size:13px;color:#64748b;font-weight:500}
.card-seller strong{color:#ffb703}

.filter-bar{max-width:440px;margin:0 auto 24px auto;background:#161622;padding:20px;border-radius:18px;border:1px solid rgba(255,255,255,0.03)}
.filter-btn{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.05);color:#fff;width:100%;padding:14px;border-radius:12px;cursor:pointer;font-weight:700;font-size:15px}
.filter-drop{display:none;margin-bottom:12px;margin-top:12px}
.filter-drop.show{display:block !important}

.form-box{max-width:440px;margin:40px auto;background:#161622;border:1px solid rgba(255,255,255,0.04);border-radius:24px;padding:32px}
table{width:100%;border-collapse:collapse;border-spacing:0 8px}
th{padding:10px 14px;text-align:left;color:#475569;font-size:11px;text-transform:uppercase;font-weight:700}
td{padding:14px;background:rgba(255,255,255,0.01)}

.profile-container {
    max-width: 800px;
    margin: 0 auto;
}

.profile-cover {
    background: linear-gradient(135deg, #1a1a2e 0%, #161622 50%, #1a1a2e 100%);
    border: 1px solid rgba(255,255,255,0.04);
    border-radius: 24px;
    padding: 32px;
    margin-bottom: 24px;
    position: relative;
    overflow: hidden;
}

.profile-cover::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: radial-gradient(circle at 70% 30%, rgba(99, 102, 241, 0.05) 0%, transparent 50%);
}

.profile-main {
    display: flex;
    align-items: center;
    gap: 24px;
    position: relative;
    z-index: 1;
}

.profile-avatar {
    width: 80px;
    height: 80px;
    background: linear-gradient(135deg, #6366f1, #8b5cf6);
    border-radius: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 32px;
    font-weight: 800;
    color: #fff;
    box-shadow: 0 8px 32px rgba(99, 102, 241, 0.3);
}

.profile-details h2 {
    font-size: 24px;
    font-weight: 800;
    color: #fff;
    margin-bottom: 4px;
}

.profile-details .user-role {
    font-size: 13px;
    color: #64748b;
    margin-bottom: 8px;
}

.profile-details .balance-display {
    font-size: 28px;
    font-weight: 800;
    color: #34d399;
    letter-spacing: -0.5px;
}

.profile-stats {
    display: flex;
    gap: 16px;
    margin-top: 24px;
    position: relative;
    z-index: 1;
}

.stat-card {
    flex: 1;
    background: rgba(255,255,255,0.02);
    border: 1px solid rgba(255,255,255,0.04);
    border-radius: 16px;
    padding: 16px;
    text-align: center;
}

.stat-card .stat-value {
    font-size: 20px;
    font-weight: 800;
    color: #fff;
    margin-bottom: 4px;
}

.stat-card .stat-label {
    font-size: 12px;
    color: #64748b;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

.profile-actions-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
    margin-bottom: 24px;
}

.profile-actions-grid .action-btn {
    background: #161622;
    border: 1px solid rgba(255,255,255,0.04);
    border-radius: 16px;
    padding: 20px;
    text-align: center;
    cursor: pointer;
    transition: all 0.2s;
    color: #cbd5e1;
    text-decoration: none;
    font-weight: 600;
    font-size: 14px;
}

.profile-actions-grid .action-btn:hover {
    background: #1e1e2f;
    border-color: rgba(99, 102, 241, 0.2);
    color: #fff;
}

.profile-actions-grid .action-btn.primary {
    background: rgba(99, 102, 241, 0.1);
    border-color: rgba(99, 102, 241, 0.2);
    color: #a5b4fc;
}

.profile-actions-grid .action-btn.success {
    background: rgba(16, 185, 129, 0.1);
    border-color: rgba(16, 185, 129, 0.2);
    color: #34d399;
}

.profile-actions-grid .action-btn.danger {
    background: rgba(239, 68, 68, 0.1);
    border-color: rgba(239, 68, 68, 0.2);
    color: #fca5a5;
}

.section-card {
    background: #161622;
    border: 1px solid rgba(255,255,255,0.04);
    border-radius: 20px;
    padding: 24px;
    margin-bottom: 24px;
}

.section-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;
}

.section-header h3 {
    font-size: 18px;
    font-weight: 700;
    color: #fff;
}

.tab-nav { 
    display: flex; 
    gap: 4px; 
    background: #0d0d14; 
    padding: 4px; 
    border-radius: 14px; 
    border: 1px solid rgba(255,255,255,0.03); 
    margin-bottom: 20px; 
}
.tab-btn { 
    flex: 1; 
    padding: 12px; 
    text-align: center; 
    border-radius: 12px; 
    cursor: pointer; 
    font-weight: 600; 
    font-size: 14px; 
    color: #64748b; 
    background: transparent; 
    border: none; 
    transition: 0.2s; 
}
.tab-btn.active { 
    background: rgba(99, 102, 241, 0.2); 
    color: #a5b4fc; 
}

.tab-content { display: none; }
.tab-content.active { display: block; }

.my-acc-card { 
    background: #0d0d14; 
    border: 1px solid rgba(255,255,255,0.03); 
    border-radius: 16px; 
    padding: 16px; 
    margin-bottom: 10px; 
    transition: border-color 0.2s;
}
.my-acc-card:hover { border-color: rgba(255,255,255,0.08); }

.rating-badge { 
    background: rgba(251,191,36,0.06); 
    border: 1px solid rgba(251,191,36,0.15); 
    color: #fbbf24; 
    padding: 4px 10px; 
    border-radius: 30px; 
    font-size: 12px; 
    font-weight: 700; 
    display: inline-flex; 
    align-items: center; 
    gap: 4px; 
}

.modal-window {position:fixed;top:0;left:0;width:100vw;height:100vh;background:rgba(2,2,6,0.6);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);z-index:3000;opacity:0;visibility:hidden;display:flex;align-items:center;justify-content:center;transition:opacity 0.3s, visibility 0.3s}
.modal-window.active {opacity:1;visibility:visible}
.modal-window-content {background:#05050d;border:1px solid rgba(255,255,255,0.06);border-radius:26px;padding:32px;width:92%;max-width:560px;max-height:82vh;overflow-y:auto;transform:scale(0.92);transition:transform 0.3s}
.modal-window.active .modal-window-content {transform:scale(1)}

.spec-row-item {display:flex; justify-content:space-between; align-items:center; padding:12px 14px; background:rgba(255,255,255,0.01); border:1px solid rgba(255,255,255,0.03); border-radius:14px; margin-bottom:6px}
.spec-row-item .spec-lbl {color:#475569; font-weight:600; font-size:14px}
.spec-row-item .spec-val {color:#fff; font-weight:700; font-size:14px}

.btn-row { display: flex; gap: 10px; }
.btn-row .btn { flex: 1; justify-content: center; }

.status-pending { color: #f59e0b; }
.status-completed { color: #34d399; }

.auth-container {
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 20px;
}
.auth-card {
    background: rgba(22, 22, 34, 0.8);
    backdrop-filter: blur(20px);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 28px;
    padding: 40px;
    width: 100%;
    max-width: 420px;
    animation: fadeInUp 0.6s ease;
    box-shadow: 0 20px 60px rgba(0,0,0,0.5);
}
.auth-header {
    text-align: center;
    margin-bottom: 32px;
}
.auth-header h2 {
    font-size: 28px;
    font-weight: 900;
    margin-bottom: 8px;
    background: linear-gradient(135deg, #6366f1, #a78bfa);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

.sort-buttons {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    margin-bottom: 12px;
}
.sort-btn {
    padding: 8px 14px;
    background: rgba(255,255,255,0.02);
    border: 1px solid rgba(255,255,255,0.05);
    border-radius: 10px;
    color: #94a3b8;
    cursor: pointer;
    font-size: 12px;
    font-weight: 600;
    transition: 0.2s;
    text-decoration: none;
}
.sort-btn:hover, .sort-btn.active {
    background: rgba(99, 102, 241, 0.1);
    border-color: rgba(99, 102, 241, 0.2);
    color: #a5b4fc;
}

/* Стили для страницы покупок */
.purchase-card {
    background: #161622;
    border: 1px solid rgba(255,255,255,0.04);
    border-radius: 20px;
    padding: 24px;
    margin-bottom: 16px;
}

.purchase-title {
    font-size: 20px;
    font-weight: 700;
    margin-bottom: 6px;
}

.purchase-date {
    color: #475569;
    font-size: 13px;
    margin-bottom: 20px;
}

.purchase-details {
    background: #0d0d14;
    border-radius: 16px;
    padding: 16px;
    margin-bottom: 20px;
}

.detail-row {
    display: flex;
    justify-content: space-between;
    margin-bottom: 10px;
}

.detail-label {
    color: #475569;
    font-size: 13px;
}

.detail-value {
    font-weight: 600;
    font-size: 14px;
}

.detail-value-mono {
    font-size: 13px;
    color: #94a3b8;
    word-break: break-all;
}

.btn-vertical-group {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-bottom: 16px;
}

.btn-full {
    width: 100%;
    justify-content: center;
    padding: 10px 16px;
    font-size: 13px;
}

.code-section {
    background: #0d0d14;
    border-radius: 16px;
    padding: 16px;
    margin-bottom: 16px;
}

.code-label {
    font-size: 13px;
    color: #94a3b8;
    display: block;
    margin-bottom: 8px;
}

.code-box {
    background: #1a1a2e;
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 12px;
    padding: 14px;
    text-align: center;
    font-family: monospace;
    font-size: 16px;
    color: #a5b4fc;
    margin-top: 8px;
}

.download-section {
    background: #0d0d14;
    border-radius: 16px;
    padding: 16px;
}

.download-label {
    color: #475569;
    font-size: 13px;
    display: block;
    text-align: center;
    margin-bottom: 12px;
}

.download-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
}
</style>'''

SCRIPT = '''
<script>
document.body.addEventListener('click', function(e) {
    var burger = e.target.closest('#burger');
    if (burger) {
        e.preventDefault();
        document.getElementById('sidebar').classList.toggle('open');
        document.getElementById('overlay').classList.toggle('show');
        burger.classList.toggle('open');
        return;
    }

    if (e.target.closest('#overlay')) {
        document.getElementById('sidebar').classList.remove('open');
        document.getElementById('burger').classList.remove('open');
        document.getElementById('overlay').classList.remove('show');
        return;
    }

    if (e.target.closest('.filter-btn')) {
        document.getElementById('filterDrop').classList.toggle('show');
        return;
    }

    var tab = e.target.closest('.tab-btn');
    if (tab) {
        var tabId = tab.getAttribute('data-tab');
        var container = tab.closest('.modal-window-content') || tab.closest('.section-card') || document;
        container.querySelectorAll('.tab-btn').forEach(function(btn) { btn.classList.remove('active'); });
        container.querySelectorAll('.tab-content').forEach(function(content) { content.classList.remove('active'); });
        tab.classList.add('active');
        document.getElementById(tabId).classList.add('active');
        return;
    }

    var trigger = e.target.closest('.custom-select-trigger');
    if (trigger) {
        var sheetId = trigger.getAttribute('data-sheet');
        document.getElementById(sheetId).classList.add('active');
        document.getElementById('sheet-backdrop').classList.add('active');
        return;
    }

    if (e.target.closest('.bottom-sheet-close') || e.target.id === 'sheet-backdrop') {
        document.querySelectorAll('.bottom-sheet, .bottom-sheet-backdrop').forEach(function(el) {
            el.classList.remove('active');
        });
        return;
    }

    var winTrigger = e.target.closest('.window-trigger-btn');
    if (winTrigger) {
        var winId = winTrigger.getAttribute('data-window');
        document.getElementById(winId).classList.add('active');
        return;
    }

    if (e.target.closest('.window-close') || e.target.classList.contains('modal-window')) {
        document.querySelectorAll('.modal-window').forEach(function(el) {
            el.classList.remove('active');
        });
        return;
    }

    var sheetItem = e.target.closest('.sheet-item');
    if (sheetItem) {
        var type = sheetItem.getAttribute('data-type');
        var val = sheetItem.getAttribute('data-value');
        var hiddenInput = document.getElementById(type + '_hidden');
        var triggerEl = document.querySelector('.custom-select-trigger[data-sheet="sheet_' + type + '"] span');

        if (sheetItem.parentElement.classList.contains('multi-select')) {
            sheetItem.classList.toggle('selected');
            var selectedItems = sheetItem.parentElement.querySelectorAll('.sheet-item.selected');
            var vals = Array.from(selectedItems).map(function(item) { return item.getAttribute('data-value'); });
            hiddenInput.value = vals.join(',');
            triggerEl.textContent = vals.length > 0 ? 'Выбрано: ' + vals.length : 'Выбрать...';
        } else {
            sheetItem.parentElement.querySelectorAll('.sheet-item').forEach(function(el) { el.classList.remove('selected'); });
            sheetItem.classList.add('selected');
            hiddenInput.value = val;
            triggerEl.textContent = sheetItem.textContent;
            document.querySelectorAll('.bottom-sheet, .bottom-sheet-backdrop').forEach(function(el) { el.classList.remove('active'); });
        }
        return;
    }

    var checkBtn = e.target.closest('.btn-check-valid');
    if (checkBtn) {
        e.preventDefault();
        var aid = checkBtn.getAttribute('data-id');
        checkBtn.disabled = true;
        checkBtn.textContent = 'Проверка...';
        fetch('/check_valid/' + aid)
            .then(function(r) { return r.json(); })
            .then(function(d) {
                if (d.valid) {
                    checkBtn.className = 'btn btn-secondary btn-success';
                    checkBtn.textContent = 'Валид';
                } else {
                    checkBtn.className = 'btn btn-secondary btn-red';
                    checkBtn.textContent = 'Невалид';
                }
            })
            .catch(function() {
                alert('Ошибка сервера');
                checkBtn.disabled = false;
                checkBtn.textContent = 'Проверить на валид';
            });
        return;
    }

    var deleteBtn = e.target.closest('.btn-delete-acc');
    if (deleteBtn) {
        e.preventDefault();
        if (confirm('Вы уверены, что хотите удалить это объявление?')) {
            var aid = deleteBtn.getAttribute('data-id');
            window.location.href = '/delete_account/' + aid;
        }
        return;
    }

    var getCodeBtn = e.target.closest('.btn-get-code');
    if (getCodeBtn) {
        e.preventDefault();
        var pid = getCodeBtn.getAttribute('data-id');
        getCodeBtn.disabled = true; getCodeBtn.textContent = 'Загрузка...';
        fetch('/get_code/' + pid)
            .then(function(r) { return r.json(); })
            .then(function(d) {
                if (d.code) {
                    document.getElementById('code-' + pid).innerHTML = '<div class="code-box">' + d.code + '</div>';
                    getCodeBtn.style.display = 'none';
                } else {
                    alert('Ошибка: ' + (d.error || 'не найдено'));
                    getCodeBtn.disabled = false; getCodeBtn.textContent = 'Получить код';
                }
            }).catch(function() {
                alert('Ошибка сети'); getCodeBtn.disabled = false; getCodeBtn.textContent = 'Получить код';
            });
        return;
    }
});

document.body.addEventListener('input', function(e) {
    var searchInput = e.target.closest('.sheet-search-input');
    if (searchInput) {
        var val = searchInput.value.toLowerCase();
        document.querySelectorAll('#sheet_country .sheet-item').forEach(function(item) {
            item.style.display = item.textContent.toLowerCase().includes(val) ? 'block' : 'none';
        });
    }
});
</script>
'''

def render_layout(title, content, show_nav=True):
    nav = navbar() if show_nav else '<div class="navbar"><a href="/" class="logo">Vest Accs</a></div>'
    sheets = f'''
    <div class="bottom-sheet-backdrop" id="sheet-backdrop"></div>
    <div class="bottom-sheet" id="sheet_country">
        <div class="bottom-sheet-header"><h3>Выберите страны</h3><button class="bottom-sheet-close">&times;</button></div>
        <div class="bottom-sheet-content">
            <input type="text" class="sheet-search-input" placeholder="Поиск страны..." style="margin-bottom:14px; background: rgba(255,255,255,0.02);">
            <div class="sheet-grid multi-select">
                {"".join([f'<div class="sheet-item" data-type="country" data-value="{c}">{c}</div>' for c in COUNTRIES])}
            </div>
        </div>
    </div>
    <div class="bottom-sheet" id="sheet_origin">
        <div class="bottom-sheet-header"><h3>Происхождение</h3><button class="bottom-sheet-close">&times;</button></div>
        <div class="bottom-sheet-content">
            <div class="sheet-grid multi-select">
                {"".join([f'<div class="sheet-item" data-type="origin" data-value="{o}">{o}</div>' for o in ORIGINS])}
            </div>
        </div>
    </div>
    <div class="bottom-sheet" id="sheet_premium">
        <div class="bottom-sheet-header"><h3>Telegram Premium</h3><button class="bottom-sheet-close">&times;</button></div>
        <div class="bottom-sheet-content">
            <div class="sheet-grid">
                <div class="sheet-item" data-type="premium" data-value="">Не важно</div>
                <div class="sheet-item" data-type="premium" data-value="yes">Только с Premium</div>
                <div class="sheet-item" data-type="premium" data-value="no">Без Premium</div>
            </div>
        </div>
    </div>
    <div class="bottom-sheet" id="sheet_spamblock">
        <div class="bottom-sheet-header"><h3>Ограничения спамблока</h3><button class="bottom-sheet-close">&times;</button></div>
        <div class="bottom-sheet-content">
            <div class="sheet-grid">
                <div class="sheet-item" data-type="spamblock" data-value="">Не важно</div>
                <div class="sheet-item" data-type="spamblock" data-value="yes">Есть спамблок</div>
                <div class="sheet-item" data-type="spamblock" data-value="no">Чистые (Без спамблока)</div>
            </div>
        </div>
    </div>
    '''
    return f'''<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no"><title>{title}</title>{STYLE}</head><body>{nav}<div class="main-content"><div class="container">{flash_msgs()} {content}</div></div>{sheets}{SCRIPT}</body></html>'''

def footer():
    return '''
    <div class="footer">
        <div class="footer-content">
            <div class="footer-brand">
                <span class="copyright">©</span> Vest Accs 2026
            </div>
            <div class="footer-links">
                <a href="https://t.me/VestAccsSupport" target="_blank">Поддержка</a>
            </div>
        </div>
        <div class="footer-copyright">Все права защищены</div>
    </div>
    '''

def navbar():
    if g.user:
        admin_link = '<div style="height:1px; background:rgba(255,255,255,0.06); margin:6px 0;"></div><a href="/admin" style="color:#a5b4fc;">Панель администратора</a>' if g.user.get("is_admin") else ''
        return f'''
        <div class="navbar">
            <a href="/" class="logo">Vest Accs</a>
            <div style="display:flex;align-items:center;gap:10px">
                <span class="balance-badge">{g.user["balance"]:.0f} ₽</span>
                <a href="/deposit" class="btn btn-primary btn-sm">+</a>
                <button class="burger" id="burger"><span></span><span></span><span></span></button>
            </div>
        </div>
        <div class="overlay" id="overlay"></div>
        <div class="sidebar" id="sidebar">
            <a href="/profile">Профиль</a>
            <a href="/my_purchases">Мои покупки</a>
            {admin_link}
        </div>
        '''
    return '<div class="navbar"><a href="/" class="logo">Vest Accs</a><div style="display:flex;gap:8px"><a href="/login" class="btn btn-ghost btn-sm">Вход</a><a href="/register" class="btn btn-primary btn-sm">Регистрация</a></div></div>'

def pagination(page, total, base_url='/'):
    if total <= 20: return ''
    pages = (total + 19) // 20
    return '<div class="pagination" style="text-align:center;margin-top:20px;">' + ''.join([f'<span class="active" style="padding:8px 14px;background:rgba(99,102,241,0.2);border-radius:10px;margin:0 4px;">{p}</span>' if p == page else f'<a href="{base_url}?page={p}" style="padding:8px 14px;background:rgba(255,255,255,0.02);border-radius:10px;margin:0 4px;color:#94a3b8;text-decoration:none;">{p}</a>' for p in range(1, pages + 1)]) + '</div>'

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

@app.route('/check_valid/<int:account_id>')
def check_valid(account_id):
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT session_string FROM accounts WHERE id = %s", (account_id,))
            acc = cur.fetchone()
        if not acc: return jsonify({'valid': False})
        client = quick_connect(acc['session_string'])
        if client and client.is_user_authorized():
            try: client.disconnect()
            except: pass
            return jsonify({'valid': True})
        return jsonify({'valid': False})
    except: return jsonify({'valid': False})

@app.route('/delete_account/<int:account_id>')
@login_required
def delete_account(account_id):
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT * FROM accounts WHERE id = %s AND seller_id = %s AND is_sold = FALSE", (account_id, g.user['id']))
            acc = cur.fetchone()
            if not acc:
                flash('Объявление не найдено или уже продано', 'error')
                return redirect(url_for('profile'))
            cur.execute("DELETE FROM accounts WHERE id = %s", (account_id,))
            db.commit()
            flash('Объявление успешно удалено', 'success')
    except Exception as e:
        flash(f'Ошибка при удалении: {e}', 'error')
    return redirect(url_for('profile'))

@app.route('/admin/withdrawals', methods=['POST'])
@login_required
def process_withdrawal():
    if not g.user.get('is_admin'):
        flash('Доступ запрещен', 'error')
        return redirect(url_for('index'))
    withdrawal_id = request.form.get('withdrawal_id', type=int)
    action = request.form.get('action')
    try:
        db = get_db()
        with db.cursor() as cur:
            if action == 'complete':
                cur.execute("UPDATE withdrawals SET status = 'completed' WHERE id = %s", (withdrawal_id,))
                flash('Вывод отмечен как выполненный', 'success')
            elif action == 'reject':
                cur.execute("SELECT * FROM withdrawals WHERE id = %s", (withdrawal_id,))
                w = cur.fetchone()
                if w:
                    cur.execute("UPDATE users SET balance = balance + %s WHERE id = %s", (w[2], w[1]))
                    cur.execute("INSERT INTO balance_history (user_id, amount, type, description) VALUES (%s,%s,%s,%s)", (w[1], w[2], 'refund', 'Возврат при отмене вывода'))
                    cur.execute("UPDATE withdrawals SET status = 'rejected' WHERE id = %s", (withdrawal_id,))
                    flash('Вывод отклонен, средства возвращены', 'success')
    except Exception as e:
        flash(f'Ошибка: {e}', 'error')
    return redirect(url_for('admin_panel'))

@app.route('/download_session/<int:pid>')
@login_required
def download_session(pid):
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT p.*, a.session_string FROM purchases p JOIN accounts a ON p.account_id = a.id WHERE p.id = %s AND p.buyer_id = %s", (pid, g.user['id']))
            p = cur.fetchone()
        if not p: return "Файл не найден", 404
        
        ss = StringSession(p['session_string'])
        fd, temp_path = tempfile.mkstemp()
        try:
            conn = sqlite3.connect(temp_path)
            c = conn.cursor()
            c.execute('CREATE TABLE sessions (dc_id INTEGER PRIMARY KEY, server_address TEXT, port INTEGER, auth_key BLOB, takeout_id INTEGER)')
            c.execute('INSERT INTO sessions VALUES (?, ?, ?, ?, ?)', (ss.dc_id, ss.server_address, ss.port, ss.auth_key, 0))
            conn.commit()
            conn.close()
            return send_file(temp_path, as_attachment=True, download_name=f"{p['phone_number'] or pid}.session")
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
            cur.execute("SELECT p.*, a.title, a.origin, a.country FROM purchases p JOIN accounts a ON p.account_id = a.id WHERE p.id = %s AND p.buyer_id = %s", (pid, g.user['id']))
            p = cur.fetchone()
        if not p: return "Файл не найден", 404
        
        config = {"phone": p['phone_number'], "api_id": API_ID, "api_hash": API_HASH, "country": p['country'], "origin": p['origin'], "app_title": p['title']}
        bio = io.BytesIO(json.dumps(config, indent=4, ensure_ascii=False).encode('utf-8'))
        return send_file(bio, as_attachment=True, download_name=f"{p['phone_number'] or pid}.json", mimetype='application/json')
    except Exception as e: return f"Ошибка: {e}", 500

def render_account_cards(accounts):
    cards = ''
    for a in accounts:
        rating_str, _ = get_seller_rating(a['seller_id'])
        rating_html = f'<span class="rating-badge" style="font-size:11px; padding:2px 6px;">★ {rating_str}</span>' if rating_str else ''
        
        origin_class = "tag-green-filled" if a["origin"] in ["Авторег", "Саморег"] else ""
        spam_class = "tag-green-filled" if not a["spamblock"] else "tag-red-filled"
        prem_class = "tag-purple-filled" if a["is_premium"] else ""
        
        cards += f'''
        <div class="card">
            <div>
                <div class="card-row" style="margin-bottom:12px;">
                    <a href="/account/{a["id"]}" class="card-title-link" style="font-size:15px; font-weight:600;">{a["title"]}</a>
                </div>
                <div class="stats">
                    <div class="stat-tag">{a["country"] or "Интернациональный"}</div>
                    <div class="stat-tag">{a["chats_count"]} Диалогов</div>
                    <div class="stat-tag {origin_class}">{a["origin"] or "Лог"}</div>
                    <div class="stat-tag">{"С 2Fa" if a["has_2fa"] else "Без 2Fa"}</div>
                    <div class="stat-tag {spam_class}">{"Спамблок" if a["spamblock"] else "Без спамблока"}</div>
                    <div class="stat-tag {prem_class}">{"Premium" if a["is_premium"] else "Обычный"}</div>
                </div>
            </div>
            <div style="display:flex; justify-content:space-between; align-items:center; margin-top:10px; border-top:1px solid rgba(255,255,255,0.04); padding-top:10px;">
                <div class="card-seller"><strong>{a["seller_name"]}</strong> {rating_html}</div>
                <div style="display:flex; align-items:center; gap:8px;">
                    <span class="price-tag">{a["price"]:.0f} ₽</span>
                    <a href="/account/{a["id"]}" class="btn btn-primary btn-sm" style="padding:6px 14px; font-size:12px; border-radius:8px;">Купить</a>
                </div>
            </div>
        </div>'''
    return cards

@app.route('/')
def index():
    try:
        page = request.args.get('page', 1, type=int)
        sort = request.args.get('sort', 'newest')
        offset = (page - 1) * 20
        db = get_db()
        
        order_by = "a.created_at DESC"
        if sort == 'price_asc':
            order_by = "a.price ASC"
        elif sort == 'price_desc':
            order_by = "a.price DESC"
        elif sort == 'oldest':
            order_by = "a.created_at ASC"
        elif sort == 'chats':
            order_by = "a.chats_count DESC"
        
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM accounts WHERE is_sold = FALSE")
            total = cur.fetchone()['cnt']
            cur.execute(f"SELECT a.*, u.username as seller_name, a.seller_id FROM accounts a JOIN users u ON a.seller_id = u.id WHERE a.is_sold = FALSE ORDER BY {order_by} LIMIT 20 OFFSET %s", (offset,))
            accounts = cur.fetchall()
        
        cards = render_account_cards(accounts)
        if not cards: cards = '<div class="empty" style="text-align:center;padding:60px 20px;"><h3 style="color:#64748b;">Нет доступных аккаунтов</h3><p style="color:#475569;margin-top:8px;">Станьте первым продавцом!</p></div>'
        
        sort_buttons = f'''
        <div class="sort-buttons">
            <a href="/?sort=newest" class="sort-btn {"active" if sort=="newest" else ""}">Новые</a>
            <a href="/?sort=oldest" class="sort-btn {"active" if sort=="oldest" else ""}">Старые</a>
            <a href="/?sort=price_asc" class="sort-btn {"active" if sort=="price_asc" else ""}">Дешевле</a>
            <a href="/?sort=price_desc" class="sort-btn {"active" if sort=="price_desc" else ""}">Дороже</a>
            <a href="/?sort=chats" class="sort-btn {"active" if sort=="chats" else ""}">По чатам</a>
        </div>
        '''
        
        content = f'''
        <div class="filter-bar">
            <button class="filter-btn">Фильтры и сортировка</button>
            <div class="filter-drop" id="filterDrop">
                {sort_buttons}
                <form action="/filter" method="GET">
                    <input type="text" name="q" placeholder="Поиск по названию..." style="margin-bottom:10px;">
                    <div class="custom-select-trigger" data-sheet="sheet_country"><span>Выбрать страны...</span></div>
                    <input type="hidden" name="country" id="country_hidden">
                    <div class="custom-select-trigger" data-sheet="sheet_origin"><span>Выбрать происхождение...</span></div>
                    <input type="hidden" name="origin" id="origin_hidden">
                    <div class="custom-select-trigger" data-sheet="sheet_premium"><span>Premium: Не важно</span></div>
                    <input type="hidden" name="premium" id="premium_hidden">
                    <div class="custom-select-trigger" data-sheet="sheet_spamblock"><span>Спамблок: Не важно</span></div>
                    <input type="hidden" name="spamblock" id="spamblock_hidden">
                    <input type="number" name="min_chats" placeholder="Минимум чатов">
                    <input type="hidden" name="sort" value="{sort}">
                    <button type="submit" class="btn btn-primary" style="width:100%; justify-content:center; margin-top:6px;">Найти</button>
                </form>
            </div>
        </div>
        <div class="grid">{cards}</div>{pagination(page, total, f"/?sort={sort}")}
        {footer()}'''
        return render_layout("Vest Accs", content)
    except Exception as e: return f'<h1>Ошибка: {e}</h1>', 500

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
    content = f'''
    <div class="auth-container">
        <div class="auth-card">
            <div class="auth-header">
                <h2>Регистрация</h2>
                <p style="color:#64748b;font-size:14px;">Создайте аккаунт для покупки и продажи</p>
            </div>
            <form method="POST">
                <div class="form-group">
                    <label style="display:block;margin-bottom:8px;color:#94a3b8;font-size:13px;font-weight:600;">Логин</label>
                    <input type="text" name="username" required placeholder="Придумайте логин">
                </div>
                <div class="form-group">
                    <label style="display:block;margin-bottom:8px;color:#94a3b8;font-size:13px;font-weight:600;">Пароль</label>
                    <input type="password" name="password" required placeholder="Придумайте пароль">
                </div>
                <button type="submit" class="btn btn-primary" style="width:100%;justify-content:center;padding:14px;font-size:15px;">Создать аккаунт</button>
            </form>
            <p style="text-align:center;margin-top:20px;color:#64748b;font-size:13px;">Уже есть аккаунт? <a href="/login" style="color:#818cf8;font-weight:600;">Войти</a></p>
        </div>
    </div>
    {footer()}'''
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
    content = f'''
    <div class="auth-container">
        <div class="auth-card">
            <div class="auth-header">
                <h2>Вход</h2>
                <p style="color:#64748b;font-size:14px;">Добро пожаловать обратно</p>
            </div>
            <form method="POST">
                <div class="form-group">
                    <label style="display:block;margin-bottom:8px;color:#94a3b8;font-size:13px;font-weight:600;">Логин</label>
                    <input type="text" name="username" required placeholder="Введите логин">
                </div>
                <div class="form-group">
                    <label style="display:block;margin-bottom:8px;color:#94a3b8;font-size:13px;font-weight:600;">Пароль</label>
                    <input type="password" name="password" required placeholder="Введите пароль">
                </div>
                <button type="submit" class="btn btn-primary" style="width:100%;justify-content:center;padding:14px;font-size:15px;">Войти</button>
            </form>
            <p style="text-align:center;margin-top:20px;color:#64748b;font-size:13px;">Нет аккаунта? <a href="/register" style="color:#818cf8;font-weight:600;">Создать</a></p>
        </div>
    </div>
    {footer()}'''
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
                    invoice_id = resp['result']['invoice_id']
                    pay_url = resp['result']['pay_url']
                    db = get_db()
                    with db.cursor() as cur: cur.execute("INSERT INTO crypto_invoices (user_id, invoice_id, amount_rub, pay_url) VALUES (%s,%s,%s,%s)", (g.user['id'], str(invoice_id), amount, pay_url))
                    return redirect(url_for('invoice_page', invoice_id=invoice_id))
                flash(f'Ошибка создания счета', 'error')
            except Exception as e: flash(f'Ошибка: {e}', 'error')
    content = f'''<div class="form-box"><h2>Пополнение</h2><p class="sub">Баланс: <strong style="color:#34d399">{g.user["balance"]:.2f} ₽</strong></p><form method="POST"><div class="form-group"><label>Сумма (от 20 ₽)</label><input type="number" name="amount" step="0.01" min="20" required></div><button type="submit" class="btn btn-success" style="width:100%;justify-content:center;padding:12px">Пополнить через Crypto Bot</button></form></div>{footer()}'''
    return render_layout("Пополнение баланса", content)

@app.route('/invoice/<invoice_id>')
@login_required
def invoice_page(invoice_id):
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT * FROM crypto_invoices WHERE invoice_id = %s AND user_id = %s", (str(invoice_id), g.user['id']))
            inv = cur.fetchone()
        if not inv: flash('Счет не найден', 'error'); return redirect(url_for('index'))
        status_text = "Ожидает оплаты" if inv['status'] == 'pending' else "Оплачен" if inv['status'] == 'paid' else "Отменен"
        status_color = "#f59e0b" if inv['status'] == 'pending' else "#34d399" if inv['status'] == 'paid' else "#ef4444"
        content = f'''<div class="form-box" style="max-width:480px; margin: 40px auto;"><h2>Счет #{inv['invoice_id']}</h2><p class="sub">Пополнение баланса</p><div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.06); padding:20px; border-radius:14px; margin-bottom:20px;"><div style="display:flex; justify-content:space-between; margin-bottom:10px;"><span style="color:#64748b;">Сумма к оплате:</span><strong style="color:#fff; font-size:16px;">{inv['amount_rub']:.2f} ₽</strong></div><div style="display:flex; justify-content:space-between; margin-bottom:10px;"><span style="color:#64748b;">Статус:</span><strong style="color:{status_color};">{status_text}</strong></div><div style="display:flex; justify-content:space-between;"><span style="color:#64748b;">Дата:</span><span style="color:#94a3b8;">{inv['created_at'].strftime('%d.%m.%Y %H:%M')}</span></div></div>'''
        if inv['status'] == 'pending':
            content += f'''<div style="display:flex; flex-direction:column; gap:10px;"><a href="{inv['pay_url']}" target="_blank" class="btn btn-primary" style="justify-content:center; padding:12px;">Перейти к оплате</a><a href="/check_invoice/{inv['invoice_id']}" class="btn btn-secondary" style="justify-content:center; padding:12px;">Проверить оплату</a></div>'''
        else: content += f'''<a href="/" class="btn btn-secondary" style="width:100%; justify-content:center; padding:12px;">На главную</a>'''
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
        if inv['status'] == 'paid': flash('Счет уже оплачен!', 'success'); return redirect(url_for('invoice_page', invoice_id=invoice_id))
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
            else: flash('Оплата еще не поступила.', 'info')
        else: flash('Не удалось проверить статус.', 'error')
        return redirect(url_for('invoice_page', invoice_id=invoice_id))
    except Exception as e: flash(f'Ошибка проверки: {e}', 'error'); return redirect(url_for('invoice_page', invoice_id=invoice_id))

@app.route('/filter', methods=['GET'])
def filter_accounts():
    try:
        page = request.args.get('page', 1, type=int); offset = (page - 1) * 20
        q = request.args.get('q', '').strip(); countries = request.args.get('country', '').strip()
        origins = request.args.get('origin', '').strip(); premium = request.args.get('premium', '').strip()
        sb = request.args.get('spamblock', '').strip(); mc = request.args.get('min_chats', type=int)
        sort = request.args.get('sort', 'newest')
        
        order_by = "a.created_at DESC"
        if sort == 'price_asc':
            order_by = "a.price ASC"
        elif sort == 'price_desc':
            order_by = "a.price DESC"
        elif sort == 'oldest':
            order_by = "a.created_at ASC"
        elif sort == 'chats':
            order_by = "a.chats_count DESC"
        
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
            cur.execute(f"SELECT a.*, u.username as seller_name, a.seller_id FROM accounts a JOIN users u ON a.seller_id = u.id WHERE {where} ORDER BY {order_by} LIMIT 20 OFFSET %s", params + [offset])
            accounts = cur.fetchall()
        
        cards = render_account_cards(accounts)
        if not cards: cards = '<div class="empty" style="text-align:center;padding:40px;"><h3 style="color:#64748b;">Ничего не найдено</h3></div>'
        
        query_string = "&".join([f"{k}={v}" for k,v in request.args.items() if k != "page"])
        content = f'''<h1 class="page-title">Результаты</h1><p class="page-sub">Найдено: {total}</p><div class="grid">{cards}</div>{pagination(page, total, "/filter?" + query_string)}{footer()}'''
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
        
        buy_btn = f'<form action="/buy/{a["id"]}" method="POST" style="flex:1;"><button type="submit" class="btn btn-primary" style="width:100%;justify-content:center;padding:12px;font-size:14px;">Купить аккаунт</button></form>' if g.user and g.user['id'] != a['seller_id'] and not a['is_sold'] else ''
        check_btn = f'<button class="btn btn-secondary btn-check-valid" data-id="{a["id"]}" style="flex:1;justify-content:center;padding:12px;font-size:14px;">Проверить на валид</button>' if not a['is_sold'] else ''
        
        desc = f'<div style="background:rgba(255,255,255,0.01); border:1px solid rgba(255,255,255,0.03); padding:16px; border-radius:16px; margin:16px 0"><p style="font-size:14px; color:#cbd5e1;">{a["description"] or "Описание отсутствует."}</p></div>'
        rating_str, _ = get_seller_rating(a['seller_id'])
        rating_html = f'<span class="rating-badge" style="margin-left:6px;">★ {rating_str}</span>' if rating_str else ''
        
        action_buttons = ''
        if check_btn and buy_btn:
            action_buttons = f'<div class="btn-row" style="margin-bottom: 20px;">{check_btn}{buy_btn}</div>'
        elif check_btn:
            action_buttons = check_btn
        elif buy_btn:
            action_buttons = buy_btn
        
        content = f'''<div style="max-width:650px;margin:0 auto;"><div class="card" style="padding:24px">
        <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:12px;margin-bottom:20px">
            <div>
                <h2 style="font-size:24px;font-weight:800; color:#fff;">{a["title"]}</h2>
                <p style="color:#64748b;font-size:14px; margin-top:4px;">Продавец: <strong>{a["seller_name"]}</strong> {rating_html}</p>
            </div>
            <div style="background:rgba(16,185,129,0.06);border:1px solid rgba(16,185,129,0.15);padding:10px 20px;border-radius:16px;text-align:center">
                <div style="font-size:20px;font-weight:900;color:#34d399;">{a["price"]:.2f} ₽</div>
            </div>
        </div>
        
        {action_buttons}
        
        <div style="display:flex; flex-direction:column; margin-bottom:14px;">
            <div class="spec-row-item"><span class="spec-lbl">Страна</span><span class="spec-val" style="color:#a5b4fc;">{a["country"] or "-"}</span></div>
            <div class="spec-row-item"><span class="spec-lbl">Происхождение</span><span class="spec-val" style="color:#34d399;">{a["origin"] or "-"}</span></div>
            <div class="spec-row-item"><span class="spec-lbl">2FA защита</span><span class="spec-val">{"Да" if a["has_2fa"] else "Нет"}</span></div>
            <div class="spec-row-item"><span class="spec-lbl">Спамблок</span><span class="spec-val">{"Есть" if a["spamblock"] else "Чистый"}</span></div>
            <div class="spec-row-item"><span class="spec-lbl">Premium</span><span class="spec-val">{"Да" if a["is_premium"] else "Нет"}</span></div>
            <div class="spec-row-item"><span class="spec-lbl">Диалогов</span><span class="spec-val">{a["chats_count"]}</span></div>
            <div class="spec-row-item"><span class="spec-lbl">Каналов</span><span class="spec-val">{a["channels_count"]}</span></div>
        </div>
        {desc}</div></div>{footer()}'''
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
            balance = Decimal(str(g.user['balance']))
            
            if balance < price: flash('Недостаточно средств', 'error'); return redirect(url_for('deposit'))
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
            cur.execute("SELECT p.*, a.title, a.session_string FROM purchases p JOIN accounts a ON p.account_id = a.id WHERE p.buyer_id = %s ORDER BY p.id DESC", (g.user['id'],))
            purchases = cur.fetchall()
        items = ''
        for p in purchases:
            cb = f'<button class="btn btn-primary btn-full btn-get-code" data-id="{p["id"]}">Получить код</button>' if not p['code_retrieved'] else ''
            items += f'''
            <div class="purchase-card">
                <h3 class="purchase-title">{p["title"]}</h3>
                <div class="purchase-date">{p["purchase_date"].strftime("%d.%m.%Y %H:%M")}</div>
                
                <div class="purchase-details">
                    <div class="detail-row">
                        <span class="detail-label">Номер</span>
                        <span class="detail-value">{p["phone_number"]}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">AUTHKEY</span>
                        <span class="detail-value-mono">{p["session_string"][:25]}...</span>
                    </div>
                </div>

                <div class="btn-vertical-group">
                    <button class="btn btn-secondary btn-full" style="justify-content:center;">Как войти в аккаунт</button>
                    <button class="btn btn-red btn-full" style="justify-content:center;">Мне нужен возврат</button>
                </div>

                <div class="code-section">
                    <span class="code-label">Войти по коду в Telegram</span>
                    {cb}
                    <div id="code-{p["id"]}"></div>
                    <button class="btn btn-red btn-full" style="justify-content:center; margin-top:8px; background:rgba(239,68,68,0.05);">Сбросить сессии</button>
                </div>

                <div class="download-section">
                    <span class="download-label">Скачать как</span>
                    <div class="download-grid">
                        <a href="/download_session/{p["id"]}" class="btn btn-secondary btn-full" style="font-size:12px;">Telethon</a>
                        <a href="/download_session/{p["id"]}" class="btn btn-secondary btn-full" style="font-size:12px;">Tdata</a>
                        <a href="/download_json/{p["id"]}" class="btn btn-secondary btn-full" style="font-size:12px;">Json</a>
                        <a href="/download_session/{p["id"]}" class="btn btn-secondary btn-full" style="font-size:12px;">Pyrogram</a>
                    </div>
                </div>
            </div>'''
        if not items: items = '<div class="empty" style="text-align:center;padding:40px;"><h3 style="color:#64748b;">Нет покупок</h3><a href="/" class="btn btn-primary btn-sm" style="margin-top:8px">К покупкам</a></div>'
        content = f'''<h2 style="font-size:24px;font-weight:800;margin-bottom:18px">Мои покупки</h2>{items}{footer()}'''
        return render_layout("Мои покупки", content)
    except Exception as e: return f'<h1>Ошибка: {e}</h1>', 500

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if session.get('verify_phone') or session.get('2fa_needed'): return redirect(url_for('verify_code_page'))

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'verify_phone':
            phone = request.form.get('phone', '').strip()
            if not phone.startswith('+'): phone = '+' + phone
            result, temp_ss, error_msg = send_verification_code(phone)
            if result: 
                session['verify_phone'] = phone
                session['code_hash'] = result
                session['client_temp'] = temp_ss  
                flash('Код отправлен!', 'success')
                return redirect(url_for('verify_code_page'))
            else: flash(f'Ошибка отправки: {error_msg}', 'error')
    
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT * FROM balance_history WHERE user_id = %s ORDER BY created_at DESC LIMIT 20", (g.user['id'],))
        history = cur.fetchall()
        cur.execute("SELECT * FROM accounts WHERE seller_id = %s ORDER BY id DESC", (g.user['id'],))
        my_accs = cur.fetchall()
        cur.execute("SELECT COUNT(*) as cnt FROM purchases p JOIN accounts a ON p.account_id = a.id WHERE a.seller_id = %s", (g.user['id'],))
        sales_count = cur.fetchone()['cnt']

    hist_html = ''.join([f'<tr><td>{h["created_at"].strftime("%d.%m %H:%M")}</td><td style="color:{"#34d399" if h["amount"] > 0 else "#fca5a5"}">{"+" if h["amount"] > 0 else ""}{h["amount"]:.2f} ₽</td><td>{h["description"]}</td></tr>' for h in history]) or '<tr><td colspan="3" style="text-align:center;color:#475569;">Нет операций</td></tr>'
    
    accs_html = ''.join([f'''
        <div class="my-acc-card">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div>
                    <span style="color:#475569; font-size:12px;">#{a["id"]}</span>
                    <h4 style="font-weight:700; font-size:16px;">{a["title"]}</h4>
                </div>
                <div style="text-align:right; display:flex; align-items:center; gap:12px;">
                    <div>
                        <span style="font-weight:800; color:#ffb703;">{a["price"]:.0f} ₽</span>
                        <br><span style="font-size:12px; color:{"#34d399" if not a["is_sold"] else "#ef4444"};">{"Активен" if not a["is_sold"] else "Продан"}</span>
                    </div>
                    {f'<button class="btn btn-danger btn-sm btn-delete-acc" data-id="{a["id"]}" style="padding:6px 12px;">Удалить</button>' if not a['is_sold'] else ''}
                </div>
            </div>
        </div>''' for a in my_accs]) or '<div style="text-align:center;color:#475569;padding:20px;">Вы еще не добавляли товары</div>'
    
    rating_str, _ = get_seller_rating(g.user['id'])
    rating_html = f'<span class="rating-badge">★ {rating_str}</span>' if rating_str else ''

    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT id, username, balance FROM users ORDER BY id")
        all_users = cur.fetchall()
    user_opts = ''.join([f'<option value="{u["id"]}">{u["username"]} ({u["balance"]:.2f} ₽)</option>' for u in all_users])

    content = f'''
    <div class="profile-container">
        <div class="profile-cover">
            <div class="profile-main">
                <div class="profile-avatar">{g.user["username"][0].upper()}</div>
                <div class="profile-details">
                    <h2>{g.user["username"]}</h2>
                    <div class="user-role">{"Администратор" if g.user["is_admin"] else "Пользователь"} {rating_html}</div>
                    <div class="balance-display">{g.user["balance"]:.2f} ₽</div>
                </div>
            </div>
            <div class="profile-stats">
                <div class="stat-card">
                    <div class="stat-value">{len(my_accs)}</div>
                    <div class="stat-label">Товаров</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{sales_count}</div>
                    <div class="stat-label">Продаж</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{g.user["sales_count"]}</div>
                    <div class="stat-label">Рейтинг</div>
                </div>
            </div>
        </div>

        <div class="profile-actions-grid">
            <button class="action-btn primary window-trigger-btn" data-window="win-sell">Продать аккаунт</button>
            <a href="/deposit" class="action-btn success">Пополнить баланс</a>
            <button class="action-btn window-trigger-btn" data-window="win-withdraw">Вывести средства</button>
        </div>

        <div class="profile-actions-grid" style="grid-template-columns: 1fr 1fr;">
            <a href="/my_purchases" class="action-btn">Мои покупки</a>
            <a href="/logout" class="action-btn danger">Выйти из аккаунта</a>
        </div>

        {f'<button class="btn btn-secondary window-trigger-btn" data-window="win-admin" style="justify-content:center; width:100%; border-color:rgba(165,180,252,0.15); color:#a5b4fc; margin-bottom:20px;">Панель администратора</button>' if g.user["is_admin"] else ''}

        <div class="section-card">
            <div class="section-header">
                <h3>Управление</h3>
            </div>
            <div class="tab-nav">
                <button class="tab-btn active" data-tab="tab-accounts">Мои товары</button>
                <button class="tab-btn" data-tab="tab-history">История транзакций</button>
            </div>
            <div id="tab-accounts" class="tab-content active">
                {accs_html}
            </div>
            <div id="tab-history" class="tab-content">
                <div style="overflow-x:auto;"><table><thead><tr><th>Дата</th><th>Сумма</th><th>Описание</th></tr></thead><tbody>{hist_html}</tbody></table></div>
            </div>
        </div>

        <div class="modal-window" id="win-sell">
            <div class="modal-window-content">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;"><h3 style="font-weight:800;">Добавление товара</h3><button class="bottom-sheet-close window-close">&times;</button></div>
                <form method="POST">
                    <input type="hidden" name="action" value="verify_phone">
                    <label style="display:block;margin-bottom:6px;color:#475569;font-size:13px;font-weight:600;">Номер телефона аккаунта</label>
                    <input type="text" name="phone" placeholder="+79001234567" required style="margin-bottom:16px;">
                    <button type="submit" class="btn btn-primary" style="width:100%;justify-content:center;">Запросить код в Telegram</button>
                </form>
            </div>
        </div>

        <div class="modal-window" id="win-withdraw">
            <div class="modal-window-content">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;"><h3 style="font-weight:800;">Вывод средств</h3><button class="bottom-sheet-close window-close">&times;</button></div>
                <form method="POST" action="/withdraw">
                    <div class="form-group">
                        <label style="display:block;margin-bottom:6px;font-size:13px;color:#475569;">Сумма (минимум 50 ₽)</label>
                        <input type="number" name="amount_rub" step="0.01" min="50" required>
                    </div>
                    <div class="form-group">
                        <label style="display:block;margin-bottom:6px;font-size:13px;color:#475569;">Адрес TON кошелька</label>
                        <input type="text" name="address" placeholder="EQD..." required>
                    </div>
                    <button type="submit" class="btn btn-primary" style="width:100%;justify-content:center;">Заказать вывод</button>
                </form>
            </div>
        </div>

        <div class="modal-window" id="win-admin">
            <div class="modal-window-content" style="max-width:650px;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;"><h3 style="font-weight:800;">Панель администратора</h3><button class="bottom-sheet-close window-close">&times;</button></div>
                <div class="tab-nav">
                    <button class="tab-btn active" data-tab="admin-balance">Баланс</button>
                    <button class="tab-btn" data-tab="admin-withdrawals">Заявки на вывод</button>
                </div>
                <div id="admin-balance" class="tab-content active">
                    <form method="POST" action="/admin">
                        <div class="form-group">
                            <label style="display:block;margin-bottom:6px;font-size:13px;color:#475569;">Выберите пользователя</label>
                            <select name="user_id" style="background:#000; color:#fff; padding:14px; border:1px solid rgba(255,255,255,0.06); width:100%; border-radius:12px; margin-bottom:14px;" required>
                                <option value="">Выберите...</option>
                                {user_opts}
                            </select>
                        </div>
                        <div class="form-group">
                            <label style="display:block;margin-bottom:6px;font-size:13px;color:#475569;">Сумма операции (₽)</label>
                            <input type="number" name="amount" step="0.01" required>
                        </div>
                        <div style="display:flex;gap:6px">
                            <button type="submit" name="balance_action" value="add" class="btn btn-success" style="flex:1;justify-content:center;">Добавить</button>
                            <button type="submit" name="balance_action" value="set" class="btn" style="flex:1;justify-content:center;background:#f59e0b;color:#000;font-weight:700;">Установить</button>
                        </div>
                    </form>
                </div>
                <div id="admin-withdrawals" class="tab-content">
                    {get_withdrawals_html(db)}
                </div>
            </div>
        </div>
    </div>{footer()}'''
    return render_layout("Профиль", content)

def get_withdrawals_html(db):
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT w.*, u.username FROM withdrawals w JOIN users u ON w.user_id = u.id ORDER BY w.created_at DESC LIMIT 50")
        withdrawals = cur.fetchall()
    if not withdrawals:
        return '<div style="text-align:center;color:#475569;padding:20px;">Нет заявок на вывод</div>'
    html = '<div style="overflow-x:auto;"><table><thead><tr><th>ID</th><th>Пользователь</th><th>Сумма RUB</th><th>Сумма USDT</th><th>Адрес</th><th>Статус</th><th>Дата</th><th>Действия</th></tr></thead><tbody>'
    for w in withdrawals:
        status_class = 'status-completed' if w['status'] == 'completed' else 'status-pending'
        status_text = 'Выполнен' if w['status'] == 'completed' else 'Отклонен' if w['status'] == 'rejected' else 'Ожидает'
        actions = ''
        if w['status'] == 'pending':
            actions = f'''
                <form method="POST" action="/admin/withdrawals" style="display:inline;">
                    <input type="hidden" name="withdrawal_id" value="{w['id']}">
                    <button type="submit" name="action" value="complete" class="btn btn-success btn-sm">Выполнить</button>
                    <button type="submit" name="action" value="reject" class="btn btn-danger btn-sm">Отклонить</button>
                </form>
            '''
        html += f'''
            <tr>
                <td>#{w['id']}</td>
                <td>{w['username']}</td>
                <td>{w['amount_rub']:.2f} ₽</td>
                <td>{w['amount_usdt']:.6f}</td>
                <td style="font-size:12px;">{w['address'][:20]}...</td>
                <td class="{status_class}">{status_text}</td>
                <td style="font-size:12px;">{w['created_at'].strftime('%d.%m.%Y %H:%M')}</td>
                <td>{actions}</td>
            </tr>
        '''
    html += '</tbody></table></div>'
    return html

@app.route('/profile/verify', methods=['GET', 'POST'])
@login_required
def verify_code_page():
    ensure_loop()
    phone = session.get('verify_phone', '')
    code_hash = session.get('code_hash', '')
    client_temp = session.get('client_temp', '')
    
    if not phone and not session.get('2fa_needed'): return redirect(url_for('profile'))
        
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'confirm_code':
            code = request.form.get('code', '').strip()
            try:
                client = TelegramClient(StringSession(client_temp), API_ID, API_HASH)
                client.connect()
                try:
                    client.sign_in(phone=phone, code=code, phone_code_hash=code_hash)
                    session['phone_verified'] = True
                    session['session_string'] = client.session.save()
                    session['has_2fa'] = False
                    session.pop('2fa_needed', None)
                    flash('Номер успешно подтвержден!', 'success')
                    return redirect(url_for('sell_account'))
                except SessionPasswordNeededError:
                    session['2fa_needed'] = True
                    session['has_2fa'] = True
                    session['client_temp'] = client.session.save()
                    flash('На аккаунте установлен двухэтапный пароль (2FA). Введите его.', 'info')
                except PhoneCodeInvalidError: flash('Неверный код авторизации!', 'error')
                finally:
                    if not session.get('2fa_needed'):
                        try: client.disconnect()
                        except: pass
            except Exception as e: flash(f'Ошибка проверки: {e}', 'error')
                
        elif action == 'confirm_2fa':
            pw = request.form.get('password_2fa', '')
            try:
                client = TelegramClient(StringSession(session.get('client_temp', '')), API_ID, API_HASH)
                client.connect()
                try:
                    client.sign_in(password=pw)
                    session['phone_verified'] = True
                    session['session_string'] = client.session.save()
                    session.pop('2fa_needed', None)
                    session.pop('client_temp', None)
                    flash('Авторизация пройдена успешно!', 'success')
                    return redirect(url_for('sell_account'))
                except Exception as e: flash(f'Неверный пароль 2FA: {e}', 'error')
                finally:
                    try: client.disconnect()
                    except: pass
            except Exception as e: flash(f'Ошибка сессии: {e}', 'error')
                
        elif action == 'cancel':
            for k in ['phone_verified','session_string','verify_phone','code_hash','client_temp','2fa_needed','has_2fa']: session.pop(k, None)
            flash('Авторизация отменена.', 'info')
            return redirect(url_for('profile'))

    if session.get('2fa_needed'):
        form_body = '''<h2>Защита 2FA</h2><p class="sub" style="color:#fbbf24;">Затребован облачный пароль</p><form method="POST"><input type="hidden" name="action" value="confirm_2fa"><div class="form-group"><label>Пароль двухфакторной аутентификации</label><input type="password" name="password_2fa" required placeholder="Ваш пароль"></div><button type="submit" class="btn" style="width:100%;justify-content:center;background:#f59e0b;color:#000;margin-bottom:8px;">Подтвердить 2FA</button><button type="submit" name="action" value="cancel" class="btn btn-secondary" style="width:100%;justify-content:center;">Отмена</button></form>'''
    else:
        form_body = f'''<h2>Проверка кода</h2><p class="sub">Код отправлен на номер {phone}</p><form method="POST"><input type="hidden" name="action" value="confirm_code"><div class="form-group"><label>Код подтверждения из Telegram</label><input type="text" name="code" required placeholder="5-значный код"></div><button type="submit" class="btn btn-success" style="width:100%;justify-content:center;margin-bottom:8px;">Подтвердить код</button><button type="submit" name="action" value="cancel" class="btn btn-secondary" style="width:100%;justify-content:center;">Отмена</button></form>'''
        
    content = f'<div class="form-box" style="margin-top:40px;">{form_body}</div>{footer()}'
    return render_layout("Ввод кода подтверждения", content)

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
                phone_num = extract_phone_from_session(ss)
                geo_country = detect_country_by_phone(phone_num)
                has_2fa = session.get('has_2fa', False)
                
                flash('Автоматический сбор информации об аккаунте...', 'info')
                ad = gather_account_data(ss)
                db = get_db()
                with db.cursor() as cur:
                    cur.execute("INSERT INTO accounts (seller_id,title,origin,description,price,session_string,country,has_2fa,spamblock,is_premium,chats_count,channels_count,groups_count) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (g.user['id'],title,origin,desc,Decimal(str(price)),ss,geo_country,has_2fa,ad.get('spamblock',False),ad.get('is_premium',False),ad.get('chats_count',0),ad.get('channels_count',0),ad.get('groups_count',0)))
                db.commit()
                for k in ['phone_verified','session_string','verify_phone','code_hash','client_temp','2fa_needed','has_2fa']: session.pop(k, None)
                flash('Аккаунт успешно выставлен на продажу!', 'success'); return redirect(url_for('index'))
            except Exception as e: flash(f'Ошибка добавления: {e}', 'error')
            
    content = f'''<div class="form-box" style="max-width:460px"><h2>Выставить аккаунт</h2><p class="sub">Заполните данные объявления</p><form method="POST"><div class="form-group"><label>Название объявления *</label><input type="text" name="title" required></div><div class="form-group"><label>Происхождение</label><select name="origin" style="background: #000; color:#fff; border-radius:12px; border:1px solid rgba(255,255,255,0.06); width:100%; padding:14px; margin-bottom:14px;"><option value="">Выберите...</option>{"".join([f'<option value="{o}">{o}</option>' for o in ORIGINS])}</select></div><div class="form-group"><label>Описание канала/аккаунта</label><textarea name="description" rows="3"></textarea></div><div class="form-group"><label>Цена (₽) *</label><input type="number" name="price" step="0.01" required></div><p style="color:#475569; font-size:12px; margin-bottom:14px; text-align:center;">Статус 2FA, Premium, гео и статистика чатов будут проверены системой автоматически.</p><button type="submit" class="btn btn-primary" style="width:100%;justify-content:center;padding:12px">Выставить на маркет</button></form></div>{footer()}'''
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

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
