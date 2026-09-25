#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
════════════════════════════════════════════════════════════════════
              SILMA F5-TTS Auto Dubber — الإصدار 3.0
     (حقل تفاعلي لاسم الملف + بحث تلقائي في Drive + تسريع بلا قطع)
════════════════════════════════════════════════════════════════════

ماذا يفعل؟
  1) يطلب منك اسم ملف الترجمة (حقل إدخال)
  2) يبحث عنه في Google Drive ويربطه
  3) يدبلج الملف كاملًا — لا قطع أبدًا: مهما طال السطر يُسَّرع
     (يحفظ النغمة) ليدخل وقته، ولا تُبتر أي كلمة.

في كولاب: شغّل خلية التشغيل — سيظهر لك حقل تكتب فيه اسم الملف.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

# ══════════════════════════════════════════════════════════════════
# القسم 1 — الإعدادات المركزية
# ══════════════════════════════════════════════════════════════════

SAMPLE_RATE = 24000          # معدل عينات النموذج
CPS_INITIAL = 11.0           # تقدير أولي: حروف نطق/ثانية — يُعاير تلقائيًا


@dataclass
class Config:
    """سياسة المزامنة — تسريع دائمًا، قطع أبدًا."""
    borrow_ratio: float = 0.60   # نسبة استعارة فجوة الصمت التالية
    borrow_max:    float = 0.50  # سقف الاستعارة (500ms)
    min_gap:       float = 0.12  # أقل صمت مضمون قبل السطر التالي
    max_gen_speed: float = 1.35  # سقف سرعة التوليد داخل النموذج
    max_parts:     int   = 6     # أقصى عدد أجزاء للسطر الواحد
    chunk_max:     int   = 230   # حد أمان عدد حروف استدعاء التوليد الواحد
    part_gap_ms:   int   = 60    # صمت بين أجزاء السطر الواحد
    no_regen:      bool  = False # تعطيل إعادة التوليد (توفير وقت)


@dataclass
class Segment:
    """سطر ترجمة + كل قياساته الميدانية (تُكتب في التقرير)."""
    index: int
    start_ms: int
    end_ms: int
    text: str
    budget_sec: float = 0.0
    raw_sec:     float = 0.0
    final_sec:   float = 0.0
    gen_speed:   float = 1.0
    dsp_factor:  float = 1.0
    parts:       int   = 1
    outcome:     str  = ""     # ok / fast / fail — لا وجود لـ cut


# ══════════════════════════════════════════════════════════════════
# القسم 2 — تجهيز البيئة (ffmpeg + الحزم) تلقائيًا
# ══════════════════════════════════════════════════════════════════

REQUIRED_PACKAGES = ["silma-tts", "soundfile", "pydub",
                     "numpy", "torch", "torchaudio", "tqdm"]


def bootstrap(ffmpeg_path: str | None) -> str:
    """يفحص ffmpeg والحزم ويثبّت الناقص. يعيد مسار ffmpeg."""
    print("⏳ [1/6] فحص البيئة والتبعيات...")

    ff = ffmpeg_path or shutil.which("ffmpeg")
    if not ff and shutil.which("apt-get"):
        subprocess.run(["apt-get", "update", "-qq"], capture_output=True)
        subprocess.run(["apt-get", "install", "-y", "-qq", "ffmpeg"],
                       capture_output=True)
        ff = shutil.which("ffmpeg")
    if not ff:
        sys.exit("❌ ffmpeg غير موجود — ثبّته أو مرّر مساره عبر --ffmpeg")

    import importlib
    for pkg in REQUIRED_PACKAGES:
        try:
            importlib.import_module(pkg.replace("-", "_"))
        except ImportError:
            print(f"   📦 تثبيت {pkg} ...")
            r = subprocess.run([sys.executable, "-m", "pip",
                                "install", "-q", pkg])
            if r.returncode != 0:
                sys.exit(f"❌ فشل تثبيت {pkg}")
    print("✅ البيئة جاهزة.")
    return ff


# ══════════════════════════════════════════════════════════════════
# القسم 3 — محلل الترجمة (SRT / VTT) المتين
# ══════════════════════════════════════════════════════════════════

TS_RE = re.compile(
    r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})\s*-->\s*"
    r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})"
)

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def _to_ms(h, m, s, ms) -> int:
    return ((int(h or 0) * 3600 + int(m) * 60 + int(s)) * 1000
            + int(ms.ljust(3, "0")))


def clean_text(t: str) -> str:
    """ينظّف ما لا يُنطق: وسوم HTML/ASS، ملاحظات [..] و(..)، رموز، تشكيل المدد."""
    t = re.sub(r"<[^>]+>", " ", t)          # <i>, <font ...>
    t = re.sub(r"\{\\[^}]*\}", " ", t)      # {\an8}
    t = re.sub(r"\[.*?\]", " ", t)          # [موسيقى]
    t = re.sub(r"\(.*?\)", " ", t)          # (على الشاشة)
    t = re.sub(r"[♪♫►#*]", " ", t)
    t = re.sub(r"^[-–—]\s*", "", t)         # شرطة حوار
    t = t.translate(_DIGITS)                # أرقام هندية → غربية
    t = re.sub(r"\u0640", "", t)            # تطويل
    t = re.sub(r"[\u200e\u200f\u00a0]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def speech_chars(t: str) -> int:
    """عدد الحروف المؤثرة في مدة النطق (بدون مسافات)."""
    return len(re.sub(r"\s", "", t))


def read_text_file(path: Path) -> str:
    """قراءة مرنة: UTF-8 (مع/بدون BOM) ثم cp1256 الشائع للعربية القديمة."""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp1256", "utf-16"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def parse_subtitles(path: Path) -> list[Segment]:
    """يمشي سطرًا سطرًا — يتحمّل CRLF، الترقيم المفقود، ترويسة VTT،
    الوسوم، الأسطر المتعددة، والطوابع بصيغتي الفاصلة والنقطة."""
    lines = read_text_file(path).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    segs: list[Segment] = []
    i, idx = 0, 0
    while i < len(lines):
        m = TS_RE.search(lines[i].strip())
        if not m:
            i += 1
            continue
        start_ms = _to_ms(m[1], m[2], m[3], m[4])
        end_ms   = _to_ms(m[5], m[6], m[7], m[8])
        i += 1
        buf = []
        while i < len(lines):
            L = lines[i].strip()
            if not L or TS_RE.search(L):
                break
            buf.append(L)
            i += 1
        text = clean_text(" ".join(buf))
        if text and end_ms > start_ms + 50:
            idx += 1
            segs.append(Segment(idx, start_ms, end_ms, text))
    segs.sort(key=lambda s: (s.start_ms, s.index))
    return segs


# ══════════════════════════════════════════════════════════════════
# القسم 4 — تقسيم النص عند حدود طبيعية
# ══════════════════════════════════════════════════════════════════

BREAK_RE = re.compile(r"(?<=[.!?؟…،؛:])\s+")


def split_sentences(t: str) -> list[str]:
    return [s for s in BREAK_RE.split(t) if s.strip()]


def split_balanced(text: str, k: int) -> list[str]:
    """يقسّم النص إلى k جزء متوازن تقريبًا:
    أولًا عند علامات الترقيم، وإن لم تكفِ يقصّ الأطول عند المسافات."""
    if k <= 1:
        return [text]
    units = split_sentences(text)
    while len(units) < k:
        units.sort(key=len, reverse=True)
        longest = units[0]
        if " " not in longest or len(longest) < 8:
            break
        mid = len(longest) // 2
        l = longest.rfind(" ", 0, mid)
        r = longest.find(" ", mid)
        cut = l if (l >= 0 and (r < 0 or mid - l <= r - mid)) else r
        if cut <= 0:
            break
        units[0] = longest[:cut]
        units.insert(1, longest[cut + 1:])

    target = len(text) / k
    out, cur, cl = [], "", 0
    for u in units:
        if cur and cl + len(u) > target and len(out) < k - 1:
            out.append(cur.strip())
            cur, cl = u, len(u)
        else:
            cur = f"{cur} {u}".strip()
            cl += len(u)
    if cur.strip():
        out.append(cur.strip())
    return out or [text]


# ══════════════════════════════════════════════════════════════════
# القسم 5 — العمليات الصوتية (تسريع بلا قطع أبدًا)
# ══════════════════════════════════════════════════════════════════

def trim_silence(seg, threshold_db: int = -42, pad_ms: int = 40):
    """اقتطاع صمت الطرفين (النموذج يضيف صمتًا مضللًا للقياس)."""
    from pydub import AudioSegment
    from pydub.silence import detect_leading_silence
    a = detect_leading_silence(seg, silence_threshold=threshold_db)
    b = detect_leading_silence(seg.reverse(), silence_threshold=threshold_db)
    trimmed = seg[a: len(seg) - b] if b else seg[a:]
    if not len(trimmed):
        return seg
    silence = lambda: AudioSegment.silent(duration=pad_ms, frame_rate=seg.frame_rate)
    return silence() + trimmed + silence()


def stretch(clip, factor: float, ffmpeg_bin: str, workdir: Path):
    """تسريع يحفظ النغمة عبر ffmpeg atempo — بلا سقف وبلا قطع أبدًا.
    مهما كان التجاوز: يُبنى سلسلة atempo بالقدر المطلوب بالضبط.
    الاحتياط عند فشل ffmpeg: إعادة تشكيل العينات (تغيّر النغمة قليلًا
    لكن تحفظ كل الكلام — لا بتر في الحالتين)."""
    from pydub import AudioSegment
    if factor <= 1.02 or len(clip) < 300:
        return clip
    factor = max(0.5, min(factor, 20.0))
    # atempo يعمل حتى ×2 لكل طبقة — نبني سلسلة بالقدر المطلوب
    chain, f = [], factor
    while f > 2.0:
        chain.append("atempo=2.0")
        f /= 2.0
    chain.append(f"atempo={f:.4f}")

    inp, outp = workdir / "st_in.wav", workdir / "st_out.wav"
    clip.export(inp, format="wav")
    r = subprocess.run(
        [ffmpeg_bin, "-y", "-loglevel", "error", "-i", str(inp),
         "-filter:a", ",".join(chain),
         "-ar", str(SAMPLE_RATE), "-ac", "1", str(outp)])
    if r.returncode != 0 or not outp.exists():
        # الاحتياط: تسريع بإعادة تشكيل العينات — يبقى كل الكلام، لا قطع
        try:
            new_rate = int(clip.frame_rate * factor)
            fast = clip._spawn(clip.raw_data,
                               overrides={"frame_rate": new_rate})
            return fast.set_frame_rate(SAMPLE_RATE)
        except Exception:
            return clip
    return AudioSegment.from_file(outp, format="wav")


def finalize_clip(clip):
    """تشذيب ناعم للحواف فقط (منع النقرات) — لا بتر أبدًا.
    التسريع يحل محل القطع في كل الحالات."""
    return clip.fade_in(10).fade_out(25)


# ══════════════════════════════════════════════════════════════════
# القسم 6 — غلاف محرك SILMA (توليد + تخزين مؤقت)
# ══════════════════════════════════════════════════════════════════

DEFAULT_REF_TEXT = ("ويدقق النظر في القرآن الكريم وسائر الكتب السماوية "
                    "ويتبع مسالك الرسل العظام عليهم الصلاة والسلام.")


def default_reference_audio() -> str:
    """العينة الصوتية المرجعية المدمجة مع الحزمة."""
    try:
        from importlib.resources import files
        return str(files("silma_tts").joinpath(
            "infer/ref_audio_samples/ar.ref.24k.wav"))
    except Exception:
        import silma_tts
        return str(Path(silma_tts.__file__).parent /
                   "infer/ref_audio_samples/ar.ref.24k.wav")


class SilmaEngine:
    """يغلّف النموذج مع: تخزين مؤقت (استئناف مجاني) وضبط موحّد للخرج."""

    def __init__(self, device="auto", seed=42, nfe=16,
                 ref_audio=None, ref_text=None,
                 cache_dir=None, use_cache=True):
        from silma_tts.api import SilmaTTS
        import torch

        dev = device
        if dev == "auto":
            dev = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = dev
        print(f"🚀 معالج التسريع: {dev.upper()}")

        self.engine = SilmaTTS(device=dev)
        self.seed, self.nfe = seed, nfe

        if ref_audio and ref_text:
            self.ref_audio = str(Path(ref_audio).resolve())
            self.ref_text = ref_text
            print(f"🎙 صوت مرجعي مخصص: {self.ref_audio}")
        else:
            self.ref_audio = default_reference_audio()
            self.ref_text = DEFAULT_REF_TEXT
            print("🎙 صوت مرجعي: العينة الفصيحة المدمجة")

        self.cache = Path(cache_dir) if (cache_dir and use_cache) else None
        if self.cache:
            self.cache.mkdir(parents=True, exist_ok=True)
            print(f"💾 التخزين المؤقت: {self.cache}")

    def _key(self, text: str, speed: float) -> str:
        h = hashlib.sha1()
        mtime = os.path.getmtime(self.ref_audio) if os.path.exists(self.ref_audio) else 0
        h.update(f"{text}|{speed:.2f}|{self.seed}|{self.nfe}|{self.ref_audio}|{mtime}"
                 .encode("utf-8"))
        return h.hexdigest()[:20]

    def generate(self, text: str, speed: float, out_wav: Path):
        """يولّد نصًا واحدًا → AudioSegment موحّد (24kHz أحادي)."""
        from pydub import AudioSegment

        cached_path = self.cache / f"{self._key(text, speed)}.wav" if self.cache else None
        if cached_path and cached_path.exists():
            seg = AudioSegment.from_file(cached_path, format="wav")
            return seg.set_frame_rate(SAMPLE_RATE).set_channels(1), True

        self.engine.infer(
            ref_file=self.ref_audio,
            ref_text=self.ref_text,
            gen_text=text,
            file_wave=str(out_wav),
            seed=self.seed,
            speed=speed,
            nfe_step=self.nfe,
        )
        seg = AudioSegment.from_file(out_wav, format="wav")
        seg = seg.set_frame_rate(SAMPLE_RATE).set_channels(1)

        if cached_path:
            try:
                shutil.copyfile(out_wav, cached_path)
            except Exception:
                pass
        return seg, False


# ══════════════════════════════════════════════════════════════════
# القسم 7 — محرك المزامنة (تسريع بدل القطع — دائمًا)
# ══════════════════════════════════════════════════════════════════

class SyncEngine:
    def __init__(self, engine: SilmaEngine, cfg: Config,
                 ffmpeg_bin: str, workdir: Path):
        self.engine = engine
        self.cfg = cfg
        self.ffmpeg = ffmpeg_bin
        self.workdir = workdir
        self.cps = CPS_INITIAL
        self.regens = 0
        self._n = itertools.count()

    # ── الزمن المتاح ──────────────────────────────────────────
    def budget(self, segs: list[Segment], i: int) -> float:
        """مدة السطر + استعارة من الفجوة التالية."""
        s = segs[i]
        win = (s.end_ms - s.start_ms) / 1000.0
        if i + 1 < len(segs):
            gap = max(0.0, (segs[i + 1].start_ms - s.end_ms) / 1000.0)
            win += min(self.cfg.borrow_ratio * gap, self.cfg.borrow_max)
        else:
            win += self.cfg.borrow_max
        return max(0.3, win)

    # ── توليد أجزاء السطر ─────────────────────────────────────
    def _generate_parts(self, parts: list[str], speed: float):
        """يولّد كل جزء، يقص صمته، يعاير السرعة المكتسبة، ويدمج بفاصل قصير."""
        from pydub import AudioSegment
        chunks, raw = [], 0.0
        for p in parts:
            wav = self.workdir / f"part_{next(self._n)}.wav"
            try:
                seg, _cached = self.engine.generate(p, speed, wav)
            except Exception as e:
                print(f"   ⚠ فشل توليد جزء: {e}")
                continue
            seg = trim_silence(seg)
            d = len(seg) / 1000.0
            raw += d
            ch = speech_chars(p)
            if ch >= 8 and d > 0.3:
                measured = ch / max(0.05, d - 0.05)
                self.cps = 0.8 * self.cps + 0.2 * measured
            chunks.append(seg)

        if not chunks:
            return None, 0.0
        if len(chunks) == 1:
            return chunks[0], raw
        gap = AudioSegment.silent(duration=self.cfg.part_gap_ms,
                                  frame_rate=SAMPLE_RATE)
        joined = chunks[0]
        for c in chunks[1:]:
            joined += gap + c
        return joined, raw + self.cfg.part_gap_ms / 1000.0 * (len(chunks) - 1)

    # ── معالجة سطر واحد ───────────────────────────────────────
    def process(self, segs: list[Segment], i: int):
        seg = segs[i]
        budget = self.budget(segs, i)
        seg.budget_sec = budget
        chars = speech_chars(seg.text)
        est = chars / self.cps

        # 1) التقسيم المسبق للجمل الطويلة
        k = max(1, math.ceil(est / (budget * 0.95)))
        k = max(k, math.ceil(len(seg.text) / self.cfg.chunk_max))
        k = min(k, self.cfg.max_parts)
        parts = [seg.text] if k <= 1 else split_balanced(seg.text, k)
        seg.parts = len(parts)

        # 2) التوليد الأول — بسرعة مقدّرة فقط لو كان التجاوز واضحًا
        speed0 = 1.0
        if est > budget * 1.25:
            speed0 = min(self.cfg.max_gen_speed, est / budget)

        joined, dur = self._generate_parts(parts, speed0)
        if joined is None:
            seg.outcome = "fail"
            return None
        dur = len(joined) / 1000.0

        # 3) إعادة توليد بسرعة أعلى إن كان التجاوز كبيرًا (جودة أفضل)
        if (not self.cfg.no_regen
                and speed0 < self.cfg.max_gen_speed
                and dur > budget * 1.10):
            speed1 = min(self.cfg.max_gen_speed, speed0 * dur / budget)
            if speed1 >= speed0 * 1.05:
                joined2, _ = self._generate_parts(parts, speed1)
                if joined2 is not None and len(joined2) < len(joined):
                    joined = joined2
                    dur = len(joined) / 1000.0
                    speed0 = speed1
                    self.regens += 1

        seg.raw_sec = dur
        seg.gen_speed = speed0

        # 4) التسريع الرقمي — بلا سقف، مهما كان التجاوز.
        #    لا قطع أبدًا: السطر يدخل وقته بالتسريع حصرًا.
        outcome = "ok"
        if dur > budget * 1.02:
            factor = dur / budget          # بالضبط المطلوب — بلا حد أقصى
            joined = stretch(joined, factor, self.ffmpeg, self.workdir)
            seg.dsp_factor = factor
            outcome = "fast"
            dur = len(joined) / 1000.0

        # 5) تشذيب الحواف فقط — لا بتر. إن بقي فارق ميلي ثوانٍ
        #    يدخل في هامش الصمت، ولا تُقطع كلمة.
        joined = finalize_clip(joined)
        seg.final_sec = len(joined) / 1000.0
        seg.outcome = outcome
        return joined


# ══════════════════════════════════════════════════════════════════
# القسم 8 — التقرير (CSV + ملخص)
# ══════════════════════════════════════════════════════════════════

OUTCOME_AR = {"ok": "✓ دخل زمنه", "fast": "⚡ سُرِّع (بلا قطع)", "fail": "✗ فشل"}


def write_report(csv_path: Path, segs: list[Segment], meta: dict):
    head = ("index,start_sec,end_sec,budget_sec,raw_sec,final_sec,"
            "gen_speed,dsp_factor,parts,outcome,text\n")
    rows = []
    for s in segs:
        rows.append(",".join([
            str(s.index), f"{s.start_ms/1000:.3f}", f"{s.end_ms/1000:.3f}",
            f"{s.budget_sec:.3f}", f"{s.raw_sec:.3f}", f"{s.final_sec:.3f}",
            f"{s.gen_speed:.2f}", f"{s.dsp_factor:.2f}",
            str(s.parts), s.outcome,
            f'"{s.text.replace(chr(34), chr(34)*2)}"',
        ]))
    csv_path.write_text("\ufeff" + head + "\n".join(rows), encoding="utf-8")

    counts = {k: sum(1 for s in segs if s.outcome == k)
              for k in ("ok", "fast", "fail")}
    ratios = [s.raw_sec / s.budget_sec for s in segs
              if s.outcome == "fast" and s.budget_sec > 0]
    avg_ratio = sum(ratios) / len(ratios) if ratios else 0.0

    lines = [
        "══════════ تقرير الدبلجة ══════════",
        f"إجمالي الأسطر          : {len(segs)}",
    ] + [f"{OUTCOME_AR[k]:<22} : {v}" for k, v in counts.items()] + [
        f"أسطر مقطوعة            : 0 (السياسة: تسريع بدل القطع)",
        f"متوسط نسبة التجاوز قبل الضبط : {avg_ratio:.2f}",
        f"سرعة النموذج المعايرة   : {meta['cps']:.1f} حرف/ث",
        f"مرات إعادة التوليد      : {meta['regens']}",
        f"زمن المعالجة            : {meta['elapsed']:.0f} ث "
        f"(عامل السرعة ×{meta['rtf']:.1f})",
        f"الإعدادات               : {meta['cfg']}",
        "",
    ]
    txt = csv_path.with_suffix(".summary.txt")
    txt.write_text("\n".join(lines), encoding="utf-8")

    print("\n".join(lines))
    print(f"📊 التقرير التفصيلي: {csv_path}")
    return counts


# ══════════════════════════════════════════════════════════════════
# القسم 9 — Google Drive + البحث عن ملف الترجمة الذي ترسله
# ══════════════════════════════════════════════════════════════════

SUB_EXTS = (".srt", ".vtt", ".ass")


def mount_drive():
    try:
        from google.colab import drive
        if not os.path.exists("/content/drive/MyDrive"):
            drive.mount("/content/drive")
        return "/content/drive/MyDrive"
    except Exception:
        return None


def collect_drive_subtitles(root) -> list[Path]:
    """يجمع كل ملفات الترجمة في Google Drive (بحث شامل في كل المجلدات)."""
    subs = []
    for dirpath, _, filenames in os.walk(root):
        for f in filenames:
            if f.lower().endswith(SUB_EXTS):
                subs.append(Path(dirpath) / f)
    return subs


def match_subtitle(subs: list[Path], name: str) -> Path | None:
    """يطابق الاسم الذي أرسلته أنت:
    1) الاسم الكامل  2) بدون الامتداد  3) جزئيًا (يحتوي الاسم)."""
    t = name.strip().lower()
    for p in subs:
        if p.name.lower() == t:
            return p
    for p in subs:
        if p.stem.lower() == t:
            return p
    for p in subs:
        if t and t in p.name.lower():
            return p
    return None


# ══════════════════════════════════════════════════════════════════
# القسم 10 — المسار الرئيسي
# ══════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(
        description="SILMA F5-TTS Auto Dubber v3.0 — حقل تفاعلي + بحث في Drive + تسريع بلا قطع")
    ap.add_argument("--file", "-f",
                    help="(اختياري) اسم الملف أو مساره — إن تُرك فارغًا سيُطلب منك")
    ap.add_argument("--out-dir", help="مجلد الإخراج (افتراضي: بجانب ملف الترجمة)")
    ap.add_argument("--ref-audio", help="عينة صوتية للاستنساخ الصوتي (wav)")
    ap.add_argument("--ref-text", help="النص المطابق حرفيًا للعينة الصوتية")
    ap.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--nfe", type=int, default=16)
    ap.add_argument("--limit", type=int, default=0,
                    help="معالجة أول N سطر فقط (بدونه: الملف كاملًا)")
    ap.add_argument("--skip", type=int, default=0,
                    help="تخطي أول N سطر (بدونه: البدء من أول سطر)")
    ap.add_argument("--borrow-ratio", type=float, default=0.60)
    ap.add_argument("--borrow-max", type=float, default=0.50)
    ap.add_argument("--min-gap", type=float, default=0.12)
    ap.add_argument("--max-parts", type=int, default=6)
    ap.add_argument("--no-regen", action="store_true")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--cache-dir", help="مجلد التخزين المؤقت (افتراضي: بجانب الترجمة)")
    ap.add_argument("--mp3", action="store_true", help="تصدير نسخة MP3 إضافية")
    ap.add_argument("--no-drive", action="store_true")
    ap.add_argument("--ffmpeg", help="مسار ffmpeg إن لم يكن في PATH")
    args = ap.parse_args()

    print("═══ SILMA Auto Dubber v3.0 — حقل تفاعلي + تسريع بلا قطع ═══")
    print(f"🔵 الأمر الواصل: {' '.join(sys.argv)}")

    ffmpeg_bin = bootstrap(args.ffmpeg)

    # [2/6] ربط Google Drive
    drive_root = None
    if not args.no_drive:
        print("\n⏳ [2/6] ربط Google Drive...")
        drive_root = mount_drive()
        print("✅ Drive جاهز." if drive_root else "ℹ تشغيل محلي بدون Drive.")

    # [3/6] ملف الترجمة — أنت ترسل الاسم، والسكربت يجده في Drive
    print("\n⏳ [3/6] ملف الترجمة...")
    if args.file:
        p = Path(args.file).expanduser()
        if p.is_file():
            srt_path = p                      # مسار مباشر صحيح
        elif drive_root:
            subs = collect_drive_subtitles(drive_root)
            print(f"🔎 البحث عن '{args.file}' في Google Drive "
                  f"({len(subs)} ملف ترجمة)...")
            srt_path = match_subtitle(subs, p.name)
            if not srt_path:
                sys.exit(f"❌ لم يُعثر على '{args.file}' في Google Drive.")
        else:
            sys.exit(f"❌ الملف غير موجود: {p}")
    else:
        # الحقل التفاعلي — السكربت يسألك وأنت تكتب الاسم
        if not drive_root:
            sys.exit("❌ مرّر الاسم عبر --file أو شغّل مع Google Drive.")
        try:
            name = input("📝 اكتب اسم ملف الترجمة (مثال: example.srt): ").strip()
        except EOFError:
            sys.exit("❌ لا يمكن إظهار حقل الإدخال هنا — مرّر الاسم عبر --file")
        subs = collect_drive_subtitles(drive_root)
        print(f"🔎 البحث عن '{name}' في Google Drive ({len(subs)} ملف ترجمة)...")
        srt_path = match_subtitle(subs, name)
        if not srt_path:
            print("❌ لم يُعثر على تطابق. الملفات المتاحة في Drive:")
            for sp in subs[:20]:
                print(f"   • {sp.name}")
            sys.exit(1)
    print(f"✅ الملف: {srt_path}")

    segs = parse_subtitles(srt_path)
    if not segs:
        sys.exit("❌ الملف لا يحتوي أسطر ترجمة صالحة.")
    total_parsed = len(segs)

    # التحديد بيدك وحدك — الافتراضي: الملف كاملًا
    if args.skip > 0:
        segs = segs[min(args.skip, len(segs)):]
    if args.limit > 0:
        segs = segs[:args.limit]
    if not segs:
        sys.exit("❌ لا توجد أسطر ضمن النطاق المحدد.")
    print(f"✅ سيتم معالجة {len(segs)} من {total_parsed} سطرًا — "
          f"آخر توقيت: {max(s.end_ms for s in segs)/1000:.1f} ثانية")

    # [4/6] النموذج
    print("\n⏳ [4/6] تحميل نموذج SILMA F5-TTS...")
    cache_dir = args.cache_dir or (srt_path.parent / ".silma_cache")
    engine = SilmaEngine(device=args.device, seed=args.seed, nfe=args.nfe,
                         ref_audio=args.ref_audio, ref_text=args.ref_text,
                         cache_dir=cache_dir, use_cache=not args.no_cache)

    # [5/6] التوليد والمزامنة
    print(f"\n⏳ [5/6] بدء التوليد والمزامنة ({len(segs)} سطرًا)...")
    cfg = Config(borrow_ratio=args.borrow_ratio, borrow_max=args.borrow_max,
                 min_gap=args.min_gap, max_parts=args.max_parts,
                 no_regen=args.no_regen)
    workdir = Path(tempfile.mkdtemp(prefix="silma_work_"))
    sync = SyncEngine(engine, cfg, ffmpeg_bin, workdir)

    import numpy as np
    from pydub import AudioSegment

    total_ms = max(s.end_ms for s in segs) + 1500
    master = np.zeros(int(total_ms * SAMPLE_RATE / 1000) + SAMPLE_RATE,
                      dtype=np.float32)

    t0 = time.time()
    marks = {"ok": "✓", "fast": "⚡", "fail": "✗"}
    for i in range(len(segs)):
        clip = sync.process(segs, i)
        seg = segs[i]
        if clip is not None and len(clip):
            a = int(seg.start_ms * SAMPLE_RATE / 1000)
            x = np.array(clip.get_array_of_samples(),
                         dtype=np.float32) / 32768.0
            end = min(a + len(x), len(master))
            master[a:end] += x[:end - a]

        done = i + 1
        print(f"  {marks[seg.outcome]} [{done}/{len(segs)}] "
              f"{seg.text[:38]}{'…' if len(seg.text) > 38 else ''} "
              f"(متاح {seg.budget_sec:.1f}ث ← ناتج {seg.final_sec:.1f}ث)")

        if done % 10 == 0 and done < len(segs):
            eta = (time.time() - t0) / done * (len(segs) - done)
            print(f"  ⏳ الوقت المتوقع للانتهاء: ~{eta/60:.1f} دقيقة")

    # [6/6] التجميع والتصدير
    print("\n⏳ [6/6] التجميع والتصدير...")
    peak = float(np.abs(master).max()) if master.size else 0.0
    if peak > 0.95:
        master *= 0.95 / peak
    pcm = np.clip(master * 32767.0, -32768, 32767).astype(np.int16)
    final = AudioSegment(pcm.tobytes(), sample_width=2,
                         frame_rate=SAMPLE_RATE, channels=1)

    out_dir = Path(args.out_dir) if args.out_dir else srt_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    base = srt_path.stem
    out_wav = out_dir / f"{base}_SILMA_Dubbed.wav"
    final.export(out_wav, format="wav")
    print(f"📁 الملف الصوتي: {out_wav}")

    if args.mp3:
        try:
            out_mp3 = out_dir / f"{base}_SILMA_Dubbed.mp3"
            final.export(out_mp3, format="mp3", bitrate="160k")
            print(f"📁 نسخة MP3   : {out_mp3}")
        except Exception as e:
            print(f"⚠ تعذّر تصدير MP3: {e}")

    elapsed = time.time() - t0
    counts = write_report(out_dir / f"{base}_report.csv", segs, {
        "cps": sync.cps, "regens": sync.regens, "elapsed": elapsed,
        "rtf": (total_ms / 1000) / max(elapsed, 0.1),
        "cfg": f"borrow={cfg.borrow_ratio}/{cfg.borrow_max}, "
               f"gen≤{cfg.max_gen_speed}, تسريع بلا سقف — لا قطع أبدًا",
    })

    print(f"\n🎉 اكتملت الدبلجة في {elapsed:.0f} ثانية "
          f"(أسرع من الزمن الحقيقي ×{(total_ms/1000)/max(elapsed,0.1):.1f})")

    # معاينة داخل كولاب (المخرج الكامل محفوظ أعلاه)
    try:
        from IPython.display import Audio, display
        ppath = workdir / "preview.wav"
        final[:60000].export(ppath, format="wav")
        print("\n🎧 معاينة سريعة (المخرج الكامل محفوظ أعلاه):")
        display(Audio(filename=str(ppath)))
    except Exception:
        pass

    shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
