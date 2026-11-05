import os
import random
import secrets
import threading
import time
from functools import wraps
from pathlib import Path

os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
import datetime
import re
import socket
import urllib.parse
import urllib.request
import string
import zlib
import subprocess
import sys
import hmac
import struct
import base64
import ipaddress
import hashlib
import getpass
from collections import deque
import collections
from types import SimpleNamespace

# حالت سرویس (service_main.py): قبل از ورود به ویندوز با حساب SYSTEM اجرا میشه؛ بخش‌هایی که به دسکتاپ/صدا/دوربینِ کاربر نیاز دارن
# اون‌موقع کار نمیکنن و بعد از ورود، نسخه‌ی کامل (start.bat) خودکار جاش رو میگیره.
HEADLESS = os.environ.get("HP_MODE") == "service"
NEEDS_LOGIN = {
    "/api/play", "/api/toggle", "/api/next", "/api/prev", "/api/stop", "/api/volume", "/api/seek", "/api/shuffle", "/api/repeat",
    "/camera.mjpg", "/api/snapshot.jpg", "/ws/talk", "/ws/listen", "/ws/sysaudio", "/api/speak",
    "/screen.mjpg", "/ws/desk", "/api/input", "/api/screenshot.png", "/api/clipboard", "/api/run",
}
if os.name == "nt":  # مختصات دقیق صفحه با زوم ویندوز
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
import pygame
import json
import queue
from flask_sock import Sock
from flask import Flask, Response, jsonify, request, session, send_file, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash

try:
    import mutagen
except ImportError:
    mutagen = None
try:
    import sounddevice as sd
except Exception:
    sd = None
try:
    import numpy as np
except ImportError:
    np = None
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
try:
    import cv2
except ImportError:
    cv2 = None
import nvr
import reactions
try:
    import mind as mind_mod
except Exception:
    mind_mod = None
try:
    import human as human_mod
except Exception as _e:
    human_mod = None
    print("human gate unavailable:", _e)
import atexit
import ssl
import http.client
import wave
import shutil
try:
    import mss
except ImportError:
    mss = None
try:
    import psutil
except ImportError:
    psutil = None
try:
    import pyperclip
except ImportError:
    pyperclip = None
try:
    from pynput.mouse import Controller as MouseC, Button
    from pynput.keyboard import Controller as KbC, Key
    mouse_c, kb_c = MouseC(), KbC()
except Exception:
    mouse_c = kb_c = None

BASE = Path(__file__).parent
# ---------- تنظیمات (با متغیر محیطی هم میشه عوض کرد) ----------
MUSIC_DIR = Path(os.environ.get("MUSIC_DIR", BASE / "music")).expanduser()
USERNAME = os.environ.get("PLAYER_USER", "admin")
CAMERA_INDEX = int(os.environ.get("CAMERA_INDEX", "0"))
USE_HTTPS = os.environ.get("PLAYER_HTTPS", "0") == "1"  # برای میکروفون گوشی لازمه
HOST = os.environ.get("PLAYER_HOST", "0.0.0.0")
PORT = int(os.environ.get("PLAYER_PORT", "8080"))
TOKEN_FILE = Path(__file__).resolve().parent / ".service_token"   # توکن تحویل بین سرویس و نسخه‌ی کامل


def _port_busy(port):
    import socket as _s
    try:
        with _s.create_connection(("127.0.0.1", port), timeout=0.7):
            return True
    except OSError:
        return False


def _take_over_from_service():
    """بعد از ورود به ویندوز: اگه سرویس (حالت قبل از ورود) پورت رو گرفته، ازش بخواه کنار بره و جاش رو بگیر"""
    if not _port_busy(PORT):
        return
    import ssl as _ssl
    import urllib.request as _ur
    import subprocess as _sp
    print("پورت اشغاله؛ احتمالا سرویس (قبل از ورود به ویندوز) داره کار میکنه → تحویل گرفتن…")
    done = False
    try:
        tok = TOKEN_FILE.read_text(encoding="utf-8").strip()
        req = _ur.Request(("https" if USE_HTTPS else "http") + f"://127.0.0.1:{PORT}/api/_handover", data=b"{}", method="POST",
                          headers={"X-Handover": tok, "Content-Type": "application/json"})
        with _ur.urlopen(req, timeout=8, context=_ssl._create_unverified_context()) as r:
            done = r.status == 200
    except Exception as e:
        print("درخواست تحویل نشد:", e)
    if not done and os.name == "nt":
        try:
            _sp.run(["schtasks", "/End", "/TN", "HomePlayer-Service"], creationflags=0x08000000, capture_output=True)
        except Exception:
            pass
    for _ in range(40):                                   # تا ۲۰ ثانیه صبر کن تا پورت آزاد بشه
        if not _port_busy(PORT):
            print("تحویل گرفته شد ✓")
            return
        time.sleep(0.5)
    print("پورت هنوز اشغاله (شاید یه نسخه‌ی کامل دیگه باز باشه). خروج…")
    sys.exit(1)


if __name__ == "__main__" and not HEADLESS:
    _take_over_from_service()
# ---------------------------------------------------------------
EXTS = {".mp3", ".wav", ".ogg", ".flac", ".opus"}
PASS_FILE = BASE / "password.hash"
IDLE_LOGOUT = int(os.environ.get("IDLE_LOGOUT_MIN", "0")) * 60    # خروج خودکار بعد از بیکاری (ثانیه)؛ 0 = خاموش
ELEVATE_SECONDS = 600                                             # اعتبار تایید مجدد رمز برای کارهای حساس


def _write_secret(path, text):
    path.write_text(text, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _setup_password():
    """رمز از متغیر محیطی یا فایل هش‌شده میاد. بار اول یه رمز تصادفی ساخته میشه و فقط یک‌بار چاپ میشه."""
    env = os.environ.get("PLAYER_PASSWORD")
    if env:
        return generate_password_hash(env), None, "env:" + env
    if PASS_FILE.exists() and PASS_FILE.read_text(encoding="utf-8").strip():
        h = PASS_FILE.read_text(encoding="utf-8").strip()
        return h, None, h
    pw = secrets.token_urlsafe(12)
    h = generate_password_hash(pw)
    _write_secret(PASS_FILE, h)
    return h, pw, h


if "--set-password" in sys.argv:
    _p1 = getpass.getpass("New password (min 10 chars): ")
    if len(_p1) < 10 or _p1 != getpass.getpass("Repeat: "):
        sys.exit("Passwords differ or too short.")
    _write_secret(PASS_FILE, generate_password_hash(_p1))
    sys.exit("Password saved. Restart the server (all old sessions are logged out).")
VIEWERS_FILE = BASE / "viewers.json"     # کاربرهای «فقط‌تماشای NVR» (فقط هش رمز)


def _viewers_raw():
    try:
        d = json.loads(VIEWERS_FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


if "--add-viewer" in sys.argv:
    _vn = input("Viewer username (letters/digits): ").strip().lower()
    if not re.fullmatch(r"[a-z0-9_.-]{2,32}", _vn) or _vn == USERNAME.lower():
        sys.exit("Bad username (2-32 letters/digits, and not the admin name).")
    _vp = getpass.getpass("Viewer password (min 8 chars): ")
    if len(_vp) < 8 or _vp != getpass.getpass("Repeat: "):
        sys.exit("Passwords differ or too short.")
    _vd = _viewers_raw()
    _vd[_vn] = generate_password_hash(_vp)
    _write_secret(VIEWERS_FILE, json.dumps(_vd, indent=1))
    sys.exit(f"Saved. '{_vn}' can log in and see ONLY the NVR cameras (nothing else). Old sessions of that user are logged out.")
if "--del-viewer" in sys.argv:
    _vn = input("Viewer username to remove: ").strip().lower()
    _vd = _viewers_raw()
    if _vd.pop(_vn, None) is None:
        sys.exit("No such viewer.")
    _write_secret(VIEWERS_FILE, json.dumps(_vd, indent=1))
    sys.exit(f"'{_vn}' removed (their sessions stop working).")
if "--list-viewers" in sys.argv:
    sys.exit("Viewers: " + (", ".join(_viewers_raw()) or "(none)"))
TOTP_FILE = BASE / "totp.secret"
EPOCH_FILE = BASE / ".epoch"
PUBLIC_HOST = os.environ.get("PUBLIC_HOST", "").strip()   # IP یا دامنه‌ی پابلیک (برای گواهی HTTPS)


def totp_secret():
    try:
        return TOTP_FILE.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _totp(secret, counter):
    h = hmac.new(base64.b32decode(secret), struct.pack(">Q", counter), "sha1").digest()
    o = h[-1] & 15
    return f"{(struct.unpack('>I', h[o:o + 4])[0] & 0x7fffffff) % 10**6:06d}"


_last_totp = [0]


def totp_ok(code):
    """کد ۶ رقمی اپ Authenticator؛ هر کد فقط یک‌بار قابل استفاده‌ست (جلوی استفاده‌ی دوباره)"""
    sec = totp_secret()
    code = re.sub(r"\D", "", str(code))[:6]
    if not sec or len(code) != 6:
        return False
    now = int(time.time() // 30)
    for c in (now - 1, now, now + 1):
        if secrets.compare_digest(_totp(sec, c), code) and c > _last_totp[0]:
            _last_totp[0] = c
            return True
    return False


if "--setup-2fa" in sys.argv:
    _sec = base64.b32encode(secrets.token_bytes(20)).decode()
    _write_secret(TOTP_FILE, _sec)
    _url = f"otpauth://totp/HomePlayer:{USERNAME}?secret={_sec}&issuer=HomePlayer"
    print("\nدر اپ Authenticator (Google Authenticator / Aegis / Microsoft) یه اکانت جدید بساز:")
    try:
        import qrcode
        _q = qrcode.QRCode(border=1)
        _q.add_data(_url)
        _q.print_ascii(invert=True)
    except Exception:
        print("(QR نشد؛ کلید رو دستی وارد کن)")
    print(f"\nکلید دستی:  {_sec}\nنوع: مبتنی بر زمان (Time based)\n\nاز این به بعد ورود از بیرون خونه = رمز + کد ۶ رقمی. سرور رو ریستارت کن.")
    sys.exit(0)
if "--disable-2fa" in sys.argv:
    TOTP_FILE.unlink(missing_ok=True)
    sys.exit("2FA disabled (ورود از بیرون خونه دوباره بسته شد تا 2FA فعال کنی).")

PASS_HASH, FIRST_PASSWORD, _ver_src = _setup_password()
try:
    SESSION_EPOCH = int(EPOCH_FILE.read_text().strip())
except (OSError, ValueError):
    SESSION_EPOCH = 0


def _pass_ver():
    return hashlib.sha256(f"{_ver_src}|{SESSION_EPOCH}".encode()).hexdigest()[:16]


PASS_VER = _pass_ver()   # با عوض شدن رمز یا «خروج همه»، همه‌ی نشست‌ها باطل میشن

pygame.mixer.init()
talkers = 0
talk_lock = threading.Lock()


def num(v, default, lo, hi, cast=float):
    """ورودی عددی امن (ورودی خراب = مقدار پیش‌فرض)"""
    try:
        return min(max(cast(v), lo), hi)
    except (TypeError, ValueError):
        return default


AUTO_MAX = [0.8]   # سقف صدای تغییرات خودکار (واکنش، شبیه‌سازی حضور)؛ صدای دستی خودت محدود نمیشه


class Player:
    def __init__(self):
        self.lock = threading.RLock()
        self.tracks = []
        self.index = None
        self.paused = False
        self.playing = False
        self.volume = 0.7
        self.shuffle = False
        self.repeat = "off"  # off | all | one
        self.offset = 0.0
        self.duck = 1.0  # وقتی کسی داره صحبت میکنه موزیک آروم میشه
        self._ramp_id = 0
        self.bad = set()       # مسیر آهنگ‌هایی که پخش نشدن (خراب/فرمت پشتیبانی‌نشده)؛ خودکار رد میشن
        self.t_start = 0.0
        self.dislike = {}             # index -> زمانی که تا اون موقع تو شافل خودکار پیشنهاد نمیشه (رد کردن زودهنگام)
        self.prefer_artist = None     # شبیه‌ساز حضور: یه مدت پشت هم آهنگ‌های یه خواننده (مثل آدم واقعی)
        pygame.mixer.music.set_volume(self.volume)
        self.scan()
        threading.Thread(target=self._watch, daemon=True).start()

    def scan(self):
        MUSIC_DIR.mkdir(parents=True, exist_ok=True)
        files = sorted(p for p in MUSIC_DIR.rglob("*") if p.suffix.lower() in EXTS)
        tracks = []
        for i, p in enumerate(files):
            title, artist, dur = p.stem, "", None
            if mutagen:
                try:
                    m = mutagen.File(p, easy=True)
                    if m is not None:
                        dur = getattr(m.info, "length", None)
                        title = (m.get("title") or [title])[0]
                        artist = (m.get("artist") or [""])[0]
                except Exception:
                    pass
            tracks.append({"id": i, "title": title, "artist": artist,
                           "duration": dur, "path": str(p)})
        with self.lock:
            cur = self.tracks[self.index]["path"] if self.index is not None and self.index < len(self.tracks) else None
            self.tracks = tracks
            self.index = next((t["id"] for t in tracks if t["path"] == cur), None)
            if self.index is None:
                if self.playing:
                    pygame.mixer.music.stop()
                self.playing = self.paused = False

    def _good_ids(self):
        return [i for i, t in enumerate(self.tracks) if t["path"] not in self.bad]

    def play(self, idx, start=0.0, _depth=0):
        with self.lock:
            if not 0 <= idx < len(self.tracks):
                return
            self.index = idx
            try:
                pygame.mixer.music.load(self.tracks[idx]["path"])
                try:
                    pygame.mixer.music.play(start=start)
                except Exception:      # بعضی فرمت‌ها seek ندارن: از اول پخش کن
                    pygame.mixer.music.play()
                    start = 0.0
            except Exception as e:
                # فایل خراب/ناشناخته: علامت بزن و برو آهنگ بعدی، متوقف نشو
                print("play error (skipped):", Path(self.tracks[idx]["path"]).name, "-", str(e)[:80])
                self.bad.add(self.tracks[idx]["path"])
                self.playing = False
                good = [i for i in self._good_ids() if i != idx]
                if good and _depth < len(self.tracks):
                    nxt = random.choice(good) if self.shuffle else next((j for j in ((idx + k) % len(self.tracks) for k in range(1, len(self.tracks) + 1)) if j in good), good[0])
                    return self.play(nxt, 0.0, _depth + 1)
                return
            self.offset = start
            self.t_start = time.time()
            self.playing, self.paused = True, False

    def toggle(self):
        with self.lock:
            if self.index is None:
                if self.tracks:
                    self.play(0)
                return
            if self.paused:
                pygame.mixer.music.unpause()
                self.paused = False
            elif self.playing:
                pygame.mixer.music.pause()
                self.paused = True
            else:
                self.play(self.index)

    def stop(self):
        with self.lock:
            pygame.mixer.music.stop()
            self.playing = self.paused = False
            self.offset = 0.0

    def _pick_next(self, auto=False):
        n = len(self.tracks)
        if n == 0:
            return None
        if auto and self.repeat == "one" and self.index is not None:
            return self.index
        good = set(self._good_ids())
        if not good:
            return None
        if self.shuffle and len(good) > 1:
            pool = [i for i in good if i != self.index]
            now = time.time()
            self.dislike = {i: t for i, t in self.dislike.items() if t > now}
            pool = [i for i in pool if i not in self.dislike] or pool     # آهنگ‌های ردشده فعلا نه (اگه چیز دیگه‌ای نبود، باشه)
            if self.prefer_artist and random.random() < 0.75:
                same = [i for i in pool if self.tracks[i].get("artist") == self.prefer_artist]
                if same:
                    return random.choice(same)
            return random.choice(pool)
        nxt = (self.index + 1) if self.index is not None else 0
        if nxt >= n:
            if auto and self.repeat == "off":
                return None
            nxt = 0
        for _ in range(n):                 # آهنگ‌های خراب رو رد کن
            if nxt in good:
                return nxt
            nxt += 1
            if nxt >= n:
                if auto and self.repeat == "off":
                    return None
                nxt = 0
        return None

    def next(self, auto=False):
        with self.lock:
            nxt = self._pick_next(auto)
            if nxt is None:
                self.stop()
            else:
                self.play(nxt)

    def prev(self):
        with self.lock:
            if not self.tracks:
                return
            if self.position() > 3 or self.index is None:
                self.play(self.index or 0)
            else:
                self.play((self.index - 1) % len(self.tracks))

    def position(self):
        with self.lock:
            if not self.playing:
                return 0.0
            ms = pygame.mixer.music.get_pos()
            return self.offset + max(ms, 0) / 1000.0

    def seek(self, pos):
        with self.lock:
            if self.index is None:
                return
            was_paused = self.paused
            self.play(self.index, start=max(0.0, pos))
            if was_paused:
                pygame.mixer.music.pause()
                self.paused = True

    def _apply(self, v):
        with self.lock:
            self.volume = min(1.0, max(0.0, v))
            pygame.mixer.music.set_volume(self.volume * self.duck)

    def set_volume(self, v):
        """تغییر دستی صدا (اسلایدر): فوری، و هر تغییر تدریجی در حال اجرا رو قطع میکنه"""
        self._ramp_id += 1
        self._apply(v)

    def ramp(self, target, secs=4.0, wait=False, cap=True):
        """تغییر صدای انسان‌گونه: پله‌پله و نرم با مکث‌های تصادفی، نه پرش ناگهانی.
        cap=True: بالا بردن خودکار هیچ‌وقت از سقف AUTO_MAX بیشتر نمیشه. True برمیگردونه اگه کامل شد."""
        target = min(1.0, max(0.0, target))
        with self.lock:
            self._ramp_id += 1
            rid, start = self._ramp_id, self.volume
        if cap and target > start:
            target = min(target, max(AUTO_MAX[0], start))

        def run():
            n = max(2, int(abs(target - start) / 0.03))
            for i in range(1, n + 1):
                if self._ramp_id != rid:
                    return False        # کاربر خودش دست برد؛ ولش کن
                f = i / n
                self._apply(start + (target - start) * f * f * (3 - 2 * f))
                time.sleep(max(0.03, secs / n * random.uniform(0.7, 1.3)))
            return True
        if wait:
            return run()
        threading.Thread(target=run, daemon=True).start()
        return True

    def fade_then(self, action, out=0.8, inn=1.6):
        """اول صدا نرم کم میشه، بعد کار (آهنگ بعدی/توقف) و بعد نرم برمیگرده؛ بدون قطع و وصل ناگهانی"""
        v0 = self.volume
        if self.playing and not self.paused and not self.ramp(v0 * 0.08, out, wait=True, cap=False):
            return
        action()
        self._apply(v0 * 0.08)
        self.ramp(v0, inn, wait=True, cap=False)

    def soft_pause(self, secs):
        """مثل آدمی که یه لحظه موزیک رو نگه میداره: نرم قطع، چند ثانیه سکوت، نرم برگشت"""
        v0 = self.volume
        if not (self.playing and not self.paused):
            return
        if not self.ramp(v0 * 0.05, 0.9, wait=True, cap=False):
            return
        self.toggle()
        time.sleep(secs)
        if self.paused:
            self.toggle()
        self.ramp(v0, 1.8, wait=True, cap=False)

    def start_soft(self, v, secs=6.0):
        """پخش آهنگ جدید با صدای خیلی کم که آروم بالا میاد (تا سقف AUTO_MAX)"""
        v = min(v, AUTO_MAX[0])
        self._ramp_id += 1
        self._apply(v * 0.1)
        self.next()
        self.ramp(v, secs)

    def _watch(self):
        while True:
            time.sleep(0.5)
            with self.lock:
                try:
                    if self.playing and not self.paused and not pygame.mixer.music.get_busy():
                        if self.index is not None and self.offset == 0 and time.time() - self.t_start < 1.5:
                            # load شد ولی همون لحظه تموم شد = فایل خراب؛ از این به بعد رد بشه
                            self.bad.add(self.tracks[self.index]["path"])
                            print("play error (skipped, ended instantly):", Path(self.tracks[self.index]["path"]).name)
                        self.next(auto=True)
                except Exception as e:
                    print("watch:", e)

    def state(self):
        with self.lock:
            t = self.tracks[self.index] if self.index is not None else None
            return {
                "current": t["id"] if t else None,
                "title": t["title"] if t else None,
                "artist": t["artist"] if t else None,
                "duration": t["duration"] if t else None,
                "position": self.position(),
                "playing": self.playing and not self.paused,
                "volume": self.volume,
                "shuffle": self.shuffle,
                "repeat": self.repeat,
                "count": len(self.tracks),
            }


player = Player()

app = Flask(__name__, static_folder=None)
secret_file = BASE / ".secret_key"
if not secret_file.exists():
    secret_file.write_text(secrets.token_hex(32))
app.secret_key = secret_file.read_text().strip()
try:
    os.chmod(secret_file, 0o600)
except OSError:
    pass
app.config.update(MAX_CONTENT_LENGTH=2 * 1024**3, SESSION_COOKIE_SECURE=USE_HTTPS, SESSION_COOKIE_HTTPONLY=True,
                  SESSION_COOKIE_SAMESITE="Strict", SESSION_COOKIE_NAME="hp_session",
                  PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 14)

fails = {}  # ip -> [count, locked_until, level]


LAN_NETS = [ipaddress.ip_network("100.64.0.0/10")]   # Tailscale هم مثل شبکه‌ی خونه حساب میشه
wan_fails, wan_lock = deque(), [0.0]


def is_lan(ip):
    try:
        a = ipaddress.ip_address(ip)
        a = getattr(a, "ipv4_mapped", None) or a
    except ValueError:
        return False
    return a.is_private or a.is_loopback or a.is_link_local or any(a in n for n in LAN_NETS if n.version == a.version)


def jbody():
    """بدنه‌ی JSON همیشه یه dict؛ اگه کسی عدد/متن/لیست بفرسته 500 نده (قبلا /api/login و /api/reauth با ورودی بد 500 میدادن)"""
    d = request.get_json(silent=True)
    return d if isinstance(d, dict) else {}


def client_ip():
    if os.environ.get("TRUST_PROXY") == "1":
        return request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr
    return request.remote_addr


_vcache = [None, {}]


def viewers():
    """{نام: هش رمز}؛ با عوض شدن فایل خودکار دوباره خونده میشه (بدون ری‌استارت)"""
    try:
        m = VIEWERS_FILE.stat().st_mtime
    except OSError:
        _vcache[:] = [None, {}]
        return {}
    if _vcache[0] != m:
        _vcache[:] = [m, {k: v for k, v in _viewers_raw().items() if isinstance(k, str) and isinstance(v, str)}]
    return _vcache[1]


def _viewer_ver(h):
    return hashlib.sha256(h.encode()).hexdigest()[:12]


def is_viewer():
    return session.get("role") == "viewer"


def is_mode_user():
    """هر کاربر «بیننده‌ی NVR» (مثلا بابا) علاوه بر دوربین‌ها دو دکمه‌ی 🏠 خونم / 🚪 رفتم بیرون هم داره"""
    return is_viewer()


def session_ok(touch=True):
    """نشست معتبر: رمز عوض نشده باشه و بیش از IDLE_LOGOUT بیکار نبوده باشه."""
    if not session.get("ok") or session.get("v") != PASS_VER:
        return False
    if is_viewer():            # بیننده‌ی NVR: وقتی حذف بشه یا رمزش عوض بشه نشستش باطل میشه
        vh = viewers().get(session.get("user"))
        if not vh or session.get("vv") != _viewer_ver(vh):
            return False
    now = time.time()
    if IDLE_LOGOUT and now - session.get("t", 0) > IDLE_LOGOUT:
        session.clear()
        return False
    if touch and request.headers.get("X-Poll") != "1" and now - session.get("t", 0) > 20:
        session["t"] = now      # فقط کار واقعی کاربر نشست رو زنده نگه میداره، نه پرسش‌های پس‌زمینه
    return True


def auth(f):
    """فقط خودت (ادمین). کاربر «فقط‌تماشای NVR» به هیچ‌کدوم از اینا دسترسی نداره."""
    @wraps(f)
    def wrapper(*a, **kw):
        if not session_ok():
            return jsonify(error="unauthorized"), 401
        if is_viewer():
            return jsonify(error="forbidden"), 403
        return f(*a, **kw)
    return wrapper


def auth_viewer(f):
    """ادمین یا بیننده‌ی NVR (فقط برای چند مسیر مربوط به تماشای دوربین)"""
    @wraps(f)
    def wrapper(*a, **kw):
        if not session_ok():
            return jsonify(error="unauthorized"), 401
        return f(*a, **kw)
    return wrapper


def elevated(f):
    """کارهای حساس: فقط لاگین کافیه (رمز دوباره نمیخواد)، ولی تو audit.log ثبت میشن."""
    return auth(f)


def ws_ok():
    """فقط کاربر واردشده و فقط از همین سایت (جلوی وب‌سوکت از سایت‌های دیگه)"""
    if not session_ok(touch=False) or is_viewer():
        return False
    o = request.headers.get("Origin")
    return not o or urllib.parse.urlparse(o).netloc == request.host


LAST_POLL = {}          # آخرین باری که صفحه‌ی هر کلاینت (به IP) سراغ سرور اومده؛ برای بستن خودکار پخش‌های زنده‌ی بی‌صاحاب
POLL_TIMEOUT = 45


def client_alive(ip):
    """صفحه‌ی باز هر ثانیه سوال میپرسه. اگه ۴۵ ثانیه خبری نبود (صفحه بسته شد، گوشی قفل شد، اینترنت رفت)، پخش‌های زنده بسته میشن."""
    return time.time() - LAST_POLL.get(ip, time.time()) < POLL_TIMEOUT


@app.before_request
def csrf_guard():
    if HEADLESS and request.path in NEEDS_LOGIN:
        return jsonify(error="needs_login", message="این بخش بعد از ورود به ویندوز فعال میشه (الان فقط سرویس اجراست)"), 503
    if (request.headers.get("X-Poll") == "1" or request.path == "/api/ping") and session_ok(touch=False):
        LAST_POLL[client_ip()] = time.time()
        if len(LAST_POLL) > 500:           # فقط کلاینت‌های واردشده ثبت میشن؛ این سقف برای اطمینانه
            for k in sorted(LAST_POLL, key=LAST_POLL.get)[:250]:
                LAST_POLL.pop(k, None)
    if not session_ok(touch=False):        # بدون ورود: بدنه‌ی بزرگ نه (جلوی پر کردن حافظه)
        if (request.content_length or 0) > 8192:
            return jsonify(error="too large"), 413
        try:
            request.max_content_length = 8192
        except AttributeError:
            pass
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        o = request.headers.get("Origin") or request.headers.get("Referer")
        if (o and urllib.parse.urlparse(o).netloc != request.host) or request.headers.get("Sec-Fetch-Site") == "cross-site":
            return jsonify(error="forbidden"), 403


@app.after_request
def secure_headers(r):
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["X-Frame-Options"] = "DENY"
    r.headers["Referrer-Policy"] = "no-referrer"
    r.headers["Content-Security-Policy"] = ("default-src 'self'; img-src 'self' data: blob:; media-src 'self' data: blob:; "
                                            "connect-src 'self' ws: wss:; style-src 'self' 'unsafe-inline'; "
                                            "script-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
    if request.path.startswith(("/api/", "/camera", "/screen", "/ws/")) or request.path == "/":
        r.headers["Cache-Control"] = "no-store"
    return r


@app.get("/s/<name>")
def public_static(name):
    if name not in ("manifest.json", "icon-192.png", "icon-512.png"):
        return "", 404
    return send_from_directory(BASE / "static", name)


@app.get("/")
def index():
    if session_ok(touch=False) and is_viewer():        # بیننده‌ی NVR فقط صفحه‌ی دوربین‌ها رو میبینه
        return send_from_directory(BASE / "static", "nvr.html")
    return send_from_directory(BASE / "static", "index.html")


@app.get("/api/login_info")
def login_info():
    wan = not is_lan(client_ip())
    has = bool(totp_secret())
    return jsonify(need_code=wan and has, blocked=False)


@app.post("/api/login")
def login():
    global PASS_VER
    ip = client_ip()
    wan = not is_lan(ip)
    now = time.time()
    rec = fails.get(ip, [0, 0.0, 0])
    if now < rec[1]:
        return jsonify(error="locked", wait=int(rec[1] - now)), 429
    data = jbody()
    ok_u = secrets.compare_digest(str(data.get("username", "")).strip().lower().encode(), USERNAME.lower().encode())
    ok_p = check_password_hash(PASS_HASH, str(data.get("password", ""))[:200])
    ok_c = (not wan) or (not totp_secret()) or (ok_u and ok_p and totp_ok(data.get("code", "")))   # 2FA فقط اگه خودت فعالش کرده باشی
    vname = None
    if not ok_u:               # شاید بیننده‌ی NVR باشه (مثلا بابا): بدون 2FA، ولی فقط دوربین‌ها
        uname = str(data.get("username", "")).strip().lower()[:40]
        vh = viewers().get(uname)
        if vh and check_password_hash(vh, str(data.get("password", ""))[:200]):
            vname = uname
    if vname:
        fails.pop(ip, None)
        session.clear()
        session.permanent = True
        session.update(ok=True, v=PASS_VER, t=time.time(), role="viewer", user=vname, vv=_viewer_ver(viewers()[vname]), lan=not wan)
        log_access(ip, True)
        audit("viewer login", vname)
        return jsonify(ok=True, role="viewer")
    if ok_u and ok_p and ok_c:
        fails.pop(ip, None)
        session.clear()
        session.permanent = True
        session.update(ok=True, v=PASS_VER, t=time.time(), elev=time.time(), lan=not wan)
        log_access(ip, True)
        return jsonify(ok=True)
    rec[0] += 1
    log_access(ip, False)
    if rec[0] >= 5:        # قفل تصاعدی: ۱، ۲، ۴ ... تا ۶۰ دقیقه
        rec[1] = time.time() + min(60 * 2 ** rec[2], 3600)
        rec[0], rec[2] = 0, rec[2] + 1
        notify(f"Warning: repeated failed logins from {ip}")
    fails[ip] = rec
    time.sleep(0.7)        # کند کردن حدس زدن
    return jsonify(error="wrong"), 403


def _logout_all_core(alert=True):
    global SESSION_EPOCH, PASS_VER
    SESSION_EPOCH += 1
    _write_secret(EPOCH_FILE, str(SESSION_EPOCH))
    PASS_VER = _pass_ver()
    audit("logout all devices", alert=alert)


@app.post("/api/logout_all")
@auth
def logout_all():
    """خروج از همه‌ی دستگاه‌ها (اگه گوشی گم شد یا شک کردی)"""
    _logout_all_core(alert=True)
    session.clear()
    return jsonify(ok=True)


@app.post("/api/_handover")
def handover():
    """فقط از خود سیستم (127.0.0.1) و با توکن: سرویس کنار میره تا نسخه‌ی کامل (بعد از ورود به ویندوز) پورت رو بگیره"""
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return jsonify(error="not found"), 404
    if not HEADLESS:
        return jsonify(error="already full"), 409
    try:
        tok = TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        tok = ""
    if not tok or not hmac.compare_digest(request.headers.get("X-Handover", ""), tok):
        return jsonify(error="forbidden"), 403

    def bye():
        time.sleep(0.6)
        try:
            security.save()
        except Exception:
            pass
        print("تحویل به نسخه‌ی کامل؛ سرویس خارج میشه")
        os._exit(0)

    threading.Thread(target=bye, daemon=True).start()
    return jsonify(ok=True)


@app.post("/api/ping")
@auth_viewer
def ping():
    return jsonify(ok=True)


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.post("/api/reauth")
@auth
def reauth():
    """تایید مجدد رمز برای کارهای حساس"""
    ip = client_ip()
    rec = fails.get("re:" + ip, [0, 0.0, 0])
    if time.time() < rec[1]:
        return jsonify(error="locked"), 429
    if check_password_hash(PASS_HASH, str(jbody().get("password", ""))[:200]):
        fails.pop("re:" + ip, None)
        session["elev"] = time.time()
        return jsonify(ok=True)
    rec[0] += 1
    if rec[0] >= 5:
        rec[:] = [0, time.time() + 300, 0]
        notify(f"Warning: failed re-auth attempts from {ip}")
    fails["re:" + ip] = rec
    time.sleep(0.7)
    return jsonify(error="wrong"), 403


@app.get("/api/state")
@auth
def state():
    return jsonify(player.state())


@app.get("/api/tracks")
@auth
def tracks():
    return jsonify([{k: t[k] for k in ("id", "title", "artist", "duration")} for t in player.tracks])


@app.post("/api/play")
@auth
def play():
    player.play(num(jbody().get("id"), 0, 0, 10**9, int))
    return jsonify(player.state())


@app.post("/api/toggle")
@auth
def toggle():
    player.toggle()
    return jsonify(player.state())


@app.post("/api/next")
@auth
def nxt():
    player.next()
    return jsonify(player.state())


@app.post("/api/prev")
@auth
def prv():
    player.prev()
    return jsonify(player.state())


@app.post("/api/stop")
@auth
def stop():
    player.stop()
    return jsonify(player.state())


@app.post("/api/volume")
@auth
def volume():
    player.set_volume(num(jbody().get("value"), 0.7, 0.0, 1.0))
    USER_VOL[0] = player.volume
    schedule_save()
    return jsonify(player.state())


@app.post("/api/seek")
@auth
def seek():
    player.seek(num(jbody().get("pos"), 0.0, 0.0, 86400.0))
    return jsonify(player.state())


@app.post("/api/shuffle")
@auth
def shuffle():
    player.shuffle = not player.shuffle
    schedule_save()
    return jsonify(player.state())


@app.post("/api/repeat")
@auth
def repeat():
    order = ["off", "all", "one"]
    player.repeat = order[(order.index(player.repeat) + 1) % 3]
    schedule_save()
    return jsonify(player.state())


@app.get("/api/prefs")
@auth
def prefs_get():
    return jsonify(UI_PREFS)


@app.post("/api/prefs")
@auth
def prefs_set():
    d = jbody()
    UI_PREFS["mon"] = num(d.get("mon", UI_PREFS["mon"]), 1, 1, 16, int)
    UI_PREFS["qual"] = num(d.get("qual", UI_PREFS["qual"]), 1, 0, 2, int)
    UI_PREFS["tpad"] = bool(d.get("tpad", UI_PREFS["tpad"]))
    schedule_save()
    return jsonify(UI_PREFS)


@app.post("/api/rescan")
@auth
def rescan():
    player.scan()
    return jsonify(count=len(player.tracks))


# ===================== دوربین / صحبت / گوش دادن =====================
sock = Sock(app)


class Camera:
    """دوربین فقط وقتی لازمه روشنه (مسلح، حالت سرگرمی یا تماشا). اگه قطع بشه خودش دوباره وصل میشه."""

    def __init__(self):
        self.lock = threading.Lock()
        self.users = 0
        self.thread = None
        self.frame = None   # jpeg (تمیز: برای عکس/ویدیو)
        self.view = None    # jpeg با کادر تشخیص: فقط برای پخش زنده
        self.raw = None     # آخرین تصویر خام
        self.ring = deque(maxlen=150)  # ~۷ ثانیه‌ی آخر (jpeg) برای ضبط ویدیو از قبل از رویداد
        self.last_ok = 0.0
        self.err, self.good, self.index_used = "", None, CAMERA_INDEX
        self.viewers = 0   # چند نفر دارن پخش زنده رو میبینن
        self.hi_viewers, self.view_hi = 0, None   # بیننده‌های تمام‌صفحه (اپ اندروید افقی): وب‌کم با رزولوشن بالاتر
        self._audio_chk = 0.0

    def _open(self):
        """چند روش (DSHOW/MSMF) و اگه CAMERA_INDEX رو دستی نذاشتی چند شماره رو امتحان میکنه؛
        فقط وقتی قبول میکنه که واقعا یه فریم بخونه. اگه نشد، دلیلش تو self.err میاد و تو صفحه نشون داده میشه."""
        if HEADLESS:
            self.err = "وب‌کم بعد از ورود به ویندوز فعال میشه (الان حالت سرویسه)"
            return None
        backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY] if os.name == "nt" else [cv2.CAP_ANY]
        idxs = [CAMERA_INDEX] if "CAMERA_INDEX" in os.environ else [CAMERA_INDEX] + [i for i in range(1, 4)]
        if self.good in [(i, b) for i in idxs for b in backends]:
            idxs = [self.good[0]] + [i for i in idxs if i != self.good[0]]
            backends = [self.good[1]] + [b for b in backends if b != self.good[1]]
        for idx in idxs:
            for be in backends:
                try:
                    cap = cv2.VideoCapture(idx, be)
                    if cap.isOpened():
                        ok, img = cap.read()
                        if ok and img is not None:
                            self.good, self.index_used, self.err = (idx, be), idx, ""
                            if idx != CAMERA_INDEX:
                                print(f"[camera] دوربین {CAMERA_INDEX} باز نشد، دوربین {idx} استفاده شد (CAMERA_INDEX={idx} تو start.bat بذار)")
                            return cap
                    cap.release()
                except Exception as e:
                    print("[camera] open:", e)
        msg = ("دوربین باز نشد. چک کن: ۱) برنامه‌ی دیگه (Zoom، Camera ویندوز، یا یه نسخه‌ی قبلی همین برنامه که هنوز باز مونده) دوربین رو نگرفته باشه "
               "۲) ویندوز: Settings > Privacy > Camera > «Let desktop apps access your camera» روشن باشه ۳) شماره‌ی درست دوربین: CAMERA_INDEX تو start.bat")
        if msg != self.err:
            print("[camera]", msg)
        self.err = msg
        return None

    def _loop(self):
        cap, fails, retry, cur_hi = None, 0, 0.0, False
        while True:
            with self.lock:
                if self.users <= 0:
                    self.thread = None
                    self.frame = self.view = self.raw = self.view_hi = None
                    self.ring.clear()
                    break
            try:
                if cap is None:
                    if time.time() < retry:
                        time.sleep(0.5)
                        continue
                    cap = self._open()
                    if cap is None:
                        retry = time.time() + 5
                        continue
                    fails, cur_hi = 0, False
                want_hi = self.hi_viewers > 0
                if want_hi != cur_hi:                     # تمام‌صفحه شد/نشد: رزولوشن وب‌کم رو بالا/پایین ببر
                    cur_hi = want_hi
                    try:
                        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280 if want_hi else 640)
                        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720 if want_hi else 480)
                    except Exception:
                        pass
                ok, img = cap.read()
                if not ok:
                    fails += 1
                    if fails > 40:      # دوربین قطع شده: ولش کن و دوباره تلاش کن
                        cap.release()
                        cap, retry = None, time.time() + 3
                    time.sleep(0.05)
                    continue
                fails = 0
                self.last_ok = time.time()
                h, w = img.shape[:2]
                full = img
                if w > 640:
                    img = cv2.resize(img, (640, int(h * 640 / w)))
                self.raw = img
                if security.armed and time.time() - self._audio_chk > 5:
                    self._audio_chk = time.time()
                    try:
                        audio_tap.check()
                    except Exception as e:
                        print("audio check:", e)
                try:                         # خطا تو تحلیل هیچ‌وقت نباید تصویر دوربین رو قطع کنه
                    if security.armed or reactor.on:
                        security.analyze(img)
                    elif self.viewers > 0:
                        security.watch(img)
                except Exception as e:
                    print("analyze:", e)
                ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
                if ok:
                    self.frame = buf.tobytes()
                    self.view = self.frame
                    if security.armed or reactor.on or self.viewers > 0:
                        ov = security.overlay(img)
                        if ov is not None:
                            ok2, b2 = cv2.imencode(".jpg", ov, [cv2.IMWRITE_JPEG_QUALITY, 70])
                            if ok2:
                                self.view = b2.tobytes()
                    if security.armed:
                        self.ring.append((time.time(), self.frame))
                if want_hi:
                    fs = full if full.shape[1] <= 1280 else cv2.resize(full, (1280, int(full.shape[0] * 1280 / full.shape[1])), interpolation=cv2.INTER_AREA)
                    ok3, b3 = cv2.imencode(".jpg", fs, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    if ok3:
                        self.view_hi = b3.tobytes()
                else:
                    self.view_hi = None
            except Exception as e:
                print("camera loop:", e)
                time.sleep(0.5)
            time.sleep(0.05)
        if cap is not None:
            cap.release()

    def acquire(self):
        with self.lock:
            self.users += 1
            if self.thread is None:
                self.thread = threading.Thread(target=self._loop, daemon=True)
                self.thread.start()

    def release(self):
        with self.lock:
            self.users = max(0, self.users - 1)


camera = Camera()
_holds, _holds_lock = set(), threading.Lock()


def camera_hold(name, on):
    """هر قابلیت (امنیت، حالت سرگرمی) فقط یک بار دوربین رو نگه میداره"""
    with _holds_lock:
        if on and name not in _holds:
            _holds.add(name)
            camera.acquire()
        elif not on and name in _holds:
            _holds.discard(name)
            camera.release()


# ======================= NVR: دو کانال، تشخیص آدم، عکس/ویدیو/تلگرام (جدا از وب‌کم) =======================
nvr_feeds = {_c: nvr.NvrFeed(_c) for _c in nvr.CHANNELS}
NVR_COOLDOWN = num(os.environ.get("NVR_COOLDOWN"), 20, 5, 600, int)      # حداقل فاصله‌ی دو رویداد یک کانال (ثانیه)


def nvr_snapshot_jpg(ch, wait=25):
    """یه عکس تازه از کانال NVR (اگه پخش خاموشه، موقتا وصل میشه)"""
    feed = nvr_feeds.get(ch)
    if feed is None or cv2 is None or not nvr.enabled():
        return None
    feed.acquire()
    try:
        t0 = time.time()
        while time.time() - t0 < wait:
            if feed.raw is not None and time.time() - feed.ts < 5:
                return feed.snapshot_jpg()
            time.sleep(0.3)
        return None
    finally:
        feed.release()


def save_nvr_still(ch, data):
    """هر عکسی که دستی از NVR گرفته میشه (دکمه‌ی 📷 تو وب/اپ، دستور /nvr تلگرام) هم تو پوشه‌ی captures ذخیره میشه، مثل عکس‌های خودکار"""
    try:
        CAP_DIR.mkdir(exist_ok=True)
        path = CAP_DIR / (datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + f"-n{ch}.jpg")
        path.write_bytes(data)
        prune_captures(protect=path)
    except Exception as e:
        print(f"nvr{ch} save still:", e)


class NvrWatch:
    """همه‌ی کارهای وب‌کم وقتی «خونه نیستم»، برای کانال‌های NVR هم: تشخیص آدم (یا حرکت ساده اگه خراب شد / «فقط آدم» خاموشه)،
    عکس + ویدیو + پیام تلگرام/ntfy، واکنش خودکار (موزیک/صدا/هوشمند)، حالت سرگرمی، هشدار تاریک/پوشیده، قطع شدن، ویدیوی دلخواه.
    گزینه‌های بخش امنیت (فقط آدم، ویدیو، کادر، حساسیت، واکنش خودکار) برای NVR هم اعمال میشن.
    روشن/خاموشش جداست (دکمه‌ی NVR، /nvron و /nvroff) و با «🚪 بیرونم / 🏠 رسیدم» هم روشن/خاموش میشه."""

    def __init__(self):
        self.on = False
        self.hd = False                                # استریم اصلی (کیفیت بالا) به‌جای فرعی
        self.enhance = False                           # «✨ بهبود کیفیت» (روشنایی/نویز/کنتراست/تیزی)
        self.ui = {"open": False, "shown": []}         # صفحه‌ی NVR باز بود؟ کدوم کانال‌ها؟ (برای وقتی دوباره باز میکنی)
        self.gen = 0
        self.threads = {}
        self.lock = threading.Lock()
        self.st = {c: {"last_event": 0.0, "gate": None, "broken": False, "err": "", "rec": False, "events": 0,
                       "dead_alerted": False, "person_t": 0.0, "prev": None, "warm": 0,
                       "dark_since": 0.0, "dark_alerted": False, "lock": threading.Lock(), "view": False} for c in nvr.CHANNELS}

    def set(self, on):
        on = bool(on) and cv2 is not None and nvr.enabled()
        with self.lock:
            if on == self.on:
                return self.on
            self.on = on
            self.gen += 1
            for ch, feed in nvr_feeds.items():
                s = self.st[ch]
                if on:
                    s.update(prev=None, warm=8, dark_since=0.0, dark_alerted=False, dead_alerted=False)
                    feed.keep_ring = True
                    feed.acquire()
                    self.threads[ch] = threading.Thread(target=self._loop, args=(ch, self.gen), daemon=True)
                    self.threads[ch].start()
                else:
                    feed.keep_ring = False
                    feed.boxes = []
                    feed.release()
        if not on:
            for ch in nvr_feeds:
                self.ensure_view(ch)                   # اگه کسی داره تماشا میکنه، کادرها همچنان بیان
        return self.on

    def ensure_view(self, ch):
        """کادر آدم روی پخش زنده حتی وقتی تشخیص (🛡) خاموشه (مثل وب‌کم): فقط کادر، بدون عکس/پیام/واکنش"""
        s, feed = self.st[ch], nvr_feeds[ch]
        if self.on or feed.viewers <= 0 or s["view"] or cv2 is None:
            return
        s["view"] = True
        threading.Thread(target=self._view_loop, args=(ch,), daemon=True).start()

    def _view_loop(self, ch):
        feed, s = nvr_feeds[ch], self.st[ch]
        last_seq = 0
        try:
            while not self.on and feed.viewers > 0:
                try:
                    img = feed.raw
                    if img is None or feed.seq == last_seq:
                        time.sleep(0.2)
                        continue
                    last_seq = feed.seq
                    if (security.opts.get("human_only", True) and security.opts.get("boxes", True)
                            and human_mod is not None and not s["broken"]):
                        small = img if img.shape[1] <= 640 else cv2.resize(img, (640, int(img.shape[0] * 640 / img.shape[1])))
                        with s["lock"]:
                            self._human(ch, s, feed, small, img, time.time())
                    else:
                        feed.boxes = []
                except Exception as e:
                    s["broken"], s["err"] = True, repr(e)[:150]
                    print(f"nvr{ch} view gate failed:", s["err"])
                    feed.boxes = []
                time.sleep(0.25)
        finally:
            s["view"] = False
            if not self.on:
                feed.boxes = []

    def to_dict(self):
        return {"on": self.on, "hd": self.hd, "enhance": self.enhance, "ui": self.ui}

    def keepalive(self):
        """وقتی تشخیص NVR روشنه، هر ۲۰ ثانیه چک میکنه ریسه‌ی دریافت و تحلیل هر کانال زنده باشه؛ مرده بود دوباره راهش میندازه (NVR «بمونه»)"""
        while True:
            time.sleep(20)
            try:
                if not self.on:
                    continue
                with self.lock:
                    gen = self.gen
                    for ch, feed in nvr_feeds.items():
                        with feed.lock:
                            alive = feed.thread is not None and feed.thread.is_alive()
                            if not alive:
                                feed.thread = None
                                if feed.users <= 0:
                                    feed.users = 1
                                feed.thread = threading.Thread(target=feed._loop, daemon=True)
                                feed.thread.start()
                                print(f"nvr{ch} keepalive: feed restarted")
                        t = self.threads.get(ch)
                        if t is None or not t.is_alive():
                            self.st[ch].update(prev=None, warm=8)
                            feed.keep_ring = True
                            self.threads[ch] = threading.Thread(target=self._loop, args=(ch, gen), daemon=True)
                            self.threads[ch].start()
                            print(f"nvr{ch} keepalive: analyzer restarted")
            except Exception as e:
                print("nvr keepalive:", e)

    def brief(self):
        """خلاصه برای بخش امنیت (وب/اپ)"""
        chans = []
        for ch, feed in nvr_feeds.items():
            s = self.st[ch]
            chans.append({"ch": ch, "state": feed.status().get("state"), "err": feed.err, "events": s["events"],
                          "person_ago": (int(time.time() - s["person_t"]) if s["person_t"] else None),
                          "last_event": (int(time.time() - s["last_event"]) if s["last_event"] else None), "broken": s["broken"]})
        return {"enabled": nvr.enabled() and cv2 is not None, "on": self.on, "hd": self.hd, "enhance": self.enhance,
                "detector": human_mod.detector_name() if human_mod else "-", "channels": chans}

    def configure(self, d):
        if not isinstance(d, dict):
            return
        self.set_opts(hd=bool(d.get("hd")), enhance=bool(d.get("enhance")), ui=d.get("ui"))
        if d.get("on") and cv2 is not None and nvr.enabled():        # تشخیص NVR بعد از ریستارت دوباره روشن
            try:
                self.set(True)
            except Exception as e:
                print("nvr restore:", e)
        if d.get("on"):
            self.set(True)

    def set_opts(self, hd=None, enhance=None, ui=None):
        """HD / بهبود کیفیت / وضعیت صفحه؛ همه روی سرور ذخیره میشن (security.save)"""
        if hd is not None:
            self.hd = bool(hd)
            for f in nvr_feeds.values():
                f.set_hd(self.hd)
        if enhance is not None:
            self.enhance = bool(enhance)
            for f in nvr_feeds.values():
                f.enhance = self.enhance
        if isinstance(ui, dict):
            shown = [c for c in ui.get("shown", []) if isinstance(c, int) and c in nvr_feeds] if isinstance(ui.get("shown"), list) else []
            self.ui = {"open": bool(ui.get("open")), "shown": shown[:4]}

    def _loop(self, ch, gen):
        feed, s = nvr_feeds[ch], self.st[ch]
        last_seq, last_ok = 0, time.time()
        while self.on and self.gen == gen:
            try:
                img = feed.raw
                if img is None or feed.seq == last_seq:
                    if time.time() - last_ok > 90 and not s["dead_alerted"]:
                        s["dead_alerted"] = True
                        notify(f"Warning: NVR camera {ch} is not delivering frames", True)
                    time.sleep(0.2)
                    continue
                last_seq, last_ok, s["dead_alerted"] = feed.seq, time.time(), False
                small = img if img.shape[1] <= 640 else cv2.resize(img, (640, int(img.shape[0] * 640 / img.shape[1])))
                self._analyze(ch, s, feed, small, img)
            except Exception as e:                     # خطا تو تحلیل هیچ‌وقت نباید پخش رو قطع کنه
                print(f"nvr{ch} analyze:", e)
                time.sleep(1)
            time.sleep(0.25)                           # ~۴ بار در ثانیه کافیه و CPU رو نمیکشه
        feed.boxes = []

    # ------------------------------------------------------------------ تحلیل
    def _dark(self, ch, s, small, now):
        """دوربین پوشونده شده / خیلی تاریک (مثل وب‌کم)"""
        gray = cv2.cvtColor(cv2.resize(small, (160, 90)), cv2.COLOR_BGR2GRAY)
        if gray.mean() < 5:
            s["dark_since"] = s["dark_since"] or now
            if now - s["dark_since"] > 60 and not s["dark_alerted"]:
                s["dark_alerted"] = True
                notify(f"Warning: NVR camera {ch} sees nothing (covered or dark)")
        else:
            s["dark_since"], s["dark_alerted"] = 0.0, False

    def _human(self, ch, s, feed, small, img, now):
        if s["gate"] is None:
            # NVR: برش‌های بزرگ‌شده (آدم دور/کوچیک) + آدمِ ایستاده هم حساب میشه (NVR_DEEP=0 / NVR_STILL=0 برای خاموش کردن)
            s["gate"] = human_mod.HumanGate(security.sens, tiles=os.environ.get("NVR_DEEP", "1") != "0",
                                            allow_still=os.environ.get("NVR_STILL", "1") != "0")
        g = s["gate"]
        g.sens = security.sens
        st = g.update(img, now)                    # تصویر کامل (تا ۹۶۰ عرض)؛ تشخیص خودش درشتش میکنه
        if g.fail >= 8:
            raise RuntimeError("detector failing: " + (g.err or "?"))
        f = 1.0
        human, boxes = g.human_now, []
        if security.opts.get("boxes", True):
            for d in list(g.people):
                if now - d["t"] > g.SHOW:
                    continue
                x, y, w, h = d["box"]
                col, label = ((0, 220, 0), "PERSON") if human else ((0, 230, 255), "person?")
                boxes.append((int(x * f), int(y * f), int(w * f), int(h * f), "%s %.0f%%" % (label, min(d.get("score", 0), 1.5) * 100), col))
        feed.boxes, feed.boxes_t = boxes, now
        return st == "human"

    def _motion(self, s, small, now):
        """حرکت ساده (وقتی «فقط آدم» خاموشه یا تشخیص آدم خراب شده): همون روش وب‌کم"""
        gray = cv2.cvtColor(cv2.resize(small, (320, max(int(small.shape[0] * 320 / small.shape[1]), 1))), cv2.COLOR_BGR2GRAY)
        g = cv2.GaussianBlur(gray, (21, 21), 0)
        prev = s["prev"]
        if prev is None or prev.shape != g.shape:
            s["prev"] = g.astype("float32")
            return False
        diff = cv2.absdiff(g, cv2.convertScaleAbs(prev))
        cv2.accumulateWeighted(g, prev, 0.05)
        if s["warm"] > 0:
            s["warm"] -= 1
            return False
        th = cv2.dilate(cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)[1], None, iterations=2)
        cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        area = sum(cv2.contourArea(c) for c in cnts)
        if area > 0.5 * th.shape[0] * th.shape[1]:        # عوض شدن ناگهانی نور، نه حرکت
            s["prev"] = g.astype("float32")
            return False
        return area > security.sens

    def _analyze(self, ch, s, feed, small, img):
        now = time.time()
        self._dark(ch, s, small, now)
        hit, person = False, None
        use_human = security.opts.get("human_only", True) and human_mod is not None and not s["broken"]
        if use_human:
            try:
                with s["lock"]:
                    hit = self._human(ch, s, feed, small, img, now)
                person = True if hit else None
            except Exception as e:                    # تشخیص آدم خراب شد: به حرکت ساده برگرد (مثل وب‌کم)
                s["broken"], s["err"] = True, repr(e)[:150]
                print(f"nvr{ch} human gate failed, falling back to plain motion:", s["err"])
                notify(f"NVR camera {ch}: person detector failed, using plain motion ({s['err'][:60]})", True)
                use_human = False
        if not use_human:
            feed.boxes = []
            hit = self._motion(s, small, now)
        if not hit:
            return
        if person:
            s["person_t"] = now
        try:
            if reactor.on:                             # حالت سرگرمی (واکنش به آدم دیده شده)
                reactor.sighting(img, human=bool(person))
        except Exception as e:
            print(f"nvr{ch} reactor:", e)
        if now - s["last_event"] > NVR_COOLDOWN:
            self._fire(ch, s, img, person)

    def _fire(self, ch, s, img, person):
        s["last_event"] = time.time()
        s["events"] += 1
        if person is None:
            try:
                person = bool(reactor.detect(img))
            except Exception:
                person = False
        quiet = bool(security.opts.get("person_only")) and not person       # «فقط آدم رو اعلان بده»
        threading.Thread(target=self._burst, args=(ch, img.copy(), person, quiet), daemon=True).start()
        if quiet:
            return
        if security.opts.get("video", True):
            threading.Thread(target=self._record, args=(ch, person), daemon=True).start()
        self._react(person)

    def _react(self, person):
        """واکنش خودکار به رویداد (همون تنظیم «واکنش خودکار» بخش امنیت).
        فقط وقتی «بیرونم» یا «مسلح» روشنه؛ وگرنه NVR فقط عکس/ویدیو/اعلان میده و آهنگ/صدا پخش نمیشه."""
        if not (security.armed or presence.away):
            return
        try:
            if security.auto == "sounds":
                threading.Thread(target=reactor.alert_sound, daemon=True).start()
            elif security.auto == "music" and player.tracks:
                player.shuffle = True
                if not player.playing:
                    player.start_soft(AUTO_MAX[0])
                else:
                    player.ramp(AUTO_MAX[0], 6)
            elif security.auto == "smart":
                reactor.escalate(person)
        except Exception as e:
            print("nvr auto action:", e)

    # ------------------------------------------------------------------ عکس و ویدیو
    def _save_frame(self, ch, img, person):
        CAP_DIR.mkdir(exist_ok=True)
        path = CAP_DIR / (datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + f"-n{ch}" + ("-p" if person else "") + ".jpg")
        if self.enhance:                               # «✨ بهبود کیفیت» روی عکس رویداد هم اعمال میشه
            try:
                import enhance
                img = enhance.still(img)
            except Exception as e:
                print("enhance photo:", e)
        elif np is not None and img.mean() < 70:      # شب/تاریک: عکس رو روشن‌تر کن
            lut = (np.arange(256) / 255.0) ** 0.5 * 255
            img = cv2.LUT(img, lut.astype("uint8"))
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            return None
        path.write_bytes(buf.tobytes())
        prune_captures(protect=path)
        return path

    def _burst(self, ch, img, person, quiet=False):
        """سه عکس پشت سر هم (اولی فوری)؛ فقط اولی روی پیام‌رسان میره (اگه ALERT_MEDIA=1 باشه، وگرنه فقط متن)"""
        try:
            first = self._save_frame(ch, img, person)
            if first and not quiet:
                send_alert(first, person, f"nvr{ch}")
            for _ in range(2):
                time.sleep(1.0)
                f = nvr_feeds[ch].raw
                if f is not None:
                    self._save_frame(ch, f.copy(), person)
        except Exception as e:
            print(f"nvr{ch} capture:", e)

    def _record(self, ch, person=True, manual=False):
        """ویدیوی چند ثانیه قبل + VIDEO_SECONDS ثانیه بعد از رویداد (بدون صدا). برمیگردونه: شد یا نشد"""
        s, feed = self.st[ch], nvr_feeds[ch]
        if s["rec"] or np is None:
            return False
        s["rec"], writer, done = True, None, False
        try:
            CAP_DIR.mkdir(exist_ok=True)
            prune_captures()
            fg = disk_free_gb()
            if fg is not None and fg < 0.5:
                print("[disk] هارد تقریبا پره؛ ویدیوی NVR ضبط نشد")
                return False
            FPS = 8.0
            frames, last_t = [], 0.0
            for t, jb in list(feed.ring):
                if t - last_t >= 1.0 / FPS:
                    im = cv2.imdecode(np.frombuffer(jb, np.uint8), cv2.IMREAD_COLOR)
                    if im is not None:
                        frames.append(im)
                        last_t = t
            first = frames[-1] if frames else feed.raw
            if first is None:
                return False
            h, w = first.shape[:2]
            base = CAP_DIR / (datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + f"-n{ch}" + ("-p" if person else ""))
            writer, path = security._open_writer(base, FPS, (w, h))
            if writer is None:
                print("nvr video: no codec available")
                return False
            fit = lambda im: im if im.shape[:2] == (h, w) else cv2.resize(im, (w, h))
            for im in frames:
                writer.write(fit(im))
            total, written, t0 = int(VIDEO_SECONDS * FPS), 0, time.time()
            while written < total and time.time() - t0 < VIDEO_SECONDS + 5:
                due, f = min(total, int((time.time() - t0) * FPS) + 1), feed.raw
                while written < due and f is not None:
                    writer.write(fit(f))
                    written += 1
                time.sleep(0.03)
            writer.release()
            writer = None
            path = security._add_audio(path, None, None)          # H.264 (تو گوشی پخش بشه)
            prune_captures(protect=path)
            label = (f"Requested clip · NVR cam {ch}" if manual else f"{'Person' if person else 'Motion'} clip · NVR cam {ch}")
            send_clip(path, label, force=manual)
            done = True
        except Exception as e:
            print(f"nvr{ch} video:", e)
        finally:
            if writer is not None:
                writer.release()
            s["rec"] = False
        return done

    def video(self, ch):
        """ویدیوی دلخواه از یه کانال (دستور تلگرام /nvrvideo)؛ حتی وقتی تشخیص خاموشه"""
        feed = nvr_feeds.get(ch)
        if feed is None or cv2 is None or not nvr.enabled():
            return False
        feed.acquire()
        try:
            t0 = time.time()
            while time.time() - t0 < 25 and feed.raw is None:
                time.sleep(0.3)
            return self._record(ch, False, manual=True) if feed.raw is not None else False
        finally:
            feed.release()

    # ------------------------------------------------------------------ وضعیت
    def status(self):
        chans = []
        for ch, feed in nvr_feeds.items():
            s = self.st[ch]
            d = feed.status()
            g = s.get("gate")
            d.update(watch_broken=s["broken"], watch_err=s["err"], events=s["events"], last_event=s["last_event"],
                     person_ago=(int(time.time() - s["person_t"]) if s["person_t"] else None),
                     score=(round(g.best, 2) if g is not None else None), det_ms=(int(g.det_ms) if g is not None else None))
            chans.append(d)
        return {"enabled": nvr.enabled() and cv2 is not None, "on": self.on, "hd": self.hd, "enhance": self.enhance,
                "ui": self.ui, "channels": chans, "detector": human_mod.detector_name() if human_mod else "-"}

    def summary(self):
        st = self.status()
        icon = {"ok": "✅", "error": "❌"}
        chs = "، ".join(f"کانال {c['ch']}: {icon.get(c['state'], '⏸')}" for c in st["channels"])
        le = max((c["last_event"] for c in st["channels"]), default=0)
        last = f"{int((time.time() - le) / 60)} دقیقه پیش" if le else "هنوز نبوده"
        return f"📹 تشخیص آدم NVR: {'✅' if self.on else '❌'} — {chs} — آخرین رویداد: {last}"


nvrwatch = NvrWatch()
threading.Thread(target=nvrwatch.keepalive, daemon=True).start()


def _nvr_ch():
    try:
        ch = int(request.args.get("ch", nvr.CHANNELS[0]))
    except (TypeError, ValueError):
        ch = nvr.CHANNELS[0]
    return ch if ch in nvr_feeds else None


@app.get("/camera-nvr.mjpg")
@auth_viewer
def nvr_stream():
    if cv2 is None:
        return jsonify(error="opencv not installed"), 501
    if not nvr.enabled():
        return jsonify(error="NVR_IP is not set in start.bat"), 404
    ch = _nvr_ch()
    if ch is None:
        return jsonify(error="bad channel"), 400
    feed, ip = nvr_feeds[ch], client_ip()
    try:
        want = float(request.args.get("fps", ""))
    except ValueError:
        want = None
    cap_fps = nvr.STREAM_FPS                                                # هر چقدر NVR بده (تا ۳۰ فریم)
    gap = 1.0 / max(0.5, min(want or cap_fps, cap_fps))
    hi = request.args.get("hi") == "1"           # اپ اندروید تو حالت تمام‌صفحه/افقی: استریم اصلی + عکس بزرگ‌تر

    def gen():
        feed.acquire()
        feed.viewers += 1
        if hi:
            feed.hi_viewers += 1
            feed.set_hd(True)                    # تا وقتی تمام‌صفحه‌ست استریم اصلی (HD)
        nvrwatch.ensure_view(ch)
        try:
            last, t0, sent = None, time.time(), 0.0
            while client_alive(ip):
                f = (feed.jpg_hi if hi else None) or feed.view
                if f is not None and f is not last and time.time() - sent >= gap:
                    last, t0, sent = f, time.time(), time.time()
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + f + b"\r\n"
                elif time.time() - t0 > 120:
                    break
                time.sleep(0.04)
        finally:
            feed.viewers = max(0, feed.viewers - 1)
            if hi:
                feed.hi_viewers = max(0, feed.hi_viewers - 1)
                if feed.hi_viewers == 0:
                    feed.set_hd(nvrwatch.hd)     # برگرد به انتخاب خودت (دکمه‌ی HD)
            feed.release()

    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.get("/api/nvr/status")
@auth_viewer
def nvr_status():
    st = nvrwatch.status()
    if is_viewer():            # بیننده فقط وضعیت ساده میبینه (نه آدرس/خطا/گزارش داخلی)
        return jsonify(enabled=st["enabled"], channels=[{"ch": c["ch"], "state": c["state"], "age": c["age"]} for c in st["channels"]])
    return jsonify(st)


@app.get("/api/nvr/snapshot.jpg")
@auth_viewer
def nvr_snapshot():
    ch = _nvr_ch()
    if ch is None or not nvr.enabled() or cv2 is None:
        return jsonify(error="not available"), 404
    data = nvr_snapshot_jpg(ch, 20)
    if data is None:
        return jsonify(error="no frame from NVR"), 503
    save_nvr_still(ch, data)
    return Response(data, mimetype="image/jpeg", headers={"Content-Disposition": f'inline; filename="nvr{ch}.jpg"'})


@app.post("/api/nvr")
@auth
def nvr_set():
    d = jbody()
    if "on" in d:
        if cv2 is None:
            return jsonify(error="opencv not installed"), 501
        if not nvr.enabled():
            return jsonify(error="NVR_IP is not set in start.bat"), 404
        nvrwatch.set(bool(d["on"]))
        audit("NVR WATCH ON" if nvrwatch.on else "NVR WATCH OFF", alert=True)
    changed = "on" in d
    if "hd" in d or "enhance" in d or "ui" in d:
        nvrwatch.set_opts(hd=d.get("hd"), enhance=d.get("enhance"), ui=d.get("ui"))
        if "hd" in d:
            audit("NVR HD " + ("ON" if nvrwatch.hd else "OFF"))
        if "enhance" in d:
            audit("NVR ENHANCE " + ("ON" if nvrwatch.enhance else "OFF"))
        changed = True
    if changed:
        security.save()                                 # روی سرور ذخیره میشه؛ بعد از بستن/باز کردن یا ری‌استارت همون میمونه
    return jsonify(nvrwatch.status())


@app.get("/camera.mjpg")
@auth
def camera_stream():
    if cv2 is None:
        return jsonify(error="opencv not installed"), 501

    ip = client_ip()
    hi = request.args.get("hi") == "1"           # اپ اندروید تو حالت تمام‌صفحه/افقی: کیفیت بالاتر

    def gen():
        camera.acquire()
        camera.viewers += 1
        if hi:
            camera.hi_viewers += 1
        try:
            last, t0 = None, time.time()
            while client_alive(ip):
                f = (camera.view_hi if hi else None) or camera.view or camera.frame
                if f is not None and f is not last:
                    last, t0 = f, time.time()
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + f + b"\r\n"
                elif time.time() - t0 > 30:
                    break
                time.sleep(0.08)
        finally:
            camera.viewers = max(0, camera.viewers - 1)
            if hi:
                camera.hi_viewers = max(0, camera.hi_viewers - 1)
            camera.release()

    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.post("/api/bye")
def bye():
    """صفحه داره بسته میشه (sendBeacon): پخش‌های زنده‌ی این کلاینت تا چند ثانیه‌ی دیگه بسته میشن"""
    if session_ok(touch=False):
        LAST_POLL[client_ip()] = time.time() - POLL_TIMEOUT + 5
    return ("", 204)


@app.get("/api/snapshot.jpg")
@auth
def snapshot():
    """عکس همین الان از دوربین"""
    if cv2 is None:
        return jsonify(error="opencv not installed"), 501
    camera.acquire()
    try:
        for _ in range(60):
            if camera.frame:
                break
            time.sleep(0.1)
        f = camera.frame
    finally:
        camera.release()
    if not f:
        return jsonify(error="no frame"), 503
    return Response(f, mimetype="image/jpeg", headers={"Content-Disposition": "inline; filename=snapshot.jpg"})


# ===================== امنیت خونه =====================
TG_TOKEN = os.environ.get("ALERT_TOKEN", "")      # توکن ربات (تلگرام یا بله)
TG_CHAT = os.environ.get("ALERT_CHAT_ID", "")     # آیدی چت شما
TG_MEDIA = os.environ.get("ALERT_MEDIA", "0") == "1"      # 1 = عکس/ویدیو هم خودکار بفرسته (پیش‌فرض: فقط متن «آدم تشخیص داده شد»)
ALERT_MIN_GAP = int(os.environ.get("ALERT_MIN_GAP", "60"))  # حداقل فاصله‌ی دو پیام رویداد (ثانیه)
ALERT_PROXY = os.environ.get("ALERT_PROXY", "")      # مثلا http://127.0.0.1:10809 اگه تلگرام فقط با پروکسی/VPN باز میشه
ALERT_API = os.environ.get("ALERT_API", "https://api.telegram.org")  # برای بله: https://tapi.bale.ai
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")     # اعلان با اپ ntfy (ساده‌ترین راه؛ نیازی به باز بودن برنامه نیست)
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
SIREN_SECONDS = num(os.environ.get("SIREN_SECONDS"), 60, 3, 600, int)
CAP_DIR = BASE / "captures"
SOUNDS_DIR = BASE / "sounds"          # هر فایل صوتی (پارس سگ، خنده، ...) بریزی اینجا، تو واکنش‌های تصادفی استفاده میشه
SETTINGS = BASE / "settings.json"
CAP_RE = re.compile(r"\d{8}-\d{6}(-n\d)?(-p)?\.(jpg|mp4|avi)")
CAPTURE_MIN_FREE_GB = float(os.environ.get("CAPTURE_MIN_FREE_GB", "5"))


def disk_free_gb():
    try:
        return shutil.disk_usage(CAP_DIR if CAP_DIR.exists() else BASE).free / 1024**3
    except Exception:
        return None


def prune_captures(protect=None):
    """عکس و ویدیو تا وقتی هارد جا داره هیچ‌وقت پاک نمیشن. وقتی فضای خالی از CAPTURE_MIN_FREE_GB (پیش‌فرض ۵ گیگ) کمتر شد،
    قدیمی‌ترین‌ها پاک میشن تا فضای خالی دوباره یک گیگ از اون حد بیشتر بشه."""
    try:
        if not CAP_DIR.exists():
            return 0
        floor = CAPTURE_MIN_FREE_GB * 1024**3
        if shutil.disk_usage(CAP_DIR).free >= floor:
            return 0
        target = floor + 1024**3
        files = sorted((f for f in CAP_DIR.iterdir() if f.is_file() and CAP_RE.fullmatch(f.name)), key=lambda f: f.stat().st_mtime)
        n = 0
        for f in files:
            if protect is not None and f == protect:
                continue
            try:
                f.unlink()
                n += 1
            except OSError:
                continue
            if shutil.disk_usage(CAP_DIR).free >= target:
                break
        if n:
            print(f"[disk] فضای هارد کم بود؛ {n} فایل قدیمی از captures پاک شد")
        return n
    except Exception as e:
        print("prune:", e)
        return 0
VIDEO_SECONDS = num(os.environ.get("VIDEO_SECONDS"), 8, 3, 60, int)    # طول ضبط ویدیو بعد از رویداد (۳ ثانیه‌ی قبلش هم ضبط میشه)
USER_VOL = [0.7]                                  # صدایی که خود کاربر گذاشته (نه تغییرات خودکار شبیه‌سازی/واکنش)
UI_PREFS = {"mon": 1, "qual": 1, "tpad": False}   # انتخاب‌های صفحه‌ی دسکتاپ


def schedule_save():
    """ذخیره‌ی تنظیمات با کمی تاخیر (اسلایدر صدا پشت سر هم میفرسته)"""
    t = threading.Timer(1.0, lambda: security.save())
    t.daemon = True
    t.start()


REASONS = {"motion": "Motion", "noise": "Loud noise", "pc": "PC used locally", "manual": "Requested"}
REASONS.update({f"nvr{_i}": f"NVR cam {_i}" for _i in range(1, 17)})
last_synth = [0.0]


def mark_synthetic():
    """ورودی‌ای که خود برنامه ساخته (کنترل از گوشی، آژیر)؛ با نشستن واقعی پشت کامپیوتر اشتباه گرفته نشه"""
    last_synth[0] = time.time()


def _tg_open(req, timeout):
    """اول مثل ویندوز (پروکسی سیستم)، اگه وصل نشد مستقیم، و اگه ALERT_PROXY گذاشتی اونم.
    (وقتی برنامه‌ی VPN/پروکسی بسته‌ست ولی ویندوز هنوز بهش اشاره میکنه، خطای 10061 میاد؛ اینطوری مستقیم هم امتحان میشه)"""
    openers = [urllib.request.urlopen, urllib.request.build_opener(urllib.request.ProxyHandler({})).open]
    if ALERT_PROXY:
        openers.append(urllib.request.build_opener(urllib.request.ProxyHandler({"http": ALERT_PROXY, "https": ALERT_PROXY})).open)
    last = None
    for op in openers:
        try:
            return op(req, timeout=timeout)
        except urllib.error.HTTPError:
            raise                      # سرور جواب داده (مثلا توکن غلط)؛ راه دیگه فایده نداره
        except Exception as e:
            last = e
    raise last


_last_alert_text = [0.0]


_last_alert_nvr = {}


def _alert_text(reason, person):
    """فقط یه پیام کوتاه (بدون عکس/ویدیو)؛ حداکثر هر ALERT_MIN_GAP ثانیه یکی"""
    now = time.time()
    if reason.startswith("nvr"):               # هر کانال NVR محدودیت زمانی جدا داره
        if now - _last_alert_nvr.get(reason, 0.0) < ALERT_MIN_GAP:
            return
        _last_alert_nvr[reason] = now
        n, t = reason[3:], datetime.datetime.now().strftime("%H:%M:%S")
        notify((f"🧍 آدم تشخیص داده شد · NVR کانال {n} · {t}" if person else f"⚠ حرکت · NVR کانال {n} · {t}")
               + f"\n(عکس زنده: /nvr{n} · آخرین عکس: /last)", bool(person))
        return
    if now - _last_alert_text[0] < ALERT_MIN_GAP:
        return
    _last_alert_text[0] = now
    t = datetime.datetime.now().strftime("%H:%M:%S")
    if reason == "motion":
        msg = f"🧍 آدم تشخیص داده شد · {t}" if person else f"⚠ حرکت تشخیص داده شد · {t}"
    else:
        msg = {"noise": "🔊 صدای بلند", "pc": "💻 استفاده از کامپیوتر"}.get(reason, "⚠ رویداد") + f" · {t}"
    notify(msg + "\n(عکس/ویدیو: /snap  /video  /last)", bool(person))


def _tg_upload(method, field, filename, data, caption="", mime="application/octet-stream"):
    b = "----b" + secrets.token_hex(8)
    head = (f'--{b}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{TG_CHAT}\r\n'
            f'--{b}\r\nContent-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n'
            + ('--%s\r\nContent-Disposition: form-data; name="supports_streaming"\r\n\r\ntrue\r\n' % b if method == "sendVideo" else "")
            + f'--{b}\r\nContent-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
            f'Content-Type: {mime}\r\n\r\n').encode()
    body = head + data + f"\r\n--{b}--\r\n".encode()
    req = urllib.request.Request(f"{ALERT_API}/bot{TG_TOKEN}/{method}", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    _tg_open(req, 60).close()


def send_alert(path, person=False, reason="motion", force=False):
    """رویداد: به‌طور پیش‌فرض فقط متن؛ عکس فقط با ALERT_MEDIA=1 یا وقتی خودت خواستی (force)"""
    if not TG_TOKEN or not TG_CHAT:
        return
    if not (TG_MEDIA or force):
        _alert_text(reason, person)
        return
    label = REASONS.get(reason, "Event") if reason != "motion" else ("Person" if person else "Motion")
    if reason.startswith("nvr"):
        label = ("Person" if person else "Motion") + " · NVR cam " + reason[3:]
    cap = label + " detected " + datetime.datetime.now().strftime("%H:%M:%S")
    send_ntfy(cap, urgent=person)
    try:
        _tg_upload("sendPhoto", "photo", "p.jpg", Path(path).read_bytes(), cap, "image/jpeg")
    except Exception as e:
        print("alert send failed:", e)


def send_clip(path, label="Clip", force=False):
    """کلیپ فقط با ALERT_MEDIA=1 یا وقتی خودت با /video خواستی فرستاده میشه"""
    if not TG_TOKEN or not TG_CHAT or not (TG_MEDIA or force) or Path(path).stat().st_size > 45 * 1024**2:
        return
    try:
        ext = Path(path).suffix.lower()
        _tg_upload("sendVideo" if ext == ".mp4" else "sendDocument", "video" if ext == ".mp4" else "document",
                   Path(path).name, Path(path).read_bytes(), label, "video/mp4" if ext == ".mp4" else "application/octet-stream")
    except Exception as e:
        print("clip send failed:", e)


def send_text(msg):
    if not TG_TOKEN or not TG_CHAT:
        return
    try:
        req = urllib.request.Request(f"{ALERT_API}/bot{TG_TOKEN}/sendMessage",
                                     data=json.dumps({"chat_id": TG_CHAT, "text": msg}).encode(),
                                     headers={"Content-Type": "application/json"})
        _tg_open(req, 20).close()
        return True
    except Exception as e:
        print("alert text failed:", e)
        return False


def send_ntfy(msg, urgent=False):
    if not NTFY_TOPIC:
        return
    try:
        req = urllib.request.Request(f"{NTFY_SERVER}/{urllib.parse.quote(NTFY_TOPIC)}", data=str(msg).encode("utf-8"),
                                     headers={"Title": "Home Player", "Priority": "5" if urgent else "3",
                                              "Tags": "rotating_light" if urgent else "house"})
        urllib.request.urlopen(req, timeout=20).close()
        return True
    except Exception as e:
        print("ntfy failed:", e)
        return False


def tg_chat_ids():
    """chat id هایی که به ربات پیام دادن (برای پیدا کردن ALERT_CHAT_ID)"""
    try:
        with _tg_open(urllib.request.Request(f"{ALERT_API}/bot{TG_TOKEN}/getUpdates"), 20) as r:
            data = json.loads(r.read().decode())
        return sorted({str(u["message"]["chat"]["id"]) for u in data.get("result", []) if "message" in u})
    except Exception:
        return None


def notify(msg, urgent=False):
    threading.Thread(target=send_text, args=(msg,), daemon=True).start()
    threading.Thread(target=send_ntfy, args=(msg, urgent), daemon=True).start()


ACCESS_LOG = BASE / "access.log"
AUDIT_LOG = BASE / "audit.log"
KNOWN_IPS = set()
try:
    for _l in ACCESS_LOG.read_text(encoding="utf-8").splitlines():
        _p = _l.split("\t")
        if len(_p) == 3 and _p[2] == "OK":
            KNOWN_IPS.add(_p[1])
except OSError:
    pass


def _append_log(path, line):
    try:
        if path.exists() and path.stat().st_size > 1_000_000:   # چرخش لاگ
            path.replace(path.with_name(path.name + ".1"))
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def log_access(ip, ok):
    _append_log(ACCESS_LOG, f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}\t{ip}\t{'OK' if ok else 'FAIL'}")
    if ok and not is_lan(ip):
        notify(f"Login from OUTSIDE the house: {ip}", True)
    elif ok and ip not in KNOWN_IPS:
        KNOWN_IPS.add(ip)
        notify(f"New login from a new address: {ip}")


def audit(action, detail="", alert=False):
    """ثبت کارهای حساس (و اعلان روی پیام‌رسان)"""
    try:
        ip = client_ip()
    except RuntimeError:
        ip = "-"
    _append_log(AUDIT_LOG, f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}\t{ip}\t{action}\t{detail[:200]}")
    if alert:
        notify(f"{action}: {detail[:100]}")


@app.get("/api/access")
@auth
def access():
    def tail(path, n):
        try:
            return path.read_text(encoding="utf-8").splitlines()[-n:]
        except OSError:
            return []
    lines = [l.replace("\t", "  ") for l in reversed(tail(ACCESS_LOG, 10))]
    ev = [l.replace("\t", "  ") for l in reversed(tail(AUDIT_LOG, 8))]
    return jsonify(lines=lines + (["-- کارهای حساس --"] + ev if ev else []))


def pcm_to_sound(x):
    f = pygame.mixer.get_init()
    if not f or np is None:
        return None
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    if f[2] > 1:
        pcm = np.repeat(pcm[:, None], f[2], axis=1)
    return pygame.sndarray.make_sound(np.ascontiguousarray(pcm))


def _pan_vols(pan):
    pan = max(-1.0, min(1.0, pan))      # -1 چپ ... +1 راست (طرف مقابل کم میشه ولی صفر نه، مثل اتاق واقعی)
    return (1.0 if pan <= 0 else 1 - 0.9 * pan, 1.0 if pan >= 0 else 1 + 0.9 * pan)


def apply_pan(ch, pan):
    """pan: عدد ثابت، یا (از, تا, ثانیه) برای صدایی که تو اتاق حرکت میکنه (مثلا قدم‌ها از چپ به راست)"""
    if ch is None or pan is None:
        return
    try:
        if isinstance(pan, (tuple, list)):
            a, b, secs = pan

            def run():
                t0 = time.time()
                while ch.get_busy():
                    f = min(1.0, (time.time() - t0) / max(secs, 0.1))
                    ch.set_volume(*_pan_vols(a + (b - a) * f))
                    if f >= 1:
                        break
                    time.sleep(0.1)
            threading.Thread(target=run, daemon=True).start()
        else:
            ch.set_volume(*_pan_vols(pan))
    except Exception:
        pass


def play_pcm(x, vol=0.7, pan=None):
    snd = pcm_to_sound(x)
    if snd:
        snd.set_volume(vol)
        apply_pan(snd.play(), pan)


_SF_CACHE = [0.0, []]


def sound_files():
    """فایل‌های پوشه‌ی sounds (هر چقدر بخوای؛ هر ۲۰ ثانیه یه بار اسکن میشه، فایل جدید خودش اضافه میشه)"""
    if time.time() - _SF_CACHE[0] < 20:
        return _SF_CACHE[1]
    try:
        _SF_CACHE[1] = sorted(f for f in SOUNDS_DIR.glob("*") if f.suffix.lower() in EXTS)
    except OSError:
        _SF_CACHE[1] = []
    _SF_CACHE[0] = time.time()
    return _SF_CACHE[1]


_SOUND_RECENT = deque(maxlen=60)


def pick_sound(files=None):
    """یه صدا از پوشه‌ی sounds؛ تا چند صدای دیگه بینش نیومده تکرار نمیشه (مثل نوبت‌چرخشی تصادفی)"""
    files = list(files) if files is not None else sound_files()
    if not files:
        return None
    keep = min(len(files) - 1, 40)          # فایل زیاد: تا ۴۰ صدای آخر تکرار نمیشه
    recent = list(_SOUND_RECENT)[-keep:] if keep > 0 else []
    pool = [f for f in files if str(f) not in recent] or files
    f = random.choice(pool)
    _SOUND_RECENT.append(str(f))
    return f


FX_CACHE = BASE / ".fxcache"


def _fx_excerpt(path, secs):
    """pygame کل فایل رو تو رم باز میکنه؛ فایل بلند (مثلا ساعت‌ها ضبط تلویزیون) = Out of memory.
    پس با ffmpeg فقط یه تیکه‌ی تصادفی (secs ثانیه) ازش برمیداریم."""
    ff = ffmpeg_exe()
    if not ff:
        return None
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    FX_CACHE.mkdir(exist_ok=True)
    for old in sorted(FX_CACHE.glob("fx-*.wav"), key=os.path.getmtime)[:-3]:
        old.unlink(missing_ok=True)
    r = subprocess.run([ff, "-i", str(path)], capture_output=True, timeout=30, creationflags=flags)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr.decode(errors="ignore"))
    dur = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0
    ss = random.uniform(0, dur - secs) if dur > secs else 0
    out = FX_CACHE / f"fx-{int(time.time() * 1000)}.wav"
    r = subprocess.run([ff, "-y", "-loglevel", "error", "-ss", f"{ss:.1f}", "-t", str(secs), "-i", str(path), "-ac", "2", "-ar", "44100", str(out)],
                       capture_output=True, timeout=60, creationflags=flags)
    return out if r.returncode == 0 and out.exists() else None


def play_file(path, vol=0.8, maxsec=None, pan=None):
    """فایل بزرگ/بلند فقط به‌صورت یه تیکه‌ی کوتاه پخش میشه (جلوگیری از Out of memory)"""
    path = Path(path)
    maxsec = maxsec or 45
    try:
        if path.stat().st_size > 4 * 1024**2:
            ex = _fx_excerpt(path, int(maxsec))
            if ex is None:
                print("sound skipped (فایل بزرگه و ffmpeg نیست):", path.name)
                return
            path = ex
        snd = pygame.mixer.Sound(str(path))
        snd.set_volume(min(vol, AUTO_MAX[0]))
        apply_pan(snd.play(maxtime=int(maxsec * 1000), fade_ms=700), pan)
    except MemoryError:
        print("sound skipped (Out of memory):", path.name)


def tts(text):
    """متن رو با صدای سیستم (ویندوز) از اسپیکر خونه میخونه؛ موزیک موقع حرف زدن آروم میشه"""
    text = str(text).strip()[:300]
    if os.name != "nt" or not text:
        return False

    def run():
        global talkers
        with talk_lock:
            talkers += 1
            player.duck = 0.2
            player._apply(player.volume)
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command",
                            "Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak($env:TTS_TEXT)"],
                           env={**os.environ, "TTS_TEXT": text}, timeout=90, creationflags=0x08000000)
        except Exception as e:
            print("speak:", e)
        finally:
            with talk_lock:
                talkers -= 1
                if talkers == 0:
                    player.duck = 1.0
                    player._apply(player.volume)

    threading.Thread(target=run, daemon=True).start()
    return True


@app.post("/api/speak")
@auth
def speak():
    text = str(jbody().get("text", ""))
    if not tts(text):
        return jsonify(error="unsupported"), 400
    return jsonify(ok=True)


class Siren:
    def __init__(self):
        self.ch = None
        self.snd = None
        self.timer = None

    @property
    def on(self):
        return self.ch is not None and self.ch.get_busy()

    def start(self, seconds=None, boost=True):
        """boost=True: صدای ویندوز هم میره بالا (آژیر واقعی). boost=False: فقط یه صدای کوتاه."""
        if self.on:
            return
        if self.snd is None:
            self.snd = pcm_to_sound(reactions.whoop((pygame.mixer.get_init() or (44100,))[0], 2.0))
            if self.snd is None:
                raise RuntimeError("numpy/mixer not available")
        if boost and kb_c is not None:
            mark_synthetic()
            try:
                for _ in range(30):
                    kb_c.tap(Key.media_volume_up)
            except Exception:
                pass
        self.snd.set_volume(1.0 if boost else 0.7)
        self.ch = self.snd.play(loops=-1)
        if self.timer:
            self.timer.cancel()
        self.timer = threading.Timer(seconds or SIREN_SECONDS, self.stop)
        self.timer.daemon = True
        self.timer.start()

    def stop(self):
        if self.timer:
            self.timer.cancel()
            self.timer = None
        if self.ch is not None:
            self.ch.stop()
            self.ch = None


class Presence:
    """شبیه‌سازی حضور: تو بازه ساعتی، موزیک تصادفی روشن/خاموش میشه و وسطش هم گاهی آهنگ عوض میشه،
    صدا کم/زیاد میشه یا چند ثانیه قطع و وصل میشه؛ مثل آدمی که تو خونه‌ست."""

    def __init__(self):
        self.on, self.start, self.end = False, 17, 23
        self.away = False      # وقتی «بیرونم» فعاله شبیه‌سازی هر ساعتی کار میکنه
        self._last_fx = ""
        self.phase, self.next_t, self.next_act = "off", 0.0, 0.0
        self.scene, self.scene_end, self.last_scene, self._stage, self._hist, self._left = None, 0.0, None, 0, [], 0
        self.mind = mind_mod.HumanMind() if mind_mod else None      # مدل رفتار انسان (حال پنهان + زمان‌بندی دم‌بلند + ضد تکرار)
        self._quiet_until = 0.0                                       # وقتی موزیک رو «قطع کرده» تا این زمان خودش برنگرده
        self._next_amb = time.time() + (self.mind.gap(300, 1500) if self.mind else random.uniform(300, 900))
        threading.Thread(target=self._run, daemon=True).start()
        threading.Thread(target=self._song_watch, daemon=True).start()

    def configure(self, d):
        self.on = bool(d.get("on", self.on))
        self.start = num(d.get("start", self.start), self.start, 0, 23, int)
        self.end = num(d.get("end", self.end), self.end, 0, 24, int)
        if "away" in d:
            self.away = bool(d["away"])
        if not self.on:
            self.away = False
        if not self.on:
            player.prefer_artist = None
        if not self.on and self.phase == "on":
            player.stop()
        self.phase, self.next_t = "off", 0.0
        self.scene, self.scene_end = None, 0.0

    def _jitter(self):
        """هر روز ساعت شروع/پایان چند دقیقه جابجا میشه تا الگوی ثابت نداشته باشه"""
        d = datetime.date.today()
        if getattr(self, "_jd", None) != d:
            self._jd, self._js, self._je = d, random.uniform(-25, 25), random.uniform(-25, 25)
        return self._js, self._je

    def _in_window(self):
        n = datetime.datetime.now()
        m, (js, je) = n.hour * 60 + n.minute, self._jitter()
        if self.away:      # «بیرونم»: بدون محدودیت ساعت
            return True
        a, b = self.start * 60 + js, self.end * 60 + je
        return a <= m < b if self.start < self.end else (m >= a or m < b)

    def _cap(self):
        """شب دیر وقت صدا آروم‌تره (طبیعی‌تر و همسایه‌ها اذیت نمیشن)"""
        h = datetime.datetime.now().hour
        return min(AUTO_MAX[0], 0.35 if (h >= 23 or h < 7) else 0.65)

    def _effect(self, quiet=False):
        """یه صدای تو-خونه: اول از پوشه‌ی sounds (تلویزیون، سرفه، ظرف، ...)، وگرنه قدم/در"""
        vol = min(AUTO_MAX[0], random.uniform(0.2, 0.4) if quiet else random.uniform(0.3, 0.55))
        files = sound_files()
        if files and random.random() < min(0.85, 0.2 * len(files)):      # فایل کم: بیشتر صدای ساختگی (تکراری نشه)
            self._day()
            play_file(pick_sound(files), vol, maxsec=random.uniform(8, 40), pan=max(-1, min(1, self._kside + random.uniform(-0.2, 0.2))))
        elif np is not None:
            kind = "door" if self._last_fx == "steps" and random.random() < 0.8 else "steps" if self._last_fx == "door" and random.random() < 0.8 else random.choice(("steps", "door"))
            self._sfx(kind, vol)

    def _skip(self):
        """مثل آدمی که آهنگ رو رد میکنه؛ گاهی دوتا پشت هم تا یکی خوشش بیاد"""
        player.fade_then(player.next)
        if random.random() < 0.1:
            time.sleep(random.uniform(5, 14))
            if self.phase == "on" and player.playing:
                player.fade_then(player.next)

    # ---------- شبیه‌ساز انسان: «صحنه»‌های روزمره با برنامه‌ی واقعی (بیدار شدن، آشپزخونه، تلویزیون، خواب، ...) ----------
    PERIODS = {                                    # موزیک همیشه هست (سکوت نداریم)؛ شب و نزدیک خواب فقط آروم‌تره
        "night":   {"music": 90, "walk": 10},
        "morning": {"music": 35, "kitchen": 30, "walk": 12, "tv": 8, "chores": 10, "phone": 5},
        "day":     {"music": 38, "kitchen": 12, "walk": 8, "tv": 17, "chores": 15, "phone": 10},
        "evening": {"music": 36, "tv": 28, "kitchen": 10, "walk": 6, "chores": 8, "phone": 12},
        "late":    {"music": 60, "tv": 20, "walk": 10, "phone": 10},
    }
    SCENE_MIN = {"music": (12, 45), "tv": (15, 50), "kitchen": (4, 12), "walk": (1, 3), "chores": (5, 15), "phone": (1, 4)}   # مدت هر صحنه (دقیقه)

    @staticmethod
    def _h(lo, hi):
        """زمان انسانی: بیشتر کوتاه، گاهی خیلی بلند (نه یکنواخت)"""
        return random.triangular(lo, hi, lo + (hi - lo) * 0.3)

    KINDS = {                                       # «تیپ» روز؛ هر روز تصادفی انتخاب میشه (به روز هفته بسته نیست)
        "homebody": {"music": 1.3, "tv": 1.5},
        "busy":     {"kitchen": 1.6, "chores": 1.8, "walk": 1.5, "phone": 1.3},
        "lazy":     {"music": 1.2, "tv": 1.3, "walk": 0.5, "chores": 0.4},
        "social":   {"phone": 2.0, "music": 1.2, "walk": 1.3},
        "mixed":    {},
    }

    def _day(self):
        """هر روز برنامه‌ی کاملا تصادفی خودش رو داره: ساعت بیدار شدن/خواب، مرز صبح/روز/عصر، تیپ روز، ریتم و حال صدا؛
        هیچ الگوی ثابتی (نه ساعتی، نه روز هفته) نیست. حال‌وهوا هم وسط روز هر ۱ تا ۴ ساعت دوباره قرعه‌کشی میشه."""
        d, now = datetime.date.today(), time.time()
        if getattr(self, "_dd", None) != d:
            self._dd = d
            late = 1.5 if (d.weekday() == 4 and random.random() < 0.6) else 0.0         # جمعه معمولا (نه همیشه) دیرتر
            self._wake = random.uniform(6.3, 8.8) + late + random.choice((0, 0, random.uniform(0, 1.2)))
            self._bed = random.uniform(22.4, 25.2)
            self._mend = random.uniform(2.3, 4.8)          # صبح چند ساعت بعد از بیدار شدن تموم میشه
            self._dend = random.uniform(15.6, 18.8)        # ساعت شروع «عصر»
            self._kind = random.choices(list(self.KINDS), (22, 22, 14, 14, 28))[0]
            self._lend = random.uniform(1.0, 2.0)          # «نزدیک خواب» چند ساعت قبل از خواب شروع میشه
            self._pace = random.uniform(0.6, 1.5)
            self._vmul = random.uniform(0.78, 1.18)
            self._kside = random.choice((-1, 1)) * random.uniform(0.5, 0.9)
            self._tvside = random.choice((-1, 1)) * random.uniform(0.3, 0.7)
            self._mood_until = 0.0
            print("presence day:", self._kind)
        if now >= getattr(self, "_mood_until", 0.0):
            self._mood = random.choice(("chatty", "calm", "calm", "busy"))
            self._mood_until = now + random.uniform(3600, 14400)
        return self._wake, self._bed, self._mood

    def _period(self):
        n = datetime.datetime.now()
        h, (wake, bed, _) = n.hour + n.minute / 60, self._day()
        asleep = (bed - 24 <= h < wake) if bed >= 24 else (h >= bed or h < wake)
        if asleep:
            return "night"
        if h < wake + self._mend:
            return "morning"
        if h < self._dend:
            return "day"
        return "evening" if h < min(bed, 24) - self._lend else "late"

    def _sfx(self, kind, vol):
        """steps | door | knock (کمد/کشو) | notify (نوتیفیکیشن گوشی)"""
        if np is None:
            return False
        sr = (pygame.mixer.get_init() or (44100,))[0]
        vol *= random.uniform(0.85, 1.15)
        if kind == "steps":      # آدم از یه طرف اتاق به طرف دیگه راه میره
            a = random.choice((-1, 1)) * random.uniform(0.5, 0.9)
            pan = (a, -a * random.uniform(0.3, 1.0), random.uniform(3, 7))
            pcm = reactions.footsteps(sr, random.randint(3, 10))
        else:
            pan = random.choice((-1, 1)) * random.uniform(0.4, 0.9)
            pcm = {"door": reactions.door_close, "knock": lambda x: reactions.knock(x, random.choice((1, 1, 2))),
                   "notify": reactions.notify}.get(kind, reactions.door_close)(sr)
        play_pcm(pcm, vol, pan=pan)
        self._last_fx = kind
        return True

    def _surprise(self):
        """اتفاق کوچیک و تصادفی: نوتیفیکیشن گوشی، کشو/کمد، قدم، در، یا دستش میره رو ریموت و صدا یه کم بالا/پایین میشه"""
        k = random.choices(("notify", "knock", "steps", "door", "vol"), (22, 26, 20, 12, 20))[0]
        if k == "vol":
            if player.playing and not player.paused:
                player.ramp(min(self._cap(), max(0.2, player.volume * random.choice((0.7, 0.8, 1.2, 1.3)))), random.uniform(1.5, 4))
        else:
            self._sfx(k, random.uniform(0.15, 0.3) if k in ("notify", "knock") else random.uniform(0.2, 0.35))

    def _next_scene(self):
        per = self._period()
        w = dict(self.PERIODS[per])
        mood = self._day()[2]
        for k, m in self.KINDS[self._kind].items():
            if k in w:
                w[k] *= m
        for k in list(w):
            if k in ("music", "tv"):
                w[k] *= 1.4 if mood == "chatty" else 0.8 if mood == "calm" else 1.0
            if k in ("kitchen", "walk") and mood == "busy":
                w[k] *= 1.4
        if not player.tracks:
            w.pop("music", None)
        nf = len(sound_files())
        if nf == 0:                                        # بدون فایل صدا: صحنه‌هایی که فقط صدای ساختگی دارن کم‌تر
            for k in ("kitchen", "walk", "chores", "phone"):
                if k in w:
                    w[k] *= 0.35
        if nf == 0:
            w.pop("tv", None)
        elif "tv" in w:
            w["tv"] *= min(1.0, nf / 6)                    # فایل کم: تلویزیون کمتر (تکراری نشه)
        if self.last_scene in w and len(w) > 1:
            w[self.last_scene] = 0.0                      # دوبار پشت هم یه کار رو نکن
        keys = list(w)
        return random.choices(keys, [w[k] for k in keys])[0] if keys else "walk"

    def _music_on(self, soft=True):
        """موزیک پایه همیشه پخشه؛ اگه نبود نرم شروع میشه (شب خیلی آروم‌تر)"""
        if self.phase == "on" or not player.tracks:
            return
        if time.time() < self._quiet_until:                                  # موزیک رو عمدا قطع کرده؛ هنوز وقتش نشده
            return
        if self._period() != "night" and np is not None and soft:
            self._sfx("steps", random.uniform(0.2, 0.35))                   # اول میاد تو اتاق، بعد موزیک
            time.sleep(random.uniform(4, 9))
        if not self.on:
            return
        mood = self._day()[2]
        self._day()
        vol = random.uniform(0.35, 0.6) * (0.85 if mood == "calm" else 1.0) * self._vmul
        if self._period() == "night":
            vol = random.uniform(0.18, 0.28)
        player.shuffle = True
        player.start_soft(min(self._cap(), vol))
        self.phase = "on"

    def _end_scene(self, nxt=None):
        if self.scene == "tv" and nxt != "tv":
            pass                                                           # صدای تلویزیون خودش تموم میشه؛ موزیک نرم برمیگرده
        if self.scene == "phone" and getattr(self, "_v0", None):
            player.ramp(min(self._cap(), self._v0), random.uniform(3, 6))      # تلفن تموم: صدا نرم برمیگرده
            self._v0 = None
        if nxt == "tv" and self.phase == "on":
            player.fade_then(player.stop, out=3.0, inn=0.1)                # موزیک کم میشه و تلویزیون میاد
            self.phase = "off"
        self.last_scene = self.scene

    def _begin(self, scene):
        now = time.time()
        lo, hi = self.SCENE_MIN[scene]
        self.scene, self._stage = scene, 0
        self.scene_end = now + self._h(lo, hi) * 60 * (min(1.0, 0.4 + 0.1 * len(sound_files())) if scene == "tv" else 1.0)
        self.next_act = now + random.uniform(8, 30)
        if scene == "tv":
            self.next_act = now + 1
        elif scene == "walk":
            self._music_on()
            self.next_act = now + random.uniform(3, 10)
        else:
            self._music_on()
            if scene in ("kitchen", "chores"):
                self.next_act = now + random.uniform(3, 10)
            elif scene == "phone" and player.playing:       # تلفن: موزیک نرم کم میشه (قطع نمیشه)
                self._v0 = player.volume
                player.ramp(max(0.12, player.volume * 0.35), 4)
                self.next_act = now + random.uniform(20, 60)
        print("presence scene:", scene, "(" + self._period() + ")")

    def _track(self):
        idx = player.index
        if idx is not None and (not self._hist or self._hist[-1] != idx):
            self._hist.append(idx)
            del self._hist[:-8]
            self._left -= 1
            if self._left <= 0:                       # حال‌وهوای جدید: چند آهنگ از یه خواننده، یا هر چی شد
                cnt = collections.Counter(t.get("artist") for t in player.tracks if t.get("artist") and str(t.get("artist")).lower() not in ("unknown", "نامشخص", "unknown artist"))
                arts = [a for a, c in cnt.items() if c >= 3]
                player.prefer_artist = random.choice(arts) if arts and random.random() < 0.7 else None
                self._left = random.randint(3, 7)
                print("presence taste:", player.prefer_artist)
        try:
            dur = float(player.tracks[idx]["duration"] or 0) if idx is not None else 0.0
        except Exception:
            dur = 0.0
        return dur, player.position()

    def _back(self):
        """برگشت به آهنگ قبلی (مثل آدمی که پشیمون شده)"""
        if len(self._hist) >= 2 and player.playing:
            prev = self._hist[-2]
            player.fade_then(lambda: player.play(prev))

    def _keeper(self, idx):
        """حدود نصف آهنگ‌ها «دوست‌داشتنی» حساب میشن (هر اجرا قرعه‌کشی جدا) و رد نمیشن"""
        if idx is None:
            return False
        k = self.__dict__.setdefault("_keep", {})
        if idx not in k:
            k[idx] = random.random() < 0.5
        return k[idx]

    def _song_watch(self):
        """با شروع هر آهنگ تصمیم میگیره رد بشه یا نه (مثل داده‌ی واقعی شنونده‌ها: بیشتر رد کردن‌ها تو ۵ تا ۳۰ ثانیه‌ی اول،
        بعدش نرخ کم و ثابت). آهنگ‌های «دوست‌داشتنی» هیچ‌وقت رد نمیشن."""
        seen = None
        while True:
            time.sleep(0.5)
            try:
                if not (self.on and self.phase == "on" and player.playing and not player.paused):
                    continue
                key = (player.index, player.t_start)
                if key == seen:
                    continue
                seen = key
                if player.offset or not self.mind:               # پرش وسط آهنگ (seek) آهنگ جدید حساب نمیشه
                    continue
                t = self.mind.skip_plan(self._keeper(player.index), calm=self._period() == "night")
                if t is not None:
                    threading.Timer(t, self._plan_skip, args=(key,)).start()
            except Exception as e:
                print("song watch:", e)

    def _plan_skip(self, key):
        if (player.index, player.t_start) != key or not self.on or self.phase != "on" or not player.playing or player.paused:
            return
        if self.scene in ("phone", "tv"):
            return
        if player.position() < 30:                               # رد کردن سریع = خوشش نیومده؛ تا مدتی تو شافل نمیاد
            player.dislike[player.index] = time.time() + random.uniform(40 * 60, 3 * 3600)
        self.mind.recent.append((time.time(), "skip"))
        print("presence act: skip@%ds" % player.position())
        self._skip()

    def _skip_early(self):
        """چند ثانیه اول آهنگ رو گوش داده و خوشش نیومده؛ رد میکنه (آهنگ تا مدتی تو شافل پیشنهاد نمیشه)"""
        if not self.mind or not self.mind.early_skip_wanted(player.position()):
            return
        idx = player.index
        if idx is not None:
            player.dislike[idx] = time.time() + random.uniform(40 * 60, 3 * 3600)
        self._skip()

    def _jump(self):
        """وسط آهنگ میپره جلو (دنبال قسمت مورد علاقه‌ش)"""
        dur, pos = self._track()
        tgt = self.mind.jump_target(dur, pos) if self.mind else None
        if tgt and player.playing and not player.paused:
            player.fade_then(lambda: player.seek(tgt), out=0.4, inn=1.2)

    def _bump(self):
        """یه تغییر صدای بزرگ‌تر (مثلا قسمت خوب آهنگ یا صحبت کردن)، بعد از مدتی نرم برمیگرده"""
        if not (player.playing and not player.paused):
            return
        v0 = player.volume
        v1 = self.mind.vol_step(self._cap(), v0) if self.mind else min(self._cap(), v0 + 0.12)
        if abs(v1 - v0) < 0.04 or not player.ramp(v1, random.uniform(1.5, 4), wait=True):
            return
        time.sleep(random.uniform(20, 120))
        if abs(player.volume - v1) < 0.02:                                  # اگه کاربر بینش دستی عوضش نکرده
            player.ramp(min(self._cap(), max(0.2, v0 + random.uniform(-0.05, 0.05))), random.uniform(3, 6), wait=True)

    def _stop_a_while(self):
        """مثل آدمی که موزیک رو کامل قطع میکنه (تلفن، تلویزیون، خواب‌آلودگی)؛ چند دقیقه سکوت، بعد خودش دوباره میذاره"""
        if not (player.playing and self.phase == "on"):
            return
        q = self.mind.quiet_for() if self.mind else random.uniform(120, 600)
        self._quiet_until = time.time() + q
        print("presence: music stopped for %d s" % q)
        player.fade_then(player.stop, out=random.uniform(1.0, 3.0), inn=0.1)
        self.phase = "off"

    def _ambient(self):
        """یه صدای مستقل از موزیک و صحنه (از پوشه‌ی sounds): گاهی کوتاه (نصفه)، گاهی بلندتر، از یه طرف"""
        files = sound_files()
        if not files:
            return
        h = datetime.datetime.now().hour
        vol = random.uniform(0.15, 0.32) if (h >= 23 or h < 7) else random.uniform(0.2, 0.5)
        play_file(pick_sound(files), min(AUTO_MAX[0], vol), maxsec=random.choice((random.uniform(3, 9), random.uniform(8, 40))),
                  pan=random.uniform(-0.9, 0.9))

    def _replay(self):
        """آهنگ که خوشش اومده؛ از اول"""
        if player.playing:
            player.fade_then(lambda: player.seek(0), out=1.5, inn=2.0)

    def _tick(self):
        now, sc = time.time(), self.scene
        if sc == "tv":                                                     # تلویزیون پیوسته: فایل بعدی درست قبل از تموم شدن قبلی
            files = sound_files()
            if files:
                secs = random.uniform(40, 120)
                self._day()
                play_file(pick_sound(files), min(AUTO_MAX[0], random.uniform(0.25, 0.45)), maxsec=secs, pan=self._tvside)
                self.next_act = now + secs - random.uniform(1, 3)
            else:
                self.next_act = now + 30
            return
        if sc == "walk":
            if self._stage == 0:
                self._sfx("steps", random.uniform(0.2, 0.35))
                self._stage, self.next_act = 1, now + random.uniform(4, 9)
            else:
                self._sfx("door", random.uniform(0.2, 0.35))
                self.scene_end = now                                       # صحنه تموم
            return
        if self.phase == "on" and not player.playing:
            self.phase = "off"
        if sc == "phone":                                                  # وسط تلفن: فقط ریزه‌کاری، نه کار بزرگ
            if random.random() < 0.5:
                self._sfx(random.choice(("steps", "knock", "notify")), random.uniform(0.15, 0.3))
            self.next_act = now + self._h(25, 80)
            return
        self._music_on(soft=False)                                         # موزیک افتاده بود؟ برگردونش (سکوت نمیخوایم)
        dur, pos = self._track()
        frac = pos / dur if dur > 30 else 0.5
        fx = 1.0 if sound_files() else 0.35                                # بدون فایل صدا: صدای ساختگی خیلی کم‌تر
        base = {"nudge": 30, "idle": 45 + (1 - fx) * 40, "back": 1,
                "surprise": (10 if sc != "chores" else 30) * fx,
                "effect": (30 if sc in ("kitchen", "chores") else 7) * fx}
        if player.playing and not player.paused:
            base.update(pause=4, bump=6)
            if self.phase == "on" and sc in ("music", "kitchen", "chores", "walk"):
                base["stop"] = 1.1
            keeper = self._keeper(player.index)                            # آهنگ مورد علاقه: هیچ‌وقت رد نمیشه، تا آخر پخش میشه
            if pos > 45 and not keeper:
                base["skip"] = 2 if 0.35 < frac < 0.92 else 0.5      # رد کردن وسط آهنگ کمه؛ بیشترش اوایل آهنگ (_song_watch)
            
            if frac > 0.7:
                base["replay"] = 2
            if dur > 90 and 0.08 < frac < 0.6:
                base["seek"] = 3
        else:                                                              # موزیک خاموشه (عمدا قطع شده): فقط صدای خونه
            base = {"idle": 40, "surprise": 12 * fx, "effect": 18 * fx}
        acts = {"nudge": self._nudge, "idle": lambda: None, "back": self._back, "surprise": self._surprise,
                "effect": lambda: self._effect(quiet=True), "pause": self._pause, "bump": self._bump, "stop": self._stop_a_while,
                "skip": self._skip, "replay": self._replay, "seek": self._jump}
        name = self.mind.choose(base, now) if self.mind else random.choices(list(base), list(base.values()))[0]
        if name:
            print("presence act:", name)
            threading.Thread(target=acts[name], daemon=True).start()      # کار طولانی (مثل _bump) تیک بعدی رو معطل نکنه
        self._day()
        gap = self.mind.gap(20, 70, now) if self.mind else self._h(20, 70)
        self.next_act = now + gap * (self._pace if sc != "chores" else min(self._pace, 0.7)) * (1.0 if fx == 1.0 else 1.3)

    def _nudge(self):
        if player.playing and not player.paused:
            step = random.choice([-1, 1]) * random.uniform(0.04, 0.15)
            player.ramp(min(self._cap(), max(0.2, player.volume + step)), random.uniform(2.5, 5))

    def _pause(self):
        if player.playing and not player.paused:
            player.soft_pause(random.uniform(8, 40))       # مثلا جواب دادن به تلفن

    def _run(self):
        while True:
            time.sleep(5)
            try:
                now = time.time()
                if not self.on or not self._in_window():
                    if self.phase == "on":
                        player.fade_then(player.stop, out=2.5, inn=0.1)
                        self.phase = "off"
                    self.scene = None
                    player.prefer_artist = None
                    continue
                if self.scene is None or now >= self.scene_end:
                    self.last_scene = self.scene
                    nxt = self._next_scene()
                    if self.scene is not None:
                        self._end_scene(nxt)
                    self._begin(nxt)
                elif now >= self.next_act:
                    self._tick()
                if now >= self._next_amb:                       # صدای مستقل از پوشه‌ی sounds، با فاصله‌ی دم‌بلند (نه ثابت)
                    self._next_amb = now + (self.mind.gap(480, 2700, now) if self.mind else random.uniform(600, 1500))
                    if self.scene not in (None, "tv") and sound_files():
                        threading.Thread(target=self._ambient, daemon=True).start()
            except Exception as e:
                print("presence:", e)


_FFMPEG = []


def ffmpeg_exe():
    if not _FFMPEG:
        try:
            import imageio_ffmpeg
            _FFMPEG.append(imageio_ffmpeg.get_ffmpeg_exe())
        except Exception:
            _FFMPEG.append(shutil.which("ffmpeg"))
    return _FFMPEG[0]


def pc_locked():
    """ویندوز قفله؟ (وقتی قفله، دسکتاپ و کیبورد از راه دور کار نمیکنن؛ محدودیت خود ویندوزه)"""
    if os.name != "nt":
        return False
    try:
        import ctypes
        u = ctypes.windll.user32
        h = u.OpenInputDesktop(0, False, 0x0100)
        if not h:
            return True
        u.CloseDesktop(h)
        return False
    except Exception:
        return False


def _keep_awake():
    """تا برنامه بازه ویندوز نخوابه و صفحه خاموش نشه (جلوی قفل شدن بعد از بیکاری/اسکرین‌سیور)"""
    if os.name != "nt" or os.environ.get("KEEP_AWAKE", "1") == "0":
        return
    import ctypes
    while True:
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001 | 0x00000002)
        except Exception:
            return
        time.sleep(30)


class AudioTap:
    """صدای میکروفون رو وقتی مسلحی تو یه بافر چند ثانیه‌ای نگه میداره تا ویدیوها صدا داشته باشن (از قبل رویداد هم)."""
    SR = 16000

    def __init__(self):
        self.ring = deque(maxlen=100)    # ۱۰۰ بلوک ۰.۱ ثانیه‌ای = ۱۰ ثانیه
        self.stream = None
        self.sink = None
        self.err, self.sr, self.name, self._last_try, self.last_cb = "", 16000, "", 0.0, 0.0

    def start(self, force=False):
        """اول میکروفون پیش‌فرض ویندوز (دقیقا همونی که بخش «گوش دادن» باهاش کار میکنه)، بعد بقیه‌ی میکروفون‌ها و نرخ‌ها"""
        if sd is None or np is None:
            self.err = "sounddevice نصب نیست"
            return
        if self.stream is not None or (not force and time.time() - self._last_try < 15):
            return
        self._last_try = time.time()
        cands = []                       # [(device, info)]
        try:
            cands.append((None, sd.query_devices(None, "input")))
        except Exception:
            pass
        try:
            d = sd.default.device
            di = d[0] if isinstance(d, (list, tuple)) else d
            for i, dv in enumerate(sd.query_devices()):
                if dv["max_input_channels"] > 0 and not (di is not None and int(di) == i and cands):
                    cands.append((i, dv))
        except Exception as e:
            self.err = str(e)
        if not cands:
            msg = "هیچ میکروفونی پیدا نشد (وصل نیست، ویندوز غیرفعالش کرده، یا با ریموت دسکتاپ دستگاه‌های صوتی عوض شدن)"
            if msg != self.err:
                print("[audio]", msg, "-> ویدیوها بدون صدا میشن")
            self.err = msg
            return
        last = self.err
        for dev, info in cands[:6]:
            try:
                dsr, name = int(info["default_samplerate"]), str(info["name"])
            except Exception:
                dsr, name = 44100, "?"
            for sr in dict.fromkeys([16000, dsr, 44100, 48000]):
                try:
                    st = sd.InputStream(device=dev, channels=1, samplerate=sr, dtype="int16", blocksize=max(int(sr / 10), 160), callback=self._cb)
                    st.start()
                    self.stream, self.sr, self.name, self.err, self.last_cb = st, sr, name, "", time.time()
                    self.ring = deque(maxlen=100)
                    print(f"[audio] میکروفون: {name} ({sr} Hz)")
                    return
                except Exception as e:
                    last = str(e)
        if (last or "") != self.err:
            print("[audio] میکروفون باز نشد، ویدیوها بدون صدا میشن:", last)
        self.err = last or "هیچ میکروفونی پیدا نشد"

    def stop(self):
        st, self.stream = self.stream, None
        if st is not None:
            try:
                st.stop()
                st.close()
            except Exception:
                pass
        self.ring.clear()

    def _cb(self, data, frames, t, status):
        self.last_cb = time.time()
        blk = data[:, 0].copy()
        self.ring.append((time.time(), blk))
        if self.sink is not None:
            self.sink.append(blk)

    def check(self):
        """میکروفون نیست یا جریانش قطع شده (مثلا با ریموت دسکتاپ/AnyDesk دستگاه‌های صوتی ویندوز عوض شدن) -> دوباره وصل شو"""
        if self.stream is None:
            self.start()
        elif time.time() - self.last_cb > 10:
            print("[audio] جریان میکروفون قطع شد (دستگاه صوتی عوض شد؟)؛ دوباره وصل میشم")
            self.stop()
            self._last_try = 0.0
            self.start()

    def grab_pre(self, secs):
        cut = time.time() - secs
        blks = [b for t, b in list(self.ring) if t >= cut]
        return np.concatenate(blks) if blks else None

    def begin(self):
        self.sink = []

    def end(self):
        blks, self.sink = self.sink, None
        return np.concatenate(blks) if blks else None


audio_tap = AudioTap()


class Security:
    AUTOS = ("none", "music", "sounds", "smart")   # smart = تشدید تدریجی: زنگ در و صدا -> موزیک و هشدار -> صدا افکت (آژیر فقط دستیه)

    def __init__(self):
        self.armed = False
        self.auto = "smart"
        self.sens = 1000    # حداقل مساحت حرکت (کمتر = حساس‌تر)
        self.prev = None
        self.last_event = 0.0
        self.warm = 0
        self.cam_alerted = False
        self.dark_since, self.dark_alerted = 0.0, False
        self.armed_at = 0.0
        # pcwatch: هشدار وقتی کسی پشت کامپیوتر میشینه | noise: صدای بلند | lock: قفل ویندوز | person_only: فقط وقتی آدم دیده شد اعلان بده
        self.recording = False
        self.opts = {"pcwatch": True, "noise": False, "lock": False, "person_only": False, "video": True, "human_only": True, "boxes": True}
        self.gate = None
        self.gate_broken = False
        self.gate_err = ""
        threading.Thread(target=self._watchdog, daemon=True).start()

    def _watchdog(self):
        while True:
            time.sleep(30)
            try:
                if self.armed and time.time() - camera.last_ok > 90:
                    if not self.cam_alerted:
                        self.cam_alerted = True
                        notify("Warning: camera is not delivering frames", True)
                else:
                    self.cam_alerted = False
            except Exception:
                pass

    def arm(self, on):
        changed = False
        if on and not self.armed:
            self.prev = None
            self.warm = 40
            camera.last_ok = time.time()
            self.armed_at = time.time()
            self.armed = True
            camera_hold("security", True)
            audio_tap.start()
            changed = True
        elif not on and self.armed:
            self.armed = False
            camera_hold("security", False)
            audio_tap.stop()
            changed = True
        noisewatch.sync()
        if changed:
            self._nvr_on_arm(on)

    def _nvr_on_arm(self, on):
        """مسلح شدن (از هر راهی: دکمه، تلگرام، بیرونم) = وصل شدن به NVR و تشخیص آدم رو همه‌ی کانال‌ها؛ با باز کردن قفل (disarm) خاموش میشه
        (فقط اگه خودِ مسلح شدن روشنش کرده باشه و «بیرونم» فعال نباشه). خاموش کردن: set NVR_WITH_ARM=0"""
        if os.environ.get("NVR_WITH_ARM", "1") != "1":
            return
        try:
            if on:
                if not nvr.enabled() or cv2 is None:
                    return
                if not nvrwatch.on:
                    self._nvr_by_arm = bool(nvrwatch.set(True))
                threading.Thread(target=self._nvr_check, args=(self.armed_at,), daemon=True).start()
            else:
                if getattr(self, "_nvr_by_arm", False) and not presence.away:
                    nvrwatch.set(False)
                self._nvr_by_arm = False
        except Exception as e:
            print("arm nvr:", e)

    def _nvr_check(self, armed_at):
        """بعد از مسلح شدن ۳۰ ثانیه فرصت میده NVR وصل بشه؛ کانالی وصل نشد یعنی «مسلحم ولی NVR نمیبینه» و همون لحظه خبر میده"""
        deadline = time.time() + 30
        bad = []
        while time.time() < deadline:
            if not self.armed or self.armed_at != armed_at:
                return
            bad = [(ch, f) for ch, f in nvr_feeds.items() if f.state != "ok"]
            if not bad:
                print("arm: NVR connected, watching for people on all channels")
                return
            time.sleep(2)
        if self.armed and self.armed_at == armed_at and bad:
            notify("Armed, but NVR is not connected: " + "; ".join("ch%s %s %s" % (ch, f.state, (f.err or "")[:50]) for ch, f in bad), True)

    def lock_pc(self):
        if os.name == "nt" and self.opts["lock"]:
            try:
                subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"], creationflags=0x08000000)
            except Exception as e:
                print("lock:", e)

    def analyze(self, img):
        small = cv2.resize(img, (320, max(int(img.shape[0] * 320 / img.shape[1]), 1)))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        now = time.time()
        if self.armed:      # دوربین پوشونده شده / خیلی تاریک
            if gray.mean() < 5:
                self.dark_since = self.dark_since or now
                if now - self.dark_since > 60 and not self.dark_alerted:
                    self.dark_alerted = True
                    notify("Warning: camera sees nothing (covered or dark)")
            else:
                self.dark_since, self.dark_alerted = 0.0, False
        if self.opts.get("human_only", True) and human_mod is not None and not self.gate_broken:
            try:
                self._analyze_human(img, now)
                return
            except Exception as e:      # تشخیص آدم خراب شد: به حالت قدیمی (حرکت) برگرد، دوربین قطع نشه
                self.gate_broken = True
                self.gate_err = repr(e)[:150]
                print("human gate failed, falling back to plain motion:", repr(e))
        g = cv2.GaussianBlur(gray, (21, 21), 0)
        if self.prev is None or self.prev.shape != g.shape:
            self.prev = g.astype("float32")
            return
        diff = cv2.absdiff(g, cv2.convertScaleAbs(self.prev))
        cv2.accumulateWeighted(g, self.prev, 0.05)
        if self.warm > 0:  # چند فریم اول (تنظیم نور دوربین) نادیده گرفته میشه
            self.warm -= 1
            return
        th = cv2.dilate(cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)[1], None, iterations=2)
        cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        area = sum(cv2.contourArea(c) for c in cnts)
        if area > 0.5 * th.shape[0] * th.shape[1]:   # عوض شدن ناگهانی نور، نه حرکت
            self.prev = g.astype("float32")
            return
        if area <= self.sens:
            return
        if self.armed and now - self.last_event > 20:
            self.trigger(img, "motion")
        if reactor.on:
            reactor.sighting(img)

    def overlay(self, img):
        """کادر روی پخش زنده: خاکستری = حرکت، سبز = آدم تایید شد، زرد = آدمِ احتمالی (هنوز تایید نشده)"""
        g = self.gate
        if not self.opts.get("boxes", True) or not self.opts.get("human_only", True):
            return None
        if self.gate_broken:      # دلیل خراب بودن تشخیص آدم رو روی خود تصویر نشون بده
            out = img.copy()
            cv2.putText(out, "PERSON DETECTOR OFF - plain motion mode", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2, cv2.LINE_AA)
            cv2.putText(out, self.gate_err.encode("ascii", "ignore").decode()[:70], (8, 44), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1, cv2.LINE_AA)
            return out
        if g is None:
            return None
        out = img.copy()
        now = time.time()
        sc = img.shape[1] / g.W
        font = cv2.FONT_HERSHEY_SIMPLEX
        for (x, y, w, h) in list(g.motion_boxes):
            cv2.rectangle(out, (int(x * sc), int(y * sc)), (int((x + w) * sc), int((y + h) * sc)), (0, 165, 255), 1)
        human = g.human_now
        for d in list(g.people):
            if now - d["t"] > g.SHOW:
                continue
            x, y, w, h = d["box"]
            col, label = ((0, 220, 0), "PERSON") if human else ((0, 230, 255), "person?")
            cv2.rectangle(out, (x, y), (x + w, y + h), col, 3)
            cv2.putText(out, "%s %.0f%%" % (label, min(d.get("score", 0), 1.5) * 100), (x, max(16, y - 6)), font, 0.6, col, 2, cv2.LINE_AA)
        if human:
            txt, col = "HUMAN DETECTED", (0, 220, 0)
        else:
            txt, col = "watching (%s)%s" % (human_mod.detector_name(), " - motion" if g.motion_boxes else ""), (210, 210, 210)
        cv2.putText(out, txt, (8, 20), font, 0.6, col, 1, cv2.LINE_AA)
        seen = "never" if not g.last_person else "%ds ago" % (now - g.last_person)
        cv2.putText(out, "orange=motion | detector %.0fms | person seen: %s" % (g.det_ms, seen), (8, 40), font, 0.45, (210, 210, 210), 1, cv2.LINE_AA)
        return out

    def watch(self, img):
        """فقط برای نمایش کادر وقتی کسی پخش زنده رو میبینه (بدون مسلح بودن): هیچ واکنش/عکسی ایجاد نمیکنه"""
        if human_mod is None or self.gate_broken or not self.opts.get("human_only", True):
            return
        try:
            if self.gate is None:
                self.gate = human_mod.HumanGate(self.sens)
            self.gate.sens = self.sens
            self.gate.update(img)
            if self.gate.fail >= 8:
                raise RuntimeError("detector failing: " + (self.gate.err or "?"))
        except Exception as e:
            self.gate_broken = True
            self.gate_err = repr(e)[:150]
            print("human gate failed (watch):", repr(e))

    def _analyze_human(self, img, now):
        """فقط آدم: حرکت برگ/باد/باران/حیوون/سایه هیچ واکنشی نداره"""
        if self.gate is None:
            self.gate = human_mod.HumanGate(self.sens)
        self.gate.sens = self.sens
        st = self.gate.update(img, now)
        if self.gate.fail >= 8:
            raise RuntimeError("detector failing: " + (self.gate.err or "?"))
        if st != "human":
            return
        if self.armed and now - self.last_event > 20:
            self.trigger(img, "motion", person=True)
        if reactor.on:
            reactor.sighting(img, human=True)

    def _save_frame(self, img, person):
        CAP_DIR.mkdir(exist_ok=True)
        path = CAP_DIR / (datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + ("-p" if person else "") + ".jpg")
        if img.mean() < 70:    # شب/تاریک: عکس رو روشن‌تر کن تا چیزی دیده بشه
            lut = (np.arange(256) / 255.0) ** 0.5 * 255
            img = cv2.LUT(img, lut.astype("uint8"))
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            return None
        path.write_bytes(buf.tobytes())
        prune_captures(protect=path)
        return path

    def _burst(self, img, person, reason="motion", quiet=False):
        """سه عکس پشت سر هم (اولی فوری)؛ فقط اولی روی پیام‌رسان فرستاده میشه"""
        try:
            first = self._save_frame(img, person)
            if first and not quiet:
                send_alert(first, person, reason)
            for _ in range(2):
                time.sleep(1.0)
                f = camera.raw
                if f is not None:
                    self._save_frame(f.copy(), person)
        except Exception as e:
            print("capture:", e)

    def _open_writer(self, base, fps, size):
        """H.264 اگه بشه (تو مرورگر گوشی پخش میشه)، وگرنه mp4v، وگرنه avi"""
        for fcc, ext in (("mp4v", ".mp4"), ("avc1", ".mp4"), ("MJPG", ".avi")):   # بعدش ffmpeg به H.264 تبدیلش میکنه
            path = base.with_suffix(ext)
            w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*fcc), fps, size)
            if w.isOpened():
                return w, path
            w.release()
        return None, None

    def _add_audio(self, path, pre, post):
        """با ffmpeg ویدیو رو H.264 میکنه (تو مرورگر گوشی پخش میشه) و اگه صدا داریم میچسبونه"""
        wav = None
        try:
            ff = ffmpeg_exe()
            if path.suffix != ".mp4" or not ff:
                if not ff:
                    print("video: ffmpeg نیست؛ ویدیو بدون صدا ذخیره شد (pip install imageio-ffmpeg)")
                return path
            parts = [a for a in (pre, post) if a is not None and len(a)] if np is not None else []
            out = path.with_name(path.stem + "-a.mp4")
            if parts:
                wav = path.with_suffix(".wav")
                with wave.open(str(wav), "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(audio_tap.sr)
                    wf.writeframes(np.concatenate(parts).astype(np.int16).tobytes())
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            for vcodec in (["-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p"], ["-c:v", "copy"]):
                cmd = [ff, "-y", "-loglevel", "error", "-i", str(path)]
                cmd += ["-i", str(wav), "-map", "0:v:0", "-map", "1:a:0"] if wav else []
                cmd += vcodec + (["-c:a", "aac", "-b:a", "96k", "-shortest"] if wav else ["-an"]) + [str(out)]
                res = subprocess.run(cmd, capture_output=True, timeout=180, creationflags=flags)
                if res.returncode == 0 and out.exists():
                    path.unlink(missing_ok=True)
                    out.replace(path)
                    break
                out.unlink(missing_ok=True)
                print("video mux:", res.stderr.decode(errors="ignore")[:200])
        except Exception as e:
            print("video audio:", e)
        finally:
            if wav is not None:
                wav.unlink(missing_ok=True)
        return path

    def _record(self, person, reason):
        """ویدیو: ~۷ ثانیه قبل از رویداد + VIDEO_SECONDS ثانیه بعدش، با صدای میکروفون"""
        if self.recording or (not self.opts["video"] and reason != "manual"):
            return
        self.recording = True
        writer = None
        began = False
        try:
            CAP_DIR.mkdir(exist_ok=True)
            prune_captures()
            fg = disk_free_gb()
            if fg is not None and fg < 0.5:
                print("[disk] هارد تقریبا پره؛ ویدیو ضبط نشد")
                return
            FPS = 10.0
            frames, last_t = [], 0.0
            for t, f in list(camera.ring):
                if t - last_t >= 1.0 / FPS:
                    img = cv2.imdecode(np.frombuffer(f, np.uint8), cv2.IMREAD_COLOR)
                    if img is not None:
                        frames.append(img)
                        last_t = t
            first = frames[-1] if frames else camera.raw
            if first is None:
                return
            h, w = first.shape[:2]
            base = CAP_DIR / (datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + ("-p" if person else ""))
            writer, path = self._open_writer(base, FPS, (w, h))
            if writer is None:
                print("video: no codec available")
                return
            fit = lambda im: im if im.shape[:2] == (h, w) else cv2.resize(im, (w, h))
            audio_tap.start(force=True)      # اگه تا الان باز نشده بود، همین الان دوباره امتحان کن (حداقل صدای بعد از رویداد ضبط میشه)
            pre = audio_tap.grab_pre(len(frames) / FPS) if audio_tap.stream is not None else None
            audio_tap.begin()
            began = True
            for im in frames:
                writer.write(fit(im))
            total, written, t0 = int(VIDEO_SECONDS * FPS), 0, time.time()
            while written < total and time.time() - t0 < VIDEO_SECONDS + 5:
                due, f = min(total, int((time.time() - t0) * FPS) + 1), camera.raw
                while written < due and f is not None:      # زمان‌بندی دقیق: طول ویدیو = طول واقعی (صدا هم‌زمان میمونه)
                    writer.write(fit(f))
                    written += 1
                time.sleep(0.03)
            post = audio_tap.end()
            began = False
            writer.release()
            writer = None
            path = self._add_audio(path, pre, post)
            prune_captures(protect=path)
            send_clip(path, REASONS.get(reason, "Event") + " clip", force=(reason == "manual"))
        except Exception as e:
            print("video:", e)
        finally:
            if began:
                audio_tap.end()
            if writer is not None:
                writer.release()
            self.recording = False

    def trigger(self, img=None, reason="motion", person=None):
        self.last_event = time.time()
        if person is None:
            person = reactor.detect(img) if img is not None else False
        quiet = reason == "motion" and self.opts["person_only"] and not person
        if img is not None:
            threading.Thread(target=self._burst, args=(img.copy(), person, reason, quiet), daemon=True).start()
        else:
            _alert_text(reason, person)
        if quiet:
            return
        if self.opts["video"] and cv2 is not None:
            threading.Thread(target=self._record, args=(person, reason), daemon=True).start()
        try:
            if self.auto == "sounds":
                threading.Thread(target=reactor.alert_sound, daemon=True).start()
            elif self.auto == "music" and player.tracks:
                player.shuffle = True
                if not player.playing:
                    player.start_soft(AUTO_MAX[0])
                else:
                    player.ramp(AUTO_MAX[0], 6)
            elif self.auto == "smart":
                reactor.escalate(person)
        except Exception as e:
            print("auto action:", e)

    def noise_event(self):
        if self.armed and time.time() - self.last_event > 20:
            f = camera.raw
            self.trigger(f.copy() if f is not None else None, "noise")

    def pc_event(self):
        f = camera.raw
        self.trigger(f.copy() if f is not None else None, "pc")
        self.lock_pc()

    def status(self):
        if self.armed and audio_tap.stream is None:
            audio_tap.start()
        events = []
        if CAP_DIR.exists():
            events = [{"name": f.name, "person": f.stem.endswith("-p")}
                      for f in sorted(CAP_DIR.glob("*.jpg"), reverse=True)[:24] if CAP_RE.fullmatch(f.name)]
        return {"armed": self.armed, "auto": self.auto, "sens": self.sens, "siren": siren.on,
                "presence": {"on": presence.on, "start": presence.start, "end": presence.end, "away": presence.away, "phase": presence.phase, "scene": presence.scene, "tracks": len(player.tracks), "sounds": len(sound_files())},
                "fun": reactor.to_dict(), "autoaway": autoaway.status(),
                "opts": self.opts, "vmax": AUTO_MAX[0], "detector": human_mod.detector_name() if human_mod else "-", "videos": [f.name for f in sorted(list(CAP_DIR.glob("*.mp4")) + list(CAP_DIR.glob("*.avi")), reverse=True)[:8]] if CAP_DIR.exists() else [],
                "events": events, "nvr": nvrwatch.brief(), "notify": bool((TG_TOKEN and TG_CHAT) or NTFY_TOPIC),
                "camera_live": camera.frame is not None, "locked": pc_locked(), "disk_free_gb": (round(disk_free_gb(), 1) if disk_free_gb() is not None else None), "camera_err": camera.err, "gate_err": (self.gate.err if self.gate else "") or self.gate_err, "audio": {"ok": audio_tap.stream is not None, "err": audio_tap.err, "ffmpeg": bool(ffmpeg_exe())}, "camera_index": camera.index_used, "gate_broken": security.gate_broken, "sounds": len(sound_files())}

    def save(self):
        data = json.dumps({"player": {"volume": USER_VOL[0], "shuffle": player.shuffle, "repeat": player.repeat},
                           "ui": UI_PREFS, "vmax": AUTO_MAX[0],
                           "armed": self.armed, "away_mode": bool(presence.away), "auto": self.auto, "sens": self.sens, "opts": self.opts,
                           "presence": {"on": presence.on, "start": presence.start, "end": presence.end, "away": presence.away, "scene": presence.scene},
                           "fun": reactor.to_dict(), "autoaway": autoaway.to_dict(), "nvr": nvrwatch.to_dict()})
        tmp = SETTINGS.with_suffix(".tmp")
        tmp.write_text(data, encoding="utf-8")
        try:
            if SETTINGS.exists():
                SETTINGS.with_suffix(".bak").write_bytes(SETTINGS.read_bytes())
        except OSError:
            pass
        tmp.replace(SETTINGS)       # نوشتن اتمیک: وسط برق رفتن فایل خراب نمیشه

    def load(self):
        try:
            d = json.loads(SETTINGS.read_text(encoding="utf-8"))
        except Exception:
            return
        pl = d.get("player") if isinstance(d.get("player"), dict) else {}
        USER_VOL[0] = num(pl.get("volume"), 0.7, 0.0, 1.0)
        player.set_volume(USER_VOL[0])
        player.shuffle = bool(pl.get("shuffle", False))
        player.repeat = pl.get("repeat") if pl.get("repeat") in ("off", "all", "one") else "off"
        AUTO_MAX[0] = num(d.get("vmax"), 0.8, 0.2, 1.0)
        if abs(AUTO_MAX[0] - 0.7) < 0.001:
            AUTO_MAX[0] = 0.8                 # ۷۰٪ همون پیش‌فرض قدیمی بود؛ پیش‌فرض جدید ۸۰٪
        ui = d.get("ui") if isinstance(d.get("ui"), dict) else {}
        UI_PREFS.update(mon=num(ui.get("mon"), 1, 1, 16, int), qual=num(ui.get("qual"), 1, 0, 2, int), tpad=bool(ui.get("tpad", False)))
        a = "sounds" if d.get("auto") == "siren" else d.get("auto")     # تنظیم قدیمی «آژیر» -> صدا افکت
        self.auto = a if a in self.AUTOS else "none"
        self.sens = num(d.get("sens"), 1000, 50, 20000, int)
        if isinstance(d.get("opts"), dict):
            for k in self.opts:
                if k in d["opts"]:
                    self.opts[k] = bool(d["opts"][k])
        presence.configure(d.get("presence", {}))
        try:
            reactor.configure(d.get("fun", {}))
            autoaway.configure(d.get("autoaway", {}))
        except Exception as e:
            print("load settings:", e)
        try:
            nvrwatch.configure(d.get("nvr", {}))
        except Exception as e:
            print("load nvr:", e)
        if d.get("armed") and cv2 is not None:
            self.arm(True)
        if d.get("away_mode"):          # «بیرونم» زده بودی: با ریستارت سرور همه‌چیز (دوربین، NVR، شبیه‌ساز حضور، حالت سرگرمی) خودکار برمیگرده
            try:
                mode_away(restore=True)
                print("[away] حالت «بیرونم» بعد از ریستارت دوباره برقرار شد")
            except Exception as e:
                print("restore away:", e)


class NoiseWatch:
    """وقتی مسلح و گزینه‌ی «صدای بلند» روشنه، صدای ناگهانی (شکستن شیشه، در، داد) رو از میکروفون کامپیوتر میشنوه."""

    def __init__(self):
        self.stream = None
        self.base = 0.01
        self.hits = 0
        self.last = 0.0

    def _cb(self, indata, frames, t, status):
        try:
            rms = float(np.sqrt(np.mean(np.square(indata.astype("float32")))))
            if rms > max(self.base * 6, 0.06):
                self.hits += 1
                if self.hits >= 2 and time.time() - self.last > 30:
                    self.last = time.time()
                    threading.Thread(target=security.noise_event, daemon=True).start()
            else:
                self.hits = 0
                self.base = self.base * 0.98 + rms * 0.02    # صدای محیط به‌مرور یاد گرفته میشه
        except Exception:
            pass

    def sync(self):
        want = bool(security.armed and security.opts["noise"] and sd is not None and np is not None)
        try:
            if want and self.stream is None:
                self.stream = sd.InputStream(channels=1, samplerate=16000, blocksize=4000, callback=self._cb)
                self.stream.start()
            elif not want and self.stream is not None:
                self.stream.stop()
                self.stream.close()
                self.stream = None
        except Exception as e:
            print("noise watch:", e)
            self.stream = None


def _idle_seconds():
    import ctypes

    class LII(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    li = LII()
    li.cbSize = ctypes.sizeof(li)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li))
    return (ctypes.windll.kernel32.GetTickCount() - li.dwTime) / 1000.0


def _pc_watch():
    """وقتی مسلحی و کسی واقعا پشت کامپیوتر موس/کیبورد میزنه (نه تو از گوشی)، عکس + اعلان."""
    prev, last_alert = None, 0.0
    while os.name == "nt":
        time.sleep(2)
        try:
            if not (security.armed and security.opts["pcwatch"]) or time.time() - security.armed_at < 60:
                prev = None
                continue
            idle = _idle_seconds()
            if prev is not None and idle < prev - 0.5 and idle < 3 and time.time() - last_synth[0] > 6 \
                    and time.time() - last_alert > 300:
                last_alert = time.time()
                security.pc_event()
            prev = idle
        except Exception as e:
            print("pc watch:", e)


def _net_watch():
    """اگه وقتی مسلحی اینترنت/کانال اعلان چند دقیقه قطع بشه، بعد از وصل شدن خبر میده (قطع برق/روتر/کابل؟)"""
    if TG_TOKEN:
        hosts = [(urllib.parse.urlparse(ALERT_API).hostname, 443)]
    elif NTFY_TOPIC:
        hosts = [(urllib.parse.urlparse(NTFY_SERVER).hostname, 443)]
    else:
        hosts = [("1.1.1.1", 53), ("8.8.8.8", 53)]
    down = None
    while True:
        time.sleep(60)
        try:
            ok = False
            for h in hosts:
                try:
                    socket.create_connection(h, timeout=4).close()
                    ok = True
                    break
                except OSError:
                    pass
            if not ok and down is None:
                down = time.time()
            elif ok and down is not None:
                mins = (time.time() - down) / 60
                down = None
                if mins >= 5 and security.armed:
                    notify(f"Internet/alert channel was down for {int(mins)} min while armed (power cut, router off or cable cut?)", True)
        except Exception as e:
            print("net watch:", e)


siren = Siren()
presence = Presence()
SOUNDS_DIR.mkdir(exist_ok=True)
reactor = reactions.Reactor(SimpleNamespace(
    player=player, siren=siren, speak=tts, play=play_pcm, play_file=play_file, sound_files=sound_files, pick_sound=pick_sound,
    sr=lambda: (pygame.mixer.get_init() or (44100,))[0], busy=lambda: siren.on or talkers > 0,
    camera_hold=camera_hold, camera_ok=lambda: cv2 is not None, vmax=lambda: AUTO_MAX[0]))
security = Security()
noisewatch = NoiseWatch()
if human_mod is not None and cv2 is not None:
    threading.Thread(target=human_mod.prepare_models, daemon=True).start()


def mode_away(restore=False):
    """از خونه رفتی: دوربین مسلح + شبیه‌ساز حضور (تو هر ساعت روز) + حالت سرگرمی، همه خودکار.
    restore=True: برگشت بعد از ریستارت سرور (دوباره قفل نمیکنه)"""
    if cv2 is not None:
        security.arm(True)
        if not restore:
            security.lock_pc()
    presence.configure({"on": True, "away": True})
    try:
        reactor.away = True
        if cv2 is not None:
            reactor.configure({"on": True})
    except Exception as e:
        print("mode_away fun:", e)
    if os.environ.get("NVR_WITH_AWAY", "1") == "1":
        try:
            nvrwatch.set(True)      # NVR وصل میشه و میمونه (نگهبان nvrwatch.keepalive اگه افتاد دوباره راهش میندازه)
        except Exception as e:
            print("mode_away nvr:", e)
    security.save()


def mode_home():
    presence.away = False          # تا مسلح نبودن، NVR‌ای که خودِ مسلح شدن روشن کرده خاموش بشه
    security.arm(False)
    siren.stop()
    presence.configure({"on": False, "away": False})
    try:
        reactor.away = False
        reactor.configure({"on": False})
    except Exception as e:
        print("mode_home fun:", e)
    if os.environ.get("NVR_WITH_AWAY", "1") == "1":
        try:
            nvrwatch.set(False)
        except Exception as e:
            print("mode_home nvr:", e)
    security.save()


autoaway = reactions.AutoAway(mode_away, mode_home, notify)
security.load()
atexit.register(lambda: security.save())
REPORT_HOUR = num(os.environ.get("DAILY_REPORT_HOUR"), 21, -1, 23, int)   # گزارش روزانه؛ -1 = خاموش


def _daily_report():
    last = None
    while REPORT_HOUR >= 0:
        time.sleep(60)
        try:
            now = datetime.datetime.now()
            if now.hour == REPORT_HOUR and last != now.date():
                last = now.date()
                names = [f.name for f in CAP_DIR.glob(f"{now:%Y%m%d}-*.jpg")] if CAP_DIR.exists() else []
                cam = "ok" if time.time() - camera.last_ok < 90 else ("OFF" if not security.armed else "NOT WORKING")
                notify(f"Daily report: armed={'yes' if security.armed else 'no'}, camera {cam}, {len(names)} photos today "
                       f"({sum(n.endswith('-p.jpg') for n in names)} with a person)")
        except Exception as e:
            print("report:", e)


threading.Thread(target=_daily_report, daemon=True).start()
threading.Thread(target=_pc_watch, daemon=True).start()
threading.Thread(target=_net_watch, daemon=True).start()
noisewatch.sync()


@app.get("/api/mode")
@auth_viewer
def mode_get():
    return jsonify(mode_user=is_mode_user(), away=bool(presence.away))


@app.post("/api/mode")
@auth_viewer
def mode_set():
    """🏠 خونم / 🚪 رفتم بیرون (برای ادمین و کاربر «فقط دو دکمه»)؛ همون کاری که دکمه‌های بیرونم/رسیدم تو بخش امنیت میکنن"""
    m = jbody().get("mode")
    if m not in ("away", "home"):
        return jsonify(error="bad mode"), 400
    if m == "away" and cv2 is None:
        return jsonify(error="opencv not installed"), 501
    try:
        mode_away() if m == "away" else mode_home()
    except Exception as e:
        return jsonify(error=str(e)), 400
    audit("MODE " + m.upper() + " by " + str(session.get("user", "admin")), alert=True)
    return jsonify(mode_user=is_mode_user(), away=bool(presence.away))


@app.get("/api/security")
@auth
def sec_get():
    return jsonify(security.status())


@app.post("/api/security")
@auth
def sec_set():
    d = jbody()
    try:
        if d.get("mode") in ("away", "home"):      # دکمه‌های 🚪 بیرونم / 🏠 رسیدم خونه
            if d["mode"] == "away":
                if cv2 is None:
                    return jsonify(error="opencv not installed"), 501
                mode_away()
            else:
                mode_home()
            audit("MODE " + d["mode"].upper(), alert=True)
        if "armed" in d:
            if d["armed"] and cv2 is None:
                return jsonify(error="opencv not installed"), 501
            was = security.armed
            security.arm(bool(d["armed"]))
            if d["armed"] and not was:
                threading.Timer(3, security.lock_pc).start()
            audit("ARMED" if d["armed"] else "DISARMED", alert=True)
        if d.get("auto") in Security.AUTOS:
            security.auto = d["auto"]
        if "sens" in d:
            security.sens = num(d["sens"], 1000, 50, 20000, int)
        if "vmax" in d:
            AUTO_MAX[0] = num(d["vmax"], 0.8, 0.2, 1.0)
        if "siren" in d:
            siren.start() if d["siren"] else siren.stop()
        if "presence" in d:
            presence.configure(d["presence"])
        if "fun" in d:
            if d["fun"].get("on") and cv2 is None:
                return jsonify(error="opencv not installed"), 501
            reactor.configure(d["fun"])
        if "autoaway" in d:
            aa = dict(d["autoaway"])
            if aa.pop("add_me", False):      # همین دستگاهی که صفحه رو باز کرده (باید به وای‌فای خونه وصل باشه)
                try:
                    ip = ipaddress.ip_address(request.remote_addr or "")
                except ValueError:
                    ip = None
                if not ip or ip.version != 4 or not ip.is_private or ip.is_loopback:
                    return jsonify(error="این دستگاه از وای‌فای خونه وصل نیست (IP داخلی نداره). گوشی رو به وای‌فای خونه وصل کن و دوباره بزن."), 400
                aa["phones"] = list(dict.fromkeys(autoaway.phones + [str(ip)]))
                aa["on"] = True
            autoaway.configure(aa)
        if isinstance(d.get("opts"), dict):
            for k, v in d["opts"].items():
                if k in security.opts:
                    security.opts[k] = bool(v)
            noisewatch.sync()
        if isinstance(d.get("nvr"), dict):
            nd = d["nvr"]
            if "on" in nd:
                if cv2 is None or not nvr.enabled():
                    return jsonify(error="NVR تنظیم نشده (NVR_IP تو start.bat) یا opencv نصب نیست"), 404
                nvrwatch.set(bool(nd["on"]))
                audit("NVR WATCH ON" if nvrwatch.on else "NVR WATCH OFF", alert=True)
            if "hd" in nd or "enhance" in nd:
                nvrwatch.set_opts(hd=nd.get("hd"), enhance=nd.get("enhance"))
        if d.get("test"):
            threading.Thread(target=reactor.fire, args=(d["test"] if d["test"] != "random" else None,), daemon=True).start()
    except Exception as e:
        return jsonify(error=str(e)), 400
    security.save()
    return jsonify(security.status())


@app.get("/api/capture/<name>")
@auth
def capture(name):
    if not CAP_RE.fullmatch(name) or not (CAP_DIR / name).is_file():
        return jsonify(error="not found"), 404
    mt = {".jpg": "image/jpeg", ".mp4": "video/mp4", ".avi": "video/x-msvideo"}[Path(name).suffix]
    return send_file(CAP_DIR / name, mimetype=mt)


@app.post("/api/notify_test")
@auth
def notify_test():
    """تست اعلان‌ها: به بله/تلگرام و ntfy پیام تست میفرسته و نتیجه رو میگه"""
    out = []
    if TG_TOKEN:
        if not TG_CHAT:
            ids = tg_chat_ids()
            out.append("بله/تلگرام: ALERT_CHAT_ID خالیه. " + (("عددهای پیدا شده: " + ", ".join(ids) + " ← یکیش رو تو start.bat بذار") if ids
                       else "اول به ربات یه پیام بده و دوباره تست کن (یا توکن/اینترنت مشکل داره)"))
        else:
            out.append("بله/تلگرام: " + ("✅ رسید" if send_text("Test message ✅") else "❌ نشد (توکن، chat id یا اینترنت/فیلترینگ رو چک کن)"))
    if NTFY_TOPIC:
        out.append("ntfy: " + ("✅ رسید" if send_ntfy("Test message") else "❌ نشد"))
    if not out:
        out.append("هیچ اعلانی تنظیم نشده (تو start.bat: ALERT_TOKEN یا NTFY_TOPIC)")
    return jsonify(lines=out)


@app.post("/api/captures/delete")
@auth
def capture_delete():
    name = str(jbody().get("name", ""))
    files = [f for f in CAP_DIR.glob("*") if CAP_RE.fullmatch(f.name)] if name == "all" else ([CAP_DIR / name] if CAP_RE.fullmatch(name) else [])
    n = 0
    for f in files:
        try:
            f.unlink()
            n += 1
        except OSError:
            pass
    audit("delete captures", str(n))
    return jsonify(deleted=n)


@sock.route("/ws/talk")
def ws_talk(ws):
    """صدای میکروفون گوشی/مرورگر -> اسپیکر سیستم خونه.
    فریم اول JSON {rate} ـه؛ اگه فریم صوتی زودتر از اون رسید (اتصال کند) خراب نمیشه. هر خطایی به کلاینت گفته میشه (نه قطع ناگهانی)."""
    global talkers
    if not ws_ok():
        return

    def fail(msg):
        print("talk error:", msg)
        try:
            ws.send(json.dumps({"error": str(msg)[:200]}))
            for _ in range(5):                    # بقیه‌ی فریم‌های در راه رو بخون تا اتصال با RST ("Connection reset") بسته نشه
                if ws.receive(timeout=0.2) is None:
                    break
        except Exception:
            pass

    if sd is None:
        return fail("sounddevice روی سرور نصب نیست")
    rate, first = 16000, None
    try:
        m = ws.receive(timeout=8)
        if isinstance(m, str):
            try:
                rate = num(json.loads(m).get("rate"), 16000, 8000, 96000, int)
            except Exception:
                pass
        elif isinstance(m, (bytes, bytearray)):
            first = bytes(m)                      # فریم صوتی قبل از JSON رسیده؛ با نرخ پیش‌فرض ۱۶k
    except Exception as e:
        return fail("handshake: " + repr(e)[:120])

    stream, out_rate = None, rate
    try:
        try:
            stream = sd.RawOutputStream(samplerate=rate, channels=1, dtype="int16")
            stream.start()
        except Exception:
            try:
                stream and stream.close()
            except Exception:
                pass
            out_rate = int(sd.query_devices(None, "output")["default_samplerate"])   # بعضی کارت‌صداها ۱۶k/۴۸k رو قبول نمیکنن
            stream = sd.RawOutputStream(samplerate=out_rate, channels=1, dtype="int16")
            stream.start()
    except Exception as e:
        return fail("اسپیکر سیستم باز نشد: " + repr(e)[:140])

    def conv(b):
        if out_rate == rate or np is None or len(b) < 4:
            return b
        a = np.frombuffer(b[: len(b) // 2 * 2], dtype=np.int16).astype(np.float32)
        n = max(1, int(len(a) * out_rate / rate))
        return np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype(np.int16).tobytes()

    with talk_lock:
        talkers += 1
        player.duck = 0.2
        player._apply(player.volume)
    ip = client_ip()
    try:
        if first:
            stream.write(conv(first))
        while True:
            data = ws.receive(timeout=20)
            if data is None:                       # ۲۰ ثانیه سکوت: اگه کلاینت زنده‌ست ادامه بده
                if not client_alive(ip):
                    break
                continue
            if isinstance(data, (bytes, bytearray)):
                stream.write(conv(bytes(data)))
    except Exception:
        pass
    finally:
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass
        with talk_lock:
            talkers -= 1
            if talkers == 0:
                player.duck = 1.0
                player._apply(player.volume)


@sock.route("/ws/listen")
def ws_listen(ws):
    """صدای میکروفون سیستم خونه (یا وب‌کم) -> مرورگر"""
    if not ws_ok() or sd is None:
        return
    q = queue.Queue(maxsize=50)
    ip = client_ip()

    def cb(indata, frames, t, status):
        try:
            q.put_nowait(bytes(indata))
        except queue.Full:
            pass

    try:
        with sd.RawInputStream(samplerate=16000, channels=1, dtype="int16", blocksize=1600, callback=cb):
            while client_alive(ip):
                ws.send(q.get(timeout=5))
    except Exception:
        pass


# ===================== کنترل دسکتاپ =====================
def _pick(mons, m):
    try:
        m = int(m)
    except (TypeError, ValueError):
        m = 1
    return mons[m] if 1 <= m < len(mons) else mons[1]


def _mon(sct, m):
    return _pick(sct.monitors, m)


_mon_cache = [0.0, []]


def monitors():
    if time.time() - _mon_cache[0] > 5:
        with mss.mss() as sct:
            _mon_cache[:] = [time.time(), list(sct.monitors)]
    return _mon_cache[1]


@app.get("/screen.mjpg")
@auth
def screen_stream():
    if cv2 is None or mss is None:
        return jsonify(error="opencv/mss not installed"), 501

    m = request.args.get("m", 1)
    max_w = num(request.args.get("w"), 1280, 320, 3840, int)
    quality = num(request.args.get("q"), 60, 20, 95, int)

    def gen():
        with mss.mss() as sct:
            mon = _mon(sct, m)
            while True:
                img = np.ascontiguousarray(np.asarray(sct.grab(mon))[:, :, :3])
                h, w = img.shape[:2]
                if w > max_w:
                    img = cv2.resize(img, (max_w, int(h * max_w / w)))
                if mouse_c is not None:  # نمایش نشانگر موس
                    sc = img.shape[1] / mon["width"]
                    cx, cy = mouse_c.position
                    px, py = int((cx - mon["left"]) * sc), int((cy - mon["top"]) * sc)
                    if 0 <= px < img.shape[1] and 0 <= py < img.shape[0]:
                        cv2.circle(img, (px, py), 9, (255, 255, 255), -1)
                        cv2.circle(img, (px, py), 6, (0, 0, 255), -1)
                ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
                if ok:
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
                time.sleep(0.05)

    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")


def _key(name):
    if name == "win":
        name = "cmd"
    if name in Key.__members__:
        return Key.__members__[name]
    if len(name) == 1:
        return name
    raise ValueError(name)


def handle_input(d):
    mark_synthetic()
    t = d.get("type")
    if t in ("click", "move", "down", "up"):
        m = _pick(monitors(), d.get("m", 1))
        x = min(max(float(d["x"]), 0), 1)
        y = min(max(float(d["y"]), 0), 1)
        mouse_c.position = (m["left"] + int(x * (m["width"] - 1)), m["top"] + int(y * (m["height"] - 1)))
        if t == "click":
            btn = Button.right if d.get("button") == "right" else Button.left
            mouse_c.click(btn, 2 if d.get("double") else 1)
        elif t == "down":
            mouse_c.press(Button.left)
        elif t == "up":
            mouse_c.release(Button.left)
    elif t == "rel":  # حالت تاچ‌پد
        m = _pick(monitors(), d.get("m", 1))
        mouse_c.move(int(float(d["dx"]) * m["width"]), int(float(d["dy"]) * m["width"]))
    elif t == "clickhere":
        btn = Button.right if d.get("button") == "right" else Button.left
        mouse_c.click(btn, 2 if d.get("double") else 1)
    elif t == "scroll":
        mouse_c.scroll(0, int(d.get("dy", 0)))
    elif t == "type":
        kb_c.type(str(d.get("text", ""))[:500])
    elif t == "key":
        keys = [_key(p.strip().lower()) for p in str(d.get("key", "")).split("+") if p.strip()]
        if keys:
            with kb_c.pressed(*keys[:-1]):
                kb_c.tap(keys[-1])
    else:
        raise ValueError("bad type")


@app.post("/api/input")
@auth
def remote_input():
    if mouse_c is None or mss is None:
        return jsonify(error="pynput/mss not available"), 501
    try:
        handle_input(jbody())
    except Exception as e:
        return jsonify(error=str(e)[:100]), 400
    return jsonify(ok=True)


@sock.route("/ws/desk")
def ws_desk(ws):
    """دسکتاپ زنده: فریم فقط وقتی صفحه تغییر کنه + ورودی موس/کیبورد روی همون اتصال"""
    if not ws_ok() or mss is None or cv2 is None:
        return
    cfg = {"m": 1, "w": 1280, "q": 60, "fps": 20}
    last_hash = last_cur = None
    idle = 0
    ip = client_ip()
    try:
        with mss.mss() as sct:
            while client_alive(ip):
                while True:
                    msg = ws.receive(timeout=0)
                    if msg is None:
                        break
                    try:
                        d = json.loads(msg)
                    except Exception:
                        continue
                    if "cfg" in d:
                        c = d["cfg"]
                        cfg["m"] = int(c.get("m", cfg["m"]))
                        cfg["w"] = min(max(int(c.get("w", cfg["w"])), 320), 3840)
                        cfg["q"] = min(max(int(c.get("q", cfg["q"])), 20), 95)
                        cfg["fps"] = min(max(int(c.get("fps", cfg["fps"])), 3), 30)
                        last_hash = last_cur = None
                    elif mouse_c is not None:
                        try:
                            handle_input(d)
                            idle = 0
                        except Exception:
                            pass
                t0 = time.time()
                mon = _mon(sct, cfg["m"])
                img = np.ascontiguousarray(np.asarray(sct.grab(mon))[:, :, :3])
                hsh = zlib.adler32(img)
                if mouse_c is not None:
                    cx, cy = mouse_c.position
                    cur = (cx, cy)
                    if cur != last_cur:
                        ws.send(json.dumps({"c": [(cx - mon["left"]) / mon["width"], (cy - mon["top"]) / mon["height"]]}))
                        last_cur = cur
                        idle = 0
                if hsh != last_hash:
                    h, w = img.shape[:2]
                    if w > cfg["w"]:
                        img = cv2.resize(img, (cfg["w"], int(h * cfg["w"] / w)), interpolation=cv2.INTER_AREA)
                    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, cfg["q"]])
                    if ok:
                        ws.send(buf.tobytes())
                    last_hash = hsh
                    idle = 0
                else:
                    idle += 1
                fps = cfg["fps"] if idle < 40 else 5
                time.sleep(max(0.0, 1.0 / fps - (time.time() - t0)))
    except Exception:
        pass


class SysAudioHub:
    """یه ریسه‌ی ضبط مشترک برای «صدای سیستم». هر اتصال فقط مشترک میشه؛ پس با رفتن و برگشتن به صفحه، ضبط‌های نیمه‌مرده روی هم جمع نمیشن."""

    def __init__(self, rate, ch):
        self.rate, self.ch = rate, ch
        self.subs, self.lock, self.thread = set(), threading.Lock(), None

    def subscribe(self):
        q = queue.Queue(maxsize=30)
        with self.lock:
            self.subs.add(q)
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._run, daemon=True)
                self.thread.start()
        return q

    def unsubscribe(self, q):
        with self.lock:
            self.subs.discard(q)

    def _push(self, item):
        with self.lock:
            for q in list(self.subs):
                try:
                    q.put_nowait(item)
                except queue.Full:
                    try:
                        q.get_nowait()
                        q.put_nowait(item)
                    except Exception:
                        pass

    def _run(self):
        try:
            import soundcard as sc
            spk = sc.default_speaker()
            mic = sc.get_microphone(id=str(spk.name), include_loopback=True)
            n = self.rate // 10
            with mic.recorder(samplerate=self.rate, channels=self.ch, blocksize=n) as rec:
                while True:
                    with self.lock:
                        if not self.subs:
                            return              # کسی گوش نمیده: دستگاه آزاد شه
                    data = rec.record(numframes=n)
                    self._push((np.clip(data, -1, 1) * 32767).astype("<i2").tobytes())
        except Exception as e:
            print("sysaudio:", e)
            self._push("ضبط صدای سیستم ممکن نشد: " + str(e)[:120])


SYS_HUBS = {}


@sock.route("/ws/sysaudio")
def ws_sysaudio(ws):
    """صدای خود سیستم (آهنگ، ویدیو، بازی...) -> گوشی"""
    if not ws_ok():
        return
    lo = request.args.get("q") == "lo"
    rate, ch = (16000, 1) if lo else (32000, 2)
    hub = SYS_HUBS.setdefault((rate, ch), SysAudioHub(rate, ch))
    ip = client_ip()
    q = hub.subscribe()
    try:
        ws.send(json.dumps({"rate": rate, "ch": ch}))
        while client_alive(ip):
            try:
                ws.receive(timeout=0)          # اگه گوشی بسته باشه همین‌جا خطا میده و میریم بیرون
            except Exception:
                break
            try:
                item = q.get(timeout=1)
            except queue.Empty:
                continue
            if isinstance(item, str):
                ws.send(json.dumps({"error": item}))
                break
            ws.send(item)
    except Exception as e:
        print("sysaudio ws:", str(e)[:80])
    finally:
        hub.unsubscribe(q)


POWER = {
    "lock": "rundll32.exe user32.dll,LockWorkStation",
    "sleep": "rundll32.exe powrprof.dll,SetSuspendState 0,1,0",
    "restart": "shutdown /r /t 5",
    "shutdown": "shutdown /s /t 5",
    "cancel": "shutdown /a",
}


@app.post("/api/power")
@elevated
def power():
    act = jbody().get("action")
    cmd = POWER.get(act)
    if os.name != "nt" or not cmd:
        return jsonify(error="unsupported"), 400
    audit("power", str(act), alert=True)
    subprocess.Popen(cmd, shell=True)
    return jsonify(ok=True)


@app.get("/api/screenshot.png")
@auth
def screenshot():
    if cv2 is None or mss is None:
        return jsonify(error="unsupported"), 501
    with mss.mss() as sct:
        img = np.ascontiguousarray(np.asarray(sct.grab(_mon(sct, request.args.get("m", 1))))[:, :, :3])
    ok, buf = cv2.imencode(".png", img)
    return Response(buf.tobytes(), mimetype="image/png",
                    headers={"Content-Disposition": "attachment; filename=screenshot.png"})


def lan_ips():
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except Exception:
        pass
    try:
        u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        u.connect(("10.255.255.255", 1))
        ips.add(u.getsockname()[0])
        u.close()
    except Exception:
        pass
    ips = [i for i in ips if not i.startswith(("127.", "169.254."))]
    return sorted(ips, key=lambda i: (not i.startswith("192.168"), i))


@app.get("/api/info")
@auth
def info():
    scheme = "https" if USE_HTTPS else "http"
    n = 1
    if mss is not None and not HEADLESS:
        try:
            with mss.mss() as sct:
                n = max(len(sct.monitors) - 1, 1)
        except Exception:
            n = 1
    return jsonify(urls=[f"{scheme}://{ip}:{PORT}" for ip in lan_ips()], monitors=n, mode="service" if HEADLESS else "full")


@app.get("/api/stats")
@auth
def stats():
    if psutil is None:
        return jsonify({})
    b = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    return jsonify(cpu=psutil.cpu_percent(), ram=psutil.virtual_memory().percent,
                   battery=b.percent if b else None)


@app.post("/api/upload")
@auth
def upload():
    saved = 0
    for f in request.files.getlist("files"):
        name = Path(f.filename or "").name
        if name and Path(name).suffix.lower() in EXTS:
            f.save(unique_path(MUSIC_DIR, name))
            saved += 1
    player.scan()
    return jsonify(saved=saved, count=len(player.tracks))


@app.get("/api/stream/<int:i>")
@auth
def stream_track(i):
    if not 0 <= i < len(player.tracks):
        return jsonify(error="not found"), 404
    return send_file(player.tracks[i]["path"], conditional=True)


# ---------- مدیریت فایل ----------
@app.get("/api/fs/list")
@elevated
def fs_list():
    p = request.args.get("path") or str(Path.home())
    if p == "::drives" and os.name == "nt":
        drives = [f"{c}:\\" for c in string.ascii_uppercase if os.path.exists(f"{c}:\\")]
        return jsonify(path="", parent=None, dirs=[{"name": d, "path": d} for d in drives], files=[])
    P = Path(p).expanduser().resolve()
    if not P.is_dir():
        return jsonify(error="not a folder"), 400
    dirs, files = [], []
    try:
        for x in sorted(P.iterdir(), key=lambda x: x.name.lower()):
            try:
                if x.is_dir():
                    dirs.append({"name": x.name, "path": str(x)})
                else:
                    files.append({"name": x.name, "path": str(x), "size": x.stat().st_size})
            except OSError:
                pass
    except PermissionError:
        return jsonify(error="دسترسی ندارم"), 403
    parent = str(P.parent) if P.parent != P else ("::drives" if os.name == "nt" else None)
    return jsonify(path=str(P), parent=parent, dirs=dirs, files=files[:1000])


@app.get("/api/fs/download")
@elevated
def fs_download():
    P = Path(request.args.get("path", "")).expanduser().resolve()
    if not P.is_file():
        return jsonify(error="not a file"), 404
    audit("file download", str(P), alert=True)
    return send_file(P, as_attachment=True)


def unique_path(D, name):
    """فایل موجود رو بازنویسی نمیکنه: a.txt -> a (1).txt"""
    P = D / name
    i = 1
    while P.exists():
        P = D / f"{Path(name).stem} ({i}){Path(name).suffix}"
        i += 1
    return P


@app.post("/api/fs/upload")
@elevated
def fs_upload():
    D = Path(request.form.get("path", "")).expanduser().resolve()
    if not D.is_dir():
        return jsonify(error="bad folder"), 400
    n = 0
    for f in request.files.getlist("files"):
        name = Path(f.filename or "").name
        if name and name not in (".", ".."):
            try:
                f.save(unique_path(D, name))
                n += 1
            except OSError as e:
                return jsonify(error=str(e)[:100], saved=n), 400
    audit("file upload", f"{n} -> {D}", alert=True)
    return jsonify(saved=n)


# ---------- کلیپ‌بورد و اجرا ----------
@app.get("/api/clipboard")
@elevated
def clip_get():
    return jsonify(text=pyperclip.paste() if pyperclip else "")


@app.post("/api/clipboard")
@elevated
def clip_set():
    if pyperclip is None:
        return jsonify(error="pyperclip not installed"), 501
    pyperclip.copy(str(jbody().get("text", "")))
    return jsonify(ok=True)


@app.post("/api/run")
@elevated
def run_target():
    t = str(jbody().get("target", "")).strip()
    if not t:
        return jsonify(error="empty"), 400
    audit("run", t, alert=True)
    try:
        if os.name == "nt":
            os.startfile(t)
        else:
            subprocess.Popen(["xdg-open", t])
    except Exception as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True)


def _atomic_write(path, data):
    """نوشتن امن: اول تو فایل موقت + fsync، بعد جایگزینی. اگه وسط کار برق بره فایل نصفه/خالی نمیشه."""
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def ensure_cert():
    """گواهی ثابت تو پوشه‌ی برنامه (certs/). با قطع برق خراب/خالی نمیشه (نوشتن اتمیک) و یه کپی پشتیبان کنارشه (certs/backup).
    فقط وقتی گواهی جدید ساخته میشه که هم اصلی هم پشتیبان نباشن/خراب باشن، یا REGEN_CERT=1 بدی. عوض شدن IP گواهی رو عوض نمیکنه."""
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    d = Path(os.environ.get("CERT_DIR", "").strip() or (BASE / "certs"))
    bk = d / "backup"
    bk.mkdir(parents=True, exist_ok=True)
    crt, key = d / "cert.pem", d / "key.pem"
    ips, dns = {"127.0.0.1", *lan_ips()}, {"localhost"}
    if PUBLIC_HOST:
        try:
            ips.add(str(ipaddress.ip_address(PUBLIC_HOST)))
        except ValueError:
            dns.add(PUBLIC_HOST)

    def valid(c_p, k_p):
        try:
            c = x509.load_pem_x509_certificate(c_p.read_bytes())
            k = serialization.load_pem_private_key(k_p.read_bytes(), None)
            same = c.public_key().public_numbers() == k.public_key().public_numbers()
            return c if same and (c.not_valid_after_utc - datetime.datetime.now(datetime.timezone.utc)).days > 0 else None
        except Exception:
            return None

    if os.environ.get("REGEN_CERT", "0") != "1":
        c = valid(crt, key)
        if c is None and valid(bk / "cert.pem", bk / "key.pem") is not None:      # اصلی خراب/پاک شده: از پشتیبان برگردون
            _atomic_write(key, (bk / "key.pem").read_bytes())
            _atomic_write(crt, (bk / "cert.pem").read_bytes())
            c = valid(crt, key)
            print("[cert] گواهی اصلی خراب/گم بود؛ از پشتیبان برگردونده شد (اثر انگشت عوض نشد)")
        if c is not None:
            if not (valid(bk / "cert.pem", bk / "key.pem") is not None and (bk / "cert.pem").read_bytes() == crt.read_bytes()):
                _atomic_write(bk / "key.pem", key.read_bytes())
                _atomic_write(bk / "cert.pem", crt.read_bytes())
            try:
                sa = c.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
                have = {str(i) for i in sa.get_values_for_type(x509.IPAddress)} | set(sa.get_values_for_type(x509.DNSName))
                miss = (ips | dns) - have
                if miss:
                    print("[cert] این آدرس‌ها تو گواهی نیستن:", ", ".join(sorted(miss)), "- گواهی عوض نشد (اپ اندروید با اثر انگشت وصل میشه). REGEN_CERT=1 برای ساخت دوباره")
            except Exception:
                pass
            return str(crt), str(key)
    k = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "home-player")])
    now = datetime.datetime.now(datetime.timezone.utc)
    san = [x509.DNSName(x) for x in sorted(dns)] + [x509.IPAddress(ipaddress.ip_address(i)) for i in sorted(ips)]
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .sign(k, hashes.SHA256()))
    kb = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    cb = cert.public_bytes(serialization.Encoding.PEM)
    for dd in (bk, d):                      # اول پشتیبان، بعد اصلی
        _atomic_write(dd / "key.pem", kb)
        _atomic_write(dd / "cert.pem", cb)
    print(f"[cert] گواهی جدید ساخته شد: {crt}")
    return str(crt), str(key)


def _tg_call(method, payload, timeout=30):
    req = urllib.request.Request(f"{ALERT_API}/bot{TG_TOKEN}/{method}", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with _tg_open(req, timeout) as r:
        return json.loads(r.read().decode())


def grab_frame(timeout=8):
    """یه عکس تازه از دوربین (اگه دوربین خاموشه موقتا روشنش میکنه)"""
    if cv2 is None:
        return None
    camera_hold("tgsnap", True)
    try:
        t0 = time.time()
        while time.time() - t0 < timeout and camera.frame is None:
            time.sleep(0.2)
        if time.time() - t0 > 0.3:
            time.sleep(0.6)           # دوربینی که تازه روشن شده نور/اکسپوژر میخواد
        return camera.frame
    finally:
        camera_hold("tgsnap", False)


class TgBot:
    """دستورهای ربات تلگرام؛ فقط از chat id خودت جواب میگیره."""
    COMMANDS = [("status", "وضعیت همه‌چیز"), ("snap", "عکس لحظه‌ای از دوربین"), ("video", "ویدیوی کوتاه با صدا"),
                ("last", "آخرین عکس ذخیره‌شده"), ("away", "حالت بیرونم (همه‌چیز روشن)"), ("home", "رسیدم خونه (همه‌چیز خاموش)"),
                ("arm", "مسلح کردن دوربین"), ("disarm", "غیرمسلح کردن"), ("siren", "آژیر"), ("stop", "قطع آژیر"),
                ("logout_all", "خروج همه‌ی دستگاه‌ها از صفحه"),
                ] + ([("nvr", "عکس زنده‌ی همه‌ی کانال‌های NVR")] + [(f"nvr{c}", f"عکس زنده‌ی NVR کانال {c}") for c in nvr.CHANNELS]
                     + [("nvrvideo", "ویدیوی کوتاه از NVR")] + [(f"nvrvideo{c}", f"ویدیوی کوتاه NVR کانال {c}") for c in nvr.CHANNELS]
                     + [("nvron", "روشن کردن تشخیص آدم NVR"), ("nvroff", "خاموش کردن تشخیص آدم NVR")] if nvr.enabled() else []) + [
                ("help", "راهنما")]

    def start(self):
        if TG_TOKEN and TG_CHAT:
            threading.Thread(target=self.run, daemon=True).start()

    def help_text(self):
        return "🤖 دستورها:\n" + "\n".join(f"/{c} — {d}" for c, d in self.COMMANDS)

    def run(self):
        offset, backoff, ready = None, 5, False
        while True:
            try:
                if not ready:
                    try:
                        _tg_call("setMyCommands", {"commands": [{"command": c, "description": d} for c, d in self.COMMANDS]})
                    except Exception:
                        pass
                    old = _tg_call("getUpdates", {"offset": -1}).get("result", [])     # دستورهای قدیمی (قبل از روشن شدن) اجرا نشن
                    offset = old[-1]["update_id"] + 1 if old else None
                    ready = True
                    print("[telegram] ربات آماده‌ست؛ تو تلگرام /help بزن")
                params = {"timeout": 25, "allowed_updates": ["message"]}
                if offset:
                    params["offset"] = offset
                for u in _tg_call("getUpdates", params, timeout=40).get("result", []):
                    offset = u["update_id"] + 1
                    try:
                        self.handle(u)
                    except Exception as e:
                        print("[telegram] handle:", e)
                backoff = 5
            except Exception as e:
                print("[telegram] bot:", str(e)[:100])
                time.sleep(backoff)
                backoff = min(60, backoff * 2)

    def handle(self, u):
        m = u.get("message") or {}
        if str(m.get("chat", {}).get("id")) != str(TG_CHAT):
            return                                            # هر کس دیگه‌ای: بی‌صدا نادیده
        text = (m.get("text") or "").strip()
        if not text.startswith("/"):
            return
        cmd = text.split()[0][1:].split("@")[0].lower()
        audit("TELEGRAM", "/" + cmd)
        if cmd in ("start", "help"):
            send_text(self.help_text())
        elif cmd == "status":
            send_text(self.status_text())
        elif cmd == "snap":
            threading.Thread(target=self._snap, daemon=True).start()
        elif cmd == "video":
            if security.recording:
                send_text("⏳ همین الان داره ضبط میشه...")
            else:
                send_text(f"🎬 دارم ضبط میکنم (~{VIDEO_SECONDS + 7} ثانیه)...")
                threading.Thread(target=self._video, daemon=True).start()
        elif cmd == "last":
            pics = sorted(CAP_DIR.glob("*.jpg"), key=os.path.getmtime)
            if pics:
                _tg_upload("sendPhoto", "photo", pics[-1].name, pics[-1].read_bytes(), pics[-1].stem, "image/jpeg")
            else:
                send_text("هنوز عکسی ذخیره نشده.")
        elif cmd == "away":
            mode_away()
            send_text("🚪 حالت بیرونم فعال شد: دوربین مسلح، شبیه‌ساز حضور و سرگرمی روشن.")
        elif cmd == "home":
            mode_home()
            send_text("🏠 رسیدی خونه: همه‌چیز خاموش شد.")
        elif cmd == "arm":
            security.arm(True)
            security.save()
            send_text("🛡 مسلح شد.")
        elif cmd == "disarm":
            security.arm(False)
            security.save()
            send_text("🔓 غیرمسلح شد.")
        elif cmd == "siren":
            siren.start()
            send_text("🚨 آژیر روشن شد. قطع: /stop")
        elif cmd == "stop":
            siren.stop()
            send_text("آژیر قطع شد.")
        elif nvr.enabled() and cmd.startswith("nvrvideo") and (cmd == "nvrvideo" or (cmd[8:].isdigit() and int(cmd[8:]) in nvr_feeds)):
            chs = list(nvr_feeds) if cmd == "nvrvideo" else [int(cmd[8:])]
            send_text(f"🎬 دارم از NVR ضبط میکنم (~{VIDEO_SECONDS + 8} ثانیه)...")
            for ch in chs:
                threading.Thread(target=self._nvr_video, args=(ch,), daemon=True).start()
        elif nvr.enabled() and (cmd == "nvr" or (cmd.startswith("nvr") and cmd[3:].isdigit() and int(cmd[3:]) in nvr_feeds)):
            for ch in (list(nvr_feeds) if cmd == "nvr" else [int(cmd[3:])]):
                threading.Thread(target=self._nvr_snap, args=(ch,), daemon=True).start()
        elif cmd in ("nvron", "nvroff"):
            if not nvr.enabled() or cv2 is None:
                send_text("❌ NVR تنظیم نشده (NVR_IP تو start.bat) یا opencv نصب نیست.")
            else:
                nvrwatch.set(cmd == "nvron")
                security.save()
                send_text("📹 تشخیص آدم NVR روشن شد." if nvrwatch.on else "📹 تشخیص آدم NVR خاموش شد.")
        elif cmd == "logout_all":
            _logout_all_core(alert=False)
            send_text("🚪 از همه‌ی دستگاه‌ها خارج شدی؛ دفعه‌ی بعد باید دوباره با رمز (و کد) وارد بشی.")
        else:
            send_text("دستور نامعلوم. /help")

    def status_text(self):
        st = security.status()
        yn = lambda v: "✅" if v else "❌"
        pr, fun = st["presence"], st["fun"]
        gate = "خراب ⚠" if st.get("gate_broken") else st.get("detector", "-")
        ev = security.last_event
        last = f"{int((time.time() - ev) / 60)} دقیقه پیش" if ev else "هنوز نبوده"
        lines = [
            f"🛡 مسلح: {yn(st['armed'])}" + ("   🔒 ویندوز قفله (دسکتاپ از راه دور کار نمیکنه)" if st.get("locked") else ""),
            f"🚪 حالت بیرونم: {yn(pr.get('away'))}",
            f"🏠 شبیه‌ساز حضور: {yn(pr['on'])}" + (" (موزیک پخش میشه)" if pr.get("phase") == "on" else ""),
            f"🎮 سرگرمی: {yn(fun['on'])}",
            f"📷 دوربین: {yn(st['camera_live'])}" + (f" — {st['camera_err'][:80]}" if st.get("camera_err") else ""),
            f"🎤 میکروفون: {yn(st['audio']['ok'])}" + (f" — {st['audio']['err'][:60]}" if st["audio"].get("err") else ""),
            f"🧍 تشخیص آدم: {gate}",
            *([nvrwatch.summary()] if nvr.enabled() else []),
            f"⏱ آخرین رویداد: {last}",
            f"🔉 سقف صدای خودکار: {int(AUTO_MAX[0] * 100)}%",
            f"💾 فضای خالی هارد: {st.get('disk_free_gb')} گیگ (قدیمی‌ها فقط زیر {CAPTURE_MIN_FREE_GB:g} گیگ پاک میشن)",
        ]
        return "\n".join(lines)

    def _nvr_video(self, ch):
        if not nvrwatch.video(ch):
            send_text(f"❌ ضبط NVR کانال {ch} نشد (تصویر نیومد یا همین الان داره ضبط میشه)")

    def _nvr_snap(self, ch):
        data = nvr_snapshot_jpg(ch)
        if data is None:
            send_text(f"❌ NVR کانال {ch} تصویر نداد" + (": " + nvr_feeds[ch].err[:120] if nvr_feeds[ch].err else ""))
            return
        save_nvr_still(ch, data)
        try:
            _tg_upload("sendPhoto", "photo", f"nvr{ch}.jpg", data, f"📹 NVR کانال {ch} · " + datetime.datetime.now().strftime("%H:%M:%S"), "image/jpeg")
        except Exception as e:
            print("[telegram] nvr snap:", e)

    def _snap(self):
        data = grab_frame()
        if data is None:
            send_text("❌ دوربین تصویر نداد" + (": " + camera.err[:120] if camera.err else ""))
            return
        try:
            _tg_upload("sendPhoto", "photo", "snap.jpg", data, "📷 " + datetime.datetime.now().strftime("%H:%M:%S"), "image/jpeg")
        except Exception as e:
            print("[telegram] snap:", e)

    def _video(self):
        if cv2 is None:
            send_text("❌ opencv نصب نیست")
            return
        camera_hold("tgvid", True)
        try:
            t0 = time.time()
            while time.time() - t0 < 8 and camera.raw is None:
                time.sleep(0.2)
            security._record(False, "manual")        # خودش با force میفرسته
        finally:
            camera_hold("tgvid", False)
            if not security.armed:
                audio_tap.stop()


tgbot = TgBot()


def _keepalive(sock):
    """اتصال‌های نیمه‌باز (گوشی از وای‌فای/دیتا رفته) بعد از ~۶۰ ثانیه خودکار بسته میشن"""
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        if os.name == "nt":
            sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 30000, 10000))
        else:
            for opt, val in (("TCP_KEEPIDLE", 30), ("TCP_KEEPINTVL", 10), ("TCP_KEEPCNT", 3)):
                if hasattr(socket, opt):
                    sock.setsockopt(socket.IPPROTO_TCP, getattr(socket, opt), val)
    except Exception:
        pass


def make_tls_server(host, port, flask_app, cert):
    """سرور HTTPS که handshake رو تو ریسه‌ی خود اتصال و با timeout انجام میده.
    (تو حالت عادی یه اتصال TCP نیمه‌کاره — مثلا از اسکنر اینترنت — کل سرور رو برای همیشه قفل میکرد.)"""
    from werkzeug.serving import ThreadedWSGIServer
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(*cert)

    class TLSThreadedServer(ThreadedWSGIServer):
        def finish_request(self, request, client_address):
            try:
                _keepalive(request)
                request.settimeout(10)
                conn = ctx.wrap_socket(request, server_side=True)
                conn.settimeout(None)
            except Exception:
                try:
                    request.close()
                except Exception:
                    pass
                return
            try:
                super().finish_request(conn, client_address)
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

    return TLSThreadedServer(host, port, flask_app)


def _watchdog():
    """هر ۳۰ ثانیه از خود سرور سوال میپرسه؛ اگه ۳ بار پشت هم جواب نداد برنامه رو میبنده تا start.bat دوباره بالاش بیاره."""
    host = "127.0.0.1" if HOST in ("0.0.0.0", "", "::") else HOST
    ctx = ssl._create_unverified_context()
    time.sleep(90)
    fails = 0
    while True:
        time.sleep(30)
        prune_captures()
        try:
            c = http.client.HTTPSConnection(host, PORT, timeout=10, context=ctx) if USE_HTTPS else http.client.HTTPConnection(host, PORT, timeout=10)
            c.request("GET", "/api/login_info")
            c.getresponse().read()
            c.close()
            fails = 0
        except Exception as e:
            fails += 1
            print(f"[watchdog] سرور جواب نداد ({fails}/3): {e}")
            if fails >= 3:
                print("[watchdog] سرور گیر کرده؛ ری‌استارت خودکار...")
                try:
                    security.save()
                except Exception:
                    pass
                os._exit(3)


if __name__ == "__main__":
    print(f"کاربر: {USERNAME}")
    if FIRST_PASSWORD:
        print("\n" + "=" * 60 + f"\n  رمز ورود (فقط همین یک بار نشون داده میشه):  {FIRST_PASSWORD}\n"
              "  عوض کردنش: set-password.bat\n" + "=" * 60 + "\n")
    if os.environ.get("PLAYER_PASSWORD") and len(os.environ["PLAYER_PASSWORD"]) < 10:
        print("!! رمز کوتاهه؛ حداقل ۱۰ کاراکتر بذار")
    if os.name == "nt":  # سیستم نخوابه تا از راه دور در دسترس بمونه
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
        except Exception:
            pass
    if not (TG_TOKEN and TG_CHAT):
        print("(اعلان عکس برای حرکت غیرفعاله: ALERT_TOKEN و ALERT_CHAT_ID رو تنظیم کن)")
    if sd is None:
        print("!! sounddevice نصب نیست -> صحبت/گوش دادن کار نمیکنه")
    if cv2 is None:
        print("!! opencv نصب نیست -> دوربین کار نمیکنه")
    print(f"پوشه موزیک: {MUSIC_DIR}  |  {len(player.tracks)} آهنگ")
    scheme = "https" if USE_HTTPS else "http"
    print(f"\n{scheme}://localhost:{PORT}")
    for ip in lan_ips():
        print(f"{scheme}://{ip}:{PORT}   <-- از گوشی/شبکه خونه")
    print()
    notify(f"Server started ({'SERVICE mode, before Windows login' if HEADLESS else 'full'}). Armed: {'YES' if security.armed else 'no'}. Two-factor: {'on' if totp_secret() else 'OFF'}")
    threading.Thread(target=_watchdog, daemon=True).start()
    threading.Thread(target=_keep_awake, daemon=True).start()
    tgbot.start()
    if USE_HTTPS:
        make_tls_server(HOST, PORT, app, ensure_cert()).serve_forever()
    else:
        app.run(host=HOST, port=PORT, threaded=True)
