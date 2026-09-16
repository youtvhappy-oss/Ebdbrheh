# -*- coding: utf-8 -*-
"""
🚀 البوت الشامل - MEGA + كشف نوع الملف تلقائياً
"""

# ==========================================
# 1. تثبيت المكتبات
# ==========================================
import subprocess
import sys

def install_packages():
    """تثبيت جميع المكتبات المطلوبة"""
    packages = [
        'pyrogram', 
        'tgcrypto', 
        'nest_asyncio', 
        'requests', 
        'playwright', 
        'libtorrent',
        'python-magic'  # 🆕 لكشف نوع الملف
    ]
    
    print("📦 تثبيت المكتبات...")
    
    for package in packages:
        try:
            __import__(package)
            print(f"✅ {package} مثبت")
        except ImportError:
            print(f"📥 تثبيت {package}...")
            subprocess.check_call([
                sys.executable, '-m', 'pip', 'install', 
                package, '-q'
            ])
    
    # تثبيت Firefox
    print("🦊 تثبيت Firefox...")
    subprocess.run(['playwright', 'install', 'firefox'], check=True)
    subprocess.run(['playwright', 'install-deps', 'firefox'], check=True)
    
    # تثبيت megatools لـ MEGA
    print("download تثبيت megatools لـ MEGA...")
    subprocess.run(['apt-get', 'update', '-qq'], capture_output=True)
    subprocess.run(['apt-get', 'install', '-y', '-qq', 'megatools'], capture_output=True)
    
    # تثبيت aria2
    subprocess.run(['apt-get', 'install', '-y', '-qq', 'aria2'], capture_output=True)
    
    print("✅ تم تثبيت جميع المكتبات")

install_packages()

# ==========================================
# 2. الاستيرادات
# ==========================================
import nest_asyncio
nest_asyncio.apply()

import os
import time
import math
import asyncio
import re
import urllib.parse
import gc
import mimetypes
import magic  # 🆕 لكشف نوع الملف
import requests
from google.colab import userdata
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from playwright.async_api import async_playwright
import libtorrent as lt

gc.collect()
print("✅ جميع المكتبات جاهزة")

# ==========================================
# 3. الإعدادات
# ==========================================
API_ID = int(userdata.get('API_ID').strip())
API_HASH = userdata.get('API_HASH').strip()
BOT_TOKEN = userdata.get('BOT_TOKEN').strip()
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024
DOWNLOAD_DIR = os.path.abspath("./downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

user_chat_id = None
ping_task = None
user_modes = {}

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
            except Exception:
                pass

# ==========================================
# 4. 🔍 كشف نوع الملف تلقائياً (جديد!)
# ==========================================
def detect_file_type(file_path):
    """
    🔍 كشف نوع الملف باستخدام python-magic
    """
    try:
        # قراءة أول 1024 bytes من الملف
        with open(file_path, 'rb') as f:
            header = f.read(1024)
        
        # استخدام python-magic لكشف النوع
        mime = magic.from_buffer(header, mime=True)
        
        # استخدام mimetypes كـ backup
        if not mime:
            mime, _ = mimetypes.guess_type(file_path)
        
        if not mime:
            mime = "application/octet-stream"
        
        return mime
        
    except Exception as e:
        print(f"⚠️ خطأ في كشف نوع الملف: {e}")
        return "application/octet-stream"

def get_file_category(file_path):
    """
    📂 تحديد فئة الملف (فيديو/صوت/مستند/صورة)
    """
    mime_type = detect_file_type(file_path)
    
    # فيديو
    if mime_type.startswith('video/'):
        return "video"
    # صوت
    elif mime_type.startswith('audio/'):
        return "audio"
    # صورة
    elif mime_type.startswith('image/'):
        return "image"
    # مستند
    else:
        return "document"

def get_mime_type(file_path):
    """
    🎯 الحصول على MIME type للملف
    """
    return detect_file_type(file_path)

# ==========================================
# 5. 🎯 محرك تحميل MEGA
# ==========================================
async def download_from_mega(url, status_msg):
    """
    📥 تحميل من MEGA باستخدام megatools
    """
    try:
        print(f"🌐 [MEGA] تحميل من: {url}")
        
        # التحقق من صحة رابط MEGA
        if 'mega.nz' not in url and 'mega.io' not in url:
            raise Exception("رابط MEGA غير صالح")
        
        # استخدام megatools للتحميل
        await status_msg.edit_text("📥 جاري التحميل من MEGA...")
        
        # إنشاء أمر megatools
        cmd = [
            'megadl',
            '--path', DOWNLOAD_DIR + os.sep,
            url
        ]
        
        # تشغيل الأمر
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )
        
        # قراءة المخرجات
        output = []
        async for line in process.stdout:
            line = line.decode().strip()
            if line:
                output.append(line)
                print(f"   📥 {line}")
        
        # انتظار الانتهاء
        await process.wait()
        
        if process.returncode != 0:
            raise Exception(f"فشل megatools: {output}")
        
        # البحث عن الملف المحمل
        files = [f for f in os.listdir(DOWNLOAD_DIR) if f not in ['temp.torrent']]
        
        if not files:
            raise Exception("لم يتم تحميل أي ملف")
        
        # اختيار أحدث ملف
        file_path = os.path.join(DOWNLOAD_DIR, sorted(files, key=lambda x: os.path.getmtime(os.path.join(DOWNLOAD_DIR, x)))[-1])
        
        # التحقق من الملف
        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            print(f"✅ [MEGA] تم تحميل: {file_path}")
            return file_path
        else:
            raise Exception("الملف فارغ أو غير موجود")
            
    except Exception as e:
        raise Exception(f"فشل تحميل MEGA: {str(e)}")

# ==========================================
# 6. محرك WorkUpload
# ==========================================
async def download_from_workupload(url, status_msg):
    try:
        async with async_playwright() as p:
            browser = await p.firefox.launch(headless=True)
            context = await browser.new_context(accept_downloads=True)
            page = await context.new_page()
            
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(5000)
                
                links = await page.evaluate("""
                    () => {
                        const allLinks = [];
                        document.querySelectorAll('a[href]').forEach(a => {
                            allLinks.push({
                                href: a.href,
                                text: a.textContent.trim()
                            });
                        });
                        return allLinks;
                    }
                """)
                
                start_url = None
                for link in links:
                    if '/start/' in link['href'] or 'download' in link['text'].lower():
                        start_url = link['href']
                        break
                
                if not start_url:
                    file_id = url.split('/')[-1]
                    start_url = f"https://workupload.com/start/{file_id}"
                
                await page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(10000)
                
                selectors = [
                    "a[href*='download']",
                    "a:has-text('Download')",
                    "button:has-text('Download')",
                    "a:has-text('Herunterladen')",
                    "button:has-text('Herunterladen')",
                    "a.btn-download",
                    "button.btn-download"
                ]
                
                download_file_path = None
                
                for selector in selectors:
                    try:
                        btn = page.locator(selector).first
                        if await btn.count() > 0 and await btn.is_visible():
                            
                            async with page.expect_download(timeout=120000) as download_info:
                                await btn.click()
                            
                            download = await download_info.value
                            filename = download.suggested_filename
                            
                            if not filename or len(filename) < 3:
                                filename = f"workupload_{int(time.time())}.bin"
                            
                            download_file_path = os.path.join(DOWNLOAD_DIR, filename)
                            
                            if os.path.exists(download_file_path):
                                base_name = os.path.splitext(filename)[0]
                                extension = os.path.splitext(filename)[1]
                                counter = 1
                                while os.path.exists(download_file_path):
                                    download_file_path = os.path.join(
                                        DOWNLOAD_DIR, 
                                        f"{base_name}_{counter}{extension}"
                                    )
                                    counter += 1
                            
                            await download.save_as(download_file_path)
                            break
                            
                    except Exception:
                        continue
                
                await browser.close()
                
                if download_file_path and os.path.exists(download_file_path):
                    return download_file_path
                else:
                    raise Exception("لم يتم تحميل الملف")
                    
            except Exception as e:
                await browser.close()
                raise Exception(f"فشل WorkUpload: {str(e)}")
                
    except Exception as e:
        raise Exception(f"خطأ في WorkUpload: {str(e)}")

# ==========================================
# 7. محرك GoFile
# ==========================================
async def download_from_gofile(url, status_msg):
    try:
        async with async_playwright() as p:
            browser = await p.firefox.launch(headless=True)
            context = await browser.new_context(accept_downloads=True)
            page = await context.new_page()
            
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(10000)
                
                selectors = [
                    "a.filesContentTableActionsDownload",
                    "a:has-text('Download')",
                    "button:has-text('Download')",
                    "a[href*='download']",
                    "a.btn-download",
                    "button.btn-download"
                ]
                
                download_file_path = None
                
                for selector in selectors:
                    try:
                        btn = page.locator(selector).first
                        if await btn.count() > 0 and await btn.is_visible():
                            
                            async with page.expect_download(timeout=300000) as download_info:
                                await btn.click()
                            
                            download = await download_info.value
                            filename = download.suggested_filename
                            
                            if not filename or len(filename) < 3:
                                filename = f"gofile_{int(time.time())}.bin"
                            
                            download_file_path = os.path.join(DOWNLOAD_DIR, filename)
                            
                            if os.path.exists(download_file_path):
                                base_name = os.path.splitext(filename)[0]
                                extension = os.path.splitext(filename)[1]
                                counter = 1
                                while os.path.exists(download_file_path):
                                    download_file_path = os.path.join(
                                        DOWNLOAD_DIR, 
                                        f"{base_name}_{counter}{extension}"
                                    )
                                    counter += 1
                            
                            await download.save_as(download_file_path)
                            break
                            
                    except Exception:
                        continue
                
                await browser.close()
                
                if download_file_path and os.path.exists(download_file_path):
                    return download_file_path
                else:
                    raise Exception("لم يتم تحميل الملف من GoFile")
                    
            except Exception as e:
                await browser.close()
                raise Exception(f"فشل GoFile: {str(e)}")
                
    except Exception as e:
        raise Exception(f"خطأ في GoFile: {str(e)}")

# ==========================================
# 8. محرك التورنت
# ==========================================
async def download_from_torrent(url, status_msg):
    try:
        session = lt.session()
        session.listen_on(6881, 6891)
        
        trackers = [
            "udp://tracker.openbittorrent.com:80",
            "udp://tracker.publicbt.com:80",
            "udp://tracker.istole.it:6969",
            "udp://tracker.ccc.de:80"
        ]
        
        for tracker in trackers:
            session.add_tracker(tracker)
        
        params = {
            'save_path': DOWNLOAD_DIR,
            'storage_mode': lt.storage_mode_t.storage_mode_sparse,
        }
        
        if url.startswith('magnet:'):
            handle = lt.add_magnet_uri(session, url, params)
        else:
            response = requests.get(url, timeout=30)
            temp_torrent = os.path.join(DOWNLOAD_DIR, 'temp.torrent')
            with open(temp_torrent, 'wb') as f:
                f.write(response.content)
            
            info = lt.torrent_info(temp_torrent)
            handle = session.add_torrent({'ti': info, **params})
            os.remove(temp_torrent)
        
        start_time = time.time()
        while not handle.has_metadata():
            if time.time() - start_time > 120:
                raise Exception("انتهت المهلة في انتظار معلومات التورنت")
            await asyncio.sleep(1)
        
        last_update = 0
        
        while True:
            status = handle.status()
            
            progress = status.progress * 100
            downloaded = status.total_done
            total = status.total_wanted
            speed = status.download_payload_rate
            eta = (total - downloaded) / speed if speed > 0 else 0
            
            now = time.time()
            if now - last_update >= 3:
                last_update = now
                
                filled = int(20 * progress / 100)
                bar = '█' * filled + '░' * (20 - filled)
                
                text = (
                    f"🎯 **تحميل التورنت**\n\n"
                    f"[{bar}] {progress:.1f}%\n"
                    f"📦 **تم تحميل:** {humanbytes(downloaded)} / {humanbytes(total)}\n"
                    f"🚀 **السرعة:** {humanbytes(speed)}/s\n"
                    f"⏱️ **المتبقي:** {eta:.0f}s\n"
                    f"🌱 **البذور:** {status.num_seeds}\n"
                    f"👥 **الأقران:** {status.num_peers}"
                )
                
                try:
                    await status_msg.edit_text(text)
                except Exception:
                    pass
            
            if status.is_seeding:
                break
            
            await asyncio.sleep(2)
        
        torrent_info = handle.torrent_file()
        if torrent_info:
            file_path = os.path.join(DOWNLOAD_DIR, torrent_info.file_at(0).path)
            if os.path.exists(file_path):
                return file_path
        
        raise Exception("لم يتم العثور على الملف")
        
    except Exception as e:
        raise Exception(f"فشل التورنت: {str(e)}")

# ==========================================
# 9. التحميل المباشر
# ==========================================
async def download_direct(url, status_msg):
    filename = url.split("/")[-1].split("?")[0] or "downloaded_file.bin"
    file_path = os.path.join(DOWNLOAD_DIR, filename)
    
    if os.path.exists(file_path):
        base_name = os.path.splitext(filename)[0]
        extension = os.path.splitext(filename)[1]
        counter = 1
        while os.path.exists(file_path):
            file_path = os.path.join(DOWNLOAD_DIR, f"{base_name}_{counter}{extension}")
            counter += 1
    
    session = requests.Session()
    session.headers = {"User-Agent": "Mozilla/5.0"}
    
    response = session.get(url, stream=True, timeout=(30, 300))
    
    if response.status_code != 200:
        raise Exception(f"HTTP {response.status_code}")
    
    total = int(response.headers.get('Content-Length', 0))
    downloaded = 0
    start_time = time.time()
    last_update = 0
    
    with open(file_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=1024*1024):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                
                now = time.time()
                if now - last_update >= 3:
                    last_update = now
                    elapsed = now - start_time
                    speed = downloaded / elapsed if elapsed > 0 else 0
                    eta = (total - downloaded) / speed if speed > 0 else 0
                    
                    if total:
                        percentage = downloaded * 100 / total
                        filled = int(20 * downloaded // total)
                        bar = '█' * filled + '░' * (20 - filled)
                        text = (
                            f"⬇️ **تحميل مباشر**\n\n"
                            f"[{bar}] {percentage:.1f}%\n"
                            f"📦 **تم تحميل:** {humanbytes(downloaded)} / {humanbytes(total)}\n"
                            f"🚀 **السرعة:** {humanbytes(speed)}/s\n"
                            f"⏱️ **المتبقي:** {eta:.0f}s"
                        )
                    else:
                        text = (
                            f"⬇️ **تحميل مباشر**\n\n"
                            f"📦 **تم تحميل:** {humanbytes(downloaded)}\n"
                            f"🚀 **السرعة:** {humanbytes(speed)}/s"
                        )
                    
                    try:
                        await status_msg.edit_text(text)
                    except Exception:
                        pass
    
    return file_path

# ==========================================
# 10. الموجه الذكي (محدث)
# ==========================================
async def smart_download(url, status_msg):
    """
    🧭 اختيار المحرك المناسب
    """
    url_lower = url.lower()
    
    # تورنت
    if url.startswith('magnet:') or url.endswith('.torrent'):
        await status_msg.edit_text("🎯 جاري التحميل من التورنت...")
        return await download_from_torrent(url, status_msg)
    
    # MEGA (جديد!)
    if 'mega.nz' in url_lower or 'mega.io' in url_lower:
        await status_msg.edit_text("📥 جاري التحميل من MEGA...")
        return await download_from_mega(url, status_msg)
    
    # WorkUpload
    if 'workupload.com' in url_lower:
        await status_msg.edit_text("📥 جاري التحميل من WorkUpload...")
        return await download_from_workupload(url, status_msg)
    
    # GoFile
    if 'gofile.io' in url_lower:
        await status_msg.edit_text("📥 جاري التحميل من GoFile...")
        return await download_from_gofile(url, status_msg)
    
    # تحميل مباشر
    await status_msg.edit_text("⬇️ جاري التحميل المباشر...")
    return await download_direct(url, status_msg)

# ==========================================
# 11. الرفع إلى Buzzheavier
# ==========================================
BUZZ_UPLOAD_BASE = "https://w.buzzheavier.com"
BUZZ_LINK_BASE = "https://buzzheavier.com"

class _ProgressReader:
    def __init__(self, path, callback=None):
        self._f = open(path, "rb")
        self.size = os.path.getsize(path)
        self.sent = 0
        self._cb = callback
        self._last = 0.0

    def __len__(self):
        return self.size

    def read(self, n=-1):
        chunk = self._f.read(n)
        if chunk:
            self.sent += len(chunk)
            if self._cb and (self.sent >= self.size or time.time() - self._last >= 3):
                self._last = time.time()
                try:
                    self._cb(self.sent, self.size)
                except Exception:
                    pass
        return chunk

    def close(self):
        try:
            self._f.close()
        except Exception:
            pass

def upload_to_buzzheavier(file_path, progress_callback=None):
    name = os.path.basename(file_path)[:500]
    endpoint = f"{BUZZ_UPLOAD_BASE}/{urllib.parse.quote(name, safe='')}"
    
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json, text/plain, */*",
    })
    
    body = None
    try:
        body = _ProgressReader(file_path, progress_callback)
        response = session.put(endpoint, data=body, timeout=(30, 900))
        
        if response.status_code in (200, 201):
            try:
                data = response.json()
                if 'data' in data and 'id' in data['data']:
                    return f"{BUZZ_LINK_BASE}/{data['data']['id']}"
            except:
                pass
            
            for m in re.finditer(r'buzzheavier\.com/(?:f/)?([A-Za-z0-9_-]{8,})', response.text or ""):
                return f"{BUZZ_LINK_BASE}/{m.group(1)}"
        
        raise Exception(f"HTTP {response.status_code}")
        
    finally:
        if body:
            body.close()

async def upload_to_buzz_with_progress(file_path, status_msg):
    loop = asyncio.get_event_loop()
    up_start = [time.time()]
    
    async def upload_progress(current, total):
        now = time.time()
        elapsed = now - up_start[0]
        speed = current / elapsed if elapsed > 0 else 1
        eta = round((total - current) / speed) if speed > 0 else 0
        percentage = current * 100 / total
        filled = int(20 * current // total)
        bar = '█' * filled + '░' * (20 - filled)
        
        text = (
            f"⬆️ **الرفع إلى Buzzheavier**\n\n"
            f"[{bar}] {percentage:.1f}%\n"
            f"📦 **تم رفع:** {humanbytes(current)} / {humanbytes(total)}\n"
            f"🚀 **السرعة:** {humanbytes(speed)}/s\n"
            f"⏱️ **المتبقي:** {eta}s"
        )
        
        try:
            await status_msg.edit_text(text)
        except Exception:
            pass
    
    def thread_progress(current, total):
        asyncio.run_coroutine_threadsafe(upload_progress(current, total), loop)
    
    return await loop.run_in_executor(
        None, lambda: upload_to_buzzheavier(file_path, thread_progress)
    )

# ==========================================
# 12. واجهة البوت
# ==========================================
MODES_INFO = {
    "link_to_file": "📥 رابط ⬅️ ملف",
    "file_to_link": "📤 ملف ⬅️ رابط",
    "link_to_link": "🔄 رابط ⬅️ رابط",
    "torrent_mode": "🎯 تورنت ⬅️ ملف/رابط",
    "mega_mode": "📥 MEGA ⬅️ ملف",  # 🆕 وضع MEGA
}

def get_main_keyboard(current_mode):
    rows = []
    for m, label in MODES_INFO.items():
        txt = f"✅ {label}" if current_mode == m else label
        rows.append([InlineKeyboardButton(txt, callback_data=f"mode_{m}")])
    return InlineKeyboardMarkup(rows)

@bot.on_message(filters.command("start") & filters.private)
async def start_handler(client, message: Message):
    global user_chat_id, ping_task
    user_chat_id = message.chat.id
    if ping_task is None or ping_task.done():
        ping_task = asyncio.create_task(keep_alive_ping())
    user_modes[message.chat.id] = user_modes.get(message.chat.id, "link_to_file")
    
    await message.reply_text(
        "أهلاً بك في البوت الشامل! 🚀\n\n"
        "📥 **رابط ⬅️ ملف:** أرسل رابطاً واستلم الملف\n"
        "📤 **ملف ⬅️ رابط:** أرسل ملفاً واستلم رابط\n"
        "🔄 **رابط ⬅️ رابط:** أرسل رابطاً واستلم رابط\n"
        "🎯 **تورنت ⬅️ ملف/رابط:** أرسل رابط مغناطيسي\n"
        "📥 **MEGA ⬅️ ملف:** أرسل رابط MEGA\n\n"
        "المصادر:\n"
        "✅ WorkUpload | GoFile | MEGA | تورنت | مباشر\n\n"
        "🎯 **كشف نوع الملف تلقائياً:** فيديو/صوت/مستند",
        reply_markup=get_main_keyboard(user_modes[message.chat.id])
    )

@bot.on_callback_query(filters.regex(r'^mode_'))
async def mode_callback(client, callback: CallbackQuery):
    mode = callback.data.replace("mode_", "")
    user_modes[callback.message.chat.id] = mode
    
    descriptions = {
        "link_to_file": "📥 **رابط ⬅️ ملف**",
        "file_to_link": "📤 **ملف ⬅️ رابط**",
        "link_to_link": "🔄 **رابط ⬅️ رابط**",
        "torrent_mode": "🎯 **تورنت ⬅️ ملف/رابط**",
        "mega_mode": "📥 **MEGA ⬅️ ملف**",
    }
    
    await callback.message.edit_text(
        f"تم التغيير! ✅\n\n{descriptions.get(mode, '')}",
        reply_markup=get_main_keyboard(mode)
    )
    await callback.answer("تم الحفظ")

# ==========================================
# 13. معالج الروابط (محدث لكشف نوع الملف)
# ==========================================
@bot.on_message(filters.regex(r'https?://[^\s]+') & filters.private)
async def handle_links(client, message: Message):
    mode = user_modes.get(message.chat.id, "link_to_file")
    
    if mode == "file_to_link":
        await message.reply_text("⚠️ أرسل ملفاً، أو بدّل الوضع.")
        return
    
    url = message.text.strip()
    status_msg = await message.reply_text("⚡ جاري التحليل...")
    file_path = None
    last_update = [0]
    
    try:
        # التحميل
        file_path = await smart_download(url, status_msg)
        
        if not file_path or not os.path.exists(file_path):
            raise Exception("تعذر التحميل")
        
        local_size = os.path.getsize(file_path)
        
        # وضع: رابط ⬅️ رابط
        if mode in ("link_to_link", "torrent_mode", "mega_mode"):
            await status_msg.edit_text(
                f"🚀 تم التحميل ({humanbytes(local_size)})!\nجاري الرفع..."
            )
            buzz_link = await upload_to_buzz_with_progress(file_path, status_msg)
            
            await status_msg.edit_text(
                f"✅ **تم التحويل!**\n\n"
                f"📁 **الملف:** `{os.path.basename(file_path)}`\n"
                f"📦 **الحجم:** `{humanbytes(local_size)}`\n"
                f"🔍 **النوع:** `{get_mime_type(file_path)}`\n\n"  # 🆕 عرض نوع الملف
                f"🔗 **الرابط:**\n{buzz_link}"
            )
            return
        
        # وضع: رابط ⬅️ ملف
        if local_size > MAX_FILE_SIZE:
            raise Exception(f"الملف كبير جداً ({humanbytes(local_size)})")
        
        await status_msg.edit_text("🚀 جاري الإرسال...")
        
        # 🆕 كشف نوع الملف تلقائياً
        file_category = get_file_category(file_path)
        mime_type = get_mime_type(file_path)
        
        start_time = time.time()
        
        async def upload_progress(current, total):
            now = time.time()
            if now - last_update[0] >= 3:
                last_update[0] = now
                percentage = current * 100 / total
                speed = current / (now - start_time) if (now - start_time) > 0 else 1
                eta = round((total - current) / speed) if speed > 0 else 0
                filled = int(20 * current // total)
                bar = '█' * filled + '░' * (20 - filled)
                text = (
                    f"⬆️ **الرفع إلى تليجرام**\n\n"
                    f"📁 **النوع:** {file_category}\n"  # 🆕 عرض نوع الملف
                    f"[{bar}] {percentage:.1f}%\n"
                    f"📦 **تم رفع:** {humanbytes(current)} / {humanbytes(total)}\n"
                    f"🚀 **السرعة:** {humanbytes(speed)}/s\n"
                    f"⏱️ **المتبقي:** {eta}s"
                )
                try:
                    await status_msg.edit_text(text)
                except Exception:
                    pass
        
        # 🆕 إرسال الملف بناءً على نوعه المكتشف
        if file_category == "video":
            await message.reply_video(
                video=file_path,
                caption=f"🎬 `{os.path.basename(file_path)}`\n🔍 النوع: فيديو",
                progress=upload_progress
            )
        elif file_category == "audio":
            await message.reply_audio(
                audio=file_path,
                caption=f"🎵 `{os.path.basename(file_path)}`\n🔍 النوع: صوت",
                progress=upload_progress
            )
        elif file_category == "image":
            await message.reply_photo(
                photo=file_path,
                caption=f"🖼️ `{os.path.basename(file_path)}`\n🔍 النوع: صورة",
                progress=upload_progress
            )
        else:
            await message.reply_document(
                document=file_path,
                caption=f"📄 `{os.path.basename(file_path)}`\n🔍 النوع: مستند",
                progress=upload_progress
            )
        
        await status_msg.delete()
        
    except Exception as e:
        await status_msg.edit_text(f"❌ خطأ:\n`{str(e)}`")
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

# ==========================================
# 14. معالج الملفات
# ==========================================
@bot.on_message((filters.document | filters.video | filters.audio) & filters.private)
async def handle_files(client, message: Message):
    mode = user_modes.get(message.chat.id, "link_to_file")
    
    if mode != "file_to_link":
        await message.reply_text("⚠️ أرسل رابطاً، أو بدّل الوضع.")
        return
    
    status_msg = await message.reply_text("⬇️ جاري التحميل...")
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
            filled = int(20 * current // total)
            bar = '█' * filled + '░' * (20 - filled)
            text = (
                f"⬇️ **التحميل من تليجرام**\n\n"
                f"[{bar}] {percentage:.1f}%\n"
                f"📦 **تم تحميل:** {humanbytes(current)} / {humanbytes(total)}\n"
                f"🚀 **السرعة:** {humanbytes(speed)}/s\n"
                f"⏱️ **المتبقي:** {eta}s"
            )
            try:
                await status_msg.edit_text(text)
            except Exception:
                pass
    
    try:
        file_path = await message.download(progress=download_progress)
        await status_msg.edit_text("🚀 جاري الرفع...")
        
        buzz_link = await upload_to_buzz_with_progress(file_path, status_msg)
        
        # 🆕 كشف نوع الملف
        file_category = get_file_category(file_path)
        mime_type = get_mime_type(file_path)
        
        await status_msg.edit_text(
            f"✅ **تم التحويل!**\n\n"
            f"📁 **الملف:** `{os.path.basename(file_path)}`\n"
            f"📦 **الحجم:** `{humanbytes(os.path.getsize(file_path))}`\n"
            f"🔍 **النوع:** `{file_category}`\n\n"
            f"🔗 **الرابط:**\n{buzz_link}"
        )
        
    except Exception as e:
        await status_msg.edit_text(f"❌ خطأ:\n`{str(e)}`")
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

# ==========================================
# 15. تشغيل البوت
# ==========================================
async def start_bot():
    try:
        await bot.start()
        print("🟢 البوت يعمل!")
        print("✅ المصادر: WorkUpload | GoFile | MEGA | تورنت | مباشر")
        print("🔍 كشف نوع الملف: ✅")
        await idle()
    except Exception as e:
        print(f"⚠️ خطأ: {e}")
    finally:
        await bot.stop()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_bot())
