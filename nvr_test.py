"""تست NVR (همه‌ی کانال‌ها): بدون اجرای برنامه‌ی اصلی میگه RTSP/ONVIF/عکس کار میکنه یا نه و چرا. خروجی رو برای من بفرست."""
import os, re, sys
from pathlib import Path

base = Path(__file__).parent
bat = base / "start.bat"
if bat.exists():                                   # مقدارها رو از start.bat میخونه
    for k, v in re.findall(r"^\s*set\s+(NVR_\w+|CAMERA_URL)=(.*?)\s*$", bat.read_text(encoding="utf-8", errors="ignore"), re.M):
        os.environ.setdefault(k, v)
import nvr

if not nvr.enabled():
    print("NVR_IP تو start.bat تنظیم نشده."); sys.exit(1)
try:
    import cv2
except ImportError:
    print("opencv نصب نیست؛ اول start.bat رو یک بار اجرا کن."); sys.exit(3)
masked = lambda s: s.replace(f":{nvr.PASS}@", ":***@").replace(nvr.PASS, "***") if nvr.PASS else s
print(f"NVR: {nvr.IP}  user={nvr.USER}  channels={nvr.CHANNELS}  port={nvr.PORT}")
bad = 0
for ch in nvr.CHANNELS:
    print(f"\n================ کانال {ch} ================")
    hits, msg = nvr.scan(nvr.IP, nvr.USER, nvr.PASS, ch, nvr.PORT, nvr.URL, log=lambda l: print(masked(l)), force=True)
    if not hits:
        print("نتیجه: ❌", msg); bad += 1; continue
    print("منبع‌های سالم:", [h[0] for h in hits])
    got = False
    for name, url in hits:
        if url.startswith("http"):
            ok, img = nvr.SnapCap(url, nvr.USER, nvr.PASS).read()
        else:
            cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
            ok, img = (False, None)
            if cap.isOpened():
                for _ in range(8):
                    ok, img = cap.read()
                    if ok and img is not None:
                        break
            cap.release()
        if ok and img is not None:
            out = base / f"nvr_test_ch{ch}.jpg"
            cv2.imwrite(str(out), img)
            print(f"✅ کانال {ch}: تصویر گرفته شد ({img.shape[1]}x{img.shape[0]}) → {out.name} | منبع: {name}")
            nvr.remember(name, ch); got = True
            break
        print(f"❌ {name}: جواب داد ولی تصویر نیومد (کدک H.265 یا محدودیت اتصال؟)")
    bad += 0 if got else 1
print("\nنتیجه‌ی کلی:", "✅ همه‌ی کانال‌ها اوکیه" if not bad else f"❌ {bad} کانال مشکل داره (متن بالا رو برای من بفرست)")
sys.exit(1 if bad else 0)
