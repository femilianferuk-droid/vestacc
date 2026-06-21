import os
import re
import asyncio
import traceback
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, render_template_string, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

app = Flask(__name__)
app.secret_key = "vest_accs_super_secret_key"

# Подключение к вашей базе данных PostgreSQL
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://bothost_db_3092f9da4312:yvzBra5xN_j2a_dafFbpHStZAVH7HiMuzJ2iCwDX-5w@node1.pghost.ru:15796/bothost_db_3092f9da4312'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Telegram API Константы
API_ID = 32480523
API_HASH = '147839735c9fa4e83451209e9b55cfc5'

# Глобальное хранилище для активных сессий авторизации продавцов (в памяти)
pending_auths = {}

# --- ВСТРОЕННЫЙ ДЕБАГГЕР (Выведет ошибку на экран вместо 500 ошибки хостинга) ---
@app.errorhandler(Exception)
def handle_exception(e):
    """Перехватывает абсолютно любой крэш сервера и показывает его лог на странице"""
    tb = traceback.format_exc()
    return f"""
    <!DOCTYPE html>
    <html>
    <head><title>Vest Accs - Ошибка Сервера</title></head>
    <body style="background: #0b1329; color: #ff5555; font-family: monospace; padding: 30px; line-height: 1.5;">
        <div style="max-w: 1000px; margin: 0 auto; background: #1c2541; padding: 25px; border-radius: 12px; border: 1px solid #ff3333; box-shadow: 0 10px 30px rgba(0,0,0,0.5);">
            <h2 style="margin-top: 0; color: #f8fafc;">⚠️ Обнаружена внутренняя ошибка Vest Accs</h2>
            <p style="color: #cbd5e1;">Ниже приведен технический лог крэша. Скопируйте его целиком:</p>
            <pre style="background: #0b1329; color: #a7f3d0; padding: 15px; border-radius: 8px; overflow-x: auto; white-space: pre-wrap; border: 1px solid #334155;">{tb}</pre>
            <p style="color: #94a3b8; font-size: 13px; margin-bottom: 0;">* После исправления этой ошибки дебаггер можно будет отключить.</p>
        </div>
    </body>
    </html>
    """, 500

# --- Модели Базы Данных ---

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    balance = db.Column(db.Float, default=0.0)
    is_admin = db.Column(db.Boolean, default=False)

class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    seller_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    origin = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    price = db.Column(db.Float, nullable=False)
    phone = db.Column(db.String(50), nullable=False)
    session_string = db.Column(db.Text, nullable=False)
    
    country = db.Column(db.String(100), default="Неизвестно")
    has_2fa = db.Column(db.Boolean, default=False)
    has_spamblock = db.Column(db.Boolean, default=False)
    chats_count = db.Column(db.Integer, default=0)
    channels_count = db.Column(db.Integer, default=0)
    groups_count = db.Column(db.Integer, default=0)
    
    status = db.Column(db.String(50), default="available")

class Purchase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    price_paid = db.Column(db.Float, nullable=False)
    
    account = db.relationship('Account', backref='purchases')

# Инициализация БД в контексте приложения (для WSGI серверов)
with app.app_context():
    db.create_all()

# --- Безопасный изолятор асинхронности для Flask ---

def run_async(coro):
    """Запускает корутину в изолированном выделенном потоке со своим Event Loop.
    Полностью убирает ошибку 'cannot be called from a running event loop' на хостингах."""
    def target(c):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(c)
        finally:
            loop.close()
            
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(target, coro).result()

def get_country_code(phone):
    if phone.startswith('+7') or phone.startswith('7'): return 'Россия / Казахстан'
    if phone.startswith('+380') or phone.startswith('380'): return 'Украина'
    if phone.startswith('+375') or phone.startswith('375'): return 'Беларусь'
    if phone.startswith('+1') or phone.startswith('1'): return 'США / Канада'
    return 'Другая страна'

# --- HTML Шаблоны (Tailwind CSS) ---

BASE_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Vest Accs - Маркетплейс Telegram</title>
    <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
    <style> body { background-color: #0b1329; color: #f8fafc; } </style>
</head>
<body class="min-h-screen flex flex-col font-sans">
    <nav class="bg-[#1c2541] border-b border-slate-700 px-6 py-4 flex justify-between items-center shadow-lg">
        <a href="/" class="text-2xl font-black tracking-wider text-indigo-400">VEST <span class="text-white">ACCS</span></a>
        <div class="flex items-center gap-4">
            {% if session.get('user_id') %}
                <div class="flex items-center bg-[#111827] rounded-full px-4 py-1.5 border border-indigo-500/30">
                    <span class="text-sm text-slate-400 mr-2">Баланс:</span>
                    <span class="font-bold text-emerald-400">{{ "%.2f"|format(user_balance) }} ₽</span>
                    <a href="{{ url_for('topup') }}" class="ml-3 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold px-2 py-1 rounded-full">+</a>
                </div>
                <a href="{{ url_for('profile') }}" class="bg-slate-800 hover:bg-slate-700 px-4 py-2 rounded-lg text-sm font-semibold transition-all">Профиль</a>
                <a href="{{ url_for('logout') }}" class="text-sm text-slate-400 hover:text-red-400 transition-all">Выйти</a>
            {% else %}
                <a href="{{ url_for('login') }}" class="bg-slate-800 hover:bg-slate-700 px-4 py-2 rounded-lg text-sm font-semibold transition-all">Войти</a>
                <a href="{{ url_for('register') }}" class="bg-indigo-600 hover:bg-indigo-500 px-4 py-2 rounded-lg text-sm font-semibold transition-all shadow-md shadow-indigo-600/20">Регистрация</a>
            {% endif %}
        </div>
    </nav>

    {% with messages = get_flashed_messages(with_categories=true) %}
      {% if messages %}
        <div class="max-w-7xl mx-auto w-full px-6 mt-4">
            {% for category, message in messages %}
                <div class="p-4 rounded-lg {% if category == 'error' %}bg-red-500/20 border border-red-500 text-red-200{% else %}bg-emerald-500/20 border border-emerald-500 text-emerald-200{% endif %} text-sm">
                    {{ message }}
                </div>
            {% endfor %}
        </div>
      {% endif %}
    {% endwith %}

    <main class="flex-grow max-w-7xl w-full mx-auto p-6">
        {% block content %}{% endblock %}
    </main>

    <footer class="bg-[#1c2541]/50 text-center py-4 text-xs text-slate-500 border-t border-slate-800">
        &copy; 2026 Vest Accs. Все права защищены. Комиссия площадки 5%.
    </footer>
</body>
</html>
"""

MAIN_PAGE = """
{% extends "base" %}
{% block content %}
<div class="flex flex-col gap-6">
    <div class="bg-[#1c2541] rounded-xl p-5 border border-slate-700 shadow-xl">
        <div class="flex justify-between items-center">
            <h2 class="text-lg font-bold tracking-wide">Каталог аккаунтов</h2>
            <button onclick="document.getElementById('filters-menu').classList.toggle('hidden')" class="bg-indigo-600/20 hover:bg-indigo-600/40 text-indigo-400 border border-indigo-500/30 px-4 py-2 rounded-lg font-semibold text-sm cursor-pointer transition-all">
                🎛️ Фильтры
            </button>
        </div>

        <form method="GET" id="filters-menu" class="hidden mt-5 grid grid-cols-1 md:grid-cols-4 gap-4 pt-4 border-t border-slate-700/50">
            <div>
                <label class="block text-xs text-slate-400 mb-1">Поиск по заголовку</label>
                <input type="text" name="title" value="{{ request.args.get('title', '') }}" class="w-full bg-[#0b1329] border border-slate-600 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-indigo-500">
            </div>
            <div>
                <label class="block text-xs text-slate-400 mb-1">Страна</label>
                <input type="text" name="country" value="{{ request.args.get('country', '') }}" class="w-full bg-[#0b1329] border border-slate-600 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-indigo-500">
            </div>
            <div>
                <label class="block text-xs text-slate-400 mb-1">Происхождение</label>
                <input type="text" name="origin" value="{{ request.args.get('origin', '') }}" class="w-full bg-[#0b1329] border border-slate-600 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-indigo-500">
            </div>
            <div>
                <label class="block text-xs text-slate-400 mb-1">Наличие 2FA</label>
                <select name="has_2fa" class="w-full bg-[#0b1329] border border-slate-600 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-indigo-500">
                    <option value="">Любое</option>
                    <option value="1" {% if request.args.get('has_2fa') == '1' %}selected{% endif %}>Да</option>
                    <option value="0" {% if request.args.get('has_2fa') == '0' %}selected{% endif %}>Нет</option>
                </select>
            </div>
            <div>
                <label class="block text-xs text-slate-400 mb-1">Спамблок</label>
                <select name="has_spamblock" class="w-full bg-[#0b1329] border border-slate-600 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-indigo-500">
                    <option value="">Любое</option>
                    <option value="0" {% if request.args.get('has_spamblock') == '0' %}selected{% endif %}>Отсутствует</option>
                    <option value="1" {% if request.args.get('has_spamblock') == '1' %}selected{% endif %}>Есть</option>
                </select>
            </div>
            <div>
                <label class="block text-xs text-slate-400 mb-1">Мин. количество чатов</label>
                <input type="number" name="min_chats" value="{{ request.args.get('min_chats', '') }}" class="w-full bg-[#0b1329] border border-slate-600 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-indigo-500">
            </div>
            <div>
                <label class="block text-xs text-slate-400 mb-1">Мин. каналов</label>
                <input type="number" name="min_channels" value="{{ request.args.get('min_channels', '') }}" class="w-full bg-[#0b1329] border border-slate-600 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-indigo-500">
            </div>
            <div class="flex items-end gap-2">
                <div class="w-full">
                    <label class="block text-xs text-slate-400 mb-1">Мин. групп</label>
                    <input type="number" name="min_groups" value="{{ request.args.get('min_groups', '') }}" class="w-full bg-[#0b1329] border border-slate-600 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-indigo-500">
                </div>
                <button type="submit" class="bg-indigo-600 hover:bg-indigo-500 text-white font-bold px-4 py-2 rounded-lg text-sm h-[38px] transition-all">Применить</button>
            </div>
        </form>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
        {% for acc in accounts %}
        <div class="bg-[#1c2541] rounded-xl border border-slate-700 p-5 flex flex-col justify-between hover:scale-[1.02] transition-all shadow-lg">
            <div>
                <div class="flex justify-between items-start mb-2">
                    <span class="text-xs font-bold px-2 py-1 bg-indigo-500/10 text-indigo-400 rounded border border-indigo-500/20">{{ acc.origin }}</span>
                    <span class="text-sm text-slate-400">🌍 {{ acc.country }}</span>
                </div>
                <h3 class="text-lg font-bold text-white mb-2">{{ acc.title }}</h3>
                <p class="text-xs text-slate-400 line-clamp-2 mb-4">{{ acc.description }}</p>
                
                <div class="grid grid-cols-3 gap-2 text-center text-xs bg-[#0b1329] p-2 rounded-lg border border-slate-800 mb-4">
                    <div><span class="block text-slate-400 font-medium">Чаты</span><span class="font-bold text-white">{{ acc.chats_count }}</span></div>
                    <div><span class="block text-slate-400 font-medium">Каналы</span><span class="font-bold text-white">{{ acc.channels_count }}</span></div>
                    <div><span class="block text-slate-400 font-medium">Группы</span><span class="font-bold text-white">{{ acc.groups_count }}</span></div>
                </div>
            </div>
            
            <div class="flex items-center justify-between mt-4 pt-4 border-t border-slate-700/50">
                <span class="text-xl font-black text-emerald-400">{{ acc.price }} ₽</span>
                
                <button 
                    data-id="{{ acc.id }}" data-title="{{ acc.title }}" data-origin="{{ acc.origin }}"
                    data-country="{{ acc.country }}" data-2fa="{{ acc.has_2fa }}" data-spam="{{ acc.has_spamblock }}"
                    data-price="{{ acc.price }}" data-desc="{{ acc.description }}"
                    onclick="openModal(this)" 
                    class="bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-bold px-4 py-2 rounded-lg transition-all cursor-pointer">
                    Посмотреть
                </button>
            </div>
        </div>
        {% else %}
        <div class="col-span-3 text-center py-12 text-slate-500">Аккаунты не найдены.</div>
        {% endfor %}
    </div>
</div>

<div id="product-modal" class="hidden fixed inset-0 bg-black/70 flex items-center justify-center p-4 z-50 backdrop-blur-sm">
    <div class="bg-[#1c2541] border border-slate-700 rounded-xl max-w-lg w-full p-6 relative">
        <button onclick="closeModal()" class="absolute top-4 right-4 text-slate-400 hover:text-white text-xl cursor-pointer">&times;</button>
        <h3 id="modal-title" class="text-xl font-bold mb-4 text-white"></h3>
        
        <div class="space-y-3 mb-6">
            <p class="text-sm text-slate-300" id="modal-desc"></p>
            <hr class="border-slate-700/50">
            <div class="grid grid-cols-2 gap-3 text-sm">
                <div><span class="text-slate-400">Происхождение:</span> <span id="modal-origin" class="font-semibold"></span></div>
                <div><span class="text-slate-400">Страна:</span> <span id="modal-country" class="font-semibold"></span></div>
                <div><span class="text-slate-400">Двухфакторка (2FA):</span> <span id="modal-2fa" class="font-semibold"></span></div>
                <div><span class="text-slate-400">Спамблок:</span> <span id="modal-spam" class="font-semibold"></span></div>
            </div>
        </div>

        <div class="flex items-center justify-between bg-[#0b1329] p-3 rounded-lg border border-slate-800 mb-6">
            <span class="text-sm text-slate-400">Стоимость:</span>
            <span id="modal-price" class="text-xl font-black text-emerald-400"></span>
        </div>

        <div class="flex gap-3">
            <button id="btn-validate" onclick="validateAccount()" class="w-1/2 bg-slate-800 hover:bg-slate-700 border border-slate-600 text-white font-bold py-2.5 rounded-lg text-sm transition-all cursor-pointer">
                Проверить на Валид
            </button>
            <form id="buy-form" method="POST" class="w-1/2">
                <button type="submit" class="w-full bg-emerald-600 hover:bg-emerald-500 text-white font-bold py-2.5 rounded-lg text-sm transition-all shadow-lg shadow-emerald-600/20 cursor-pointer">
                    Купить
                </button>
            </form>
        </div>
        <p id="validation-result" class="text-center text-xs mt-3 font-semibold"></p>
    </div>
</div>

<script>
    let currentAccountId = null;
    function openModal(btn) {
        currentAccountId = btn.getAttribute('data-id');
        document.getElementById('modal-title').innerText = btn.getAttribute('data-title');
        document.getElementById('modal-desc').innerText = btn.getAttribute('data-desc') || "Описание отсутствует.";
        document.getElementById('modal-origin').innerText = btn.getAttribute('data-origin');
        document.getElementById('modal-country').innerText = btn.getAttribute('data-country');
        document.getElementById('modal-2fa').innerText = btn.getAttribute('data-2fa') === 'True' ? 'Есть' : 'Нет';
        document.getElementById('modal-spam').innerText = btn.getAttribute('data-spam') === 'True' ? 'Есть' : 'Нет';
        document.getElementById('modal-price').innerText = btn.getAttribute('data-price') + ' ₽';
        document.getElementById('buy-form').action = '/buy/' + currentAccountId;
        document.getElementById('validation-result').innerText = '';
        document.getElementById('product-modal').classList.remove('hidden');
    }
    function closeModal() { document.getElementById('product-modal').classList.add('hidden'); }
    function validateAccount() {
        const resEl = document.getElementById('validation-result');
        resEl.innerText = "Проверяем статус...";
        resEl.className = "text-center text-xs mt-3 text-slate-400 animate-pulse";
        fetch('/check_valid/' + currentAccountId)
            .then(res => res.json())
            .then(data => {
                if(data.valid) {
                    resEl.innerText = "✓ Аккаунт полностью валиден!";
                    resEl.className = "text-center text-xs mt-3 text-emerald-400 font-bold";
                } else {
                    resEl.innerText = "✗ Аккаунт невалиден (Сессия закрыта).";
                    resEl.className = "text-center text-xs mt-3 text-red-400 font-bold";
                }
            });
    }
</script>
{% endblock %}
"""

PROFILE_PAGE = """
{% extends "base" %}
{% block content %}
<div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
    <div class="lg:col-span-1 flex flex-col gap-6">
        <div class="bg-[#1c2541] rounded-xl p-5 border border-slate-700 shadow-xl text-center">
            <div class="w-20 h-20 bg-indigo-600 rounded-full mx-auto flex items-center justify-center text-2xl font-black text-white mb-4 shadow-lg shadow-indigo-600/30">
                {{ user.username[0]|upper }}
            </div>
            <h2 class="text-xl font-bold">{{ user.username }}</h2>
            <p class="text-xs text-slate-400 mt-1">ID: {{ user.id }}</p>
            {% if user.is_admin %}
                <span class="inline-block bg-red-500/20 text-red-400 border border-red-500/30 rounded text-[10px] font-bold px-2 py-0.5 mt-2 uppercase">Администратор</span>
            {% endif %}
        </div>

        <div class="bg-[#1c2541] rounded-xl p-5 border border-slate-700 shadow-xl">
            <h3 class="text-base font-bold mb-4 pb-2 border-b border-slate-700/50">Выставить аккаунт</h3>
            
            {% if not session.get('auth_step') %}
            <form method="POST" action="{{ url_for('sell_step1') }}" class="space-y-3">
                <div>
                    <label class="block text-xs text-slate-400 mb-1">Название объявления</label>
                    <input type="text" name="title" required class="w-full bg-[#0b1329] border border-slate-600 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-indigo-500">
                </div>
                <div>
                    <label class="block text-xs text-slate-400 mb-1">Происхождение</label>
                    <input type="text" name="origin" placeholder="Авторег, Фишинг" required class="w-full bg-[#0b1329] border border-slate-600 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-indigo-500">
                </div>
                <div>
                    <label class="block text-xs text-slate-400 mb-1">Описание</label>
                    <textarea name="description" rows="2" class="w-full bg-[#0b1329] border border-slate-600 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-indigo-500"></textarea>
                </div>
                <div>
                    <label class="block text-xs text-slate-400 mb-1">Цена (в рублях)</label>
                    <input type="number" step="0.01" name="price" required class="w-full bg-[#0b1329] border border-slate-600 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-indigo-500">
                </div>
                <div>
                    <label class="block text-xs text-slate-400 mb-1">Номер телефона</label>
                    <input type="text" name="phone" placeholder="+79991234567" required class="w-full bg-[#0b1329] border border-slate-600 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-indigo-500">
                </div>
                <button type="submit" class="w-full bg-indigo-600 hover:bg-indigo-500 text-white font-bold py-2 rounded-lg text-sm transition-all cursor-pointer">
                    Отправить код подтверждения
                </button>
            </form>
            {% else %}
            <form method="POST" action="{{ url_for('sell_step2') }}" class="space-y-3">
                <p class="text-xs text-amber-400 font-semibold bg-amber-500/10 border border-amber-500/20 p-2 rounded">
                    Код отправлен на {{ session['auth_phone'] }}. Сбор статистики займет 5 секунд после входа.
                </p>
                <div>
                    <label class="block text-xs text-slate-400 mb-1">Код из Telegram</label>
                    <input type="text" name="code" required class="w-full bg-[#0b1329] border border-slate-600 rounded-lg p-2 text-sm text-white tracking-widest text-center font-bold focus:outline-none focus:border-indigo-500">
                </div>
                <div>
                    <label class="block text-xs text-slate-400 mb-1">Облачный пароль (2FA)</label>
                    <input type="password" name="password" placeholder="Пусто, если нет" class="w-full bg-[#0b1329] border border-slate-600 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-indigo-500">
                </div>
                <div class="flex gap-2">
                    <a href="{{ url_for('cancel_sell') }}" class="w-1/3 bg-slate-800 text-center hover:bg-slate-700 text-slate-300 font-bold py-2 rounded-lg text-sm transition-all">Отмена</a>
                    <button type="submit" class="w-2/3 bg-emerald-600 hover:bg-emerald-500 text-white font-bold py-2 rounded-lg text-sm transition-all cursor-pointer">
                        Подтвердить
                    </button>
                </div>
            </form>
            {% endif %}
        </div>
    </div>

    <div class="lg:col-span-2 flex flex-col gap-6">
        <div class="bg-[#1c2541] rounded-xl p-5 border border-slate-700 shadow-xl">
            <h3 class="text-base font-bold mb-4 pb-2 border-b border-slate-700/50">🛒 Мои покупки</h3>
            <div class="overflow-x-auto">
                <table class="w-full text-left text-sm text-slate-300">
                    <thead>
                        <tr class="text-slate-400 text-xs uppercase border-b border-slate-800">
                            <th class="py-2">Товар</th>
                            <th class="py-2">Номер телефона</th>
                            <th class="py-2 text-center">Действия</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-800">
                        {% for p in purchases %}
                        <tr>
                            <td class="py-3 font-semibold text-white">{{ p.account.title }}</td>
                            <td class="py-3 font-mono">
                                <span id="phone-{{ p.id }}">{{ p.account.phone }}</span>
                                <button onclick="navigator.clipboard.writeText('{{ p.account.phone }}'); alert('Номер скопирован!')" class="ml-2 text-xs text-indigo-400 hover:underline cursor-pointer">Копировать</button>
                            </td>
                            <td class="py-3 text-center">
                                <button onclick="getTelegramCode('{{ p.id }}')" class="bg-indigo-600/30 hover:bg-indigo-600 text-indigo-300 hover:text-white px-3 py-1 rounded text-xs font-bold transition-all cursor-pointer">
                                    Получить код
                                </button>
                            </td>
                        </tr>
                        <tr id="code-row-{{ p.id }}" class="hidden bg-[#0b1329]">
                            <td colspan="3" class="p-3 text-xs border border-indigo-500/20 rounded">
                                <div class="flex items-center justify-between">
                                    <span class="text-slate-400">Последний код из аккаунта:</span>
                                    <span id="code-val-{{ p.id }}" class="text-sm font-black text-amber-400 font-mono tracking-wider">Загрузка...</span>
                                </div>
                            </td>
                        </tr>
                        {% else %}
                        <tr> <td colspan="3" class="text-center py-6 text-slate-500">Покупки отсутствуют.</td> </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>

        {% if user.is_admin %}
        <div class="bg-[#1c2541] rounded-xl p-5 border border-slate-700 shadow-xl border-l-4 border-l-red-500">
            <h3 class="text-base font-bold text-red-400 mb-4 pb-2 border-b border-slate-700/50">🛡️ Панель Администратора</h3>
            <form method="POST" action="{{ url_for('admin_update_balance') }}" class="grid grid-cols-1 md:grid-cols-3 gap-4 items-end">
                <div>
                    <label class="block text-xs text-slate-400 mb-1">Никнейм пользователя</label>
                    <input type="text" name="username" required placeholder="Ivan B" class="w-full bg-[#0b1329] border border-slate-600 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-indigo-500">
                </div>
                <div>
                    <label class="block text-xs text-slate-400 mb-1">Новый баланс (₽)</label>
                    <input type="number" step="0.01" name="balance" required class="w-full bg-[#0b1329] border border-slate-600 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-indigo-500">
                </div>
                <button type="submit" class="bg-red-600 hover:bg-red-500 text-white font-bold py-2 rounded-lg text-sm transition-all h-[38px] cursor-pointer">
                    Изменить
                </button>
            </form>
        </div>
        {% endif %}
    </div>
</div>

<script>
    function getTelegramCode(purchaseId) {
        const row = document.getElementById('code-row-' + purchaseId);
        const val = document.getElementById('code-val-' + purchaseId);
        row.classList.remove('hidden');
        val.innerText = "Подключение к сессии и поиск кода...";
        
        fetch('/get_code/' + purchaseId)
            .then(res => res.json())
            .then(data => {
                if(data.success) { val.innerText = data.code; } 
                else { val.innerText = "Ошибка: " + data.error; }
            })
            .catch(err => { val.innerText = "Ошибка соединения."; });
    }
</script>
{% endblock %}
"""

AUTH_TEMPLATE = """
{% extends "base" %}
{% block content %}
<div class="max-w-md mx-auto bg-[#1c2541] border border-slate-700 rounded-xl p-6 shadow-2xl mt-12">
    <h2 class="text-xl font-bold mb-6 text-center text-white">{{ action_title }}</h2>
    <form method="POST" class="space-y-4">
        <div>
            <label class="block text-xs text-slate-400 mb-1">Имя пользователя / Логин</label>
            <input type="text" name="username" required class="w-full bg-[#0b1329] border border-slate-600 rounded-lg p-2.5 text-sm text-white focus:outline-none focus:border-indigo-500">
        </div>
        <div>
            <label class="block text-xs text-slate-400 mb-1">Пароль</label>
            <input type="password" name="password" required class="w-full bg-[#0b1329] border border-slate-600 rounded-lg p-2.5 text-sm text-white focus:outline-none focus:border-indigo-500">
        </div>
        <button type="submit" class="w-full bg-indigo-600 hover:bg-indigo-500 text-white font-bold py-2.5 rounded-lg text-sm transition-all shadow-lg shadow-indigo-600/20 cursor-pointer">
            Продолжить
        </button>
    </form>
</div>
{% endblock %}
"""

# --- Маршруты Flask ---

@app.context_processor
def inject_user_context():
    if 'user_id' in session:
        user = db.session.get(User, session['user_id'])
        if user: return dict(user_balance=user.balance)
    return dict(user_balance=0.0)

def render_vest_template(template_name, **kwargs):
    templates = {"base": BASE_TEMPLATE, "main": MAIN_PAGE, "profile": PROFILE_PAGE, "auth": AUTH_TEMPLATE}
    return render_template_string(templates[template_name], **kwargs)

@app.route('/')
def index():
    query = Account.query.filter_by(status='available')
    if request.args.get('title'): query = query.filter(Account.title.ilike(f"%{request.args.get('title')}%"))
    if request.args.get('country'): query = query.filter(Account.country.ilike(f"%{request.args.get('country')}%"))
    if request.args.get('origin'): query = query.filter(Account.origin.ilike(f"%{request.args.get('origin')}%"))
    if request.args.get('has_2fa') in ['1', '0']: query = query.filter_by(has_2fa=(request.args.get('has_2fa') == '1'))
    if request.args.get('has_spamblock') in ['1', '0']: query = query.filter_by(has_spamblock=(request.args.get('has_spamblock') == '1'))
    if request.args.get('min_chats'): query = query.filter(Account.chats_count >= int(request.args.get('min_chats')))
    if request.args.get('min_channels'): query = query.filter(Account.channels_count >= int(request.args.get('min_channels')))
    if request.args.get('min_groups'): query = query.filter(Account.groups_count >= int(request.args.get('min_groups')))
        
    accounts = query.order_by(Account.id.desc()).all()
    return render_vest_template("main", accounts=accounts)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            flash("Этот логин уже занят", "error")
        else:
            is_admin = (User.query.count() == 0) or (username == "Ivan B")
            user = User(username=username, password_hash=generate_password_hash(password), is_admin=is_admin, balance=1000.0)
            db.session.add(user)
            db.session.commit()
            session['user_id'] = user.id
            flash("Успешная регистрация! Бонус 1000 ₽ начислен.", "success")
            return redirect(url_for('index'))
    return render_vest_template("auth", action_title="Регистрация")

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            flash(f"Добро пожаловать, {user.username}!", "success")
            return redirect(url_for('index'))
        flash("Неверный логин или пароль", "error")
    return render_vest_template("auth", action_title="Вход")

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/topup')
def topup():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = db.session.get(User, session['user_id'])
    user.balance += 500
    db.session.commit()
    flash("Демо-баланс пополнен на 500 ₽", "success")
    return redirect(request.referrer or url_for('index'))

@app.route('/profile')
def profile():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = db.session.get(User, session['user_id'])
    purchases = Purchase.query.filter_by(buyer_id=user.id).order_by(Purchase.id.desc()).all()
    return render_vest_template("profile", user=user, purchases=purchases)

@app.route('/sell/step1', methods=['POST'])
def sell_step1():
    if 'user_id' not in session: return redirect(url_for('login'))
    user_id = session['user_id']
    phone = request.form['phone'].replace(" ", "").replace("-", "")
    
    session['sell_meta'] = {
        'title': request.form['title'], 'origin': request.form['origin'],
        'description': request.form['description'], 'price': float(request.form['price']),
    }
    session['auth_phone'] = phone
    session['auth_step'] = 'verify_code'

    try:
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        run_async(client.connect())
        send_code_res = run_async(client.send_code_request(phone))
        
        pending_auths[user_id] = {
            'client': client, 'phone': phone, 'phone_code_hash': send_code_res.phone_code_hash
        }
        flash("Код подтверждения успешно отправлен.", "success")
    except Exception as e:
        session.pop('auth_step', None)
        flash(f"Ошибка Telethon: {str(e)}", "error")
        
    return redirect(url_for('profile'))

@app.route('/sell/step2', methods=['POST'])
def sell_step2():
    if 'user_id' not in session: return redirect(url_for('login'))
    user_id = session['user_id']
    code = request.form['code'].strip()
    password = request.form.get('password', '').strip()
    
    auth_data = pending_auths.get(user_id)
    if not auth_data:
        flash("Сессия не найдена. Начните заново.", "error")
        session.pop('auth_step', None)
        return redirect(url_for('profile'))
        
    client = auth_data['client']
    phone = auth_data['phone']
    phone_code_hash = auth_data['phone_code_hash']
    meta = session.get('sell_meta')

    try:
        try:
            run_async(client.sign_in(phone, code, phone_code_hash=phone_code_hash))
        except SessionPasswordNeededError:
            if not password:
                flash("Требуется ввести двухфакторный пароль (2FA)!", "error")
                return redirect(url_for('profile'))
            run_async(client.sign_in(password=password))

        chats_count = 0
        channels_count = 0
        groups_count = 0
        
        dialogs = run_async(client.get_dialogs(limit=100))
        for d in dialogs:
            chats_count += 1
            if d.is_channel: channels_count += 1
            elif d.is_group: groups_count += 1

        session_str = client.session.save()
        
        new_acc = Account(
            seller_id=user_id, title=meta['title'], origin=meta['origin'],
            description=meta['description'], price=meta['price'], phone=phone,
            session_string=session_str, country=get_country_code(phone),
            has_2fa=bool(password), chats_count=chats_count,
            channels_count=channels_count, groups_count=groups_count
        )
        db.session.add(new_acc)
        db.session.commit()
        flash("Аккаунт успешно добавлен на маркетплейс!", "success")
    except Exception as e:
        flash(f"Не удалось авторизовать аккаунт: {str(e)}", "error")
    finally:
        pending_auths.pop(user_id, None)
        session.pop('auth_step', None)
        session.pop('sell_meta', None)
        session.pop('auth_phone', None)
        
    return redirect(url_for('profile'))

@app.route('/sell/cancel')
def cancel_sell():
    pending_auths.pop(session.get('user_id'), None)
    session.pop('auth_step', None)
    return redirect(url_for('profile'))

@app.route('/buy/<int:account_id>', methods=['POST'])
def buy_account(account_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    buyer = db.session.get(User, session['user_id'])
    acc = db.session.get(Account, account_id)
    
    if not acc or acc.status != 'available':
        flash("Аккаунт недоступен.", "error")
        return redirect(url_for('index'))
    if buyer.id == acc.seller_id:
        flash("Вы не можете купить свой аккаунт.", "error")
        return redirect(url_for('index'))
    if buyer.balance < acc.price:
        flash("Недостаточно денег на балансе.", "error")
        return redirect(url_for('index'))
        
    buyer.balance -= acc.price
    seller = db.session.get(User, acc.seller_id)
    if seller:
        seller.balance += (acc.price * 0.95)
        
    acc.status = 'sold'
    purchase = Purchase(buyer_id=buyer.id, account_id=acc.id, price_paid=acc.price)
    db.session.add(purchase)
    db.session.commit()
    
    flash("Успешная покупка! Аккаунт добавлен в профиль.", "success")
    return redirect(url_for('profile'))

@app.route('/check_valid/<int:account_id>')
def check_valid(account_id):
    acc = db.session.get(Account, account_id)
    if not acc: return jsonify({'valid': False})
    try:
        client = TelegramClient(StringSession(acc.session_string), API_ID, API_HASH)
        run_async(client.connect())
        return jsonify({'valid': run_async(client.is_user_authorized())})
    except:
        return jsonify({'valid': False})

@app.route('/get_code/<int:purchase_id>')
def get_code(purchase_id):
    if 'user_id' not in session: return jsonify({'success': False, 'error': 'Unauthorized'})
    purchase = db.session.get(Purchase, purchase_id)
    if not purchase or purchase.buyer_id != session['user_id']:
        return jsonify({'success': False, 'error': 'Доступ запрещен'})
        
    try:
        client = TelegramClient(StringSession(purchase.account.session_string), API_ID, API_HASH)
        run_async(client.connect())
        if not run_async(client.is_user_authorized()):
            return jsonify({'success': False, 'error': 'Сессия невалидна'})
            
        dialogs = run_async(client.get_dialogs(limit=1))
        if not dialogs: return jsonify({'success': False, 'error': 'Диалоги отсутствуют'})
        
        text = dialogs[0].message.message
        code_match = re.search(r'\b\d{5}\b', text)
        return jsonify({'success': True, 'code': code_match.group(0) if code_match else text})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/admin/update_balance', methods=['POST'])
def admin_update_balance():
    if 'user_id' not in session: return redirect(url_for('login'))
    admin = db.session.get(User, session['user_id'])
    if not admin.is_admin: return redirect(url_for('index'))
    
    target = User.query.filter_by(username=request.form['username'].strip()).first()
    if target:
        target.balance = float(request.form['balance'])
        db.session.commit()
        flash("Баланс изменен.", "success")
    else:
        flash("Пользователь не найден.", "error")
    return redirect(url_for('profile'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)
