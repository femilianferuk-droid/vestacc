import os
import re
import asyncio
import logging
from datetime import datetime, timezone
from functools import wraps

import bcrypt
import psycopg2
import psycopg2.extras
from flask import Flask, render_template_string, request, redirect, url_for, session, flash, jsonify
from telethon import TelegramClient, errors
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.types import InputPeerEmpty
from telethon.sessions import StringSession

# --- Инициализация Flask ---
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'super-secret-key-change-in-prod-1234567890')

# --- Конфигурация ---
DB_URL = "postgresql://bothost_db_3092f9da4312:yvzBra5xN_j2a_dafFbpHStZAVH7HiMuzJ2iCwDX-5w@node1.pghost.ru:15796/bothost_db_3092f9da4312"
API_ID = 32480523
API_HASH = "147839735c9fa4e83451209e9b55cfc5"
ADMIN_USERNAME = "vestnik"
ADMIN_PASSWORD = "5533789q"
COMMISSION_RATE = 0.05

# --- Настройка логирования ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Хелпер для работы с БД ---
def get_db_connection():
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    return conn

def init_db():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    balance DECIMAL DEFAULT 0,
                    is_admin BOOLEAN DEFAULT FALSE
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id SERIAL PRIMARY KEY,
                    seller_id INTEGER REFERENCES users(id),
                    title TEXT,
                    origin TEXT,
                    description TEXT,
                    price DECIMAL,
                    phone TEXT,
                    country TEXT,
                    has_2fa BOOLEAN DEFAULT FALSE,
                    two_fa_password TEXT,
                    session_string TEXT,
                    spamblock BOOLEAN,
                    chats_count INTEGER,
                    channels_count INTEGER,
                    groups_count INTEGER,
                    is_valid BOOLEAN DEFAULT TRUE,
                    is_sold BOOLEAN DEFAULT FALSE,
                    buyer_id INTEGER REFERENCES users(id),
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS purchases (
                    id SERIAL PRIMARY KEY,
                    account_id INTEGER REFERENCES accounts(id),
                    buyer_id INTEGER REFERENCES users(id),
                    price DECIMAL,
                    commission DECIMAL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            try:
                hashed_pw = bcrypt.hashpw(ADMIN_PASSWORD.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                cur.execute(
                    "INSERT INTO users (username, password_hash, is_admin, balance) VALUES (%s, %s, TRUE, 0) ON CONFLICT (username) DO NOTHING;",
                    (ADMIN_USERNAME, hashed_pw))
            except Exception as e:
                logger.error(f"Error creating admin: {e}")

# --- Telethon helpers ---
async def create_client_from_session(session_string=None):
    if session_string:
        client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
    else:
        client = TelegramClient(StringSession(), API_ID, API_HASH)
    return client

async def check_session_validity(session_string):
    client = await create_client_from_session(session_string)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return False
        await client.get_me()
        return True
    except Exception:
        return False
    finally:
        await client.disconnect()

async def get_dialogs_count(session_string):
    client = await create_client_from_session(session_string)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise Exception("Session is not authorized")
        chats_count = 0
        channels_count = 0
        groups_count = 0
        result = await client(GetDialogsRequest(
            offset_date=None, offset_id=0, offset_peer=InputPeerEmpty(), limit=100, hash=0
        ))
        for dialog in result.dialogs:
            if dialog.is_user:
                chats_count += 1
            elif dialog.is_channel:
                if dialog.is_group:
                    groups_count += 1
                else:
                    channels_count += 1
        return chats_count, channels_count, groups_count
    finally:
        await client.disconnect()

async def check_spamblock(session_string):
    client = await create_client_from_session(session_string)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise Exception("Session is not authorized")
        await client.send_message('spambot', '/start')
        await asyncio.sleep(2)
        messages = await client.get_messages('spambot', limit=3)
        for msg in messages:
            if msg.text and ("account is limited" in msg.text.lower() or
                             "спам-блок" in msg.text.lower() or
                             "temporarily limited" in msg.text.lower()):
                return True
        return False
    except Exception as e:
        logger.warning(f"Spamblock check error: {e}")
        return None
    finally:
        await client.disconnect()

def get_country_by_phone(phone):
    codes_to_country = {
        '7': 'Россия', '380': 'Украина', '1': 'США', '44': 'Великобритания',
        '998': 'Узбекистан', '77': 'Казахстан', '375': 'Беларусь',
    }
    for code, country in codes_to_country.items():
        if phone.startswith(code):
            return country
    return "Неизвестно"

def get_code_from_message(message):
    match = re.search(r'\b(\d{5,6})\b', message)
    return match.group(1) if match else None

# --- Декораторы ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Пожалуйста, войдите в систему.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Пожалуйста, войдите в систему.', 'warning')
            return redirect(url_for('login'))
        if not session.get('is_admin'):
            flash('Доступ запрещён.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# --- HTML-шаблоны (как строки) ---
BASE_HTML = '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Vest Accs - Маркетплейс Telegram аккаунтов</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { padding-top: 20px; background-color: #f8f9fa; }
        .card { margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .navbar { margin-bottom: 30px; }
        .flash-messages { margin-bottom: 20px; }
    </style>
</head>
<body>
    <div class="container">
        <nav class="navbar navbar-expand-lg navbar-light bg-light rounded">
            <div class="container-fluid">
                <a class="navbar-brand" href="/">Vest Accs</a>
                <div class="d-flex">
                    {% if user %}
                        <span class="navbar-text me-3">Баланс: {{ "%.2f"|format(user.balance) }} ₽ <a href="/top-up" class="btn btn-sm btn-success">+</a></span>
                        <a href="/sell" class="btn btn-outline-primary me-2">Продать</a>
                        <a href="/my-purchases" class="btn btn-outline-secondary me-2">Мои покупки</a>
                        {% if session.get('is_admin') %}
                            <a href="/admin" class="btn btn-outline-warning me-2">Админ</a>
                        {% endif %}
                        <a href="/logout" class="btn btn-outline-danger">Выйти</a>
                    {% else %}
                        <a href="/login" class="btn btn-outline-primary me-2">Войти</a>
                        <a href="/register" class="btn btn-outline-success">Регистрация</a>
                    {% endif %}
                </div>
            </div>
        </nav>
        <div class="flash-messages">
            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="alert alert-{{ category }} alert-dismissible fade show" role="alert">
                            {{ message }}
                            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                        </div>
                    {% endfor %}
                {% endif %}
            {% endwith %}
        </div>
        {% block content %}{% endblock %}
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>'''

INDEX_TEMPLATE = BASE_HTML.replace('{% block content %}{% endblock %}', '''{% block content %}
{% if user %}
    <h2>Доступные аккаунты</h2>
    <button class="btn btn-secondary mb-3" type="button" data-bs-toggle="collapse" data-bs-target="#filterMenu">Фильтры</button>
    <div class="collapse mb-4" id="filterMenu">
        <div class="card card-body">
            <form method="GET" action="/">
                <div class="row">
                    <div class="col-md-3"><input class="form-control" name="search" placeholder="Поиск по названию"></div>
                    <div class="col-md-2"><input class="form-control" name="country" placeholder="Страна"></div>
                    <div class="col-md-2">
                        <select class="form-control" name="origin">
                            <option value="">Происхождение</option>
                            <option>авторег</option><option>саморег</option><option>фишинг</option><option>стилер</option>
                        </select>
                    </div>
                    <div class="col-md-1"><label><input type="checkbox" name="2fa"> 2FA</label></div>
                    <div class="col-md-1"><label><input type="checkbox" name="spamblock"> Спамблок</label></div>
                    <div class="col-md-1"><input class="form-control" name="chats_min" placeholder="Чаты от"></div>
                    <div class="col-md-1"><input class="form-control" name="chats_max" placeholder="до"></div>
                    <div class="col-md-1"><button type="submit" class="btn btn-primary">Фильтр</button></div>
                </div>
            </form>
        </div>
    </div>
    <div class="row">
        {% if accounts %}
            {% for acc in accounts %}
                <div class="col-md-4">
                    <div class="card">
                        <div class="card-body">
                            <h5 class="card-title">{{ acc.title }}</h5>
                            <p class="card-text">
                                <strong>Страна:</strong> {{ acc.country or '?' }}<br>
                                <strong>Происхождение:</strong> {{ acc.origin }}<br>
                                <strong>2FA:</strong> {{ 'Да' if acc.has_2fa else 'Нет' }}<br>
                                <strong>Спамблок:</strong> {{ 'Да' if acc.spamblock else 'Нет' }}<br>
                                <strong>Цена:</strong> {{ "%.2f"|format(acc.price) }} ₽
                            </p>
                            <a href="/account/{{ acc.id }}" class="btn btn-primary">Подробнее</a>
                        </div>
                    </div>
                </div>
            {% endfor %}
        {% else %}
            <p>Нет доступных аккаунтов.</p>
        {% endif %}
    </div>
{% else %}
    <div class="jumbotron p-5 bg-light rounded-3">
        <h1 class="display-4">Vest Accs</h1>
        <p class="lead">Маркетплейс Telegram аккаунтов. Войдите или зарегистрируйтесь.</p>
    </div>
{% endif %}
{% endblock %}''')

LOGIN_TEMPLATE = BASE_HTML.replace('{% block content %}{% endblock %}', '''{% block content %}
<h2>Вход</h2>
<form method="POST">
    <div class="mb-3"><input class="form-control" name="username" placeholder="Логин" required></div>
    <div class="mb-3"><input class="form-control" name="password" type="password" placeholder="Пароль" required></div>
    <button class="btn btn-primary">Войти</button>
</form>
{% endblock %}''')

REGISTER_TEMPLATE = BASE_HTML.replace('{% block content %}{% endblock %}', '''{% block content %}
<h2>Регистрация</h2>
<form method="POST">
    <div class="mb-3"><input class="form-control" name="username" placeholder="Логин" required></div>
    <div class="mb-3"><input class="form-control" name="password" type="password" placeholder="Пароль" required></div>
    <button class="btn btn-success">Зарегистрироваться</button>
</form>
{% endblock %}''')

ACCOUNT_DETAIL_TEMPLATE = BASE_HTML.replace('{% block content %}{% endblock %}', '''{% block content %}
{% if account %}
    <h2>{{ account.title }}</h2>
    <p><strong>Страна:</strong> {{ account.country or '?' }}</p>
    <p><strong>Происхождение:</strong> {{ account.origin }}</p>
    <p><strong>2FA:</strong> {{ 'Да' if account.has_2fa else 'Нет' }}</p>
    <p><strong>Спамблок:</strong> {{ 'Да' if account.spamblock else 'Нет' }}</p>
    <p><strong>Чаты:</strong> {{ account.chats_count }}, <strong>Каналы:</strong> {{ account.channels_count }}, <strong>Группы:</strong> {{ account.groups_count }}</p>
    <p><strong>Описание:</strong> {{ account.description }}</p>
    <p><strong>Цена:</strong> {{ "%.2f"|format(account.price) }} ₽</p>
    <button class="btn btn-info mb-2" onclick="checkValid({{ account.id }})">Проверить на Валид</button>
    <form method="POST" action="/account/{{ account.id }}/buy" style="display:inline;">
        <button class="btn btn-success">Купить</button>
    </form>
    <p id="validResult" class="mt-2"></p>
{% else %}
    <p>Аккаунт не найден.</p>
{% endif %}
<script>
function checkValid(id) {
    fetch('/account/' + id + '/check-valid', { method: 'POST' })
        .then(r => r.json())
        .then(d => document.getElementById('validResult').innerText = d.message);
}
</script>
{% endblock %}''')

SELL_FORM_TEMPLATE = BASE_HTML.replace('{% block content %}{% endblock %}', '''{% block content %}
<h2>Выставить на продажу</h2>
<form method="POST">
    <div class="mb-3"><input class="form-control" name="title" placeholder="Название" required></div>
    <div class="mb-3">
        <select class="form-control" name="origin" required>
            <option value="">Происхождение</option>
            <option>авторег</option><option>саморег</option><option>фишинг</option><option>стилер</option>
        </select>
    </div>
    <div class="mb-3"><textarea class="form-control" name="description" placeholder="Описание"></textarea></div>
    <div class="mb-3"><input class="form-control" name="price" type="number" step="0.01" placeholder="Цена" required></div>
    <div class="mb-3"><input class="form-control" name="phone" placeholder="Номер телефона" required></div>
    <div class="mb-3"><input class="form-control" name="two_fa_password" placeholder="Пароль 2FA (если есть)"></div>
    <button class="btn btn-primary">Далее</button>
</form>
{% endblock %}''')

SELL_CONFIRM_TEMPLATE = BASE_HTML.replace('{% block content %}{% endblock %}', '''{% block content %}
<h2>Подтверждение кода</h2>
<p>Код отправлен на номер <strong>{{ phone }}</strong></p>
<form method="POST" action="/sell/verify-code">
    <div class="mb-3"><input class="form-control" name="code" placeholder="Код подтверждения" required></div>
    <button class="btn btn-primary">Подтвердить</button>
</form>
{% endblock %}''')

MY_PURCHASES_TEMPLATE = BASE_HTML.replace('{% block content %}{% endblock %}', '''{% block content %}
<h2>Мои покупки</h2>
{% if purchases %}
    <table class="table">
        <tr><th>Аккаунт</th><th>Цена</th><th>Дата</th><th>Действия</th></tr>
        {% for p in purchases %}
        <tr>
            <td>{{ p.title }} ({{ p.phone }})</td>
            <td>{{ "%.2f"|format(p.final_price) }} ₽</td>
            <td>{{ p.created_at.strftime('%d.%m.%Y %H:%M') }}</td>
            <td>
                <button class="btn btn-sm btn-info" onclick="getCode({{ p.account_id }})">Получить код</button>
                <span id="code-{{ p.account_id }}"></span>
            </td>
        </tr>
        {% endfor %}
    </table>
{% else %}
    <p>Нет покупок.</p>
{% endif %}
<script>
function getCode(id) {
    fetch('/account/' + id + '/get-code', { method: 'POST' })
        .then(r => r.json())
        .then(d => {
            if (d.status === 'success') document.getElementById('code-' + id).innerText = 'Код: ' + d.code;
            else alert(d.message);
        });
}
</script>
{% endblock %}''')

ADMIN_TEMPLATE = BASE_HTML.replace('{% block content %}{% endblock %}', '''{% block content %}
<h2>Админ-панель</h2>
<table class="table">
    <tr><th>ID</th><th>Логин</th><th>Баланс</th><th>Админ</th><th>Изменить баланс</th></tr>
    {% for u in users %}
    <tr>
        <td>{{ u.id }}</td>
        <td>{{ u.username }}</td>
        <td>{{ "%.2f"|format(u.balance) }} ₽</td>
        <td>{{ 'Да' if u.is_admin else 'Нет' }}</td>
        <td>
            <form method="POST" action="/admin/update-balance" style="display:inline;">
                <input type="hidden" name="user_id" value="{{ u.id }}">
                <input type="number" step="0.01" name="amount" placeholder="Сумма" required>
                <button class="btn btn-sm btn-warning">Обновить</button>
            </form>
        </td>
    </tr>
    {% endfor %}
</table>
{% endblock %}''')

TOP_UP_TEMPLATE = BASE_HTML.replace('{% block content %}{% endblock %}', '''{% block content %}
<h2>Пополнение баланса</h2>
<div class="alert alert-info">Функция пополнения баланса находится в разработке.</div>
{% endblock %}''')

# --- Маршруты ---
@app.route('/')
def index():
    if 'user_id' not in session:
        return render_template_string(INDEX_TEMPLATE, user=None, accounts=[])
    user_id = session['user_id']
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT balance FROM users WHERE id = %s", (user_id,))
            user = cur.fetchone()
            query = "SELECT * FROM accounts WHERE is_sold = FALSE AND is_valid = TRUE AND status = 'active'"
            params = []
            # Фильтры
            search = request.args.get('search')
            if search:
                query += " AND title ILIKE %s"
                params.append(f'%{search}%')
            origin = request.args.get('origin')
            if origin:
                query += " AND origin = %s"
                params.append(origin)
            has_2fa = request.args.get('2fa')
            if has_2fa:
                query += " AND has_2fa = TRUE"
            spamblock = request.args.get('spamblock')
            if spamblock:
                query += " AND spamblock = TRUE"
            query += " ORDER BY created_at DESC"
            cur.execute(query, params)
            accounts = cur.fetchall()
    return render_template_string(INDEX_TEMPLATE, user=user, accounts=accounts)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if not username or not password:
            flash('Логин и пароль обязательны.', 'danger')
            return redirect(url_for('register'))
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT id FROM users WHERE username = %s", (username,))
                if cur.fetchone():
                    flash('Пользователь уже существует.', 'danger')
                    return redirect(url_for('register'))
                hashed_pw = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                cur.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s) RETURNING id", (username, hashed_pw))
                user_id = cur.fetchone()['id']
                session['user_id'] = user_id
                session['username'] = username
                session['is_admin'] = False
                flash('Регистрация успешна!', 'success')
                return redirect(url_for('index'))
    return render_template_string(REGISTER_TEMPLATE, user=None)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM users WHERE username = %s", (username,))
                user = cur.fetchone()
                if user and bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
                    session['user_id'] = user['id']
                    session['username'] = user['username']
                    session['is_admin'] = user['is_admin']
                    flash('Вход выполнен!', 'success')
                    return redirect(url_for('index'))
                flash('Неверный логин или пароль.', 'danger')
    return render_template_string(LOGIN_TEMPLATE, user=None)

@app.route('/logout')
def logout():
    session.clear()
    flash('Вы вышли.', 'info')
    return redirect(url_for('index'))

@app.route('/account/<int:account_id>')
@login_required
def view_account(account_id):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM accounts WHERE id = %s", (account_id,))
            account = cur.fetchone()
    return render_template_string(ACCOUNT_DETAIL_TEMPLATE, user={'balance': 0}, account=account)

@app.route('/account/<int:account_id>/check-valid', methods=['POST'])
@login_required
def check_valid(account_id):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT session_string FROM accounts WHERE id = %s", (account_id,))
            account = cur.fetchone()
            if not account or not account['session_string']:
                return jsonify({'status': 'error', 'message': 'Сессия не найдена'})
            is_valid = asyncio.run(check_session_validity(account['session_string']))
            if not is_valid:
                cur.execute("UPDATE accounts SET is_valid = FALSE, status = 'invalid', is_sold = TRUE WHERE id = %s", (account_id,))
                return jsonify({'status': 'invalid', 'message': 'Аккаунт невалиден и снят с продажи'})
            return jsonify({'status': 'valid', 'message': 'Аккаунт валиден'})

@app.route('/account/<int:account_id>/buy', methods=['POST'])
@login_required
def buy_account(account_id):
    if session.get('is_admin'):
        flash('Администраторы не могут покупать.', 'warning')
        return redirect(url_for('view_account', account_id=account_id))
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM accounts WHERE id = %s AND is_sold = FALSE FOR UPDATE", (account_id,))
            account = cur.fetchone()
            if not account:
                flash('Аккаунт уже продан.', 'danger')
                return redirect(url_for('index'))
            buyer_id = session['user_id']
            if account['seller_id'] == buyer_id:
                flash('Нельзя купить свой аккаунт.', 'danger')
                return redirect(url_for('view_account', account_id=account_id))
            cur.execute("SELECT balance FROM users WHERE id = %s FOR UPDATE", (buyer_id,))
            buyer = cur.fetchone()
            price = float(account['price'])
            commission = price * COMMISSION_RATE
            total_cost = price + commission
            if buyer['balance'] < total_cost:
                flash(f'Недостаточно средств. Нужно {total_cost:.2f} ₽.', 'danger')
                return redirect(url_for('view_account', account_id=account_id))
            cur.execute("UPDATE users SET balance = balance - %s WHERE id = %s", (total_cost, buyer_id))
            cur.execute("UPDATE users SET balance = balance + %s WHERE id = %s", (price, account['seller_id']))
            cur.execute("UPDATE accounts SET is_sold = TRUE, buyer_id = %s, status = 'sold' WHERE id = %s", (buyer_id, account_id))
            cur.execute("INSERT INTO purchases (account_id, buyer_id, price, commission) VALUES (%s, %s, %s, %s)",
                        (account_id, buyer_id, price, commission))
            flash(f'Покупка успешна! Списано {total_cost:.2f} ₽.', 'success')
    return redirect(url_for('my_purchases'))

@app.route('/account/<int:account_id>/get-code', methods=['POST'])
@login_required
def get_code(account_id):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM accounts WHERE id = %s AND buyer_id = %s", (account_id, session['user_id']))
            purchase = cur.fetchone()
            if not purchase:
                return jsonify({'status': 'error', 'message': 'Не ваша покупка.'})
            if not purchase['session_string']:
                return jsonify({'status': 'error', 'message': 'Сессия не найдена.'})
            session_string = purchase['session_string']

            async def fetch_code():
                client = await create_client_from_session(session_string)
                try:
                    await client.connect()
                    if not await client.is_user_authorized():
                        return None, "Сессия не авторизована"
                    messages = []
                    async for dialog in client.iter_dialogs(limit=50):
                        if dialog.message and dialog.message.text:
                            messages.append(dialog.message)
                    if not messages:
                        return None, "Нет сообщений"
                    messages.sort(key=lambda m: m.date, reverse=True)
                    for msg in messages[:20]:
                        code = get_code_from_message(msg.text)
                        if code:
                            return code, None
                    return None, "Код не найден"
                except Exception as e:
                    return None, str(e)
                finally:
                    await client.disconnect()

            code, error = asyncio.run(fetch_code())
            if code:
                return jsonify({'status': 'success', 'code': code})
            return jsonify({'status': 'error', 'message': error or 'Код не найден'})

@app.route('/sell', methods=['GET', 'POST'])
@login_required
def sell_account():
    if request.method == 'POST':
        phone = request.form.get('phone')
        if not phone:
            flash('Введите номер.', 'danger')
            return redirect(url_for('sell_account'))
        session['sell_data'] = {
            'title': request.form.get('title'),
            'origin': request.form.get('origin'),
            'description': request.form.get('description'),
            'price': request.form.get('price'),
            'phone': phone,
            'two_fa_password': request.form.get('two_fa_password')
        }
        async def send_code():
            client = await create_client_from_session()
            try:
                await client.connect()
                result = await client.send_code_request(phone)
                return result.phone_code_hash
            except Exception as e:
                logger.error(f"Send code error: {e}")
                return None
            finally:
                await client.disconnect()
        phone_code_hash = asyncio.run(send_code())
        if phone_code_hash:
            session['phone_code_hash'] = phone_code_hash
            flash('Код отправлен.', 'info')
            return render_template_string(SELL_CONFIRM_TEMPLATE, user={'balance': 0}, phone=phone)
        else:
            flash('Ошибка отправки кода.', 'danger')
            return redirect(url_for('sell_account'))
    return render_template_string(SELL_FORM_TEMPLATE, user={'balance': 0})

@app.route('/sell/verify-code', methods=['POST'])
@login_required
def verify_code():
    code = request.form.get('code')
    if not code:
        flash('Введите код.', 'danger')
        return render_template_string(SELL_CONFIRM_TEMPLATE, user={'balance': 0}, phone=session.get('sell_data', {}).get('phone'))
    data = session.get('sell_data')
    phone_code_hash = session.get('phone_code_hash')
    if not data or not phone_code_hash:
        flash('Сессия истекла.', 'danger')
        return redirect(url_for('sell_account'))
    phone = data['phone']
    two_fa_pwd = data.get('two_fa_password')

    async def verify_and_collect():
        session_string = StringSession()
        client = TelegramClient(session_string, API_ID, API_HASH)
        try:
            await client.connect()
            try:
                await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
            except errors.SessionPasswordNeededError:
                if not two_fa_pwd:
                    raise Exception("Требуется пароль 2FA.")
                await client.sign_in(password=two_fa_pwd)
            if not await client.is_user_authorized():
                raise Exception("Не удалось авторизоваться.")
            country = get_country_by_phone(phone)
            has_2fa = bool(two_fa_pwd)
            spamblock = await check_spamblock(session_string.save())
            chats, channels, groups = await get_dialogs_count(session_string.save())
            return {
                'session_string': session_string.save(),
                'country': country,
                'has_2fa': has_2fa,
                'spamblock': spamblock,
                'chats_count': chats,
                'channels_count': channels,
                'groups_count': groups
            }
        finally:
            await client.disconnect()

    try:
        collected = asyncio.run(verify_and_collect())
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO accounts (seller_id, title, origin, description, price, phone, country, has_2fa, two_fa_password, session_string, spamblock, chats_count, channels_count, groups_count, status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active')
                """, (session['user_id'], data['title'], data['origin'], data['description'], data['price'], phone,
                      collected['country'], collected['has_2fa'], data.get('two_fa_password'), collected['session_string'],
                      collected['spamblock'], collected['chats_count'], collected['channels_count'], collected['groups_count']))
        session.pop('sell_data', None)
        session.pop('phone_code_hash', None)
        flash('Аккаунт опубликован!', 'success')
        return redirect(url_for('index'))
    except Exception as e:
        flash(f'Ошибка: {str(e)}', 'danger')
        return redirect(url_for('sell_account'))

@app.route('/my-purchases')
@login_required
def my_purchases():
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""SELECT p.*, a.phone, a.title, p.price as final_price FROM purchases p JOIN accounts a ON p.account_id = a.id WHERE p.buyer_id = %s ORDER BY p.created_at DESC""", (session['user_id'],))
            purchases = cur.fetchall()
    return render_template_string(MY_PURCHASES_TEMPLATE, user={'balance': 0}, purchases=purchases)

@app.route('/admin')
@admin_required
def admin_panel():
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id, username, balance, is_admin FROM users ORDER BY id")
            users = cur.fetchall()
    return render_template_string(ADMIN_TEMPLATE, user={'balance': 0}, users=users)

@app.route('/admin/update-balance', methods=['POST'])
@admin_required
def update_balance():
    user_id = request.form.get('user_id')
    amount = request.form.get('amount')
    if not user_id or amount is None:
        flash('Неверные данные.', 'danger')
        return redirect(url_for('admin_panel'))
    try:
        amount = float(amount)
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE users SET balance = %s WHERE id = %s", (amount, user_id))
                flash(f'Баланс обновлён.', 'success')
    except ValueError:
        flash('Сумма должна быть числом.', 'danger')
    return redirect(url_for('admin_panel'))

@app.route('/top-up')
@login_required
def top_up():
    return render_template_string(TOP_UP_TEMPLATE, user={'balance': 0})

# --- Инициализация ---
with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
