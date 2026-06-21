import os
import re
import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, render_template_string, request, redirect, url_for, session, flash, jsonify, g
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
import psycopg2.extras
from telethon import TelegramClient
from telethon.sessions import StringSession

# --- Конфигурация ---
DATABASE_URL = "postgresql://bothost_db_3092f9da4312:yvzBra5xN_j2a_dafFbpHStZAVH7HiMuzJ2iCwDX-5w@node1.pghost.ru:15796/bothost_db_3092f9da4312"
API_ID = 32480523
API_HASH = "147839735c9fa4e83451209e9b55cfc5"
SECRET_KEY = secrets.token_hex(32)
COMMISSION = 0.05  # 5%

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

# --- HTML шаблоны как строки ---
BASE_STYLE = """
<style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #0f0f0f; color: #e0e0e0; min-height: 100vh; }
    .navbar { background: #1a1a1a; padding: 15px 30px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #2a2a2a; }
    .navbar .logo { color: #7c3aed; font-size: 24px; font-weight: bold; text-decoration: none; }
    .navbar .nav-links { display: flex; gap: 15px; align-items: center; }
    .btn { padding: 10px 20px; border: none; border-radius: 8px; cursor: pointer; font-size: 14px; text-decoration: none; display: inline-block; transition: all 0.3s; }
    .btn-primary { background: #7c3aed; color: white; }
    .btn-primary:hover { background: #6d28d9; }
    .btn-secondary { background: #2a2a2a; color: #e0e0e0; }
    .btn-secondary:hover { background: #3a3a3a; }
    .btn-success { background: #10b981; color: white; }
    .btn-success:hover { background: #059669; }
    .btn-danger { background: #ef4444; color: white; }
    .btn-danger:hover { background: #dc2626; }
    .btn-warning { background: #f59e0b; color: white; }
    .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
    .card { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 12px; padding: 20px; margin-bottom: 15px; }
    .card:hover { border-color: #7c3aed; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 15px; }
    .badge { padding: 5px 10px; border-radius: 20px; font-size: 12px; background: #2a2a2a; }
    .badge-success { background: #10b981; color: white; }
    .badge-warning { background: #f59e0b; color: black; }
    .badge-danger { background: #ef4444; color: white; }
    input, textarea, select { width: 100%; padding: 12px; background: #0f0f0f; border: 1px solid #2a2a2a; border-radius: 8px; color: #e0e0e0; margin-bottom: 10px; }
    input:focus, textarea:focus, select:focus { outline: none; border-color: #7c3aed; }
    .flash-messages { margin-bottom: 20px; }
    .flash { padding: 12px; border-radius: 8px; margin-bottom: 10px; }
    .flash-success { background: #10b981; color: white; }
    .flash-error { background: #ef4444; color: white; }
    .flash-info { background: #3b82f6; color: white; }
    .filter-panel { background: #1a1a1a; padding: 20px; border-radius: 12px; margin-bottom: 20px; display: none; }
    .filter-panel.active { display: block; }
    .filter-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; margin-bottom: 10px; }
    .price { color: #10b981; font-size: 20px; font-weight: bold; }
    .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.8); z-index: 1000; }
    .modal.active { display: flex; align-items: center; justify-content: center; }
    .modal-content { background: #1a1a1a; padding: 30px; border-radius: 12px; max-width: 500px; width: 90%; }
    .copy-btn { cursor: pointer; color: #7c3aed; }
    .balance { color: #10b981; font-weight: bold; font-size: 18px; }
</style>
"""

BASE_SCRIPT = """
<script>
function toggleFilters() {
    document.getElementById('filterPanel').classList.toggle('active');
}
function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        alert('Скопировано!');
    });
}
function openModal(id) {
    document.getElementById('modal-' + id).classList.add('active');
}
function closeModal(id) {
    document.getElementById('modal-' + id).classList.remove('active');
}
function getCode(purchaseId) {
    fetch('/get_code/' + purchaseId)
        .then(r => r.json())
        .then(data => {
            if (data.code) {
                document.getElementById('code-' + purchaseId).innerHTML = 'Код: <strong>' + data.code + '</strong>';
            } else {
                alert('Не удалось получить код. Попробуйте позже.');
            }
        });
}
</script>
"""

INDEX_TEMPLATE = BASE_STYLE + """
<div class="navbar">
    <a href="/" class="logo">Vest Accs</a>
    <div class="nav-links">
        <a href="/" class="btn btn-secondary">Главная</a>
        {% if g.user %}
            <span class="balance">Баланс: {{ "%.2f"|format(g.user.balance) }} ₽</span>
            <a href="/deposit" class="btn btn-primary">+</a>
            <a href="/my_purchases" class="btn btn-secondary">Мои покупки</a>
            <a href="/profile" class="btn btn-secondary">Профиль</a>
            <a href="/logout" class="btn btn-danger">Выйти</a>
        {% else %}
            <a href="/login" class="btn btn-primary">Войти</a>
            <a href="/register" class="btn btn-secondary">Регистрация</a>
        {% endif %}
    </div>
</div>

<div class="container">
    <h1 style="margin-bottom: 20px;">Маркетплейс Telegram аккаунтов</h1>
    
    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            <div class="flash-messages">
                {% for category, message in messages %}
                    <div class="flash flash-{{ category }}">{{ message }}</div>
                {% endfor %}
            </div>
        {% endif %}
    {% endwith %}
    
    <button onclick="toggleFilters()" class="btn btn-secondary" style="margin-bottom: 20px;">🔍 Фильтры</button>
    
    <div id="filterPanel" class="filter-panel">
        <form action="/filter" method="GET">
            <div class="filter-row">
                <input type="text" name="q" placeholder="Поиск по заголовку...">
                <input type="text" name="country" placeholder="Страна...">
                <input type="text" name="origin" placeholder="Происхождение...">
            </div>
            <div class="filter-row">
                <select name="2fa">
                    <option value="">2FA (любой)</option>
                    <option value="yes">Есть 2FA</option>
                    <option value="no">Нет 2FA</option>
                </select>
                <select name="spamblock">
                    <option value="">Спамблок (любой)</option>
                    <option value="yes">Есть спамблок</option>
                    <option value="no">Нет спамблока</option>
                </select>
                <input type="number" name="min_chats" placeholder="Мин. кол-во чатов...">
            </div>
            <button type="submit" class="btn btn-primary">Применить фильтры</button>
            <a href="/" class="btn btn-secondary">Сбросить</a>
        </form>
    </div>
    
    <div class="grid">
        {% for account in accounts %}
        <div class="card">
            <h3 style="color: #7c3aed;">{{ account.title }}</h3>
            <p>Продавец: {{ account.seller_name }}</p>
            <p>Страна: {{ account.country or 'Не указана' }}</p>
            <p>Происхождение: {{ account.origin or 'Не указано' }}</p>
            <p>2FA: {% if account.has_2fa %}<span class="badge badge-success">Да</span>{% else %}<span class="badge badge-danger">Нет</span>{% endif %}</p>
            <p>Спамблок: {% if account.spamblock %}<span class="badge badge-warning">Есть</span>{% else %}<span class="badge badge-success">Нет</span>{% endif %}</p>
            <p>Чаты: {{ account.chats_count }} | Каналы: {{ account.channels_count }} | Группы: {{ account.groups_count }}</p>
            <div class="price">{{ "%.2f"|format(account.price) }} ₽</div>
            <div style="margin-top: 10px; display: flex; gap: 10px;">
                <a href="/account/{{ account.id }}" class="btn btn-secondary">Подробнее</a>
                {% if g.user and g.user.id != account.seller_id %}
                <form action="/buy/{{ account.id }}" method="POST" style="display: inline;">
                    <button type="submit" class="btn btn-success">Купить</button>
                </form>
                {% endif %}
            </div>
        </div>
        {% endfor %}
        {% if not accounts %}
        <p>Нет доступных аккаунтов</p>
        {% endif %}
    </div>
</div>
""" + BASE_SCRIPT

LOGIN_TEMPLATE = BASE_STYLE + """
<div class="navbar">
    <a href="/" class="logo">Vest Accs</a>
    <div class="nav-links">
        <a href="/register" class="btn btn-secondary">Регистрация</a>
    </div>
</div>

<div class="container" style="max-width: 400px; margin-top: 100px;">
    <div class="card">
        <h2 style="text-align: center; margin-bottom: 20px;">Вход</h2>
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="flash flash-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        <form method="POST">
            <input type="text" name="username" placeholder="Логин" required>
            <input type="password" name="password" placeholder="Пароль" required>
            <button type="submit" class="btn btn-primary" style="width: 100%;">Войти</button>
        </form>
        <p style="text-align: center; margin-top: 15px;">Нет аккаунта? <a href="/register" style="color: #7c3aed;">Регистрация</a></p>
    </div>
</div>
"""

REGISTER_TEMPLATE = BASE_STYLE + """
<div class="navbar">
    <a href="/" class="logo">Vest Accs</a>
    <div class="nav-links">
        <a href="/login" class="btn btn-primary">Войти</a>
    </div>
</div>

<div class="container" style="max-width: 400px; margin-top: 100px;">
    <div class="card">
        <h2 style="text-align: center; margin-bottom: 20px;">Регистрация</h2>
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="flash flash-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        <form method="POST">
            <input type="text" name="username" placeholder="Логин" required>
            <input type="password" name="password" placeholder="Пароль" required>
            <button type="submit" class="btn btn-primary" style="width: 100%;">Зарегистрироваться</button>
        </form>
    </div>
</div>
"""

ACCOUNT_DETAIL_TEMPLATE = BASE_STYLE + """
<div class="navbar">
    <a href="/" class="logo">Vest Accs</a>
    <div class="nav-links">
        <a href="/" class="btn btn-secondary">На главную</a>
    </div>
</div>

<div class="container" style="max-width: 600px;">
    <div class="card">
        <h2 style="color: #7c3aed;">{{ account.title }}</h2>
        <div style="margin-top: 20px;">
            <p><strong>Продавец:</strong> {{ account.seller_name }}</p>
            <p><strong>Страна:</strong> {{ account.country or 'Не указана' }}</p>
            <p><strong>Происхождение:</strong> {{ account.origin or 'Не указано' }}</p>
            <p><strong>Описание:</strong> {{ account.description or 'Нет описания' }}</p>
            <p><strong>2FA:</strong> {% if account.has_2fa %}Да{% else %}Нет{% endif %}</p>
            <p><strong>Спамблок:</strong> {% if account.spamblock %}Есть{% else %}Нет{% endif %}</p>
            <p><strong>Чаты:</strong> {{ account.chats_count }}</p>
            <p><strong>Каналы:</strong> {{ account.channels_count }}</p>
            <p><strong>Группы:</strong> {{ account.groups_count }}</p>
            <div class="price" style="margin: 20px 0;">{{ "%.2f"|format(account.price) }} ₽</div>
        </div>
        <div style="display: flex; gap: 10px;">
            <a href="/" class="btn btn-secondary">Назад</a>
            {% if g.user and g.user.id != account.seller_id and not account.is_sold %}
            <form action="/buy/{{ account.id }}" method="POST">
                <button type="submit" class="btn btn-success">Купить</button>
            </form>
            {% endif %}
        </div>
    </div>
</div>
"""

PROFILE_TEMPLATE = BASE_STYLE + """
<div class="navbar">
    <a href="/" class="logo">Vest Accs</a>
    <div class="nav-links">
        <a href="/" class="btn btn-secondary">Главная</a>
        <span class="balance">{{ "%.2f"|format(g.user.balance) }} ₽</span>
        <a href="/deposit" class="btn btn-primary">+</a>
    </div>
</div>

<div class="container" style="max-width: 600px;">
    <h1>Профиль</h1>
    <div class="card" style="margin-top: 20px;">
        <h3>Информация</h3>
        <p>Логин: {{ g.user.username }}</p>
        <p>Баланс: <span class="balance">{{ "%.2f"|format(g.user.balance) }} ₽</span></p>
    </div>
    
    <div class="card" style="margin-top: 20px;">
        <h3>Выставить аккаунт на продажу</h3>
        <form method="POST">
            <input type="hidden" name="action" value="verify_phone">
            <p><strong>Шаг 1: Подтверждение номера телефона</strong></p>
            <input type="text" name="phone" placeholder="+79001234567" required>
            <button type="submit" class="btn btn-primary">Отправить код</button>
        </form>
        
        {% if session.get('verify_phone') %}
        <form method="POST" style="margin-top: 20px;">
            <input type="hidden" name="action" value="confirm_code">
            <p><strong>Шаг 2: Введите код из Telegram</strong></p>
            <input type="text" name="code" placeholder="12345" required>
            <button type="submit" class="btn btn-success">Подтвердить код</button>
        </form>
        {% endif %}
        
        {% if session.get('phone_verified') %}
        <div style="margin-top: 20px;">
            <p style="color: #10b981;">✓ Номер подтвержден</p>
            <a href="/sell" class="btn btn-primary">Заполнить данные аккаунта</a>
        </div>
        {% endif %}
    </div>
    
    {% if g.user.is_admin %}
    <div class="card" style="margin-top: 20px;">
        <h3>Админ-панель</h3>
        <a href="/admin" class="btn btn-warning">Перейти в админ-панель</a>
    </div>
    {% endif %}
</div>
""" + BASE_STYLE

SELL_TEMPLATE = BASE_STYLE + """
<div class="navbar">
    <a href="/" class="logo">Vest Accs</a>
    <div class="nav-links">
        <a href="/profile" class="btn btn-secondary">Профиль</a>
    </div>
</div>

<div class="container" style="max-width: 600px;">
    <h1>Выставить аккаунт на продажу</h1>
    <div class="card" style="margin-top: 20px;">
        <form method="POST">
            <input type="text" name="title" placeholder="Название аккаунта *" required>
            <input type="text" name="origin" placeholder="Происхождение (например, парсинг)">
            <textarea name="description" placeholder="Описание аккаунта" rows="4"></textarea>
            <input type="number" name="price" placeholder="Цена в рублях *" step="0.01" required>
            <label style="display: flex; align-items: center; gap: 10px; margin-bottom: 10px;">
                <input type="checkbox" name="has_2fa" style="width: auto;">
                <span>Есть 2FA</span>
            </label>
            <button type="submit" class="btn btn-primary" style="width: 100%;">Выставить на продажу</button>
        </form>
        <p style="margin-top: 10px; color: #888;">Комиссия платформы: 5%</p>
    </div>
</div>
"""

MY_PURCHASES_TEMPLATE = BASE_STYLE + """
<div class="navbar">
    <a href="/" class="logo">Vest Accs</a>
    <div class="nav-links">
        <a href="/" class="btn btn-secondary">Главная</a>
        <span class="balance">{{ "%.2f"|format(g.user.balance) }} ₽</span>
        <a href="/deposit" class="btn btn-primary">+</a>
    </div>
</div>

<div class="container">
    <h1>Мои покупки</h1>
    <div style="margin-top: 20px;">
        {% for purchase in purchases %}
        <div class="card">
            <h3>{{ purchase.title }}</h3>
            <p>Дата покупки: {{ purchase.purchase_date.strftime('%d.%m.%Y %H:%M') }}</p>
            <p>Номер телефона: 
                <span id="phone-{{ purchase.id }}">{{ purchase.phone_number }}</span>
                <button onclick="copyToClipboard('{{ purchase.phone_number }}')" class="btn btn-secondary" style="padding: 5px 10px; font-size: 12px;">📋</button>
            </p>
            <div id="code-{{ purchase.id }}" style="margin: 10px 0;">
                {% if purchase.code_retrieved %}
                <p>Код уже был получен</p>
                {% endif %}
            </div>
            <button onclick="getCode({{ purchase.id }})" class="btn btn-primary">Получить код</button>
        </div>
        {% endfor %}
        {% if not purchases %}
        <p>У вас пока нет покупок</p>
        {% endif %}
    </div>
</div>
""" + BASE_SCRIPT

DEPOSIT_TEMPLATE = BASE_STYLE + """
<div class="navbar">
    <a href="/" class="logo">Vest Accs</a>
    <div class="nav-links">
        <a href="/" class="btn btn-secondary">Главная</a>
        <span class="balance">{{ "%.2f"|format(g.user.balance) }} ₽</span>
    </div>
</div>

<div class="container" style="max-width: 400px; margin-top: 100px;">
    <div class="card">
        <h2>Пополнение баланса</h2>
        <form method="POST">
            <input type="number" name="amount" placeholder="Сумма пополнения" step="0.01" required>
            <button type="submit" class="btn btn-primary" style="width: 100%;">Пополнить</button>
        </form>
    </div>
</div>
"""

ADMIN_TEMPLATE = BASE_STYLE + """
<div class="navbar">
    <a href="/" class="logo">Vest Accs</a>
    <div class="nav-links">
        <a href="/profile" class="btn btn-secondary">Профиль</a>
    </div>
</div>

<div class="container">
    <h1>Админ-панель</h1>
    
    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            {% for category, message in messages %}
                <div class="flash flash-{{ category }}">{{ message }}</div>
            {% endfor %}
        {% endif %}
    {% endwith %}
    
    <div class="card" style="margin-top: 20px;">
        <h3>Управление балансом пользователей</h3>
        <form method="POST" style="margin-top: 20px;">
            <select name="user_id" required>
                <option value="">Выберите пользователя</option>
                {% for user in users %}
                <option value="{{ user.id }}">{{ user.username }} (Баланс: {{ "%.2f"|format(user.balance) }} ₽)</option>
                {% endfor %}
            </select>
            <input type="number" name="amount" placeholder="Сумма" step="0.01" required>
            <div style="display: flex; gap: 10px;">
                <button type="submit" name="action" value="add" class="btn btn-success">Добавить</button>
                <button type="submit" name="action" value="set" class="btn btn-warning">Установить</button>
            </div>
        </form>
    </div>
    
    <div class="card" style="margin-top: 20px;">
        <h3>Все пользователи</h3>
        <table style="width: 100%; margin-top: 10px; border-collapse: collapse;">
            <thead>
                <tr style="border-bottom: 1px solid #2a2a2a;">
                    <th style="padding: 10px; text-align: left;">ID</th>
                    <th style="padding: 10px; text-align: left;">Логин</th>
                    <th style="padding: 10px; text-align: left;">Баланс</th>
                    <th style="padding: 10px; text-align: left;">Админ</th>
                </tr>
            </thead>
            <tbody>
                {% for user in users %}
                <tr style="border-bottom: 1px solid #2a2a2a;">
                    <td style="padding: 10px;">{{ user.id }}</td>
                    <td style="padding: 10px;">{{ user.username }}</td>
                    <td style="padding: 10px;">{{ "%.2f"|format(user.balance) }} ₽</td>
                    <td style="padding: 10px;">{% if user.is_admin %}Да{% else %}Нет{% endif %}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>
"""

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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS phone_verifications (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                phone_number VARCHAR(20),
                code_hash VARCHAR(255),
                code VARCHAR(10),
                verified BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW()
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

# --- Маршруты ---
@app.route('/')
def index():
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("""
            SELECT a.*, u.username as seller_name
            FROM accounts a
            JOIN users u ON a.seller_id = u.id
            WHERE a.is_sold = FALSE
            ORDER BY a.created_at DESC
        """)
        accounts = cur.fetchall()
    return render_template_string(INDEX_TEMPLATE, accounts=accounts)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if not username or not password:
            flash('Заполните все поля', 'error')
            return render_template_string(REGISTER_TEMPLATE)
        db = get_db()
        with db.cursor() as cur:
            try:
                cur.execute(
                    "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
                    (username, generate_password_hash(password))
                )
                db.commit()
                flash('Регистрация успешна! Войдите.', 'success')
                return redirect(url_for('login'))
            except psycopg2.IntegrityError:
                db.rollback()
                flash('Пользователь уже существует', 'error')
    return render_template_string(REGISTER_TEMPLATE)

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
    return render_template_string(LOGIN_TEMPLATE)

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
                cur.execute(
                    "UPDATE users SET balance = balance + %s WHERE id = %s",
                    (amount, g.user['id'])
                )
            flash(f'Баланс пополнен на {amount} ₽', 'success')
            return redirect(url_for('index'))
    return render_template_string(DEPOSIT_TEMPLATE)

@app.route('/filter', methods=['GET'])
def filter_accounts():
    query = request.args.get('q', '').strip()
    country = request.args.get('country', '').strip()
    origin = request.args.get('origin', '').strip()
    has_2fa = request.args.get('2fa', '').strip()
    spamblock = request.args.get('spamblock', '').strip()
    min_chats = request.args.get('min_chats', type=int)
    
    db = get_db()
    conditions = ["a.is_sold = FALSE"]
    params = []
    
    if query:
        conditions.append("a.title ILIKE %s")
        params.append(f"%{query}%")
    if country:
        conditions.append("a.country ILIKE %s")
        params.append(f"%{country}%")
    if origin:
        conditions.append("a.origin ILIKE %s")
        params.append(f"%{origin}%")
    if has_2fa == 'yes':
        conditions.append("a.has_2fa = TRUE")
    elif has_2fa == 'no':
        conditions.append("a.has_2fa = FALSE")
    if spamblock == 'yes':
        conditions.append("a.spamblock = TRUE")
    elif spamblock == 'no':
        conditions.append("a.spamblock = FALSE")
    if min_chats is not None:
        conditions.append("a.chats_count >= %s")
        params.append(min_chats)
    
    where = " AND ".join(conditions)
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute(f"""
            SELECT a.*, u.username as seller_name
            FROM accounts a
            JOIN users u ON a.seller_id = u.id
            WHERE {where}
            ORDER BY a.created_at DESC
        """, params)
        accounts = cur.fetchall()
    return render_template_string(INDEX_TEMPLATE, accounts=accounts)

@app.route('/account/<int:account_id>')
def account_detail(account_id):
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("""
            SELECT a.*, u.username as seller_name
            FROM accounts a
            JOIN users u ON a.seller_id = u.id
            WHERE a.id = %s
        """, (account_id,))
        account = cur.fetchone()
    if not account:
        flash('Аккаунт не найден', 'error')
        return redirect(url_for('index'))
    return render_template_string(ACCOUNT_DETAIL_TEMPLATE, account=account)

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
        
        commission_amount = account['price'] * COMMISSION
        seller_earn = account['price'] - commission_amount
        
        cur.execute(
            "UPDATE users SET balance = balance - %s WHERE id = %s",
            (account['price'], g.user['id'])
        )
        cur.execute(
            "UPDATE users SET balance = balance + %s WHERE id = %s",
            (seller_earn, account['seller_id'])
        )
        cur.execute(
            "UPDATE accounts SET is_sold = TRUE WHERE id = %s",
            (account_id,)
        )
        cur.execute(
            "INSERT INTO purchases (buyer_id, account_id, phone_number) VALUES (%s, %s, %s) RETURNING id",
            (g.user['id'], account_id, 'Загрузка...')
        )
        purchase = cur.fetchone()
        db.commit()
        
        # Извлекаем номер телефона из сессии
        phone = extract_phone_from_session(account['session_string'])
        if phone:
            cur.execute(
                "UPDATE purchases SET phone_number = %s WHERE id = %s",
                (phone, purchase['id'])
            )
            db.commit()
        
        flash('Покупка успешна! Перейдите в "Мои покупки" для получения кода.', 'success')
        return redirect(url_for('my_purchases'))

def extract_phone_from_session(session_string):
    """Извлекает номер телефона из сессии"""
    try:
        client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
        client.connect()
        if client.is_user_authorized():
            me = client.get_me()
            phone = me.phone if me.phone else "Номер скрыт"
            client.disconnect()
            return phone
        client.disconnect()
    except:
        pass
    return "Номер скрыт"

@app.route('/my_purchases')
@login_required
def my_purchases():
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("""
            SELECT p.*, a.title, a.session_string
            FROM purchases p
            JOIN accounts a ON p.account_id = a.id
            WHERE p.buyer_id = %s
            ORDER BY p.purchase_date DESC
        """, (g.user['id'],))
        purchases = cur.fetchall()
    return render_template_string(MY_PURCHASES_TEMPLATE, purchases=purchases)

@app.route('/get_code/<int:purchase_id>')
@login_required
def get_code(purchase_id):
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("""
            SELECT p.*, a.session_string
            FROM purchases p
            JOIN accounts a ON p.account_id = a.id
            WHERE p.id = %s AND p.buyer_id = %s
        """, (purchase_id, g.user['id']))
        purchase = cur.fetchone()
        if not purchase:
            return jsonify({'error': 'Покупка не найдена'}), 404
        
        code = extract_latest_code(purchase['session_string'])
        if code:
            cur.execute(
                "UPDATE purchases SET code_retrieved = TRUE WHERE id = %s",
                (purchase_id,)
            )
            db.commit()
            return jsonify({'code': code})
        return jsonify({'error': 'Не удалось получить код'}), 500

def extract_latest_code(session_string):
    """Извлекает последний 5-значный код из сообщений"""
    try:
        client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
        client.connect()
        if not client.is_user_authorized():
            client.disconnect()
            return None
        
        dialogs = client.get_dialogs(limit=10)
        for dialog in dialogs:
            try:
                messages = client.get_messages(dialog, limit=10)
                for msg in messages:
                    if msg.message:
                        codes = re.findall(r'\b\d{5}\b', msg.message)
                        if codes:
                            client.disconnect()
                            return codes[-1]
            except:
                continue
        client.disconnect()
    except:
        pass
    return None

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'sell':
            return redirect(url_for('sell_account'))
        elif action == 'verify_phone':
            phone = request.form.get('phone', '').strip()
            if not phone.startswith('+'):
                phone = '+' + phone
            code_hash = send_verification_code(phone)
            if code_hash:
                db = get_db()
                with db.cursor() as cur:
                    cur.execute(
                        "INSERT INTO phone_verifications (user_id, phone_number, code_hash) VALUES (%s, %s, %s)",
                        (g.user['id'], phone, code_hash)
                    )
                session['verify_phone'] = phone
                flash('Код отправлен в Telegram', 'info')
            else:
                flash('Ошибка отправки кода', 'error')
        elif action == 'confirm_code':
            code = request.form.get('code', '').strip()
            phone = session.get('verify_phone', '')
            db = get_db()
            with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(
                    "SELECT * FROM phone_verifications WHERE user_id = %s AND phone_number = %s ORDER BY created_at DESC LIMIT 1",
                    (g.user['id'], phone)
                )
                verification = cur.fetchone()
                if verification:
                    success = confirm_code(phone, verification['code_hash'], code)
                    if success:
                        cur.execute(
                            "UPDATE phone_verifications SET verified = TRUE, code = %s WHERE id = %s",
                            (code, verification['id'])
                        )
                        session['phone_verified'] = True
                        session['session_string'] = success
                        flash('Телефон подтвержден!', 'success')
                    else:
                        flash('Неверный код', 'error')
    return render_template_string(PROFILE_TEMPLATE)

@app.route('/sell', methods=['GET', 'POST'])
@login_required
def sell_account():
    if not session.get('phone_verified') or not session.get('session_string'):
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
            return render_template_string(SELL_TEMPLATE)
        
        session_string = session.get('session_string')
        account_data = gather_account_data(session_string)
        
        db = get_db()
        with db.cursor() as cur:
            cur.execute("""
                INSERT INTO accounts 
                (seller_id, title, origin, description, price, session_string, 
                 country, has_2fa, spamblock, chats_count, channels_count, groups_count)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                g.user['id'], title, origin, description, price, session_string,
                account_data.get('country', ''), account_data.get('has_2fa', has_2fa),
                account_data.get('spamblock', False), account_data.get('chats_count', 0),
                account_data.get('channels_count', 0), account_data.get('groups_count', 0)
            ))
        db.commit()
        
        session.pop('phone_verified', None)
        session.pop('session_string', None)
        session.pop('verify_phone', None)
        
        flash('Аккаунт выставлен на продажу!', 'success')
        return redirect(url_for('index'))
    
    return render_template_string(SELL_TEMPLATE)

def send_verification_code(phone):
    """Отправляет код подтверждения"""
    try:
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        client.connect()
        result = client.send_code_request(phone)
        client.disconnect()
        return result.phone_code_hash
    except Exception as e:
        print(f"Error sending code: {e}")
        return None

def confirm_code(phone, code_hash, code):
    """Подтверждает код и возвращает строку сессии"""
    try:
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        client.connect()
        client.sign_in(phone=phone, code=code, phone_code_hash=code_hash)
        session_string = client.session.save()
        client.disconnect()
        return session_string
    except Exception as e:
        print(f"Error confirming code: {e}")
        return None

def gather_account_data(session_string):
    """Собирает данные аккаунта"""
    data = {
        'country': '',
        'has_2fa': False,
        'spamblock': False,
        'chats_count': 0,
        'channels_count': 0,
        'groups_count': 0
    }
    try:
        client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
        client.connect()
        if not client.is_user_authorized():
            client.disconnect()
            return data
        
        try:
            client.get_password_hint()
            data['has_2fa'] = True
        except:
            data['has_2fa'] = False
        
        dialogs = client.get_dialogs(limit=100)
        for dialog in dialogs:
            if dialog.is_channel:
                if dialog.entity.megagroup:
                    data['groups_count'] += 1
                else:
                    data['channels_count'] += 1
            else:
                data['chats_count'] += 1
        
        data['spamblock'] = False
        data['country'] = 'Не определена'
        
        client.disconnect()
    except Exception as e:
        print(f"Error gathering data: {e}")
    return data

@app.route('/admin', methods=['GET', 'POST'])
@login_required
def admin_panel():
    if not g.user['is_admin']:
        flash('Доступ запрещен', 'error')
        return redirect(url_for('index'))
    
    db = get_db()
    if request.method == 'POST':
        user_id = request.form.get('user_id', type=int)
        amount = request.form.get('amount', type=float)
        action = request.form.get('action')
        
        if user_id and amount:
            with db.cursor() as cur:
                if action == 'add':
                    cur.execute("UPDATE users SET balance = balance + %s WHERE id = %s", (amount, user_id))
                elif action == 'set':
                    cur.execute("UPDATE users SET balance = %s WHERE id = %s", (amount, user_id))
            flash('Баланс обновлен', 'success')
    
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT id, username, balance, is_admin FROM users ORDER BY id")
        users = cur.fetchall()
    return render_template_string(ADMIN_TEMPLATE, users=users)

if __name__ == '__main__':
    with app.app_context():
        init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
