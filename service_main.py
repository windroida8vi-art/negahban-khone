"""سرویس: نسخه‌ی «قبل از ورود به ویندوز» برنامه (با حساب SYSTEM از Task Scheduler اجرا میشه، بدون لاگین).
هر دقیقه اجرا میشه (نگهبان)؛ اگه نسخه‌ی دیگه‌ای (سرویس یا نسخه‌ی کامل بعد از ورود) پورت رو گرفته باشه بی‌صدا خارج میشه.
تنظیمات رو از start.bat و telegram-alerts.bat میخونه، پس لازم نیست جای دیگه‌ای چیزی تنظیم کنی."""
import os
import re
import secrets
import socket
import sys
import runpy
import time

BASE = os.path.dirname(os.path.abspath(__file__))
SKIP_KEYS = {"PY"}


def _expand(v, env):
    return re.sub(r"%(\w+)%", lambda m: env.get(m.group(1), os.environ.get(m.group(1), m.group(0))), v)


def load_bat_env(files=("start.bat", "telegram-alerts.bat")):
    """خط‌های `set NAME=VALUE` (و `if not defined X set X=...`) فایل‌های bat رو میخونه"""
    env = {}
    for fn in files:
        p = os.path.join(BASE, fn)
        if not os.path.exists(p):
            continue
        for raw in open(p, encoding="utf-8", errors="ignore").read().splitlines():
            line = raw.strip()
            low = line.lower()
            if not line or low.startswith(("rem ", "rem\t", "::", "@echo", "echo", "title", "chcp")) or low == "rem":
                continue
            m = re.match(r'(?i)^if\s+not\s+defined\s+(\w+)\s+set\s+"?(\w+)=(.*?)"?\s*$', line)
            if m:
                if m.group(1) not in env and m.group(1) not in os.environ:
                    env[m.group(2)] = _expand(m.group(3), env)
                continue
            m = re.match(r'(?i)^set\s+"?(\w+)=(.*?)"?\s*$', line)
            if m and m.group(1).upper() not in SKIP_KEYS:
                env[m.group(1)] = _expand(m.group(2).strip(), env)
    return env


def port_busy(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.7):
            return True
    except OSError:
        return False


def main():
    os.chdir(BASE)
    sys.path.insert(0, BASE)
    env = load_bat_env()
    for k, v in env.items():
        os.environ[k] = v
    os.environ["HP_MODE"] = "service"
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")        # بدون کارت صدا/جلسه‌ی کاربر هم pygame کرش نکنه
    os.environ.setdefault("PLAYER_PORT", "8080")
    port = int(os.environ["PLAYER_PORT"])
    if port_busy(port):                                       # نسخه‌ی کامل یا سرویس قبلی داره کار میکنه: هیچ کاری نکن
        return
    log_path = os.path.join(BASE, "service.log")
    try:
        if os.path.getsize(log_path) > 5_000_000:
            os.replace(log_path, log_path + ".1")
    except OSError:
        pass
    log = open(log_path, "a", buffering=1, encoding="utf-8")
    sys.stdout = sys.stderr = log
    print("\n=== " + time.strftime("%Y-%m-%d %H:%M:%S") + " سرویس شروع شد ===")
    if not (os.path.exists(os.path.join(BASE, "password.hash")) or os.environ.get("PLAYER_PASSWORD")):
        print("هنوز رمزی ساخته نشده؛ یه بار start.bat رو اجرا کن (رمز اولیه اونجا نشون داده میشه) و بعد سرویس خودش کار میکنه.")
        return
    with open(os.path.join(BASE, ".service_token"), "w", encoding="utf-8") as f:
        f.write(secrets.token_hex(24))
    runpy.run_path(os.path.join(BASE, "app.py"), run_name="__main__")


if __name__ == "__main__":
    main()
