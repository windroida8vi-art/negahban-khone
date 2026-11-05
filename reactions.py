"""واکنش هوشمند، تشخیص آدم و حضور خودکار.

همه‌ی این‌ها سمت سرور (کامپیوتر خونه) اجرا میشن؛ لازم نیست صفحه‌ی گوشی باز باشه.
"""
import ipaddress
import os
import random
import subprocess
import threading
import time
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------- صداهای ساختگی
# هیچ فایل صوتی لازم نیست؛ همه‌ی صداها با ریاضی ساخته میشن (خروجی: float مونو بین -1 و 1).


def _t(sr, dur):
    return np.arange(int(sr * dur)) / sr


def _tone(sr, f, dur, decay=3.0):
    t = _t(sr, dur)
    return np.sin(2 * np.pi * f * t) * np.exp(-decay * t)


def doorbell(sr):
    """دینگ‌دانگ"""
    return np.concatenate([_tone(sr, 880, 0.8, 3.5), _tone(sr, 660, 1.2, 3.0)]) * 0.8


def knock(sr, n=3):
    """تق‌تق‌تق"""
    out = []
    for _ in range(n):
        t = _t(sr, 0.14)
        thump = np.sin(2 * np.pi * 120 * t) * np.exp(-38 * t)
        noise = np.convolve(np.random.randn(len(t)), np.ones(40) / 40, "same") * np.exp(-60 * t) * 3
        out += [(thump + noise) * 0.9, np.zeros(int(sr * random.uniform(0.16, 0.3)))]
    return np.concatenate(out)


def footsteps(sr, n=None):
    """چند قدم آروم (کف خونه)"""
    n = n or random.randint(4, 8)
    out = []
    for _ in range(n):
        t = _t(sr, 0.12)
        step = np.sin(2 * np.pi * random.uniform(70, 95) * t) * np.exp(-30 * t)
        scuff = np.convolve(np.random.randn(len(t)), np.ones(25) / 25, "same") * np.exp(-45 * t) * 1.5
        out += [(step + scuff) * 0.6, np.zeros(int(sr * random.uniform(0.35, 0.6)))]
    return np.concatenate(out)


def door_close(sr):
    """بسته شدن در داخل خونه"""
    t = _t(sr, 0.5)
    thud = np.sin(2 * np.pi * 55 * t) * np.exp(-14 * t)
    click = np.convolve(np.random.randn(len(t)), np.ones(10) / 10, "same") * np.exp(-90 * t)
    return (thud * 0.9 + click * 0.6)


def notify(sr):
    """دینگ نرم نوتیفیکیشن گوشی"""
    return np.concatenate([_tone(sr, 988, 0.22, 6.0), _tone(sr, 1319, 0.4, 5.0)]) * 0.55


def sparkle(sr):
    """آرپژ شاد صعودی"""
    return np.concatenate([_tone(sr, f, 0.22, 5) for f in (523, 659, 784, 1047, 1319)]) * 0.7


def beeps(sr, n=4):
    """بیپ‌بیپ هشدار"""
    on = np.sin(2 * np.pi * 1500 * _t(sr, 0.13)) * 0.7
    return np.concatenate([np.concatenate([on, np.zeros(int(sr * 0.1))]) for _ in range(n)])


def whoop(sr, secs=2.0):
    """آژیر (فرکانس بالا و پایین میره)"""
    t = _t(sr, secs)
    f = 900 + 500 * np.sin(2 * np.pi * 0.5 * t)
    return np.sin(2 * np.pi * np.cumsum(f) / sr) * 0.95


# ---------------------------------------------------------------- تشخیص آدم
class PersonDetector:
    """چهره (Haar) یا کل بدن (HOG) با خود OpenCV؛ بدون دانلود مدل."""

    def __init__(self):
        import cv2
        self.cv2 = cv2
        try:
            self.hog = cv2.HOGDescriptor()
            self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        except Exception:
            self.hog = None
        self.face = None
        try:
            f = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
            self.face = None if f.empty() else f
        except Exception:
            pass

    def seen(self, img):
        cv2 = self.cv2
        h, w = img.shape[:2]
        if w > 480:
            img = cv2.resize(img, (480, int(h * 480 / w)))
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if self.face is not None and len(self.face.detectMultiScale(gray, 1.2, 6, minSize=(28, 28))):
            return True
        if self.hog is None:
            return False
        rects, weights = self.hog.detectMultiScale(img, winStride=(8, 8), padding=(8, 8), scale=1.05)
        return any(float(x) >= 0.6 for x in np.ravel(weights))


# ---------------------------------------------------------------- موتور واکنش
PHRASES = ["Hello there!", "Welcome home.", "I see you.", "Nice to see you.", "Hey, who is there?",
           "Oh, hello!", "Looking good today."]


class Reactor:
    """وقتی آدم دیده بشه، گاهی (نه همیشه) یه واکنش طبیعی و تصادفی نشون میده:
    عوض کردن آهنگ، پخش موزیک، زنگ در، تق‌تق، حرف زدن، صدای دلخواه، و در شدت بالا آژیر کوتاه."""

    FREQ = {"low": (900, 2400), "mid": (300, 900), "high": (90, 300)}

    def __init__(self, ctx):
        self.c = ctx
        self.on, self.level, self.freq = False, 1, "mid"
        self.away = False      # وقتی «بیرونم» فعاله، بدون محدودیت ساعت کار میکنه
        self.start, self.end = 10, 22
        self.next_ok = 0.0
        self.last_kind = None
        self.last_person = 0.0
        self._seen_t = 0.0       # آخرین باری که آدم دیده شد (برای «ورود تازه» تو حالت بیرونم)
        self.hist = []
        self.det = None
        self._det_t, self._det_res = 0.0, False
        self.lock = threading.Lock()

    # --- تنظیمات
    def configure(self, d):
        if "away" in d:                      # «بیرونم» بعد از ری‌استارت/بستن برنامه هم میمونه
            self.away = bool(d["away"])
        if d.get("level") in (1, 2):
            self.level = d["level"]
        if d.get("freq") in self.FREQ:
            self.freq = d["freq"]
        if "start" in d:
            self.start = min(max(int(d["start"]), 0), 23)
        if "end" in d:
            self.end = min(max(int(d["end"]), 1), 24)
        if "on" in d:
            self.on = bool(d["on"]) and self.c.camera_ok()
            self.c.camera_hold("fun", self.on)
            self.next_ok = 0.0

    def to_dict(self):
        return {"on": self.on, "level": self.level, "freq": self.freq, "start": self.start, "end": self.end, "away": self.away}

    def _in_window(self):
        h = time.localtime().tm_hour
        if self.away:
            return True
        return self.start <= h < self.end if self.start < self.end else (h >= self.start or h < self.end)

    # --- تشخیص آدم (حداکثر هر ۱.۵ ثانیه یک بار تا پردازنده درگیر نشه)
    def detect(self, img):
        now = time.time()
        if now - self._det_t < 0.7:
            return self._det_res
        self._det_t = now
        try:
            if self.det is None:
                self.det = PersonDetector()
            self._det_res = self.det.seen(img)
        except Exception as e:
            print("person detect:", e)
            self._det_res = False
        if self._det_res:
            self.last_person = now
        return self._det_res

    # --- حالت سرگرمی: از دوربین صدا زده میشه
    def sighting(self, img, human=False):
        if not self.on or not self._in_window() or self.c.busy():
            return
        if not (human or (time.time() >= self.next_ok and self.detect(img))):
            return
        now = time.time()
        # حالت بیرونم: وقتی آدمی بعد از ≥۹۰ ثانیه «نبودن» دوباره دیده شد = ورود تازه؛ بدون صبر و بدون شانس نشون ندادن واکنش میده
        fresh = self.away and now - self._seen_t > 90
        self._seen_t = now
        if now < self.next_ok and not fresh:
            return
        if random.random() < 0.35 and not fresh:  # «بعضی وقتا»: همیشه واکنش نشون نمیده
            self.next_ok = now + random.uniform(20, 60)
            return
        lo, hi = self.FREQ[self.freq]
        self.next_ok = now + random.uniform(lo, hi)
        threading.Thread(target=self.fire, daemon=True).start()

    def _pool(self):
        c = self.c
        playing = c.player.playing and not c.player.paused
        p = {"song": 3, "music": 2, "doorbell": 2, "knock": 1, "sparkle": 2, "speak": 3}
        if playing:
            p.update(swell=2, hush=1)
        if c.sound_files():
            p["file"] = 3
        if self.level >= 2:
            p.update(beeps=1)               # آژیر خودکار نداریم؛ فقط دستی
        if len(p) > 1:
            p.pop(self.last_kind, None)
        return p

    def fire(self, kind=None):
        """یه واکنش اجرا کن (kind ندی = تصادفی)."""
        with self.lock:
            p = self._pool()
            kind = kind if kind in p or kind in ("siren", "beeps") else random.choices(list(p), list(p.values()))[0]
            self.last_kind = kind
        try:
            getattr(self, "_do_" + kind)()
        except Exception as e:
            print("reaction", kind, "failed:", e)
        return kind

    # --- واکنش‌ها
    def _v(self, x):
        return min(x, self.c.vmax())

    def _do_song(self):
        pl = self.c.player
        if pl.tracks:
            pl.fade_then(pl.next)          # نرم کم میشه، آهنگ عوض میشه، نرم برمیگرده

    def _do_music(self):
        pl = self.c.player
        if pl.tracks:
            pl.shuffle = True
            pl.start_soft(random.uniform(0.4, 0.65))

    def _do_swell(self):
        pl = self.c.player
        v0 = pl.volume
        v1 = min(self.c.vmax(), v0 + random.uniform(0.08, 0.15))     # کم بالا میره، نه تا ته
        if v1 <= v0 + 0.02 or not pl.ramp(v1, random.uniform(3, 5), wait=True):
            return
        time.sleep(random.uniform(4, 8))
        if abs(pl.volume - v1) < 0.02:  # اگه کاربر بینش دستی عوضش نکرده
            pl.ramp(v0, random.uniform(4, 6), wait=True, cap=False)

    def _do_hush(self):
        self.c.player.soft_pause(random.uniform(3, 5))

    def _do_doorbell(self):
        self.c.play(doorbell(self.c.sr()), self._v(0.7))

    def _do_knock(self):
        self.c.play(knock(self.c.sr()), self._v(0.8))

    def _do_sparkle(self):
        self.c.play(sparkle(self.c.sr()), self._v(0.6))

    def _do_beeps(self):
        self.c.play(beeps(self.c.sr()), self._v(0.6))

    def _do_speak(self):
        if not self.c.speak(random.choice(PHRASES)):
            self._do_doorbell()

    def _do_file(self):
        files = self.c.sound_files()
        if files:
            self.c.play_file(self.c.pick_sound(files), self._v(0.8))

    def _do_siren(self):
        self.c.siren.start(seconds=random.randint(3, 6), boost=False)

    # --- تشدید تدریجی برای حالت امنیتی «هوشمند»
    def alert_sound(self):
        """هشدار با صدا افکت: یه فایل تصادفی از پوشه‌ی sounds؛ اگه خالی بود زنگ در و در زدن ساختگی"""
        files = self.c.sound_files()
        if files:
            self.c.play_file(self.c.pick_sound(files), self._v(0.8))
        else:
            self.c.play(doorbell(self.c.sr()), self._v(0.7))
            time.sleep(1.5)
            self.c.play(knock(self.c.sr()), self._v(0.8))

    _wild_on = False

    def _wild(self):
        """جلو دوربین موند: موزیک چند بار عوض میشه و صدا تا سقف تنظیم‌شده (مثلا ۸۰٪) بالا و پایین میره؛ بعدش آروم میشه. آژیر نیست."""
        if self._wild_on:
            return
        self._wild_on = True
        try:
            pl = self.c.player
            if not pl.tracks:
                return
            pl.shuffle = True
            top = self.c.vmax()
            if not (pl.playing and not pl.paused):
                pl.start_soft(max(0.5, top - 0.2), 3)
            for i in range(random.randint(4, 6)):
                pl.ramp(top if i % 2 == 0 else max(0.5, top - 0.15), random.uniform(1.5, 3), wait=True)
                if i % 2 == 0:
                    pl.fade_then(pl.next, out=0.5, inn=0.8)
                if i == 0:
                    self.c.play(doorbell(self.c.sr()), self._v(0.7))
                elif i == 1:
                    threading.Thread(target=self.alert_sound, daemon=True).start()
                elif i == 3:
                    self.c.play(knock(self.c.sr()), self._v(0.8))
                time.sleep(random.uniform(5, 10))
            pl.ramp(max(0.45, top - 0.2), 8)
        finally:
            self._wild_on = False

    def escalate(self, person):
        """آدم جلو دوربین: ۱) آهنگ عوض میشه و صدا یه کم بالا ۲) صدا بیشتر ۳) «دیوونه»: چند بار آهنگ عوض + صدا تا سقف. آژیر فقط دستیه."""
        now = time.time()
        self.hist = [t for t in self.hist if now - t < 300] + [now]
        n = len(self.hist) + (1 if person else 0)
        pl = self.c.player
        if n <= 1:
            self.c.play(random.choice((doorbell, knock))(self.c.sr()), self._v(0.7))     # زنگ در یا تق‌تق (مثل قبل)
            if pl.tracks:
                pl.shuffle = True
                if pl.playing and not pl.paused:
                    pl.fade_then(pl.next, out=0.6, inn=1.2)
                    pl.ramp(min(self.c.vmax(), pl.volume + 0.12), 4)
                else:
                    pl.start_soft(min(self.c.vmax(), 0.55), 4)
            else:
                self.c.play(doorbell(self.c.sr()), 0.8)
            if random.random() < 0.5:
                self.c.speak("Hello? Who is there?")
        elif n == 2:
            if pl.tracks:
                pl.shuffle = True
                if pl.playing and not pl.paused:
                    pl.fade_then(pl.next, out=0.6, inn=1.2)
                    pl.ramp(min(self.c.vmax(), max(pl.volume, 0.55) + 0.12), 5)
                else:
                    pl.start_soft(min(self.c.vmax(), 0.65), 4)
            self.c.speak("This house is monitored. Please leave.")
        else:
            threading.Thread(target=self._wild, daemon=True).start()


# ---------------------------------------------------------------- حضور خودکار
def _ping(ip):
    try:
        if os.name == "nt":
            r = subprocess.run(["ping", "-n", "4", "-w", "1500", ip], capture_output=True, text=True,
                               timeout=20, creationflags=0x08000000)
            return "ttl=" in r.stdout.lower()
        return subprocess.run(["ping", "-c", "4", "-W", "2", ip], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=20).returncode == 0
    except Exception:
        return False


class AutoAway:
    """اگه گوشی(ها) از وای‌فای خونه برن (برای چند دقیقه)، خودکار «حالت بیرونم» فعال میشه؛
    وقتی برگشتن «رسیدم خونه». نیازی به باز بودن برنامه روی گوشی نیست.
    (برای دقت: تو روتر برای گوشی IP ثابت بذار)"""

    def __init__(self, on_away, on_home, notify):
        self.on_away, self.on_home, self.notify = on_away, on_home, notify
        self.on, self.phones, self.grace = False, [], 15
        self.state, self.last_seen, self.present = "home", time.time(), None
        threading.Thread(target=self._run, daemon=True).start()

    def configure(self, d):
        if "phones" in d:
            raw = d["phones"] if isinstance(d["phones"], list) else str(d["phones"]).replace("،", ",").split(",")
            ok = []
            for x in raw:
                try:
                    ip = ipaddress.ip_address(str(x).strip())
                    if ip.version == 4 and ip.is_private:
                        ok.append(str(ip))
                except ValueError:
                    pass
            self.phones = ok[:5]
        if "grace" in d:
            self.grace = min(max(int(d["grace"]), 3), 120)
        if "on" in d:
            self.on = bool(d["on"]) and bool(self.phones)
            self.last_seen, self.state = time.time(), "home"

    def to_dict(self):
        return {"on": self.on, "phones": self.phones, "grace": self.grace}

    def status(self):
        return {**self.to_dict(), "state": self.state, "present": self.present}

    def _run(self):
        while True:
            time.sleep(30)
            try:
                if not self.on or not self.phones:
                    continue
                self.present = any(_ping(ip) for ip in self.phones)
                now = time.time()
                if self.present:
                    self.last_seen = now
                if self.state == "home" and not self.present and now - self.last_seen > self.grace * 60:
                    self.state = "away"
                    self.on_away()
                    self.notify("Auto: everyone left, away mode ON")
                elif self.state == "away" and self.present:
                    self.state = "home"
                    self.on_home()
                    self.notify("Auto: someone arrived, home mode ON")
            except Exception as e:
                print("autoaway:", e)
