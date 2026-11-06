"""بات تلگرام: تبدیل SRT به Word"""
import io
import logging
import os
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
    MessageHandler, filters,
)

from converter import srt_bytes_to_docx

logging.basicConfig(level=logging.INFO)
TOKEN = os.environ.get("BOT_TOKEN")
MAX_SIZE = 5 * 1024 * 1024  # ۵ مگابایت


def mode_keyboard(with_times: bool):
    label = "✅ با زمان‌بندی" if with_times else "✅ فقط متن"
    other = "فقط متن" if with_times else "با زمان‌بندی"
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(label, callback_data="noop"),
        InlineKeyboardButton(f"تغییر به: {other}", callback_data="toggle"),
    ]])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with_times = context.user_data.get("with_times", False)
    await update.message.reply_text(
        "سلام 👋\nفایل زیرنویس ‎.srt‎ رو بفرست تا برات فایل Word بسازم.\n\n"
        "حالت خروجی رو از دکمه‌های زیر انتخاب کن:",
        reply_markup=mode_keyboard(with_times),
    )


async def toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "toggle":
        context.user_data["with_times"] = not context.user_data.get("with_times", False)
        await q.edit_message_reply_markup(mode_keyboard(context.user_data["with_times"]))


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    name = doc.file_name or "subtitle.srt"
    if not name.lower().endswith(".srt"):
        await update.message.reply_text("⚠️ فقط فایل با پسوند ‎.srt‎ قبول می‌کنم.")
        return
    if doc.file_size and doc.file_size > MAX_SIZE:
        await update.message.reply_text("⚠️ حجم فایل زیاده (حداکثر ۵ مگابایت).")
        return

    msg = await update.message.reply_text("⏳ در حال تبدیل...")
    tg_file = await doc.get_file()
    data = bytes(await tg_file.download_as_bytearray())

    stem = Path(name).stem
    with_times = context.user_data.get("with_times", False)
    try:
        docx_bytes, count = srt_bytes_to_docx(data, stem, with_times)
    except Exception:
        logging.exception("conversion failed")
        await msg.edit_text("❌ مشکلی در خواندن فایل پیش اومد.")
        return
    if count == 0:
        await msg.edit_text("❌ هیچ زیرنویسی توی این فایل پیدا نکردم.")
        return

    await update.message.reply_document(
        document=io.BytesIO(docx_bytes),
        filename=f"{stem}.docx",
        caption=f"✅ آماده‌ست — {count} خط زیرنویس",
    )
    await msg.delete()


async def other(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("فایل ‎.srt‎ رو به صورت فایل (Document) بفرست 📎")


def main():
    if not TOKEN:
        raise SystemExit("متغیر BOT_TOKEN تنظیم نشده.")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(toggle))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, other))
    app.run_polling()


if __name__ == "__main__":
    main()
