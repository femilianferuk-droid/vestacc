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

# --- Стили ---
GLOBAL_STYLES = """
:root {
    --bg-primary: #0a0a0f;
    --bg-secondary: #13131a;
    --bg-card: #1a1a24;
    --bg-hover: #22222d;
    --accent: #8b5cf6;
    --accent-hover: #7c3aed;
    --accent-glow: rgba(139, 92, 246, 0.3);
    --success: #10b981;
    --success-glow: rgba(16, 185, 129, 0.3);
    --warning: #f59e0b;
    --danger: #ef4444;
    --text: #e2e8f0;
    --text-secondary: #94a3b8;
    --text-muted: #64748b;
    --border: #2d2d3a;
    --border-light: #3d3d4a;
    --radius: 16px;
    --radius-sm: 10px;
    --shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
    --shadow-glow: 0 0 20px var(--accent-glow);
    --transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: var(--bg-primary);
    color: var(--text);
    min-height: 100vh;
    line-height: 1.6;
    overflow-x: hidden;
    background-image: 
        radial-gradient(ellipse at 20% 50%, rgba(139, 92, 246, 0.05) 0%, transparent 50%),
        radial-gradient(ellipse at 80% 20%, rgba(16, 185, 129, 0.05) 0%, transparent 50%),
        radial-gradient(ellipse at 50% 80%, rgba(59, 130, 246, 0.03) 0%, transparent 50%);
}

/* Скроллбар */
::-webkit-scrollbar {
    width: 8px;
}
::-webkit-scrollbar-track {
    background: var(--bg-primary);
}
::-webkit-scrollbar-thumb {
    background: var(--border);
    border-radius: 4px;
}
::-webkit-scrollbar-thumb:hover {
    background: var(--border-light);
}

/* Навбар */
.navbar {
    background: rgba(19, 19, 26, 0.8);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border-bottom: 1px solid var(--border);
    padding: 16px 32px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    position: sticky;
    top: 0;
    z-index: 100;
    gap: 20px;
}

.logo {
    display: flex;
    align-items: center;
    gap: 10px;
    text-decoration: none;
    font-size: 24px;
    font-weight: 800;
    background: linear-gradient(135deg, var(--accent), #a78bfa);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}

.logo-icon {
    width: 40px;
    height: 40px;
    background: linear-gradient(135deg, var(--accent), #a78bfa);
    border-radius: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 20px;
}

.nav-right {
    display: flex;
    align-items: center;
    gap: 16px;
}

.balance-display {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 50px;
    padding: 8px 20px;
    display: flex;
    align-items: center;
    gap: 8px;
    font-weight: 700;
    color: var(--success);
}

.balance-display .icon {
    font-size: 18px;
}

.btn {
    padding: 10px 20px;
    border: none;
    border-radius: 50px;
    cursor: pointer;
    font-size: 14px;
    font-weight: 600;
    text-decoration: none;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    transition: var(--transition);
    white-space: nowrap;
    position: relative;
    overflow: hidden;
}

.btn::after {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: linear-gradient(135deg, transparent, rgba(255,255,255,0.1), transparent);
    transform: translateX(-100%);
    transition: transform 0.5s;
}

.btn:hover::after {
    transform: translateX(100%);
}

.btn-primary {
    background: linear-gradient(135deg, var(--accent), #a78bfa);
    color: white;
    box-shadow: 0 4px 15px var(--accent-glow);
}
.btn-primary:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 25px var(--accent-glow);
}

.btn-secondary {
    background: var(--bg-card);
    color: var(--text);
    border: 1px solid var(--border);
}
.btn-secondary:hover {
    background: var(--bg-hover);
    border-color: var(--border-light);
    transform: translateY(-1px);
}

.btn-success {
    background: linear-gradient(135deg, var(--success), #34d399);
    color: white;
    box-shadow: 0 4px 15px var(--success-glow);
}
.btn-success:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 25px var(--success-glow);
}

.btn-danger {
    background: var(--danger);
    color: white;
}
.btn-danger:hover {
    background: #dc2626;
}

.btn-ghost {
    background: transparent;
    color: var(--text);
    border: 1px solid transparent;
}
.btn-ghost:hover {
    background: var(--bg-card);
    border-color: var(--border);
}

.btn-add {
    width: 36px;
    height: 36px;
    padding: 0;
    border-radius: 50%;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 20px;
    font-weight: bold;
}

/* Контейнер */
.container {
    max-width: 1300px;
    margin: 0 auto;
    padding: 32px 24px;
}

/* Заголовок страницы */
.page-header {
    text-align: center;
    margin-bottom: 40px;
}

.page-title {
    font-size: 36px;
    font-weight: 800;
    background: linear-gradient(135deg, var(--text), #cbd5e1);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin-bottom: 8px;
}

.page-subtitle {
    color: var(--text-secondary);
    font-size: 16px;
}

/* Фильтры */
.filter-section {
    display: flex;
    justify-content: center;
    margin-bottom: 32px;
}

.filter-toggle {
    background: var(--bg-card);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 14px 32px;
    border-radius: 50px;
    cursor: pointer;
    font-size: 15px;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 10px;
    transition: var(--transition);
}

.filter-toggle:hover {
    background: var(--bg-hover);
    border-color: var(--accent);
    box-shadow: var(--shadow-glow);
}

.filter-toggle .icon {
    font-size: 20px;
}

.filter-panel {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 24px;
    margin-top: 16px;
    display: none;
    animation: slideDown 0.3s ease;
}

.filter-panel.active {
    display: block;
}

@keyframes slideDown {
    from {
        opacity: 0;
        transform: translateY(-10px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

.filter-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 12px;
    margin-bottom: 16px;
}

.filter-actions {
    display: flex;
    gap: 12px;
    justify-content: center;
}

/* Инпуты */
input, textarea, select {
    width: 100%;
    padding: 12px 16px;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text);
    font-size: 14px;
    font-family: inherit;
    transition: var(--transition);
}

input:focus, textarea:focus, select:focus {
    outline: none;
    border-color: var(--accent);
    box-shadow: 0 0 0 3px var(--accent-glow);
}

input::placeholder, textarea::placeholder {
    color: var(--text-muted);
}

select {
    cursor: pointer;
    appearance: none;
    background-image: url("data:image/svg+xml,%3Csvg width='12' height='8' viewBox='0 0 12 8' fill='none' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M1 1.5L6 6.5L11 1.5' stroke='%2394a3b8' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
    background-repeat: no-repeat;
    background-position: right 16px center;
    padding-right: 40px;
}

/* Сетка карточек */
.accounts-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 20px;
    margin-top: 24px;
}

/* Карточка аккаунта */
.account-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 24px;
    transition: var(--transition);
    position: relative;
    overflow: hidden;
}

.account-card::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 2px;
    background: linear-gradient(90deg, var(--accent), #a78bfa, var(--accent));
    opacity: 0;
    transition: opacity 0.3s;
}

.account-card:hover {
    border-color: var(--accent);
    box-shadow: var(--shadow), var(--shadow-glow);
    transform: translateY(-4px);
}

.account-card:hover::before {
    opacity: 1;
}

.card-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 16px;
}

.card-title {
    font-size: 18px;
    font-weight: 700;
    color: var(--text);
    margin-bottom: 4px;
}

.card-seller {
    font-size: 13px;
    color: var(--text-muted);
}

.card-price {
    background: linear-gradient(135deg, rgba(16, 185, 129, 0.2), rgba(16, 185, 129, 0.1));
    border: 1px solid rgba(16, 185, 129, 0.3);
    color: var(--success);
    padding: 8px 16px;
    border-radius: 50px;
    font-weight: 700;
    font-size: 16px;
}

.card-stats {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;
    margin-bottom: 16px;
}

.stat-item {
    text-align: center;
    padding: 10px;
    background: var(--bg-secondary);
    border-radius: var(--radius-sm);
}

.stat-value {
    font-size: 18px;
    font-weight: 700;
    color: var(--accent);
}

.stat-label {
    font-size: 11px;
    color: var(--text-muted);
    margin-top: 2px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

.card-tags {
    display: flex;
    gap: 8px;
    margin-bottom: 16px;
    flex-wrap: wrap;
}

.tag {
    padding: 6px 12px;
    border-radius: 50px;
    font-size: 12px;
    font-weight: 600;
}

.tag-success {
    background: rgba(16, 185, 129, 0.2);
    color: var(--success);
}

.tag-warning {
    background: rgba(245, 158, 11, 0.2);
    color: var(--warning);
}

.tag-default {
    background: var(--bg-secondary);
    color: var(--text-secondary);
}

.card-actions {
    display: flex;
    gap: 10px;
}

/* Детальная страница */
.detail-card {
    max-width: 700px;
    margin: 0 auto;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 32px;
}

.detail-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin: 24px 0;
}

.detail-item {
    background: var(--bg-secondary);
    padding: 16px;
    border-radius: var(--radius-sm);
}

.detail-label {
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-muted);
    margin-bottom: 4px;
}

.detail-value {
    font-weight: 600;
    color: var(--text);
}

/* Формы */
.form-container {
    max-width: 450px;
    margin: 60px auto;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 40px;
    box-shadow: var(--shadow);
}

.form-title {
    font-size: 28px;
    font-weight: 800;
    text-align: center;
    margin-bottom: 8px;
    background: linear-gradient(135deg, var(--accent), #a78bfa);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}

.form-subtitle {
    text-align: center;
    color: var(--text-secondary);
    margin-bottom: 32px;
    font-size: 14px;
}

.form-group {
    margin-bottom: 20px;
}

.form-group label {
    display: block;
    margin-bottom: 8px;
    font-weight: 600;
    color: var(--text-secondary);
    font-size: 14px;
}

.form-footer {
    text-align: center;
    margin-top: 24px;
    color: var(--text-secondary);
    font-size: 14px;
}

.form-footer a {
    color: var(--accent);
    text-decoration: none;
    font-weight: 600;
}

/* Алерты */
.alert {
    padding: 14px 20px;
    border-radius: var(--radius-sm);
    margin-bottom: 20px;
    font-weight: 500;
    animation: slideDown 0.3s ease;
}

.alert-success {
    background: rgba(16, 185, 129, 0.15);
    border: 1px solid rgba(16, 185, 129, 0.3);
    color: var(--success);
}

.alert-error {
    background: rgba(239, 68, 68, 0.15);
    border: 1px solid rgba(239, 68, 68, 0.3);
    color: var(--danger);
}

.alert-info {
    background: rgba(59, 130, 246, 0.15);
    border: 1px solid rgba(59, 130, 246, 0.3);
    color: #3b82f6;
}

/* Кнопка профиля внизу */
.profile-bottom-btn {
    display: block;
    width: 100%;
    max-width: 400px;
    margin: 40px auto;
    padding: 16px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    color: var(--text);
    text-align: center;
    text-decoration: none;
    font-weight: 600;
    font-size: 16px;
    transition: var(--transition);
    cursor: pointer;
}

.profile-bottom-btn:hover {
    background: var(--bg-hover);
    border-color: var(--accent);
    box-shadow: var(--shadow-glow);
}

/* Админ-таблица */
.admin-table {
    width: 100%;
    border-collapse: collapse;
    background: var(--bg-card);
    border-radius: var(--radius);
    overflow: hidden;
}

.admin-table th {
    background: var(--bg-secondary);
    padding: 14px 20px;
    text-align: left;
    font-weight: 600;
    color: var(--text-secondary);
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

.admin-table td {
    padding: 14px 20px;
    border-top: 1px solid var(--border);
}

.admin-table tr:hover td {
    background: var(--bg-hover);
}

/* Модалка кода */
.code-display {
    font-size: 32px;
    font-weight: 800;
    letter-spacing: 8px;
    color: var(--success);
    text-align: center;
    padding: 20px;
    background: var(--bg-secondary);
    border-radius: var(--radius-sm);
    margin: 16px 0;
}

/* Адаптивность */
@media (max-width: 768px) {
    .navbar {
        padding: 12px 16px;
        flex-wrap: wrap;
    }
    
    .logo {
        font-size: 20px;
    }
    
    .nav-right {
        gap: 8px;
    }
    
    .btn {
        padding: 8px 14px;
        font-size: 13px;
    }
    
    .container {
        padding: 20px 16px;
    }
    
    .page-title {
        font-size: 28px;
    }
    
    .accounts-grid {
        grid-template-columns: 1fr;
    }
    
    .filter-grid {
        grid-template-columns: 1fr;
    }
    
    .form-container {
        margin: 20px 16px;
        padding: 24px;
    }
    
    .detail-grid {
        grid-template-columns: 1fr;
    }
    
    .card-stats {
        grid-template-columns: repeat(3, 1fr);
    }
    
    .balance-display {
        padding: 6px 14px;
        font-size: 13px;
    }
    
    .profile-bottom-btn {
        max-width: 100%;
        margin: 24px 16px;
    }
}

@media (max-width: 480px) {
    .nav-right {
        width: 100%;
        justify-content: space-between;
        margin-top: 8px;
    }
    
    .btn-add {
        width: 30px;
        height: 30px;
        font-size: 16px;
    }
    
    .card-actions {
        flex-direction: column;
    }
    
    .card-actions .btn {
        width: 100%;
        justify-content: center;
    }
}
"""

# --- Скрипты ---
SCRIPTS = """
<script>
function toggleFilters() {
    const panel = document.getElementById('filterPanel');
    panel.classList.toggle('active');
}

function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        const toast = document.createElement('div');
        toast.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:var(--success);color:white;padding:12px 24px;border-radius:50px;font-weight:600;z-index:1000;animation:slideUp 0.3s ease';
        toast.textContent = '✓ Скопировано!';
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 2000);
    });
}

function getCode(purchaseId) {
    const btn = event.target;
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span style="animation:spin 1s linear infinite;">⏳</span> Загрузка...';
    
    fetch('/get_code/' + purchaseId)
        .then(r => r.json())
        .then(data => {
            if (data.code) {
                document.getElementById('code-' + purchaseId).innerHTML = 
                    '<div class="code-display">' + data.code + '</div>';
                btn.style.display = 'none';
            } else {
                alert('Ошибка: ' + (data.error || 'не удалось получить код'));
            }
        })
        .catch(e => alert('Ошибка: ' + e))
        .finally(() => {
            btn.disabled = false;
            btn.innerHTML = originalText;
        });
}

// Анимация появления
document.addEventListener('DOMContentLoaded', () => {
    const cards = document.querySelectorAll('.account-card');
    cards.forEach((card, index) => {
        card.style.opacity = '0';
        card.style.transform = 'translateY(20px)';
        setTimeout(() => {
            card.style.transition = 'all 0.5s ease ' + (index * 0.1) + 's';
            card.style.opacity = '1';
            card.style.transform = 'translateY(0)';
        }, 100);
    });
});

const style = document.createElement('style');
style.textContent = `
    @keyframes slideUp { from { opacity: 0; transform: translateX(-50%) translateY(20px); } to { opacity: 1; transform: translateX(-50%) translateY(0); } }
    @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
`;
document.head.appendChild(style);
</script>
"""

# --- HTML шаблоны ---
NAVBAR_GUEST = """
<div class="navbar">
    <a href="/" class="logo">
        <div class="logo-icon">⚡</div>
        Vest Accs
    </a>
    <div class="nav-right">
        <a href="/login" class="btn btn-ghost">Войти</a>
        <a href="/register" class="btn btn-primary">Регистрация</a>
    </div>
</div>
"""

NAVBAR_USER = """
<div class="navbar">
    <a href="/" class="logo">
        <div class="logo-icon">⚡</div>
        Vest Accs
    </a>
    <div class="nav-right">
        <div class="balance-display">
            <span class="icon">💰</span>
            <span>{{ "%.2f"|format(g.user.balance) }} ₽</span>
        </div>
        <a href="/deposit" class="btn btn-add btn-success" title="Пополнить">+</a>
        <a href="/my_purchases" class="btn btn-ghost">📦 Покупки</a>
        <a href="/logout" class="btn btn-ghost">🚪</a>
    </div>
</div>
"""

INDEX_PAGE = GLOBAL_STYLES + """
{% if g.user %}
""" + NAVBAR_USER + """
{% else %}
""" + NAVBAR_GUEST + """
{% endif %}

<div class="container">
    <div class="page-header">
        <h1 class="page-title">Маркетплейс Telegram аккаунтов</h1>
        <p class="page-subtitle">Покупайте и продавайте проверенные аккаунты Telegram</p>
    </div>

    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            {% for category, message in messages %}
                <div class="alert alert-{{ category }}">{{ message }}</div>
            {% endfor %}
        {% endif %}
    {% endwith %}

    <div class="filter-section">
        <div style="text-align: center; width: 100%;">
            <button onclick="toggleFilters()" class="filter-toggle">
                <span class="icon">🔍</span>
                Фильтры и поиск
            </button>
            <div id="filterPanel" class="filter-panel">
                <form action="/filter" method="GET">
                    <div class="filter-grid">
                        <input type="text" name="q" placeholder="🔎 Поиск по заголовку...">
                        <input type="text" name="country" placeholder="🌍 Страна...">
                        <input type="text" name="origin" placeholder="📋 Происхождение...">
                        <select name="2fa">
                            <option value="">🔐 2FA (любой)</option>
                            <option value="yes">✅ Есть 2FA</option>
                            <option value="no">❌ Нет 2FA</option>
                        </select>
                        <select name="spamblock">
                            <option value="">🚫 Спамблок (любой)</option>
                            <option value="yes">⚠️ Есть</option>
                            <option value="no">✅ Нет</option>
                        </select>
                        <input type="number" name="min_chats" placeholder="💬 Мин. чатов...">
                    </div>
                    <div class="filter-actions">
                        <button type="submit" class="btn btn-primary">🔍 Применить</button>
                        <a href="/" class="btn btn-secondary">↺ Сбросить</a>
                    </div>
                </form>
            </div>
        </div>
    </div>

    <div class="accounts-grid">
        {% for account in accounts %}
        <div class="account-card">
            <div class="card-header">
                <div>
                    <div class="card-title">{{ account.title }}</div>
                    <div class="card-seller">👤 {{ account.seller_name }}</div>
                </div>
                <div class="card-price">{{ "%.0f"|format(account.price) }} ₽</div>
            </div>

            <div class="card-stats">
                <div class="stat-item">
                    <div class="stat-value">{{ account.chats_count }}</div>
                    <div class="stat-label">Чаты</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">{{ account.channels_count }}</div>
                    <div class="stat-label">Каналы</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">{{ account.groups_count }}</div>
                    <div class="stat-label">Группы</div>
                </div>
            </div>

            <div class="card-tags">
                {% if account.has_2fa %}
                <span class="tag tag-warning">🔐 2FA</span>
                {% endif %}
                {% if account.spamblock %}
                <span class="tag tag-warning">🚫 Спамблок</span>
                {% endif %}
                <span class="tag tag-default">🌍 {{ account.country or '?' }}</span>
                <span class="tag tag-default">{{ account.origin or '?' }}</span>
            </div>

            <div class="card-actions">
                <a href="/account/{{ account.id }}" class="btn btn-secondary" style="flex:1; justify-content:center;">📋 Детали</a>
                {% if g.user and g.user.id != account.seller_id %}
                <form action="/buy/{{ account.id }}" method="POST" style="flex:1;">
                    <button type="submit" class="btn btn-success" style="width:100%; justify-content:center;">🛒 Купить</button>
                </form>
                {% endif %}
            </div>
        </div>
        {% endfor %}

        {% if not accounts %}
        <div style="text-align: center; grid-column: 1/-1; padding: 60px 20px; color: var(--text-muted);">
            <div style="font-size: 64px; margin-bottom: 16px;">📭</div>
            <h3>Нет доступных аккаунтов</h3>
            <p>Станьте первым продавцом!</p>
        </div>
        {% endif %}
    </div>

    {% if g.user %}
    <a href="/profile" class="profile-bottom-btn">👤 Профиль и продажа аккаунтов</a>
    {% endif %}
</div>
""" + SCRIPTS

LOGIN_PAGE = GLOBAL_STYLES + NAVBAR_GUEST + """
<div class="form-container">
    <h1 class="form-title">С возвращением</h1>
    <p class="form-subtitle">Войдите в свой аккаунт Vest Accs</p>

    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            {% for category, message in messages %}
                <div class="alert alert-{{ category }}">{{ message }}</div>
            {% endfor %}
        {% endif %}
    {% endwith %}

    <form method="POST">
        <div class="form-group">
            <label>👤 Логин</label>
            <input type="text" name="username" placeholder="Введите логин" required>
        </div>
        <div class="form-group">
            <label>🔒 Пароль</label>
            <input type="password" name="password" placeholder="Введите пароль" required>
        </div>
        <button type="submit" class="btn btn-primary" style="width:100%; justify-content:center; padding:14px;">🚀 Войти</button>
    </form>
    <div class="form-footer">
        Нет аккаунта? <a href="/register">Создать</a>
    </div>
</div>
"""

REGISTER_PAGE = GLOBAL_STYLES + NAVBAR_GUEST + """
<div class="form-container">
    <h1 class="form-title">Присоединяйтесь</h1>
    <p class="form-subtitle">Создайте аккаунт для покупки и продажи</p>

    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            {% for category, message in messages %}
                <div class="alert alert-{{ category }}">{{ message }}</div>
            {% endfor %}
        {% endif %}
    {% endwith %}

    <form method="POST">
        <div class="form-group">
            <label>👤 Логин</label>
            <input type="text" name="username" placeholder="Придумайте логин" required>
        </div>
        <div class="form-group">
            <label>🔒 Пароль</label>
            <input type="password" name="password" placeholder="Придумайте пароль" required>
        </div>
        <button type="submit" class="btn btn-primary" style="width:100%; justify-content:center; padding:14px;">✨ Зарегистрироваться</button>
    </form>
    <div class="form-footer">
        Уже есть аккаунт? <a href="/login">Войти</a>
    </div>
</div>
"""

ACCOUNT_DETAIL_PAGE = GLOBAL_STYLES + NAVBAR_USER.replace('{% if g.user %}', '').replace('{% else %}', '').replace('{% endif %}', '') + """
<div class="container">
    <div class="detail-card">
        <div style="display:flex; justify-content:space-between; align-items:start; flex-wrap:wrap; gap:16px;">
            <div>
                <h2 style="font-size:28px; font-weight:800; margin-bottom:4px;">{{ account.title }}</h2>
                <p style="color:var(--text-secondary);">Продавец: {{ account.seller_name }}</p>
            </div>
            <div style="background:linear-gradient(135deg, rgba(16,185,129,0.2), rgba(16,185,129,0.1)); border:1px solid rgba(16,185,129,0.3); padding:16px 24px; border-radius:var(--radius); text-align:center;">
                <div style="font-size:12px; color:var(--text-muted);">Цена</div>
                <div style="font-size:28px; font-weight:800; color:var(--success);">{{ "%.2f"|format(account.price) }} ₽</div>
            </div>
        </div>

        <div class="detail-grid">
            <div class="detail-item">
                <div class="detail-label">🌍 Страна</div>
                <div class="detail-value">{{ account.country or 'Не указана' }}</div>
            </div>
            <div class="detail-item">
                <div class="detail-label">📋 Происхождение</div>
                <div class="detail-value">{{ account.origin or 'Не указано' }}</div>
            </div>
            <div class="detail-item">
                <div class="detail-label">🔐 2FA</div>
                <div class="detail-value">{% if account.has_2fa %}✅ Да{% else %}❌ Нет{% endif %}</div>
            </div>
            <div class="detail-item">
                <div class="detail-label">🚫 Спамблок</div>
                <div class="detail-value">{% if account.spamblock %}⚠️ Есть{% else %}✅ Нет{% endif %}</div>
            </div>
            <div class="detail-item">
                <div class="detail-label">💬 Чаты</div>
                <div class="detail-value">{{ account.chats_count }}</div>
            </div>
            <div class="detail-item">
                <div class="detail-label">📢 Каналы</div>
                <div class="detail-value">{{ account.channels_count }}</div>
            </div>
            <div class="detail-item">
                <div class="detail-label">👥 Группы</div>
                <div class="detail-value">{{ account.groups_count }}</div>
            </div>
        </div>

        {% if account.description %}
        <div style="background:var(--bg-secondary); padding:20px; border-radius:var(--radius-sm); margin:20px 0;">
            <div class="detail-label">📝 Описание</div>
            <p style="margin-top:8px;">{{ account.description }}</p>
        </div>
        {% endif %}

        <div style="display:flex; gap:12px; margin-top:24px; flex-wrap:wrap;">
            <a href="/" class="btn btn-secondary">← Назад</a>
            {% if g.user and g.user.id != account.seller_id and not account.is_sold %}
            <form action="/buy/{{ account.id }}" method="POST" style="flex:1;">
                <button type="submit" class="btn btn-success" style="width:100%; justify-content:center;">🛒 Купить аккаунт</button>
            </form>
            {% endif %}
        </div>
    </div>
</div>
""" + SCRIPTS

PROFILE_PAGE = GLOBAL_STYLES + NAVBAR_USER + """
<div class="container" style="max-width: 600px;">
    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            {% for category, message in messages %}
                <div class="alert alert-{{ category }}">{{ message }}</div>
            {% endfor %}
        {% endif %}
    {% endwith %}

    <div class="card" style="background:var(--bg-card); border:1px solid var(--border); border-radius:var(--radius); padding:32px; margin-bottom:24px;">
        <div style="display:flex; align-items:center; gap:16px; margin-bottom:24px;">
            <div style="width:60px; height:60px; background:linear-gradient(135deg, var(--accent), #a78bfa); border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:28px;">👤</div>
            <div>
                <h3 style="font-size:20px;">{{ g.user.username }}</h3>
                <div class="balance-display" style="display:inline-flex; margin-top:4px;">
                    <span>{{ "%.2f"|format(g.user.balance) }} ₽</span>
                </div>
            </div>
        </div>
    </div>

    <div class="card" style="background:var(--bg-card); border:1px solid var(--border); border-radius:var(--radius); padding:32px; margin-bottom:24px;">
        <h3 style="font-size:20px; margin-bottom:24px;">📱 Выставить аккаунт на продажу</h3>
        
        <form method="POST" style="margin-bottom:24px;">
            <input type="hidden" name="action" value="verify_phone">
            <div class="form-group">
                <label>Шаг 1: Номер телефона</label>
                <input type="text" name="phone" placeholder="+79001234567" required>
            </div>
            <button type="submit" class="btn btn-primary" style="width:100%; justify-content:center;">📤 Отправить код</button>
        </form>

        {% if session.get('verify_phone') %}
        <form method="POST" style="margin-bottom:24px; padding:20px; background:var(--bg-secondary); border-radius:var(--radius-sm);">
            <input type="hidden" name="action" value="confirm_code">
            <div class="form-group">
                <label>Шаг 2: Код из Telegram</label>
                <input type="text" name="code" placeholder="12345" required>
            </div>
            <button type="submit" class="btn btn-success" style="width:100%; justify-content:center;">✅ Подтвердить</button>
        </form>
        {% endif %}

        {% if session.get('2fa_needed') %}
        <form method="POST" style="margin-bottom:24px; padding:20px; background:rgba(245,158,11,0.1); border:1px solid rgba(245,158,11,0.3); border-radius:var(--radius-sm);">
            <input type="hidden" name="action" value="confirm_2fa">
            <div class="form-group">
                <label>Шаг 3: Пароль 2FA</label>
                <input type="password" name="password_2fa" placeholder="Введите пароль 2FA" required>
            </div>
            <button type="submit" class="btn btn-warning" style="width:100%; justify-content:center; background:var(--warning);">🔐 Подтвердить 2FA</button>
        </form>
        {% endif %}

        {% if session.get('phone_verified') %}
        <div style="padding:20px; background:rgba(16,185,129,0.1); border:1px solid rgba(16,185,129,0.3); border-radius:var(--radius-sm); text-align:center;">
            <p style="color:var(--success); font-weight:600; margin-bottom:16px;">✅ Номер подтвержден!</p>
            <a href="/sell" class="btn btn-primary" style="justify-content:center;">📝 Заполнить данные аккаунта</a>
        </div>
        {% endif %}
    </div>

    {% if g.user.is_admin %}
    <div class="card" style="background:var(--bg-card); border:1px solid var(--border); border-radius:var(--radius); padding:32px;">
        <h3 style="font-size:20px; margin-bottom:16px;">⚙️ Админ-панель</h3>
        <a href="/admin" class="btn btn-warning" style="width:100%; justify-content:center; background:var(--warning);">🔧 Управление пользователями</a>
    </div>
    {% endif %}
</div>
"""

SELL_PAGE = GLOBAL_STYLES + NAVBAR_USER + """
<div class="container" style="max-width: 600px;">
    <h2 style="font-size:28px; font-weight:800; margin-bottom:24px; text-align:center;">📱 Выставить аккаунт</h2>
    
    <div style="background:var(--bg-card); border:1px solid var(--border); border-radius:var(--radius); padding:32px;">
        <form method="POST">
            <div class="form-group">
                <label>📛 Название *</label>
                <input type="text" name="title" placeholder="Например: Премиум аккаунт 2023" required>
            </div>
            <div class="form-group">
                <label>📋 Происхождение</label>
                <input type="text" name="origin" placeholder="Парсинг / Регистрация / Покупка">
            </div>
            <div class="form-group">
                <label>📝 Описание</label>
                <textarea name="description" placeholder="Опишите аккаунт подробнее..." rows="4"></textarea>
            </div>
            <div class="form-group">
                <label>💎 Цена (₽) *</label>
                <input type="number" name="price" placeholder="1000" step="0.01" required>
            </div>
            <div class="form-group">
                <label style="display:flex; align-items:center; gap:8px; cursor:pointer;">
                    <input type="checkbox" name="has_2fa" style="width:auto;">
                    🔐 Есть 2FA
                </label>
            </div>
            <button type="submit" class="btn btn-primary" style="width:100%; justify-content:center; padding:14px;">🚀 Выставить на продажу</button>
        </form>
        <p style="text-align:center; color:var(--text-muted); margin-top:16px; font-size:14px;">💡 Комиссия платформы: 5%</p>
    </div>
</div>
"""

PURCHASES_PAGE = GLOBAL_STYLES + NAVBAR_USER + """
<div class="container">
    <h2 style="font-size:28px; font-weight:800; margin-bottom:24px;">📦 Мои покупки</h2>

    {% for purchase in purchases %}
    <div style="background:var(--bg-card); border:1px solid var(--border); border-radius:var(--radius); padding:24px; margin-bottom:16px;">
        <div style="display:flex; justify-content:space-between; align-items:start; flex-wrap:wrap; gap:16px; margin-bottom:16px;">
            <div>
                <h3 style="font-size:18px;">{{ purchase.title }}</h3>
                <p style="color:var(--text-muted); font-size:14px;">📅 {{ purchase.purchase_date.strftime('%d.%m.%Y %H:%M') }}</p>
            </div>
        </div>
        
        <div style="background:var(--bg-secondary); padding:16px; border-radius:var(--radius-sm); margin-bottom:16px;">
            <p style="margin-bottom:8px;">📱 Номер телефона:</p>
            <div style="display:flex; align-items:center; gap:8px;">
                <code style="font-size:18px; font-weight:600;">{{ purchase.phone_number }}</code>
                <button onclick="copyToClipboard('{{ purchase.phone_number }}')" class="btn btn-secondary" style="padding:8px 12px; font-size:12px;">📋 Копировать</button>
            </div>
        </div>

        <div id="code-{{ purchase.id }}"></div>
        
        {% if not purchase.code_retrieved %}
        <button onclick="getCode({{ purchase.id }})" class="btn btn-primary" style="width:100%; justify-content:center;">📨 Получить код подтверждения</button>
        {% endif %}
    </div>
    {% endfor %}

    {% if not purchases %}
    <div style="text-align:center; padding:60px 20px; color:var(--text-muted);">
        <div style="font-size:64px; margin-bottom:16px;">🛒</div>
        <h3>Нет покупок</h3>
        <p>Купите свой первый аккаунт!</p>
        <a href="/" class="btn btn-primary" style="margin-top:16px; justify-content:center;">🔍 Смотреть аккаунты</a>
    </div>
    {% endif %}
</div>
""" + SCRIPTS

DEPOSIT_PAGE = GLOBAL_STYLES + NAVBAR_USER + """
<div class="form-container">
    <h1 class="form-title">Пополнение баланса</h1>
    <p class="form-subtitle">Текущий баланс: <strong style="color:var(--success);">{{ "%.2f"|format(g.user.balance) }} ₽</strong></p>
    
    <form method="POST">
        <div class="form-group">
            <label>💰 Сумма пополнения</label>
            <input type="number" name="amount" placeholder="1000" step="0.01" required>
        </div>
        <button type="submit" class="btn btn-success" style="width:100%; justify-content:center; padding:14px;">💎 Пополнить</button>
    </form>
</div>
"""

ADMIN_PAGE = GLOBAL_STYLES + NAVBAR_USER + """
<div class="container">
    <h2 style="font-size:28px; font-weight:800; margin-bottom:24px;">⚙️ Админ-панель</h2>

    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            {% for category, message in messages %}
                <div class="alert alert-{{ category }}">{{ message }}</div>
            {% endfor %}
        {% endif %}
    {% endwith %}

    <div style="background:var(--bg-card); border:1px solid var(--border); border-radius:var(--radius); padding:32px; margin-bottom:24px;">
        <h3 style="margin-bottom:20px;">💳 Изменить баланс пользователя</h3>
        <form method="POST">
            <div class="form-group">
                <label>👤 Пользователь</label>
                <select name="user_id" required>
                    <option value="">Выберите пользователя</option>
                    {% for user in users %}
                    <option value="{{ user.id }}">{{ user.username }} ({{ "%.2f"|format(user.balance) }} ₽)</option>
                    {% endfor %}
                </select>
            </div>
            <div class="form-group">
                <label>💰 Сумма</label>
                <input type="number" name="amount" placeholder="1000" step="0.01" required>
            </div>
            <div style="display:flex; gap:12px;">
                <button type="submit" name="action" value="add" class="btn btn-success" style="flex:1; justify-content:center;">➕ Добавить</button>
                <button type="submit" name="action" value="set" class="btn btn-warning" style="flex:1; justify-content:center; background:var(--warning);">📌 Установить</button>
            </div>
        </form>
    </div>

    <div style="background:var(--bg-card); border:1px solid var(--border); border-radius:var(--radius); overflow:hidden;">
        <h3 style="padding:24px; margin:0;">👥 Все пользователи</h3>
        <div style="overflow-x:auto;">
            <table class="admin-table">
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Логин</th>
                        <th>Баланс</th>
                        <th>Админ</th>
                    </tr>
                </thead>
                <tbody>
                    {% for user in users %}
                    <tr>
                        <td>#{{ user.id }}</td>
                        <td><strong>{{ user.username }}</strong></td>
                        <td style="color:var(--success); font-weight:600;">{{ "%.2f"|format(user.balance) }} ₽</td>
                        <td>{% if user.is_admin %}✅{% else %}—{% endif %}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
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
        cur.execute("SELECT COUNT(*) FROM users")
        if cur.fetchone()[0] == 0:
            cur.execute(
                "INSERT INTO users (username, password_hash, is_admin, balance) VALUES (%s, %s, TRUE, 999999.00)",
                ("admin", generate_password_hash("admin123"))
            )
    db.commit()

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

# --- Маршруты (без изменений в логике) ---
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
    return render_template_string(INDEX_PAGE, accounts=accounts)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if not username or not password:
            flash('Заполните все поля', 'error')
            return render_template_string(REGISTER_PAGE)
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
    return render_template_string(REGISTER_PAGE)

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
    return render_template_string(LOGIN_PAGE)

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
    return render_template_string(DEPOSIT_PAGE)

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
    return render_template_string(INDEX_PAGE, accounts=accounts)

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
    return render_template_string(ACCOUNT_DETAIL_PAGE, account=account)

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
        
        cur.execute("UPDATE users SET balance = balance - %s WHERE id = %s", (account['price'], g.user['id']))
        cur.execute("UPDATE users SET balance = balance + %s WHERE id = %s", (seller_earn, account['seller_id']))
        cur.execute("UPDATE accounts SET is_sold = TRUE WHERE id = %s", (account_id,))
        cur.execute(
            "INSERT INTO purchases (buyer_id, account_id, phone_number) VALUES (%s, %s, %s) RETURNING id",
            (g.user['id'], account_id, 'Загрузка...')
        )
        purchase = cur.fetchone()
        db.commit()
        
        phone = extract_phone_from_session(account['session_string'])
        if phone:
            cur.execute("UPDATE purchases SET phone_number = %s WHERE id = %s", (phone, purchase['id']))
            db.commit()
        
        flash('Покупка успешна! Перейдите в "Мои покупки" для получения кода.', 'success')
        return redirect(url_for('my_purchases'))

def extract_phone_from_session(session_string):
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
    return render_template_string(PURCHASES_PAGE, purchases=purchases)

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
            cur.execute("UPDATE purchases SET code_retrieved = TRUE WHERE id = %s", (purchase_id,))
            db.commit()
            return jsonify({'code': code})
        return jsonify({'error': 'Не удалось найти код в сообщениях'}), 404

def extract_latest_code(session_string):
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
            try:
                client.disconnect()
            except:
                pass

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'verify_phone':
            phone = request.form.get('phone', '').strip()
            if not phone.startswith('+'):
                phone = '+' + phone
            result = send_verification_code(phone)
            if result:
                session['verify_phone'] = phone
                session['code_hash'] = result
                session.pop('2fa_needed', None)
                flash('Код отправлен в Telegram', 'info')
            else:
                flash('Ошибка отправки кода', 'error')
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
                    session_string = client.session.save()
                    session['phone_verified'] = True
                    session['session_string'] = session_string
                    session.pop('2fa_needed', None)
                    session.pop('code_hash', None)
                    flash('Телефон подтвержден!', 'success')
                except SessionPasswordNeededError:
                    session['2fa_needed'] = True
                    session['client_temp'] = client.session.save()
                    flash('Требуется пароль 2FA', 'info')
                except PhoneCodeInvalidError:
                    flash('Неверный код', 'error')
                except Exception as e:
                    flash(f'Ошибка: {str(e)}', 'error')
                finally:
                    if not session.get('2fa_needed'):
                        client.disconnect()
            except Exception as e:
                flash(f'Ошибка: {str(e)}', 'error')
        elif action == 'confirm_2fa':
            password = request.form.get('password_2fa', '').strip()
            try:
                client = TelegramClient(StringSession(session.get('client_temp', '')), API_ID, API_HASH)
                client.connect()
                try:
                    client.sign_in(password=password)
                    session_string = client.session.save()
                    session['phone_verified'] = True
                    session['session_string'] = session_string
                    session.pop('2fa_needed', None)
                    session.pop('code_hash', None)
                    session.pop('client_temp', None)
                    flash('2FA подтвержден!', 'success')
                except Exception as e:
                    flash(f'Неверный пароль 2FA: {str(e)}', 'error')
                finally:
                    client.disconnect()
            except Exception as e:
                flash(f'Ошибка: {str(e)}', 'error')
    return render_template_string(PROFILE_PAGE)

def send_verification_code(phone):
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
            try:
                client.disconnect()
            except:
                pass

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
            return render_template_string(SELL_PAGE)
        
        session_string = session.get('session_string')
        flash('Собираем данные аккаунта...', 'info')
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
                account_data.get('country', 'Не определена'), 
                account_data.get('has_2fa', has_2fa),
                account_data.get('spamblock', False), 
                account_data.get('chats_count', 0),
                account_data.get('channels_count', 0), 
                account_data.get('groups_count', 0)
            ))
        db.commit()
        
        session.pop('phone_verified', None)
        session.pop('session_string', None)
        session.pop('verify_phone', None)
        session.pop('code_hash', None)
        session.pop('client_temp', None)
        session.pop('2fa_needed', None)
        
        flash('Аккаунт выставлен на продажу!', 'success')
        return redirect(url_for('index'))
    
    return render_template_string(SELL_PAGE)

def gather_account_data(session_string):
    data = {'country': 'Не определена', 'has_2fa': False, 'spamblock': False, 'chats_count': 0, 'channels_count': 0, 'groups_count': 0}
    client = None
    try:
        client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
        client.connect()
        if not client.is_user_authorized():
            return data
        try:
            client.get_password_hint()
            data['has_2fa'] = True
        except:
            pass
        dialogs = client.get_dialogs(limit=100)
        for dialog in dialogs:
            if dialog.is_channel:
                if hasattr(dialog.entity, 'megagroup') and dialog.entity.megagroup:
                    data['groups_count'] += 1
                else:
                    data['channels_count'] += 1
            else:
                data['chats_count'] += 1
    except:
        pass
    finally:
        if client:
            try:
                client.disconnect()
            except:
                pass
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
    return render_template_string(ADMIN_PAGE, users=users)

if __name__ == '__main__':
    with app.app_context():
        try:
            init_db()
            print("✓ База данных готова")
        except Exception as e:
            print(f"✗ Ошибка БД: {e}")
    app.run(debug=True, host='0.0.0.0', port=5000)
