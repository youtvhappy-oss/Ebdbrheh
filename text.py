import sys
import subprocess
import os
import shutil
import time
import math
import asyncio
import re
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import partial

# 1. تثبيت المكتبات والمتصفح تلقائياً
def check_and_install_dependencies():
    required_packages = {
        "pyrogram": "pyrogram",
        "tgcrypto": "tgcrypto",
        "nest_asyncio": "nest_asyncio",
        "requests": "requests",
        "yt_dlp": "yt-dlp",
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

    # تثبيت مكتبة التورنت
    try:
        import libtorrent as lt
    except ImportError:
        print("⚙️ جاري تثبيت مكتبة التورنت...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "libtorrent"])
        
    # تثبيت Firefox
    firefox_cache = os.path.expanduser("~/.cache/ms-playwright")
    if not os.path.exists(firefox_cache) or not any(
            "firefox" in f for f in os.listdir(firefox_cache)
            if os.path.isdir(os.path.join(firefox_cache, f))):
        print("🦊 جاري تثبيت متصفح Firefox...")
        os.system("playwright install firefox")
        os.system("playwright install-deps firefox")
    else:
        print("✅ متصفح Firefox مثبت وجاهز للعمل.")

check_and_install_dependencies()

# ==========================================
# 2. الاستيراد والتهيئات
# ==========================================
import warnings
warnings.filterwarnings("ignore")
import gc
import urllib.parse
import nest_asyncio
import requests
from google.colab import userdata
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from playwright.async_api import async_playwright
import libtorrent as lt

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
user_modes = {}

# إدارة عمليات التورنت
torrent_sessions = {}
executor = ThreadPoolExecutor(max_workers=10)

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
            except Exception as e:
                print(f"⚠️ تعذر إرسال الإشارة: {e}")

# ==========================================
# 3. 🚀 الرفع إلى Buzzheavier
# ==========================================

BUZZ_UPLOAD_BASE = "https://w.buzzheavier.com"
BUZZ_LINK_BASE   = "https://buzzheavier.com"
WARP_PROXIES     = {"http": "socks5h://127.0.0.1:40000", "https": "socks5h://127.0.0.1:40000"}
_warp_ready      = [False]

class _ProgressReader:
    def __init__(self, path, callback=None, report_every=2):
        self._f = open(path, "rb")
        self.size = os.path.getsize(path)
        self.sent = 0
        self._cb = callback
        self._every = report_every
        self._last = 0.0

    def __len__(self):
        return self.size

    def read(self, n=-1):
        chunk = self._f.read(n)
        if chunk:
            self.sent += len(chunk)
            if self._cb and (self.sent >= self.size or time.time() - self._last >= self._every):
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

def _get_buzz_link(response):
    try:
        data = response.json()
    except Exception:
        data = None

    if isinstance(data, dict):
        d = data.get("data")
        if isinstance(d, dict) and d.get("id"):
            return f"{BUZZ_LINK_BASE}/{str(d['id']).strip()}"
        if isinstance(d, str) and d.strip():
            return f"{BUZZ_LINK_BASE}/{d.strip()}"
        fid = data.get("id")
        if isinstance(fid, str) and len(fid.strip()) >= 6:
            return f"{BUZZ_LINK_BASE}/{fid.strip()}"

    for m in re.finditer(r'buzzheavier\.com/(?:f/)?([A-Za-z0-9_-]{8,})', response.text or ""):
        cand = m.group(1)
        if cand.lower() not in ("speed-test", "developers"):
            return f"{BUZZ_LINK_BASE}/{cand}"
    return None

def _start_warp():
    if _warp_ready[0]:
        return True
    print("🛡️ شبكة كولاب محجوبة → تشغيل WARP VPN...")
    if os.system("which warp-cli >/dev/null 2>&1") != 0:
        codename = subprocess.getoutput("lsb_release -cs 2>/dev/null").strip() or "jammy"
        os.system("curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg | gpg --yes --dearmor --output /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg 2>/dev/null")
        os.system(f'echo "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ {codename} main" | tee /etc/apt/sources.list.d/cloudflare-client.list')
        os.system("apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq cloudflare-warp")
    if os.system("pgrep -f warp-svc >/dev/null 2>&1") != 0:
        subprocess.Popen("warp-svc > /var/log/warp.log 2>&1", shell=True, start_new_session=True)
        time.sleep(5)
    for _ in range(3):
        r = subprocess.getoutput("warp-cli --accept-tos registration new 2>&1")
        if "Success" in r or "already" in r.lower():
            break
        time.sleep(3)
    for m in ("warp-cli --accept-tos mode proxy", "warp-cli --accept-tos tunnel mode set proxy"):
        if os.system(m + " >/dev/null 2>&1") == 0:
            break
    os.system("warp-cli --accept-tos proxy port 40000 >/dev/null 2>&1")
    os.system("warp-cli --accept-tos connect >/dev/null 2>&1")
    time.sleep(4)
    ip = subprocess.getoutput("curl -s --max-time 12 --socks5-hostname 127.0.0.1:40000 https://api.ipify.org")
    if ip:
        _warp_ready[0] = True
        print(f"   ✅ WARP يعمل — IP جديد: {ip}")
    else:
        print("   ❌ فشل تشغيل WARP")
    return _warp_ready[0]

def upload_to_buzzheavier(file_path, progress_callback=None):
    name = os.path.basename(file_path)[:500]
    endpoint = f"{BUZZ_UPLOAD_BASE}/{urllib.parse.quote(name, safe='')}"

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
    })

    use_proxy = False
    last_err = None

    for attempt in range(1, 4):
        body = None
        try:
            body = _ProgressReader(file_path, progress_callback)
            response = session.put(
                endpoint,
                data=body,
                proxies=WARP_PROXIES if use_proxy else None,
                timeout=(30, 900),
            )

            if response.status_code in (200, 201):
                link = _get_buzz_link(response)
                if link:
                    return link
                last_err = Exception(f"رد غير مفهوم من السيرفر: {str(response.text)[:200]}")

            elif response.status_code in (403, 429, 451):
                last_err = Exception(f"HTTP {response.status_code} — حظر الشبكة")
                if not use_proxy:
                    print(f"⛔ محاولة {attempt}: HTTP {response.status_code} → تشغيل WARP...")
                    if _start_warp():
                        use_proxy = True
                        continue

            else:
                last_err = Exception(f"HTTP {response.status_code}: {str(response.text)[:200]}")

        except Exception as e:
            last_err = e
        finally:
            if body is not None:
                body.close()
        time.sleep(3)

    raise Exception(f"فشل الرفع إلى Buzzheavier: {last_err}")

# ==========================================
# 3.5 ⬆️ رفع Buzzheavier مع شريط تقدم
# ==========================================
async def upload_to_buzz_with_progress(file_path, status_msg):
    loop = asyncio.get_event_loop()
    up_last = [0.0]
    up_start = [time.time()]

    async def upload_progress(current, total):
        now = time.time()
        if now - up_last[0] >= 3 and total:
            up_last[0] = now
            percentage = current * 100 / total
            speed = current / (now - up_start[0]) if (now - up_start[0]) > 0 else 1
            eta = round((total - current) / speed) if speed > 0 else 0
            filled = int(20 * current // total)
            bar = '█' * filled + '░' * (20 - filled)
            text = (
                f"⬆️ **جاري الرفع إلى Buzzheavier...**\n\n"
                f"[{bar}] {percentage:.1f}%\n"
                f"🚀 **السرعة:** {humanbytes(speed)}/s\n"
                f"📦 **المرفوع:** {humanbytes(current)} / {humanbytes(total)}\n"
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
# 4. 🌐 محركات التحميل
# ==========================================

async def download_from_workupload(url):
    """
    📥 تحميل ملف من WorkUpload - محسّن مع تحليل الشبكة
    """
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()
        
        try:
            # إضافة user agent
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined})
            """)
            
            # اعتراض طلبات الشبكة للعثور على رابط التحميل المباشر
            download_urls = []
            
            async def handle_response(response):
                if 'download' in response.url.lower() or 'file' in response.url.lower():
                    if response.status == 200:
                        content_type = response.headers.get('content-type', '')
                        if 'octet-stream' in content_type or 'application/zip' in content_type:
                            download_urls.append(response.url)
            
            page.on('response', handle_response)
            
            # الانتقال إلى الصفحة
            await page.goto(url, wait_until="networkidle", timeout=60000)
            
            # انتظار ظهور زر التحميل
            download_button = None
            
            # محاولة العثور على زر التحميل
            selectors = [
                "a.btn-download",
                "button:has-text('Download')",
                "a:has-text('Download')",
                "a[href*='download']",
                "button[class*='download']"
            ]
            
            for selector in selectors:
                try:
                    btn = page.locator(selector).first
                    if await btn.count() > 0 and await btn.is_visible():
                        download_button = btn
                        print(f"✅ [WorkUpload] تم العثور على زر التحميل: {selector}")
                        break
                except Exception:
                    continue
            
            if not download_button:
                # إذا لم يتم العثور على الزر، نبحث عن الروابط المباشرة
                await page.wait_for_timeout(10000)
                if download_urls:
                    direct_url = download_urls[0]
                    print(f"✅ [WorkUpload] تم العثور على رابط مباشر: {direct_url}")
                    
                    # تحميل الملف مباشرة
                    return await download_direct_from_url(direct_url)
                else:
                    raise Exception("لم يتم العثور على زر التحميل أو رابط مباشر")
            
            # محاولة التحميل عبر النقر على الزر
            try:
                async with page.expect_download(timeout=180000) as download_info:
                    await download_button.click()
                
                download = await download_info.value
                file_path = os.path.join(DOWNLOAD_DIR, download.suggested_filename)
                
                # حفظ الملف
                if os.path.exists(file_path):
                    base_name = os.path.splitext(download.suggested_filename)[0]
                    extension = os.path.splitext(download.suggested_filename)[1]
                    counter = 1
                    while os.path.exists(file_path):
                        file_path = os.path.join(DOWNLOAD_DIR, f"{base_name}_{counter}{extension}")
                        counter += 1
                
                await download.save_as(file_path)
                
                if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                    print(f"✅ [WorkUpload] تم تحميل الملف بنجاح: {file_path}")
                    return file_path
                else:
                    raise Exception("الملف فارغ أو غير موجود")
                    
            except Exception as e:
                # إذا فشل التحميل عبر النقر، نحاول الروابط المباشرة
                if download_urls:
                    direct_url = download_urls[0]
                    return await download_direct_from_url(direct_url)
                else:
                    raise Exception(f"فشل التحميل: {str(e)}")
                    
        except Exception as e:
            raise Exception(f"فشل تحميل WorkUpload: {str(e)}")
        finally:
            await browser.close()

async def download_direct_from_url(url):
    """
    📥 تحميل مباشر من رابط
    """
    file_name = url.split("/")[-1].split("?")[0] or "downloaded_file.bin"
    file_path = os.path.join(DOWNLOAD_DIR, file_name)
    
    response = requests.get(url, stream=True, timeout=(30, 300))
    
    if response.status_code == 200:
        total = int(response.headers.get('Content-Length', 0))
        downloaded = 0
        
        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=1024*1024):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
        
        return file_path
    else:
        raise Exception(f"HTTP {response.status_code} — الرابط غير متاح")

async def download_from_gofile(url):
    """
    📥 تحميل ملف من GoFile
    """
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()
        
        try:
            # الانتقال إلى الصفحة
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(5000)
            
            # البحث عن زر التحميل
            download_button = page.locator("a.filesContentTableActionsDownload, button:has-text('Download')").first
            
            if await download_button.count() == 0:
                raise Exception("لم يتم العثور على زر التحميل في GoFile")
            
            # التحميل
            async with page.expect_download(timeout=300000) as download_info:
                await download_button.click()
            
            download = await download_info.value
            file_path = os.path.join(DOWNLOAD_DIR, download.suggested_filename)
            await download.save_as(file_path)
            
            return file_path
            
        except Exception as e:
            raise Exception(f"فشل تحميل GoFile: {str(e)}")
        finally:
            await browser.close()

async def download_from_mega(url):
    """
    ⭕ تحميل من MEGA
    """
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()
        
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=90000)
            await page.wait_for_timeout(12000)
            
            # روابط المجلدات → فتح أول ملف
            if "/folder/" in url or "#F!" in url:
                try:
                    row = page.locator("tr[data-handle], .grid-scrolling-table-row, tbody tr").first
                    if await row.count() > 0:
                        await row.dblclick()
                        await page.wait_for_timeout(6000)
                except Exception:
                    pass
            
            # البحث عن زر التحميل
            download = None
            for sel in ["button.download-button",
                        "a.download-button",
                        "a[class*='download']",
                        "button:has-text('Download')",
                        "a:has-text('Download')"]:
                try:
                    btn = page.locator(sel).first
                    if await btn.count() == 0 or not await btn.is_visible():
                        continue
                    async with page.expect_download(timeout=2700000) as dl_info:
                        await btn.click()
                    download = await dl_info.value
                    break
                except Exception:
                    continue
            
            if download is None:
                raise Exception("لم يتم العثور على زر التحميل في صفحة MEGA")
            
            fname = download.suggested_filename or "mega_file.bin"
            file_path = os.path.join(DOWNLOAD_DIR, fname)
            if os.path.exists(file_path):
                os.remove(file_path)
            await download.save_as(file_path)
            return file_path
        finally:
            await browser.close()

# ==========================================
# 5. 🎯 محرك التورنت
# ==========================================

class TorrentEngine:
    """
    🎯 محرك تحميل التورنت باستخدام libtorrent
    """
    
    def __init__(self):
        self.session = None
        self.active_torrents = {}
        
    def _create_session(self):
        """إنشاء جلسة تورنت جديدة"""
        if self.session is None:
            self.session = lt.session()
            self.session.listen_on(6881, 6891)
            
            # إضافة trackers شائعة
            trackers = [
                "udp://tracker.openbittorrent.com:80",
                "udp://tracker.publicbt.com:80", 
                "udp://tracker.istole.it:6969",
                "udp://tracker.ccc.de:80",
                "http://tracker.openbittorrent.com:80/announce",
                "http://tracker.publicbt.com:80/announce"
            ]
            
            for tracker in trackers:
                self.session.add_tracker(tracker)
        
        return self.session
    
    def add_torrent(self, torrent_url, save_path=DOWNLOAD_DIR):
        """
        إضافة تورنت جديد (روابط مغناطيسية أو ملفات .torrent)
        """
        session = self._create_session()
        
        # إعداد معاملات التورنت
        params = {
            'save_path': save_path,
            'storage_mode': lt.storage_mode_t.storage_mode_sparse,
        }
        
        try:
            if torrent_url.startswith('magnet:'):
                # رابط مغناطيسي
                handle = lt.add_magnet_uri(session, torrent_url, params)
            elif torrent_url.endswith('.torrent'):
                # ملف تورنت
                info = lt.torrent_info(torrent_url)
                handle = session.add_torrent({'ti': info, **params})
            else:
                # تحميل ملف التورنت من URL
                response = requests.get(torrent_url, timeout=30)
                temp_torrent = os.path.join(DOWNLOAD_DIR, 'temp.torrent')
                with open(temp_torrent, 'wb') as f:
                    f.write(response.content)
                
                info = lt.torrent_info(temp_torrent)
                handle = session.add_torrent({'ti': info, **params})
                
                # حذف الملف المؤقت
                os.remove(temp_torrent)
            
            return handle
            
        except Exception as e:
            raise Exception(f"فشل إضافة التورنت: {str(e)}")
    
    def get_torrent_info(self, handle):
        """
        الحصول على معلومات التورنت
        """
        if not handle.is_valid():
            return None
        
        status = handle.status()
        
        return {
            'progress': status.progress,
            'download_rate': status.download_payload_rate,
            'upload_rate': status.upload_payload_rate,
            'num_peers': status.num_peers,
            'num_seeds': status.num_seeds,
            'state': str(status.state),
            'total_done': status.total_done,
            'total_wanted': status.total_wanted,
            'num_pieces': status.num_pieces
        }
    
    def get_files_list(self, handle):
        """
        الحصول على قائمة الملفات في التورنت
        """
        if not handle.is_valid():
            return []
        
        torrent_info = handle.torrent_file()
        if not torrent_info:
            return []
        
        files = []
        for i in range(torrent_info.num_files()):
            file_entry = torrent_info.file_at(i)
            files.append({
                'path': file_entry.path,
                'size': file_entry.size,
                'index': i
            })
        
        return files
    
    def select_file(self, handle, file_index, priority=7):
        """
        تحديد ملف للتحميل فقط
        """
        if handle.is_valid():
            handle.file_priority(file_index, priority)
    
    def is_finished(self, handle):
        """التحقق من اكتمال التحميل"""
        if not handle.is_valid():
            return False
        return handle.status().is_seeding

# إنشاء مثيل من محرك التورنت
torrent_engine = TorrentEngine()

async def download_from_torrent(url, status_msg):
    """
    🎯 تحميل من تورنت مع شريط تقدم
    """
    try:
        # إضافة التورنت
        await status_msg.edit_text("🎯 جاري إضافة التورنت...")
        handle = await asyncio.get_event_loop().run_in_executor(
            executor, torrent_engine.add_torrent, url
        )
        
        if not handle.is_valid():
            raise Exception("التورنت غير صالح")
        
        # انتظار الحصول على معلومات التورنت
        await status_msg.edit_text("⏳ جاري الحصول على معلومات التورنت...")
        
        # انتظار معلومات التورنت
        start_time = time.time()
        while not handle.has_metadata():
            if time.time() - start_time > 120:  # مهلة 2 دقيقة
                raise Exception("انتهت المهلة في انتظار معلومات التورنت")
            await asyncio.sleep(1)
        
        # الحصول على معلومات الملفات
        files = await asyncio.get_event_loop().run_in_executor(
            executor, torrent_engine.get_files_list, handle
        )
        
        if not files:
            raise Exception("لا توجد ملفات في التورنت")
        
        # اختيار أكبر ملف للتحميل (أو كل الملفات إذا كان ملف واحد)
        if len(files) == 1:
            file_path = os.path.join(DOWNLOAD_DIR, files[0]['path'])
        else:
            # في حالة وجود عدة ملفات، نحمّل الكل
            file_path = os.path.join(DOWNLOAD_DIR, files[0]['path'])
        
        # تحديث الحالة
        last_update = 0
        start_time = time.time()
        
        while True:
            # الحصول على معلومات التحميل
            info = await asyncio.get_event_loop().run_in_executor(
                executor, torrent_engine.get_torrent_info, handle
            )
            
            if info is None:
                raise Exception("فقدان الاتصال بالتورنت")
            
            # حساب التقدم
            progress = info['progress'] * 100
            downloaded = info['total_done']
            total = info['total_wanted']
            speed = info['download_rate']
            eta = (total - downloaded) / speed if speed > 0 else 0
            
            # تحديث الحالة كل 3 ثواني
            now = time.time()
            if now - last_update >= 3:
                last_update = now
                
                # حساب شريط التقدم
                filled = int(20 * progress / 100)
                bar = '█' * filled + '░' * (20 - filled)
                
                text = (
                    f"🎯 **جاري تحميل التورنت...**\n\n"
                    f"[{bar}] {progress:.1f}%\n"
                    f"🚀 **السرعة:** {humanbytes(speed)}/s\n"
                    f"📦 **تم تحميل:** {humanbytes(downloaded)} / {humanbytes(total)}\n"
                    f"⏱️ **المتبقي:** {eta:.0f}s\n"
                    f"🌱 **البذور:** {info['num_seeds']}\n"
                    f"👥 **الأقران:** {info['num_peers']}\n"
                    f"📋 **الملفات:** {len(files)}"
                )
                
                try:
                    await status_msg.edit_text(text)
                except Exception:
                    pass
            
            # التحقق من اكتمال التحميل
            finished = await asyncio.get_event_loop().run_in_executor(
                executor, torrent_engine.is_finished, handle
            )
            
            if finished:
                break
            
            # انتظار قصير
            await asyncio.sleep(2)
        
        # التحقق من وجود الملف
        if os.path.exists(file_path):
            await status_msg.edit_text(
                f"✅ **تم تحميل التورنت بنجاح!**\n\n"
                f"📁 **الملف:** `{os.path.basename(file_path)}`\n"
                f"📦 **الحجم:** `{humanbytes(os.path.getsize(file_path))}`"
            )
            return file_path
        else:
            raise Exception("لم يتم العثور على الملف بعد اكتمال التحميل")
        
    except Exception as e:
        raise Exception(f"فشل تحميل التورنت: {str(e)}")

# ==========================================
# 6. 📥 التحميل المباشر مع شريط تقدم
# ==========================================

def _download_direct_sync(url, progress_callback=None):
    file_name = os.path.join(
        DOWNLOAD_DIR,
        url.split("/")[-1].split("?")[0] or "downloaded_file.bin"
    )
    
    session = requests.Session()
    session.headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        response = session.get(url, stream=True, timeout=(30, 300))
        
        if response.status_code >= 400:
            raise Exception(f"HTTP {response.status_code} — الرابط غير متاح")
        
        total = int(response.headers.get("Content-Length") or 0)
        downloaded = 0
        last = 0.0
        
        with open(file_name, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024*1024):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and (time.time() - last >= 2 or downloaded >= total):
                        last = time.time()
                        try:
                            progress_callback(downloaded, total)
                        except Exception:
                            pass
        
        return file_path
    except Exception as e:
        if os.path.exists(file_name):
            os.remove(file_name)
        raise e

async def download_direct(url, status_msg):
    loop = asyncio.get_event_loop()
    dl_last = [0.0]
    dl_start = [time.time()]

    async def dl_progress(current, total):
        now = time.time()
        if now - dl_last[0] >= 3:
            dl_last[0] = now
            elapsed = now - dl_start[0]
            speed = current / elapsed if elapsed > 0 else 1
            if total:
                percentage = current * 100 / total
                eta = round((total - current) / speed) if speed > 0 else 0
                filled = int(20 * current // total)
                bar = '█' * filled + '░' * (20 - filled)
                text = (
                    f"⬇️ **جاري التنزيل المباشر...**\n\n"
                    f"[{bar}] {percentage:.1f}%\n"
                    f"🚀 **السرعة:** {humanbytes(speed)}/s\n"
                    f"📦 **تم تنزيل:** {humanbytes(current)} / {humanbytes(total)}\n"
                    f"⏱️ **المتبقي:** {eta}s"
                )
            else:
                text = (
                    f"⬇️ **جاري التنزيل المباشر...**\n\n"
                    f"📦 **تم تنزيل:** {humanbytes(current)}\n"
                    f"🚀 **السرعة:** {humanbytes(speed)}/s"
                )
            try:
                await status_msg.edit_text(text)
            except Exception:
                pass

    def thread_cb(current, total):
        asyncio.run_coroutine_threadsafe(dl_progress(current, total), loop)

    return await loop.run_in_executor(None, lambda: _download_direct_sync(url, thread_cb))

# ==========================================
# 7. 🧭 الموجه الذكي
# ==========================================

async def smart_download(url, status_msg):
    """
    🧭 الموجه الذكي لاختيار المحرك المناسب
    """
    # تحويل URL إلى نص صغير للمقارنة
    url_lower = url.lower()
    
    # تورنت
    if url.startswith('magnet:') or url.endswith('.torrent'):
        await status_msg.edit_text("🎯 جاري التحميل من التورنت...")
        return await download_from_torrent(url, status_msg)
    
    # WorkUpload
    if 'workupload.com' in url_lower:
        await status_msg.edit_text("📥 جاري التحميل من WorkUpload...")
        return await download_from_workupload(url)
    
    # GoFile
    if 'gofile.io' in url_lower:
        await status_msg.edit_text("📥 جاري التحميل من GoFile...")
        return await download_from_gofile(url)
    
    # MEGA
    if 'mega.nz' in url_lower or 'mega.io' in url_lower:
        await status_msg.edit_text("⭕ جاري التحميل من MEGA...")
        return await download_from_mega(url)
    
    # تحميل مباشر
    await status_msg.edit_text("⏳ جاري التنزيل المباشر...")
    return await download_direct(url, status_msg)

# ==========================================
# 8. 🔘 لوحة التحكم
# ==========================================

MODES_INFO = {
    "link_to_file": "📥 رابط ⬅️ ملف (تليجرام)",
    "file_to_link": "📤 ملف ⬅️ رابط (Buzzheavier)",
    "link_to_link": "🔄 رابط ⬅️ رابط (Buzzheavier)",
    "torrent_mode": "🎯 تورنت ⬅️ ملف/رابط",
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
        "📥 **رابط ⬅️ ملف:** أرسل رابطاً واستلم الملف في تليجرام\n"
        "📤 **ملف ⬅️ رابط:** أرسل ملفاً واستلم رابط Buzzheavier\n"
        "🔄 **رابط ⬅️ رابط:** أرسل أي رابط واستلم رابط Buzzheavier\n"
        "🎯 **تورنت ⬅️ ملف/رابط:** أرسل رابط مغناطيسي أو ملف تورنت\n\n"
        "المصادر المدعومة:\n"
        "✅ WorkUpload | GoFile | MEGA | تورنت | روابط مباشرة\n\n"
        "اختر الوضع من الأزرار أدناه:",
        reply_markup=get_main_keyboard(user_modes[message.chat.id])
    )

@bot.on_callback_query(filters.regex(r'^mode_'))
async def mode_callback(client, callback: CallbackQuery):
    mode = callback.data.replace("mode_", "")
    user_modes[callback.message.chat.id] = mode
    
    descriptions = {
        "link_to_file": "الوضع الحالي: **تحويل الرابط إلى ملف وإرساله إليك في تليجرام** 📥",
        "file_to_link": "الوضع الحالي: **تحويل الملف المرفوع إلى رابط Buzzheavier** 🔗",
        "link_to_link": "الوضع الحالي: **تحويل أي رابط إلى رابط Buzzheavier جديد** ♻️",
        "torrent_mode": "الوضع الحالي: **تحميل التورنت وإرسال الملف أو الرابط** 🎯\n_(يدعم: روابط مغناطيسية + ملفات .torrent)_",
    }
    
    await callback.message.edit_text(
        f"تم تغيير الوضع بنجاح! ✅\n\n{descriptions.get(mode, '')}\n\nاختر الوضع الذي تريده دائماً عبر الأزرار:",
        reply_markup=get_main_keyboard(mode)
    )
    await callback.answer("تم حفظ الاختيار")

# ==========================================
# 9. 📥 معالج الروابط
# ==========================================

@bot.on_message(filters.regex(r'https?://[^\s]+') & filters.private)
async def handle_links(client, message: Message):
    mode = user_modes.get(message.chat.id, "link_to_file")
    
    if mode == "file_to_link":
        await message.reply_text(
            "⚠️ أنت في وضع **(ملف ⬅️ رابط)**. أرسل ملفاً، أو بدّل إلى وضع آخر من الأزرار."
        )
        return
    
    url = message.text.strip()
    status_msg = await message.reply_text("⚡ جاري تحليل الرابط واختيار المحرك...")
    file_path = None
    last_update = [0]
    
    try:
        file_path = await smart_download(url, status_msg)
        
        if not file_path or not os.path.exists(file_path):
            raise Exception("تعذر تنزيل الملف، يرجى التأكد من الرابط.")
        
        local_size = os.path.getsize(file_path)
        
        # 🔄 وضع: رابط ⬅️ رابط Buzzheavier
        if mode == "link_to_link":
            await status_msg.edit_text(
                f"🚀 تم التنزيل بنجاح ({humanbytes(local_size)})!\nجاري الرفع إلى **Buzzheavier**..."
            )
            buzz_link = await upload_to_buzz_with_progress(file_path, status_msg)
            
            await status_msg.edit_text(
                f"✅ **تم تحويل الرابط إلى رابط Buzzheavier بنجاح!**\n\n"
                f"📁 **اسم الملف:** `{os.path.basename(file_path)}`\n"
                f"📦 **الحجم:** `{humanbytes(local_size)}`\n\n"
                f"🔗 **الرابط الجديد:**\n{buzz_link}"
            )
            return
        
        # 📥 وضع: رابط ⬅️ ملف (تليجرام)
        if local_size > MAX_FILE_SIZE:
            raise Exception(
                f"الملف كبير جداً لتليجرام ({humanbytes(local_size)}).\n"
                f"💡 جرّب وضع 🔄 (رابط ⬅️ رابط) — لا يمر بتليجرام ولا حد عليه."
            )
        
        await status_msg.edit_text(
            f"🚀 تم التنزيل بنجاح ({humanbytes(local_size)})!\nجاري الرفع إلى تليجرام..."
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
        
        # إرسال الملف
        if file_path.lower().endswith(('.mp4', '.mkv', '.avi', '.mov')):
            await message.reply_video(
                video=file_path,
                caption=f"🎬 `{os.path.basename(file_path)}`",
                progress=upload_progress
            )
        else:
            await message.reply_document(
                document=file_path,
                caption=f"📦 `{os.path.basename(file_path)}`",
                progress=upload_progress
            )
        await status_msg.delete()
        
    except Exception as e:
        await status_msg.edit_text(f"❌ حدث خطأ:\n`{str(e)}`")
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

# ==========================================
# 10. 🎯 معالج التورنت
# ==========================================

@bot.on_message(filters.regex(r'(magnet:\?xt=urn:btih:|\.torrent$)') & filters.private)
async def handle_torrent_links(client, message: Message):
    """
    🎯 معالج روابط التورنت
    """
    mode = user_modes.get(message.chat.id, "link_to_file")
    
    if mode not in ("torrent_mode", "link_to_file", "link_to_link"):
        await message.reply_text(
            "⚠️ أرسل رابطاً عادياً، أو بدّل إلى وضع 🎯 **(تورنت)** من الأزرار."
        )
        return
    
    url = message.text.strip()
    status_msg = await message.reply_text("🎯 جاري بدء تحميل التورنت...")
    
    try:
        # تحميل التورنت
        file_path = await download_from_torrent(url, status_msg)
        
        if not file_path or not os.path.exists(file_path):
            raise Exception("تعذر تحميل ملف التورنت")
        
        local_size = os.path.getsize(file_path)
        
        # إذا كان في وضع التورنت
        if mode == "torrent_mode":
            if local_size > MAX_FILE_SIZE:
                # رفع إلى Buzzheavier
                await status_msg.edit_text(
                    f"✅ تم تحميل التورنت ({humanbytes(local_size)})!\n"
                    f"🔗 جاري الرفع إلى Buzzheavier..."
                )
                
                buzz_link = await upload_to_buzz_with_progress(file_path, status_msg)
                
                await status_msg.edit_text(
                    f"✅ **تم تحويل التورنت إلى رابط بنجاح!**\n\n"
                    f"📁 **اسم الملف:** `{os.path.basename(file_path)}`\n"
                    f"📦 **الحجم:** `{humanbytes(local_size)}`\n\n"
                    f"🔗 **الرابط:**\n{buzz_link}"
                )
            else:
                # إرسال مباشر إلى تليجرام
                await status_msg.edit_text(
                    f"✅ تم تحميل التورنت ({humanbytes(local_size)})!\n"
                    f"📤 جاري الإرسال إلى تليجرام..."
                )
                
                # إرسال الملف
                await message.reply_document(
                    document=file_path,
                    caption=f"🎯 `{os.path.basename(file_path)}`"
                )
                await status_msg.delete()
        
        # إذا كان في وضع رابط ⬅️ رابط
        elif mode == "link_to_link":
            await status_msg.edit_text(
                f"✅ تم تحميل التورنت ({humanbytes(local_size)})!\n"
                f"🔗 جاري الرفع إلى Buzzheavier..."
            )
            
            buzz_link = await upload_to_buzz_with_progress(file_path, status_msg)
            
            await status_msg.edit_text(
                f"✅ **تم تحويل التورنت إلى رابط بنجاح!**\n\n"
                f"📁 **اسم الملف:** `{os.path.basename(file_path)}`\n"
                f"📦 **الحجم:** `{humanbytes(local_size)}`\n\n"
                f"🔗 **الرابط:**\n{buzz_link}"
            )
        
    except Exception as e:
        await status_msg.edit_text(f"❌ حدث خطأ أثناء تحميل التورنت:\n`{str(e)}`")
    
    finally:
        if 'file_path' in locals() and os.path.exists(file_path):
            os.remove(file_path)

# ==========================================
# 11. 📤 معالج الملفات
# ==========================================

@bot.on_message((filters.document | filters.video | filters.audio) & filters.private)
async def handle_files(client, message: Message):
    mode = user_modes.get(message.chat.id, "link_to_file")
    
    if mode != "file_to_link":
        await message.reply_text(
            f"⚠️ أنت في وضع **({MODES_INFO.get(mode, 'رابط ⬅️ ملف')})** — أرسل رابطاً، "
            f"أو بدّل إلى وضع 🔗 **(ملف ⬅️ رابط)** من الأزرار."
        )
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
            filled = int(20 * current // total)
            bar = '█' * filled + '░' * (20 - filled)
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
        await status_msg.edit_text("🚀 اكتمل التحميل من تليجرام! جاري الرفع إلى **Buzzheavier**...")
        
        buzz_link = await upload_to_buzz_with_progress(file_path, status_msg)
        
        file_name = os.path.basename(file_path)
        file_size = humanbytes(os.path.getsize(file_path))
        
        await status_msg.edit_text(
            f"✅ **تم تحويل الملف إلى رابط بنجاح!**\n\n"
            f"📁 **اسم الملف:** `{file_name}`\n"
            f"📦 **الحجم:** `{file_size}`\n\n"
            f"🔗 **رابط التحميل المباشر:**\n{buzz_link}"
        )
        
    except Exception as e:
        await status_msg.edit_text(f"❌ حدث خطأ أثناء المعالجة:\n`{str(e)}`")
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

# ==========================================
# 12. 🚀 تشغيل البوت
# ==========================================

async def start_bot():
    try:
        await bot.start()
        print("🟢 البوت يعمل — 4 أوضاع: رابط⬅️ملف | ملف⬅️رابط | رابط⬅️رابط | تورنت⬅️ملف/رابط")
        print("✅ المصادر المدعومة: WorkUpload | GoFile | MEGA | تورنت | روابط مباشرة")
        print("🎯 التورنت: روابط مغناطيسية + ملفات .torrent")
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
