"""مدل کوچیک رفتار انسان برای شبیه‌ساز حضور (بدون وابستگی؛ جدا قابل تست).

هدف: کارهای «کنار پخش‌کننده» (رد کردن آهنگ، قطع کردن، صدا بالا/پایین، پخش صدا) طوری زمان‌بندی و انتخاب بشن که
هیچ الگوی قابل حدسی نداشته باشن، نه ساعتی، نه ترتیبی، نه فاصله‌ای:

- «توجه» (attention): یه حال پنهان که آروم و تصادفی بالا/پایین میره. بالا = بیشتر سراغ پخش‌کننده میره، پایین = غرق کار خودشه.
- «بی‌قراری» (restless): تمایل به رد کردن آهنگ؛ بعد از چند رد کردن پشت‌هم خودش فروکش میکنه.
- فاصله‌ی بین کارها: توزیع دم‌بلند (گاهی خیلی کوتاه، گاهی خیلی طولانی) نه یه عدد تقریبا ثابت.
- ضد تکرار: کاری که تازه انجام شده کم‌تر انتخاب میشه؛ ولی ممنوع نیست (تکرار کامل‌ا ممنوع هم الگوئه).
- هر بار که برنامه بالا میاد، شخصیت (پارامترها) دوباره از os.urandom قرعه‌کشی میشه.
"""
import math
import os
import random
import time
from collections import deque


class HumanMind:
    SKIPS = ("skip", "skip_early", "back", "seek")        # خانواده‌ی «رد کردن/جابجا شدن تو آهنگ»

    def __init__(self, seed=None):
        self.rng = random.Random(seed if seed is not None else int.from_bytes(os.urandom(8), "big"))
        r = self.rng
        # شخصیت این اجرا (هر بار فرق میکنه)
        self.base_restless = r.uniform(0.25, 0.75)
        self.base_attention = r.uniform(0.35, 0.7)
        self.volume_fiddler = r.uniform(0.6, 1.5)          # چقدر با صدا ور میره
        self.stopper = r.uniform(0.5, 1.6)                 # چقدر موزیک رو کامل قطع میکنه
        self.attention = self.base_attention
        self.restless = self.base_restless
        self.recent = deque(maxlen=14)                      # (زمان، کار)
        self.t = time.time()

    # ------------------------------------------------------------------ حال پنهان
    def step(self, now=None):
        """حال پنهان رو یه قدم جلو ببر (حرکت تصادفی که به میانگین خودش برمیگرده)"""
        now = now or time.time()
        dt = min(max(now - self.t, 0.0), 600.0)
        self.t = now
        k = 1 - math.exp(-dt / 900.0)                       # حدود ۱۵ دقیقه حافظه
        r = self.rng
        self.attention += (self.base_attention - self.attention) * k + r.gauss(0, 0.06) * math.sqrt(dt / 60.0 + 0.01)
        self.restless += (self.base_restless - self.restless) * k + r.gauss(0, 0.07) * math.sqrt(dt / 60.0 + 0.01)
        self.attention = min(1.0, max(0.05, self.attention))
        self.restless = min(1.0, max(0.05, self.restless))

    # ------------------------------------------------------------------ زمان
    def gap(self, lo, hi, now=None):
        """فاصله تا کار بعدی (ثانیه): لگ‌نرمال بین lo و hi، با شانس کمِ غیبت طولانی.
        توجه بالا = فاصله کوتاه‌تر."""
        self.step(now)
        r = self.rng
        mid = math.sqrt(lo * hi)
        g = mid * math.exp(r.gauss(0, 0.55)) * (1.45 - self.attention * 0.9)
        if r.random() < 0.07:                                # گاهی کلی سرش گرمه
            g *= r.uniform(2.5, 6.0)
        return min(max(g, lo * 0.6), hi * 6.0)

    def quiet_for(self):
        """مدت سکوتی که بعد از قطع کردن موزیک میمونه (ثانیه): معمولا ۱ تا ۲ دقیقه، حداکثر ۵ دقیقه"""
        q = 100 * math.exp(self.rng.gauss(0, 0.55)) / max(0.5, self.stopper)
        return min(max(q, 30.0), 300.0)

    # ------------------------------------------------------------------ انتخاب کار
    def weights(self, base, now=None):
        """وزن‌های پایه رو با حال پنهان، حافظه‌ی اخیر و ضد تکرار تعدیل کن"""
        now = now or time.time()
        w = {}
        recent = list(self.recent)
        last3 = [a for _, a in recent[-3:]]
        last8 = [a for _, a in recent[-8:]]
        skips10 = sum(1 for t, a in recent if a in self.SKIPS and now - t < 600)
        skip_recent = any(a in self.SKIPS and now - t < 150 for t, a in recent)
        for k, v in base.items():
            x = float(v)
            if k in self.SKIPS:
                x *= 0.5 + self.restless
                if skip_recent and skips10 < 3:
                    x *= 2.0                                 # دنبال آهنگ مورد نظر میگرده: چند تا پشت هم
                elif skips10 >= 3:
                    x *= 0.15                                # بسه دیگه؛ یه مدت آروم
            elif k in ("nudge", "bump", "surprise"):
                x *= (0.5 + self.attention) * (self.volume_fiddler if k != "surprise" else 1.0)
            elif k == "stop":
                x *= self.stopper * (0.4 + (1 - self.attention))
            if k in last3:
                x *= 0.2
            elif k in last8:
                x *= 0.65
            w[k] = max(x, 0.0)
        return w

    def choose(self, base, now=None):
        now = now or time.time()
        self.step(now)
        w = self.weights(base, now)
        keys = [k for k in w if w[k] > 0]
        if not keys:
            return None
        pick = self.rng.choices(keys, [w[k] for k in keys])[0]
        self.recent.append((now, pick))
        return pick

    # ------------------------------------------------------------------ تصمیم‌های ریز
    def skip_plan(self, keeper=False, calm=False):
        """با شروع یه آهنگ: ثانیه‌ی رد کردنش، یا None (تا آخر گوش میده).
        شکل توزیع از داده‌ی واقعی شنونده‌ها (Spotify): ~۵۵٪ رد کردن‌ها تو چند ثانیه‌ی اول، ~۲۵٪ تا ۳۰ ثانیه، بقیه دیرتر."""
        if keeper:
            return None
        now = time.time()
        r = self.rng
        recent = list(self.recent)
        skips10 = sum(1 for t, a in recent if a in self.SKIPS and now - t < 600)
        p = (0.15 + 0.30 * self.restless) * (0.4 if calm else 1.0)
        if any(a in self.SKIPS and now - t < 120 for t, a in recent) and skips10 < 3:
            p = min(0.75, p * 1.8)                            # دنبال آهنگ مورد نظر میگرده
        elif skips10 >= 3:
            p *= 0.2
        if r.random() >= p:
            return None
        u = r.random()
        if u < 0.55:
            return r.uniform(2.5, 8)
        if u < 0.8:
            return r.uniform(8, 30)
        return r.uniform(30, 150)

    def early_skip_wanted(self, pos):
        """چند ثانیه اول آهنگ گوش داده و خوشش نیومد؟ (pos = ثانیه از شروع)"""
        if pos < 4 or pos > 28:
            return False
        return self.rng.random() < 0.18 + 0.35 * self.restless

    def jump_target(self, dur, pos):
        """پرش تو آهنگ (مثلا رفتن سمت ریتم/کورس): ثانیه‌ی مقصد، یا None اگه جا نداره"""
        if dur < 90 or pos > dur - 40:
            return None
        lo, hi = pos + 15, min(dur - 25, pos + dur * 0.45)
        if hi <= lo:
            return None
        return self.rng.uniform(lo, hi)

    def vol_step(self, cap, cur):
        """مقصد جدید صدا: بیشتر قدم‌های کوچیک، گاهی بزرگ؛ همیشه زیر سقف"""
        big = self.rng.random() < 0.15
        step = self.rng.uniform(0.12, 0.28) if big else self.rng.uniform(0.03, 0.12)
        step *= self.rng.choice((-1, 1))
        return min(cap, max(0.18, cur + step))
