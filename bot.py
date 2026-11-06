"""بات تلگرام: تبدیل SRT به Word"""
import io
import logging
import os
import zipfile
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
    MessageHandler, filters,
)

from converter import srt_bytes_to_docx

logging.basicConfig(level=logging.INFO)
TOKEN = os.environ.get("BOT_TOKEN")
MAX_SIZE = 20 * 1024 * 1024       # سقف دانلود بات‌های تلگرام ۲۰ مگابایت است
MAX_UNZIPPED = 100 * 1024 * 1024  # سقف حجم باز شده‌ی zip
MAX_FILES = 300                   # سقف تعداد srt داخل zip
MAX_SEPARATE = 10                 # تا ۱۰ فایل جدا می‌فرستد، بیشتر از آن یک zip


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
        "سلام 👋\nفایل زیرنویس ‎.srt‎ یا یه فایل ‎.zip‎ پر از srt بفرست تا برات فایل Word بسازم.\n\n"
        "حالت خروجی رو از دکمه‌های زیر انتخاب کن:",
        reply_markup=mode_keyboard(with_times),
    )


async def toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "toggle":
        context.user_data["with_times"] = not context.user_data.get("with_times", False)
        await q.edit_message_reply_markup(mode_keyboard(context.user_data["with_times"]))


def _zip_name(info: zipfile.ZipInfo) -> str:
    """اسم فارسی فایل‌های داخل zip ویندوزی معمولاً خراب نمایش داده می‌شود؛ درستش می‌کنیم."""
    name = info.filename
    if not info.flag_bits & 0x800:
        raw = name.encode("cp437", errors="ignore")
        for enc in ("utf-8", "cp1256", "cp720"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
    return name


def srts_from_zip(data: bytes):
    """همه‌ی فایل‌های srt داخل zip (حتی داخل پوشه‌ها) را برمی‌گرداند: [(اسم، محتوا)]"""
    out, total = [], 0
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            name = _zip_name(info)
            base = Path(name.replace("\\", "/")).name
            if info.is_dir() or not base.lower().endswith(".srt") or base.startswith("._"):
                continue
            total += info.file_size
            if total > MAX_UNZIPPED or len(out) >= MAX_FILES:
                raise ValueError("too big")
            out.append((base, zf.read(info)))
    return out


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    name = doc.file_name or "subtitle.srt"
    lower = name.lower()
    if not lower.endswith((".srt", ".zip")):
        await update.message.reply_text("⚠️ فقط فایل ‎.srt‎ یا ‎.zip‎ قبول می‌کنم.")
        return
    if doc.file_size and doc.file_size > MAX_SIZE:
        await update.message.reply_text("⚠️ حجم فایل زیاده (حداکثر ۲۰ مگابایت).")
        return

    msg = await update.message.reply_text("⏳ در حال تبدیل...")
    tg_file = await doc.get_file()
    data = bytes(await tg_file.download_as_bytearray())

    if lower.endswith(".zip"):
        try:
            srts = srts_from_zip(data)
        except ValueError:
            await msg.edit_text("❌ فایل zip خیلی بزرگه یا فایل‌های زیادی داره.")
            return
        except zipfile.BadZipFile:
            await msg.edit_text("❌ فایل zip خرابه یا رمز داره.")
            return
        if not srts:
            await msg.edit_text("❌ توی این zip هیچ فایل ‎.srt‎ پیدا نکردم.")
            return
    else:
        srts = [(name, data)]

    with_times = context.user_data.get("with_times", False)
    results, used = [], set()
    for srt_name, srt_data in srts:
        stem = Path(srt_name).stem
        out_name, i = f"{stem}.docx", 2
        while out_name in used:  # اسم تکراری
            out_name, i = f"{stem} ({i}).docx", i + 1
        used.add(out_name)
        try:
            docx_bytes, count = srt_bytes_to_docx(srt_data, stem, with_times)
        except Exception:
            logging.exception("conversion failed: %s", srt_name)
            continue
        if count:
            results.append((out_name, docx_bytes, count))

    if not results:
        await msg.edit_text("❌ هیچ زیرنویسی توی فایل پیدا نکردم.")
        return

    if len(results) <= MAX_SEPARATE:
        for out_name, docx_bytes, count in results:
            await update.message.reply_document(
                document=io.BytesIO(docx_bytes), filename=out_name,
                caption=f"✅ {out_name} — {count} خط زیرنویس",
            )
    else:  # تعداد زیاد: همه را در یک zip می‌فرستیم
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for out_name, docx_bytes, _ in results:
                zf.writestr(out_name, docx_bytes)
        await update.message.reply_document(
            document=io.BytesIO(buf.getvalue()), filename=f"{Path(name).stem}-word.zip",
            caption=f"✅ {len(results)} فایل Word داخل این zip هست",
        )
    skipped = len(srts) - len(results)
    if skipped:
        await update.message.reply_text(f"⚠️ {skipped} فایل خالی بود یا خونده نشد.")
    await msg.delete()


async def other(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("فایل ‎.srt‎ یا ‎.zip‎ رو به صورت فایل (Document) بفرست 📎")


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
