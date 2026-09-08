import sys
import subprocess
import os
import shutil

# 1. 🧠 تثبيت المكتبات والمتصفح تلقائياً
def check_and_install_dependencies():
    required_packages = {
        "pyrogram": "pyrogram",
        "tgcrypto": "tgcrypto",
        "nest_asyncio": "nest_asyncio",
        "requests": "requests",
        "socks": "pysocks",
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
    if not os.path.exists(firefox_cache) or not any(
            "firefox" in f for f in os.listdir(firefox_cache)
            if os.path.isdir(os.path.join(firefox_cache, f))):
        print("🦊 جاري تثبيت متصفح Firefox الخفيف...")
        os.system("playwright install firefox")
        os.system("playwright install-deps firefox")
    else:
        print("✅ متصفح Firefox الخفيف مثبت وجاهز للعمل.")

check_and_install_dependencies()

# ==========================================
# 2. الاستيراد والتهيئات
# ==========================================
import warnings
warnings.filterwarnings("ignore")
import gc
import re
import time
import math
import asyncio
import urllib.parse
import nest_asyncio
import requests
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
                print("🟢 تم إرسال إشارة النشاط لمنع الخمول.")
            except Exception as e:
                print(f"⚠️ تعذر إرسال الإشارة: {e}")

# ==========================================
# 3. 🚀 الرفع إلى Buzzheavier (كما هو — يعمل)
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
    """الرد الرسمي: {"data": {"id": "xxxx"}} → https://buzzheavier.com/{id}"""
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
# 3.5 ⬆️ رفع Buzzheavier مع شريط تقدم (مشترك بين الوضعين)
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
            filled = int(10 * current // total)
            bar = '█' * filled + '░' * (10 - filled)
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

# ⭕ MEGA عبر المتصفح (جديد)
async def download_from_mega(url):
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

            # البحث عن زر التحميل (الأدق أولاً)
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
                    async with page.expect_download(timeout=2700000) as dl_info:  # حتى 45 دقيقة
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

# ⭕ MEGA: المتصفح أولاً — وإن فشل → megatools تلقائياً
async def download_mega_smart(url):
    try:
        return await download_from_mega(url)
    except Exception as e:
        print(f"⚠️ متصفح MEGA فشل: {e} → تجربة megatools...")
    if shutil.which("megadl") is None:
        os.system("apt-get update -qq && apt-get install -y -qq megatools")
    before = set(os.listdir(DOWNLOAD_DIR))
    proc = await asyncio.create_subprocess_exec(
        "megadl", "--path", DOWNLOAD_DIR + os.sep, url,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    await proc.wait()
    new_files = [f for f in os.listdir(DOWNLOAD_DIR) if f not in before]
    if new_files:
        return os.path.join(DOWNLOAD_DIR, sorted(new_files)[0])
    raise Exception("فشل تحميل رابط MEGA (المتصفح و megatools كلاهما)")

# ⬇️ تنزيل مباشر مع شريط تقدم (محسّن)
def _download_direct_sync(url, progress_callback=None):
    file_name = os.path.join(
        DOWNLOAD_DIR,
        url.split("/")[-1].split("?")[0] or "downloaded_file.bin"
    )
    session = requests.Session()
    session.headers = {"User-Agent": "Mozilla/5.0"}
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
    return file_name

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
                filled = int(10 * current // total)
                bar = '█' * filled + '░' * (10 - filled)
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

# 🧭 الموجّه الذكي — يختار المحرك حسب نوع الرابط
async def smart_download(url, status_msg):
    if "gofile.io" in url:
        await status_msg.edit_text("🦊 جاري تشغيل المتصفح الخفيف والتحميل من GoFile...")
        return await download_from_gofile(url)
    if "workupload.com" in url:
        await status_msg.edit_text("🦊 جاري تشغيل المتصفح الخفيف والتحميل من WorkUpload...")
        return await download_from_workupload(url)
    if "mega.nz" in url or "mega.io" in url:
        await status_msg.edit_text("⭕ جاري التحميل من MEGA (MEGA يشفّر الملفات — اصبر عليه)...")
        return await download_mega_smart(url)
    await status_msg.edit_text("⏳ جاري التنزيل المباشر...")
    return await download_direct(url, status_msg)

# ==========================================
# 5. 🔘 لوحة التحكم (3 أوضاع)
# ==========================================
MODES_INFO = {
    "link_to_file": "رابط ⬅️ ملف (تليجرام)",
    "file_to_link": "ملف ⬅️ رابط (Buzzheavier)",
    "link_to_link": "رابط ⬅️ رابط (Buzzheavier)",
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
        "📥 **رابط ⬅️ ملف:** أرسل رابطاً (GoFile/WorkUpload/MEGA/مباشر) واستلم الملف في تليجرام\n"
        "🔗 **ملف ⬅️ رابط:** أرسل ملفاً واستلم رابط Buzzheavier\n"
        "♻️ **رابط ⬅️ رابط:** أرسل أي رابط واستلم رابط Buzzheavier جديداً (بدون حد 2GB!)\n\n"
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
        "link_to_link": "الوضع الحالي: **تحويل أي رابط إلى رابط Buzzheavier جديد** ♻️\n_(يدعم: GoFile + WorkUpload + MEGA + الروابط المباشرة)_",
    }
    await callback.message.edit_text(
        f"تم تغيير الوضع بنجاح! ✅\n\n{descriptions.get(mode, '')}\n\nاختر الوضع الذي تريده دائماً عبر الأزرار:",
        reply_markup=get_main_keyboard(mode)
    )
    await callback.answer("تم حفظ الاختيار")

# 📥📥 استقبال الروابط (وضعا: رابط⬅️ملف + رابط⬅️رابط)
@bot.on_message(filters.regex(r'https?://[^\s]+') & filters.private)
async def handle_links(client, message: Message):
    mode = user_modes.get(message.chat.id, "link_to_file")
    if mode == "file_to_link":
        await message.reply_text(
            "⚠️ أنت في وضع **(ملف ⬅️ رابط)**. أرسل ملفاً، أو بدّل إلى وضع 📥 أو ♻️ من الأزرار."
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

        # ♻️ الوضع الجديد: رابط ⬅️ رابط Buzzheavier (بدون حد تليجرام)
        if mode == "link_to_link":
            await status_msg.edit_text(
                f"🚀 تم التنزيل بنجاح ({humanbytes(local_size)})!\nجاري الرفع إلى **Buzzheavier**..."
            )
            buzz_link = await upload_to_buzz_with_progress(file_path, status_msg)
            print(f"🔗 [رابط⬅️رابط] تم الرفع: {buzz_link}")
            await status_msg.edit_text(
                f"✅ **تم تحويل الرابط إلى رابط Buzzheavier بنجاح!**\n\n"
                f"📁 **اسم الملف:** `{os.path.basename(file_path)}`\n"
                f"📦 **الحجم:** `{humanbytes(local_size)}`\n\n"
                f"🔗 **الرابط الجديد:**\n{buzz_link}"
            )
            return

        # 📥 الوضع القديم: رابط ⬅️ ملف (تليجرام)
        if local_size > MAX_FILE_SIZE:
            raise Exception(
                f"الملف كبير جداً لتليجرام ({humanbytes(local_size)}).\n"
                f"💡 جرّب وضع ♻️ (رابط ⬅️ رابط) — لا يمر بتليجرام ولا حد عليه."
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

# 📤 استقبال الملفات → رفع إلى Buzzheavier
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
        await status_msg.edit_text("🚀 اكتمل التحميل من تليجرام! جاري الرفع إلى **Buzzheavier**...")

        buzz_link = await upload_to_buzz_with_progress(file_path, status_msg)
        print(f"🔗 [ملف⬅️رابط] تم الرفع: {buzz_link}")

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

async def start_bot():
    try:
        await bot.start()
        print("🟢 البوت يعمل — 3 أوضاع: رابط⬅️ملف | ملف⬅️رابط | رابط⬅️رابط (مع دعم MEGA)")
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
