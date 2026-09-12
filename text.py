# -*- coding: utf-8 -*-
"""
🚀 البوت الشامل - مع محرك تورنت يعمل بشكل صحيح
"""

# ==========================================
# 1. تثبيت المكتبات
# ==========================================
import subprocess
import sys

def install_packages():
    packages = [
        'pyrogram', 
        'tgcrypto', 
        'nest_asyncio', 
        'requests', 
        'playwright', 
        'libtorrent',
        'python-magic'
    ]
    
    print("📦 تثبيت المكتبات...")
    
    for package in packages:
        try:
            __import__(package)
        except ImportError:
            subprocess.check_call([
                sys.executable, '-m', 'pip', 'install', 
                package, '-q'
            ])
    
    subprocess.run(['playwright', 'install', 'firefox'], check=True)
    subprocess.run(['playwright', 'install-deps', 'firefox'], check=True)
    subprocess.run(['apt-get', 'update', '-qq'], capture_output=True)
    subprocess.run(['apt-get', 'install', '-y', '-qq', 'megatools', 'aria2'], capture_output=True)
    
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
import threading
import subprocess
import re
import urllib.parse
import gc
import mimetypes
import requests
from google.colab import userdata
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from playwright.async_api import async_playwright
import libtorrent as lt

try:
    import magic
    HAS_MAGIC = True
except ImportError:
    HAS_MAGIC = False

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

def detect_file_type(file_path):
    """🔍 كشف نوع الملف"""
    try:
        if HAS_MAGIC:
            with open(file_path, 'rb') as f:
                header = f.read(1024)
            mime = magic.from_buffer(header, mime=True)
            if mime:
                return mime
        
        mime, _ = mimetypes.guess_type(file_path)
        return mime or "application/octet-stream"
    except:
        return "application/octet-stream"

def get_file_category(file_path):
    """📂 تحديد فئة الملف"""
    mime_type = detect_file_type(file_path)
    if mime_type.startswith('video/'):
        return "video", "🎬"
    elif mime_type.startswith('audio/'):
        return "audio", "🎵"
    elif mime_type.startswith('image/'):
        return "image", "🖼️"
    else:
        return "document", "📄"

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
# 4. 🎯 محرك التورنت - استخدام libtorrent مباشرة
# ==========================================

async def download_torrent_with_libtorrent(url, status_msg):
    """
    🎯 تحميل التورنت باستخدام libtorrent بشكل صحيح
    """
    session = None
    handle = None
    
    try:
        print(f"🎯 [تورنت] بدء تحميل: {url[:80]}")
        
        # إنشاء جلسة libtorrent
        session = lt.session()
        session.listen_on(6881, 6891)
        
        # إعداد معاملات التحميل
        params = {
            'save_path': DOWNLOAD_DIR,
            'storage_mode': lt.storage_mode_t.storage_mode_sparse,
        }
        
        # إضافة التورنت
        if url.startswith('magnet:'):
            print("🎯 [تورنت] إضافة رابط مغناطيسي...")
            
            # 🔧 إضافة trackers يدوياً من الرابط
            trackers = []
            for match in re.finditer(r'&tr=([^&]+)', url):
                tracker = urllib.parse.unquote(match.group(1))
                trackers.append(tracker)
            
            # إضافة trackers إلى الجلسة
            for tracker in trackers:
                try:
                    session.add_tracker({'url': tracker, 'tier': 0})
                    print(f"   📍 Tracker: {tracker}")
                except:
                    pass
            
            # إضافة الرابط المغناطيسي
            handle = lt.add_magnet_uri(session, url, params)
            
            # 🔧 انتظار الميتاداتا - استخدام حلقة منفصلة
            await status_msg.edit_text(
                "📡 **جاري الحصول على معلومات التورنت...**\n\n"
                "⏳ **الرجاء الانتظار...**"
            )
            
            metadata_start = time.time()
            while not handle.has_metadata():
                if time.time() - metadata_start > 120:
                    raise Exception("انتهت المهلة في انتظار الميتاداتا")
                
                # 🔧 استخدام await بدلاً من time.sleep
                await asyncio.sleep(1)
            
            print("✅ [تورنت] تم الحصول على الميتاداتا!")
            
        else:
            # ملف .torrent
            print("📁 [تورنت] تحميل ملف التورنت...")
            response = requests.get(url, timeout=30)
            temp_torrent = os.path.join(DOWNLOAD_DIR, 'temp.torrent')
            with open(temp_torrent, 'wb') as f:
                f.write(response.content)
            
            info = lt.torrent_info(temp_torrent)
            handle = session.add_torrent({'ti': info, **params})
            os.remove(temp_torrent)
        
        # 🔧 بدء التحميل - استخدام حلقة مع تحديث التقدم
        print("⬇️ [تورنت] بدء التحميل...")
        
        start_time = time.time()
        last_update = 0
        update_count = 0
        
        while True:
            # الحصول على الحالة
            status = handle.status()
            
            # حساب المعلومات
            progress = status.progress * 100
            downloaded = status.total_done
            total = status.total_wanted
            speed = status.download_payload_rate
            peers = status.num_peers
            seeds = status.num_seeds
            
            # التحقق من الاكتمال
            if status.is_seeding:
                print("✅ [تورنت] اكتمل التحميل!")
                break
            
            # تحديث الرسالة كل 3 ثواني
            now = time.time()
            if now - last_update >= 3:
                last_update = now
                update_count += 1
                
                # إنشاء شريط التقدم
                if total > 0:
                    filled = int(20 * progress / 100)
                    bar = '█' * filled + '░' * (20 - filled)
                else:
                    bar = '░' * 20
                    progress = 0
                
                # حساب الوقت المتبقي
                if speed > 0:
                    eta = (total - downloaded) / speed
                    eta_str = f"{int(eta // 60)}:{int(eta % 60):02d}"
                else:
                    eta_str = "∞"
                
                elapsed = int(time.time() - start_time)
                
                # إنشاء النص
                text = (
                    f"🎯 **تحميل التورنت**\n\n"
                    f"[{bar}] {progress:.1f}%\n\n"
                    f"📦 **تم تحميل:** {humanbytes(downloaded)} / {humanbytes(total)}\n"
                    f"🚀 **السرعة:** {humanbytes(speed)}/s\n"
                    f"⏱️ **المتبقي:** {eta_str}\n"
                    f"🌱 **البذور:** {seeds}\n"
                    f"👥 **الأقران:** {peers}\n"
                    f"⏳ **الوقت:** {elapsed}s"
                )
                
                # محاولة تحديث الرسالة
                try:
                    await status_msg.edit_text(text)
                    
                    # طباعة في console كل 5 تحديثات
                    if update_count % 5 == 0:
                        print(f"   📊 {progress:.1f}% | "
                              f"{humanbytes(downloaded)}/{humanbytes(total)} | "
                              f"{humanbytes(speed)}/s")
                    
                except Exception as e:
                    # إذا فشل التحديث، استمر
                    pass
            
            # 🔧 مهم: استخدام await asyncio.sleep(1) يسمح لـ Pyrogram بالعمل
            await asyncio.sleep(1)
        
        # إيجاد الملف المحمل
        torrent_info = handle.torrent_file()
        if torrent_info:
            if torrent_info.num_files() == 1:
                file_path = os.path.join(DOWNLOAD_DIR, torrent_info.file_at(0).path)
            else:
                # اختيار أكبر ملف
                largest_idx = 0
                largest_size = 0
                for i in range(torrent_info.num_files()):
                    file_size = torrent_info.file_at(i).size
                    if file_size > largest_size:
                        largest_size = file_size
                        largest_idx = i
                file_path = os.path.join(DOWNLOAD_DIR, torrent_info.file_at(largest_idx).path)
            
            if os.path.exists(file_path):
                file_size = os.path.getsize(file_path)
                if file_size > 0:
                    print(f"✅ [تورنت] الملف: {file_path} ({humanbytes(file_size)})")
                    return file_path
                else:
                    raise Exception("الملف فارغ")
            else:
                # البحث في المجلد
                files = [f for f in os.listdir(DOWNLOAD_DIR) if f not in ['temp.torrent']]
                if files:
                    latest_file = max(files, key=lambda x: os.path.getmtime(os.path.join(DOWNLOAD_DIR, x)))
                    file_path = os.path.join(DOWNLOAD_DIR, latest_file)
                    if os.path.getsize(file_path) > 0:
                        return file_path
                
                raise Exception("لم يتم العثور على الملف")
        else:
            raise Exception("لم يتم العثور على معلومات التورنت")
        
    except Exception as e:
        print(f"❌ [تورنت] خطأ: {e}")
        raise Exception(f"فشل التورنت: {str(e)}")
    finally:
        # تنظيف
        if session:
            try:
                if handle:
                    session.remove_torrent(handle)
            except:
                pass

# ==========================================
# 5. 📥 محرك MEGA
# ==========================================
async def download_from_mega(url, status_msg):
    """
    📥 تحميل من MEGA
    """
    try:
        print(f"🌐 [MEGA] تحميل: {url[:60]}")
        
        await status_msg.edit_text(
            f"📥 **جاري التحميل من MEGA...**\n\n"
            f"⏳ **الحالة:** جاري البدء..."
        )
        
        loop = asyncio.get_event_loop()
        
        def mega_sync():
            result = subprocess.run(
                ['megadl', '--path', DOWNLOAD_DIR + os.sep, url],
                capture_output=True,
                text=True,
                timeout=600
            )
            return result.returncode, result.stdout, result.stderr
        
        # تشغيل في executor
        returncode, stdout, stderr = await loop.run_in_executor(None, mega_sync)
        
        if returncode != 0:
            raise Exception(f"فشل MEGA: {stderr}")
        
        # البحث عن الملف
        files = [f for f in os.listdir(DOWNLOAD_DIR) if f not in ['temp.torrent']]
        if files:
            latest_file = max(files, key=lambda x: os.path.getmtime(os.path.join(DOWNLOAD_DIR, x)))
            file_path = os.path.join(DOWNLOAD_DIR, latest_file)
            
            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                return file_path
        
        raise Exception("لم يتم تحميل أي ملف من MEGA")
        
    except Exception as e:
        raise Exception(f"فشل MEGA: {str(e)}")

# ==========================================
# 6. محرك WorkUpload
# ==========================================
async def download_from_workupload(url, status_msg):
    """
    📥 تحميل من WorkUpload
    """
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()
        
        try:
            await status_msg.edit_text(
                f"📥 **جاري فتح صفحة WorkUpload...**\n\n"
                f"🌐 **الرابط:** `{url[:50]}...`"
            )
            
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(3)
            
            # البحث عن رابط البدء
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
            
            await status_msg.edit_text("🔍 **جاري البحث عن زر التحميل...**")
            
            await page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(8)
            
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
                        
                        await status_msg.edit_text("⬇️ **جاري بدء التحميل...**")
                        
                        async with page.expect_download(timeout=300000) as download_info:
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
                if os.path.getsize(download_file_path) > 1000:
                    return download_file_path
                else:
                    os.remove(download_file_path)
                    raise Exception("الملف صغير جداً")
            else:
                raise Exception("لم يتم تحميل الملف")
                
        except Exception as e:
            await browser.close()
            raise Exception(f"فشل WorkUpload: {str(e)}")

# ==========================================
# 7. محرك GoFile
# ==========================================
async def download_from_gofile(url, status_msg):
    """
    📥 تحميل من GoFile
    """
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()
        
        try:
            await status_msg.edit_text(
                f"📥 **جاري فتح صفحة GoFile...**\n\n"
                f"🌐 **الرابط:** `{url[:50]}...`"
            )
            
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(8)
            
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
                        
                        await status_msg.edit_text("⬇️ **جاري بدء التحميل...**")
                        
                        async with page.expect_download(timeout=600000) as download_info:
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

# ==========================================
# 8. التحميل المباشر
# ==========================================
async def download_direct(url, status_msg):
    """
    📥 تحميل مباشر
    """
    filename = url.split("/")[-1].split("?")[0] or "downloaded_file.bin"
    file_path = os.path.join(DOWNLOAD_DIR, filename)
    
    if os.path.exists(file_path):
        base_name = os.path.splitext(filename)[0]
        extension = os.path.splitext(filename)[1]
        counter = 1
        while os.path.exists(file_path):
            file_path = os.path.join(DOWNLOAD_DIR, f"{base_name}_{counter}{extension}")
            counter += 1
    
    await status_msg.edit_text("⬇️ **جاري التحميل المباشر...**")
    
    loop = asyncio.get_event_loop()
    
    def sync_download():
        session = requests.Session()
        session.headers = {"User-Agent": "Mozilla/5.0"}
        
        response = session.get(url, stream=True, timeout=(30, 300))
        
        if response.status_code != 200:
            raise Exception(f"HTTP {response.status_code}")
        
        total = int(response.headers.get('Content-Length', 0))
        downloaded = 0
        
        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=1024*1024):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
        
        return file_path
    
    return await loop.run_in_executor(None, sync_download)

# ==========================================
# 9. الموجه الذكي
# ==========================================
async def smart_download(url, status_msg):
    """
    🧭 اختيار المحرك المناسب
    """
    url_lower = url.lower()
    
    if url.startswith('magnet:') or url.endswith('.torrent'):
        return await download_torrent_with_libtorrent(url, status_msg)
    
    if 'mega.nz' in url_lower or 'mega.io' in url_lower:
        return await download_from_mega(url, status_msg)
    
    if 'workupload.com' in url_lower:
        return await download_from_workupload(url, status_msg)
    
    if 'gofile.io' in url_lower:
        return await download_from_gofile(url, status_msg)
    
    return await download_direct(url, status_msg)

# ==========================================
# 10. الرفع إلى Buzzheavier
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
    """
    ⬆️ الرفع مع شريط تقدم
    """
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
# 11. واجهة البوت
# ==========================================
MODES_INFO = {
    "link_to_file": "📥 رابط ⬅️ ملف",
    "file_to_link": "📤 ملف ⬅️ رابط",
    "link_to_link": "🔄 رابط ⬅️ رابط",
    "torrent_mode": "🎯 تورنت ⬅️ ملف/رابط",
    "mega_mode": "📥 MEGA ⬅️ ملف",
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
        "🎯 **كشف نوع الملف تلقائياً**\n"
        "📊 **شريط تقدم لجميع العمليات**",
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
# 12. معالج الروابط
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
        
        # كشف نوع الملف
        file_category, emoji = get_file_category(file_path)
        
        # وضع: رابط ⬅️ رابط
        if mode in ("link_to_link", "torrent_mode", "mega_mode"):
            await status_msg.edit_text(
                f"🚀 **تم التحميل!**\n\n"
                f"📁 **الملف:** `{os.path.basename(file_path)}`\n"
                f"📦 **الحجم:** `{humanbytes(local_size)}`\n"
                f"🔍 **النوع:** {emoji} `{file_category}`\n\n"
                f"🔗 **جاري الرفع إلى Buzzheavier...**"
            )
            
            buzz_link = await upload_to_buzz_with_progress(file_path, status_msg)
            
            await status_msg.edit_text(
                f"✅ **تم التحويل بنجاح!**\n\n"
                f"📁 **الملف:** `{os.path.basename(file_path)}`\n"
                f"📦 **الحجم:** `{humanbytes(local_size)}`\n"
                f"🔍 **النوع:** {emoji} `{file_category}`\n\n"
                f"🔗 **الرابط:**\n{buzz_link}"
            )
            return
        
        # وضع: رابط ⬅️ ملف
        if local_size > MAX_FILE_SIZE:
            raise Exception(f"الملف كبير جداً ({humanbytes(local_size)})")
        
        await status_msg.edit_text(
            f"🚀 **تم التحميل!**\n\n"
            f"📁 **الملف:** `{os.path.basename(file_path)}`\n"
            f"📦 **الحجم:** `{humanbytes(local_size)}`\n"
            f"🔍 **النوع:** {emoji} `{file_category}`\n\n"
            f"📤 **جاري الإرسال...**"
        )
        
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
                    f"{emoji} **النوع:** `{file_category}`\n\n"
                    f"[{bar}] {percentage:.1f}%\n"
                    f"📦 **تم رفع:** {humanbytes(current)} / {humanbytes(total)}\n"
                    f"🚀 **السرعة:** {humanbytes(speed)}/s\n"
                    f"⏱️ **المتبقي:** {eta}s"
                )
                try:
                    await status_msg.edit_text(text)
                except Exception:
                    pass
        
        # إرسال الملف بناءً على نوعه
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
# 13. معالج الملفات
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
        
        file_category, emoji = get_file_category(file_path)
        
        await status_msg.edit_text(
            f"✅ **تم التحويل!**\n\n"
            f"📁 **الملف:** `{os.path.basename(file_path)}`\n"
            f"📦 **الحجم:** `{humanbytes(os.path.getsize(file_path))}`\n"
            f"🔍 **النوع:** {emoji} `{file_category}`\n\n"
            f"🔗 **الرابط:**\n{buzz_link}"
        )
        
    except Exception as e:
        await status_msg.edit_text(f"❌ خطأ:\n`{str(e)}`")
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

# ==========================================
# 14. تشغيل البوت
# ==========================================
async def start_bot():
    try:
        await bot.start()
        print("🟢 البوت يعمل!")
        print("✅ المصادر: WorkUpload | GoFile | MEGA | تورنت | مباشر")
        print("🎯 محرك التورنت: يستخدم libtorrent مباشرة")
        await idle()
    except Exception as e:
        print(f"⚠️ خطأ: {e}")
    finally:
        await bot.stop()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_bot())
