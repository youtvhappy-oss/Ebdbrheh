import sys
import subprocess
import os

# 1. تثبيت المكتبات والاعتماديات تلقائياً
def check_and_install_dependencies():
    required_packages = {
        "pyrogram": "pyrogram",
        "tgcrypto": "tgcrypto",
        "nest_asyncio": "nest_asyncio",
        "requests": "requests",
        "aiohttp": "aiohttp",
        "yt_dlp": "yt-dlp",
        "gdown": "gdown",
        "bs4": "bs4",
        "playwright": "playwright"
    }
    
    missing_packages = []
    for module, pip_name in required_packages.items():
        try:
            __import__(module)
        except ImportError:
            missing_packages.append(pip_name)
            
    if missing_packages:
        print(f"📦 جاري تثبيت المكتبات الناقصة: {', '.join(missing_packages)}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing_packages)
    else:
        print("✅ جميع مكتبات Python مثبتة مسبقاً.")

    try:
        subprocess.run(["aria2c", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except Exception:
        print("⚙️ جاري تثبيت حزمة aria2...")
        os.system("apt-get update -y && apt-get install -y aria2")

    firefox_cache = os.path.expanduser("~/.cache/ms-playwright")
    if not os.path.exists(firefox_cache) or not any("firefox" in f for f in os.listdir(firefox_cache) if os.path.isdir(os.path.join(firefox_cache, f))):
        print("🦊 جاري تثبيت متصفح Firefox الخفيف...")
        os.system("playwright install firefox")
        os.system("playwright install-deps firefox")
    else:
        print("✅ متصفح Firefox الخفيف مثبت وجاهز للعمل.")

check_and_install_dependencies()

# ==========================================
# 2. استيراد المكتبات والتهيئات
# ==========================================
import warnings
warnings.filterwarnings("ignore")

import gc
import time
import math
import asyncio
import nest_asyncio
import requests
import aiohttp
import gdown
from google.colab import userdata
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from playwright.async_api import async_playwright

nest_asyncio.apply()
gc.collect()

API_ID = int(userdata.get('API_ID').strip())
API_HASH = userdata.get('API_HASH').strip()
BOT_TOKEN = userdata.get('BOT_TOKEN').strip()

MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024 

DOWNLOAD_DIR = os.path.abspath("./downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

user_chat_id = None
ping_task = None

user_modes = {}       # {chat_id: "link_to_file" أو "file_to_link"}
pending_urls = {}     # {chat_id: "url"} للتخزين المؤقت لروابط Drive

bot = Client(
    f"bot_session_{int(time.time())}",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True
)

def humanbytes(size):
    if not size:
        return "0 B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size, 1024)))
    p = math.pow(1024, i)
    s = round(size / p, 2)
    return f"{s} {size_name[i]}"

async def keep_alive_ping():
    global user_chat_id
    while True:
        await asyncio.sleep(1200)
        if user_chat_id:
            try:
                await bot.send_message(chat_id=user_chat_id, text=".")
                print("🟢 تم إرسال إشارة النشاط لمنع الخمول.")
            except Exception as e:
                print(f"⚠️ تعذر إرسال الإشارة: {e}")

# قارئ مخصص للرفع اللحظي عبر aiohttp لتجنب مشاكل الخيوط والتكرار
class AsyncProgressFileReader:
    def __init__(self, filename, callback):
        self.filename = filename
        self.file = open(filename, 'rb')
        self.total_size = os.path.getsize(filename)
        self.uploaded = 0
        self.callback = callback

    async def __aiter__(self):
        chunk_size = 64 * 1024
        while True:
            chunk = self.file.read(chunk_size)
            if not chunk:
                break
            self.uploaded += len(chunk)
            await self.callback(self.uploaded, self.total_size)
            yield chunk

    def close(self):
        self.file.close()

# 🚀 دالة الرفع إلى Fileditch مع إظهار النسبة المئوية والتقدم بشكل async كامل
async def upload_to_fileditch_with_progress(file_path, status_msg):
    url = "https://new.fileditch.com/upload.php"
    start_time = time.time()
    last_update = [0]

    async def on_upload_progress(current, total):
        now = time.time()
        if now - last_update[0] >= 3 or current == total:
            last_update[0] = now
            percentage = (current / total * 100) if total > 0 else 0
            speed = current / (now - start_time) if (now - start_time) > 0 else 1
            eta = round((total - current) / speed) if speed > 0 else 0

            filled = int(10 * current // total)
            bar = '█' * filled + '░' * (10 - filled)

            text = (
                f"⬆️ **جاري الرفع إلى Fileditch...**\n\n"
                f"[{bar}] {percentage:.1f}%\n"
                f"🚀 **السرعة:** {humanbytes(speed)}/s\n"
                f"📦 **المرفوع:** {humanbytes(current)} / {humanbytes(total)}\n"
                f"⏱️ **المتبقي:** {eta}s"
            )
            try:
                await status_msg.edit_text(text)
            except Exception:
                pass

    reader = AsyncProgressFileReader(file_path, on_upload_progress)
    try:
        data = aiohttp.FormData()
        data.add_field('file', reader, filename=os.path.basename(file_path))
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data) as resp:
                response = await resp.json()
    finally:
        reader.close()

    if response.get("success"):
        return response.get("url")
    else:
        raise Exception(response.get("error", "فشل الرفع إلى Fileditch."))

# 🌐 معالج GoFile باستخدام Firefox الخفيف
async def download_from_gofile(url):
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)
        
        download_button = page.locator("a.filesContentTableActionsDownload, button:has-text('Download')").first
        async with page.expect_download(timeout=120000) as download_info:
            await download_button.click()
        
        download = await download_info.value
        file_path = os.path.join(DOWNLOAD_DIR, download.suggested_filename)
        await download.save_as(file_path)
        await browser.close()
        return file_path

# 🌐 معالج WorkUpload باستخدام Firefox الخفيف
async def download_from_workupload(url):
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)
        
        download_button = page.locator("a.btn-download, a:has-text('Download')").first
        async with page.expect_download(timeout=120000) as download_info:
            await download_button.click()
        
        download = await download_info.value
        file_path = os.path.join(DOWNLOAD_DIR, download.suggested_filename)
        await download.save_as(file_path)
        await browser.close()
        return file_path

# 📥 دالة التحميل المباشر مع النسبة المئوية
async def download_direct(url, status_msg):
    file_name = os.path.join(DOWNLOAD_DIR, url.split("/")[-1].split("?")[0] or "downloaded_file.bin")
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            start_time = time.time()
            last_update = 0

            with open(file_name, 'wb') as f:
                async for chunk in response.content.iter_chunked(1024 * 1024):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        now = time.time()
                        
                        if now - last_update >= 3 or (total_size > 0 and downloaded == total_size):
                            last_update = now
                            percentage = (downloaded / total_size * 100) if total_size > 0 else 0
                            speed = downloaded / (now - start_time) if (now - start_time) > 0 else 1
                            eta = round((total_size - downloaded) / speed) if speed > 0 and total_size > 0 else 0
                            
                            filled = int(10 * downloaded // total_size) if total_size > 0 else 0
                            bar = '█' * filled + '░' * (10 - filled)

                            text = (
                                f"⬇️ **جاري التنزيل المباشر إلى السيرفر...**\n\n"
                                f"[{bar}] {percentage:.1f}%\n"
                                f"🚀 **السرعة:** {humanbytes(speed)}/s\n"
                                f"📦 **المُحمل:** {humanbytes(downloaded)} / {humanbytes(total_size if total_size > 0 else downloaded)}\n"
                                f"⏱️ **المتبقي:** {eta}s"
                            )
                            try:
                                await status_msg.edit_text(text)
                            except Exception:
                                pass
                        
    return file_name

# 🔘 لوحات التحكم بالزرار
def get_main_keyboard(current_mode):
    btn1_text = "✅ رابط ⬅️ ملف (تليجرام)" if current_mode == "link_to_file" else "رابط ⬅️ ملف (تليجرام)"
    btn2_text = "✅ ملف ⬅️ رابط (Fileditch)" if current_mode == "file_to_link" else "ملف ⬅️ رابط (Fileditch)"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(btn1_text, callback_data="mode_link_to_file")],
        [InlineKeyboardButton(btn2_text, callback_data="mode_file_to_link")]
    ])
    return keyboard

def get_gdrive_options_keyboard():
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 تنزيل إلى Drive ثم التحويل لـ Fileditch", callback_data="gdrive_download_first")],
        [InlineKeyboardButton("⚡ النقل المباشر من Google Drive إلى Fileditch", callback_data="gdrive_direct_fileditch")]
    ])
    return keyboard

@bot.on_message(filters.command("start") & filters.private)
async def start_handler(client, message: Message):
    global user_chat_id, ping_task
    user_chat_id = message.chat.id
    
    if ping_task is None or ping_task.done():
        ping_task = asyncio.create_task(keep_alive_ping())
        
    user_modes[message.chat.id] = user_modes.get(message.chat.id, "link_to_file")
    
    await message.reply_text(
        "أهلاً بك في البوت الشامل! 🚀\n\n"
        "الرجاء اختيار الوضع المفضل للتعامل مع البوت من الأزرار أدناه:",
        reply_markup=get_main_keyboard(user_modes[message.chat.id])
    )

@bot.on_callback_query(filters.regex(r'^mode_'))
async def mode_callback(client, callback: CallbackQuery):
    mode = callback.data.replace("mode_", "")
    user_modes[callback.message.chat.id] = mode
    
    mode_msg = "الوضع الحالي: **تحويل الرابط إلى ملف وإرساله إليك** 📥" if mode == "link_to_file" else "الوضع الحالي: **تحويل الملف المرفوع إلى رابط Fileditch** 🔗"
    
    await callback.message.edit_text(
        f"تم تغيير الوضع بنجاح! ✅\n\n{mode_msg}\n\nاختر العملية التي تريدها دائماً عبر الأزرار:",
        reply_markup=get_main_keyboard(mode)
    )
    await callback.answer("تم حفظ الاختيار")

# 📥 1. استقبال الروابط ومعالجتها
@bot.on_message(filters.regex(r'https?://[^\s]+') & filters.private)
async def handle_links(client, message: Message):
    mode = user_modes.get(message.chat.id, "link_to_file")
    url = message.text.strip()

    if mode == "file_to_link" and ("drive.google.com" in url or "docs.google.com" in url):
        pending_urls[message.chat.id] = url
        await message.reply_text(
            "⚙️ **تم اكتشاف رابط Google Drive!**\nكيف ترغب في معالجة الملف للرفع إلى Fileditch؟",
            reply_markup=get_gdrive_options_keyboard()
        )
        return

    if mode != "link_to_file":
        await message.reply_text("⚠️ أنت في وضع **(ملف ⬅️ رابط)**. يرجى إرسال ملف أو رابط Google Drive المخصص لـ Fileditch.")
        return

    status_msg = await message.reply_text("⚡ جاري تحليل الرابط واختيار المحرك...")
    file_path = None
    last_update = [0]

    try:
        if "gofile.io" in url:
            await status_msg.edit_text("🦊 جاري تشغيل المتصفح الخفيف والتحميل من GoFile...")
            file_path = await download_from_gofile(url)

        elif "workupload.com" in url:
            await status_msg.edit_text("🦊 جاري تشغيل المتصفح الخفيف والتحميل من WorkUpload...")
            file_path = await download_from_workupload(url)

        else:
            file_path = await download_direct(url, status_msg)

        if not file_path or not os.path.exists(file_path):
            raise Exception("تعذر تنزيل الملف، يرجى التأكد من صحة الرابط.")

        local_size = os.path.getsize(file_path)
        if local_size > MAX_FILE_SIZE:
            raise Exception(f"الملف كبير جداً ({humanbytes(local_size)}).")

        await status_msg.edit_text(f"🚀 تم التنزيل بنجاح ({humanbytes(local_size)})!\nجاري الرفع إلى تليجرام...")
        start_time = time.time()

        async def upload_progress(current, total):
            now = time.time()
            if now - last_update[0] >= 3:
                last_update[0] = now
                percentage = current * 100 / total
                speed = current / (now - start_time) if (now - start_time) > 0 else 1
                eta = round((total - current) / speed) if speed > 0 else 0

                filled = int(10 * current // total)
                bar = '█' * filled + '░' * (10 - filled)

                text = (
                    f"⬆️ **جاري الرفع إلى تليجرام...**\n\n"
                    f"[{bar}] {percentage:.1f}%\n"
                    f"🚀 **السرعة:** {humanbytes(speed)}/s\n"
                    f"📦 **المرفوع:** {humanbytes(current)} / {humanbytes(total)}\n"
                    f"⏱️ **المتبقي:** {eta}s"
                )
                try:
                    await status_msg.edit_text(text)
                except Exception:
                    pass

        if file_path.lower().endswith(('.mp4', '.mkv', '.avi', '.mov')):
            await message.reply_video(video=file_path, caption=f"🎬 `{os.path.basename(file_path)}`", progress=upload_progress)
        else:
            await message.reply_document(document=file_path, caption=f"📦 `{os.path.basename(file_path)}`", progress=upload_progress)

        await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text(f"❌ حدث خطأ:\n`{str(e)}`")

    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

# 🔄 معالجة خيارات Google Drive بالزرار
@bot.on_callback_query(filters.regex(r'^gdrive_'))
async def gdrive_callback(client, callback: CallbackQuery):
    chat_id = callback.message.chat.id
    action = callback.data
    url = pending_urls.get(chat_id)

    if not url:
        await callback.answer("❌ تعذر العثور على الرابط، الرجاء إعادة إرساله.", show_alert=True)
        return

    status_msg = await callback.message.edit_text("⏳ جاري بدء معالجة الرابط عبر Google Drive...")
    file_path = None

    try:
        await status_msg.edit_text("📥 جاري تنزيل الملف من Google Drive...")
        loop = asyncio.get_event_loop()
        file_path = os.path.join(DOWNLOAD_DIR, f"gdrive_{int(time.time())}.bin")
        
        await loop.run_in_executor(None, lambda: gdown.download(url, file_path, quiet=True))

        if not os.path.exists(file_path):
            raise Exception("فشل تنزيل الملف من Google Drive.")

        fileditch_url = await upload_to_fileditch_with_progress(file_path, status_msg)
        file_name = os.path.basename(file_path)
        file_size = humanbytes(os.path.getsize(file_path))

        await status_msg.edit_text(
            f"✅ **تم تحويل الملف من Google Drive إلى Fileditch بنجاح!**\n\n"
            f"📁 **اسم الملف:** `{file_name}`\n"
            f"📦 **الحجم:** `{file_size}`\n\n"
            f"🔗 **رابط التحميل المباشر:**\n{fileditch_url}"
        )

    except Exception as e:
        await status_msg.edit_text(f"❌ حدث خطأ أثناء المعالجة:\n`{str(e)}`")

    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        pending_urls.pop(chat_id, None)

# 📤 2. استقبال الملفات وتحويلها إلى Fileditch مع شريط النسبة اللحظي
@bot.on_message((filters.document | filters.video | filters.audio) & filters.private)
async def handle_files(client, message: Message):
    mode = user_modes.get(message.chat.id, "link_to_file")
    
    if mode != "file_to_link":
        await message.reply_text("⚠️ أنت في وضع **(رابط ⬅️ ملف)**. يرجى التبديل إلى وضع **(ملف ⬅️ رابط)** من القائمة أولاً.")
        return

    status_msg = await message.reply_text("⬇️ جاري بدء تحميل الملف من تليجرام...")
    file_path = None
    last_update = [0]
    start_time = time.time()

    async def download_progress(current, total):
        now = time.time()
        if now - last_update[0] >= 3:
            last_update[0] = now
            percentage = current * 100 / total
            speed = current / (now - start_time) if (now - start_time) > 0 else 1
            eta = round((total - current) / speed) if speed > 0 else 0

            filled = int(10 * current // total)
            bar = '█' * filled + '░' * (10 - filled)

            text = (
                f"⬇️ **جاري التحميل من تليجرام إلى السيرفر...**\n\n"
                f"[{bar}] {percentage:.1f}%\n"
                f"🚀 **السرعة:** {humanbytes(speed)}/s\n"
                f"📦 **المُحمل:** {humanbytes(current)} / {humanbytes(total)}\n"
                f"⏱️ **المتبقي:** {eta}s"
            )
            try:
                await status_msg.edit_text(text)
            except Exception:
                pass

    try:
        file_path = await message.download(progress=download_progress)
        fileditch_url = await upload_to_fileditch_with_progress(file_path, status_msg)

        file_name = os.path.basename(file_path)
        file_size = humanbytes(os.path.getsize(file_path))

        await status_msg.edit_text(
            f"✅ **تم تحويل الملف إلى رابط بنجاح!**\n\n"
            f"📁 **اسم الملف:** `{file_name}`\n"
            f"📦 **الحجم:** `{file_size}`\n\n"
            f"🔗 **رابط التحميل المباشر:**\n{fileditch_url}"
        )

    except Exception as e:
        await status_msg.edit_text(f"❌ حدث خطأ أثناء المعالجة:\n`{str(e)}`")

    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

async def start_bot():
    try:
        await bot.start()
        print("🟢 تم تشغيل البوت بنجاح ومزود بنسب التقدم اللحظية!")
        await idle()
    except Exception as e:
        print(f"⚠️ تنبيه أثناء التشغيل: {e}")
    finally:
        await bot.stop()

if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(start_bot())
    except KeyboardInterrupt:
        print("\n🛑 تم إيقاف البوت.")
