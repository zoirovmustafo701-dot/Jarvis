import asyncio
import json
import os
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from aiohttp import web
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# 🛡️ БЕЗОПАСНОСТЬ: Токен берется из переменных окружения Render или локального терминала
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ ОШИБКА: Переменная окружения BOT_TOKEN не найдена! Установите её в Render или локально.")

# ✅ ИСПРАВЛЕНО: Твой реальный Telegram ID
ADMIN_ID = 6141071010 

PAY_PHONE = "+992931580081"
PAY_WALLET = "Душанбе Сити (Dushanbe City)"
PAY_PRICE = "30 сомони (3$)"
DB_FILE = Path("plus_keys.json")


def load_db() -> dict:
    if DB_FILE.exists():
        data = json.loads(DB_FILE.read_text(encoding="utf-8"))
        if "keys" not in data:
            data["keys"] = {}
        return data
    # Создаем тестовый ключ только если файла нет
    data = {
        "keys": {
            "JPLUS-TESTKEY": {
                "user_id": 0,
                "used": False,
                "expires_at": (datetime.now() + timedelta(days=1)).isoformat(),
            }
        }
    }
    save_db(data)
    return data


def save_db(data: dict) -> None:
    DB_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def create_one_time_key(user_id: int) -> tuple[str, str]:
    db = load_db()
    key = "JPLUS-" + secrets.token_hex(4).upper()
    expires_at = (datetime.now() + timedelta(days=30)).isoformat()
    db["keys"][key] = {
        "user_id": user_id,
        "used": False,
        "expires_at": expires_at,
    }
    save_db(db)
    return key, datetime.fromisoformat(expires_at).strftime("%d.%m.%Y %H:%M")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"Здравствуйте! Подписка JARVIS PLUS на 1 месяц стоит {PAY_PRICE}.\n"
        f"Переведите {PAY_PRICE} на номер {PAY_PHONE} ({PAY_WALLET}) и отправьте сюда фото или файл чека.\n"
        f"После проверки администратором вам придёт личный одноразовый ключ на 30 дней."
    )


async def handle_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    user = msg.from_user
    caption = msg.caption or msg.text or "(без комментария)"
    
    # Проверка на наличие ADMIN_ID
    if ADMIN_ID == 0:
        await msg.reply_text("Ошибка конфигурации: Администратор не назначен.")
        return

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Разрешить PLUS (30 дней)", callback_data=f"allow:{user.id}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"deny:{user.id}"),
            ]
        ]
    )
    info_text = (
        f"Новый чек ({PAY_PRICE} · {PAY_PHONE} · {PAY_WALLET}):\n"
        f"Имя: {user.full_name}\n"
        f"Username: @{user.username or 'нет'}\n"
        f"ID: {user.id}\n"
        f"Комментарий: {caption}"
    )

    try:
        if msg.photo:
            await context.bot.send_photo(
                chat_id=ADMIN_ID,
                photo=msg.photo[-1].file_id,
                caption=info_text,
                reply_markup=keyboard,
            )
        elif msg.document:
            await context.bot.send_document(
                chat_id=ADMIN_ID,
                document=msg.document.file_id,
                caption=info_text,
                reply_markup=keyboard,
            )
        else:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=info_text,
                reply_markup=keyboard,
            )
        await msg.reply_text("Чек отправлен администратору. Ожидайте подтверждения оплаты.")
    except Exception as e:
        await msg.reply_text(f"Ошибка отправки админу: {e}")


async def on_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    # Проверка безопасности: только админ может нажимать кнопки
    if query.from_user.id != ADMIN_ID:
        await query.answer("⛔ Доступ запрещен", show_alert=True)
        return

    action, raw_uid = query.data.split(":", 1)
    target_uid = int(raw_uid)

    if action == "allow":
        key, exp_str = create_one_time_key(target_uid)
        try:
            await context.bot.send_message(
                chat_id=target_uid,
                text=(
                    f"Оплата {PAY_PRICE} подтверждена! Подключён JARVIS PLUS на 1 месяц (до {exp_str}).\n"
                    f"Ваш личный одноразовый ключ для сайта (действует только 1 раз):\n{key}"
                ),
            )
            if query.message.caption is not None:
                await query.edit_message_caption(caption=query.message.caption + f"\n\n✅ ВЫДАН КЛЮЧ: {key}")
            else:
                await query.edit_message_text(text=(query.message.text or "") + f"\n\n✅ ВЫДАН КЛЮЧ: {key}")
        except Exception as e:
            await query.answer(f"Ошибка отправки ключа: {e}")
    else:
        try:
            await context.bot.send_message(
                chat_id=target_uid,
                text=f"Чек отклонён. Переведите {PAY_PRICE} на {PAY_PHONE} ({PAY_WALLET}) и отправьте чек снова.",
            )
            if query.message.caption is not None:
                await query.edit_message_caption(caption=query.message.caption + "\n\n❌ ОТКЛОНЕНО")
            else:
                await query.edit_message_text(text=(query.message.text or "") + "\n\n❌ ОТКЛОНЕНО")
        except Exception as e:
            await query.answer(f"Ошибка уведомления: {e}")


async def verify_http(request: web.Request) -> web.Response:
    headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }
    if request.method == "OPTIONS":
        return web.Response(status=204, headers=headers)

    try:
        data = await request.json()
    except:
        return web.json_response({"ok": False, "error": "Invalid JSON"}, headers=headers, status=400)

    code = str(data.get("code", "")).strip().upper()
    db = load_db()
    rec = db.get("keys", {}).get(code)
    
    client_ip = request.headers.get('X-Forwarded-For', request.remote)

    if not rec:
        return web.json_response(
            {"ok": False, "error": "Ключ не найден. Оплатите 30 сомони (3$) и отправьте чек в Telegram-бот."},
            headers=headers,
        )
    if rec.get("used"):
        return web.json_response(
            {"ok": False, "error": "Этот ключ уже был использован."},
            headers=headers,
        )
    if datetime.fromisoformat(rec["expires_at"]) <= datetime.now():
        return web.json_response(
            {"ok": False, "error": "Срок действия ключа истёк."},
            headers=headers,
        )

    rec["used"] = True
    rec["activated_at"] = datetime.now().isoformat()
    rec["activated_ip"] = client_ip
    save_db(db)
    return web.json_response({"ok": True, "expires_at": rec["expires_at"]}, headers=headers)


async def run_all() -> None:
    load_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL | (filters.TEXT & ~filters.COMMAND), handle_receipt))
    app.add_handler(CallbackQueryHandler(on_decision))

    web_app = web.Application()
    web_app.router.add_route("*", "/verify", verify_http)
    runner = web.AppRunner(web_app)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 8765))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"✅ HTTP сервер запущен на порту {port}")

    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(run_all())