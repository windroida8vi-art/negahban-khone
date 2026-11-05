"""تشخیص «فقط آدم» برای دوربین حیاط.

حرکت خام (برگ، باد، باران، حشره، گربه، سایه، نور ماشین) به‌تنهایی هیچ واکنشی ایجاد نمیکنه.
روش: وقتی تو تصویر حرکتی هست، تشخیص‌دهنده‌ی آدم (MobileNet-SSD اگه فایلش تو models/ باشه،
وگرنه HOG خود OpenCV) روی «کل تصویر» تو یه ریسه‌ی جدا اجرا میشه (دوربین کند نمیشه).
وقتی تو چند ثانیه حداقل دو بار آدم دیده بشه و همزمان حرکت هم باشه، «آدم» حساب میشه.
کادرها (حرکت = خاکستری، آدم = سبز/زرد) روی پخش زنده کشیده میشن.
"""
import os
import threading
import time
import urllib.request
from collections import deque
from pathlib import Path

import cv2
import numpy as np

BASE = Path(__file__).parent
MODEL_DIR = BASE / "models"
PROTO = MODEL_DIR / "MobileNetSSD_deploy.prototxt"
WEIGHTS = MODEL_DIR / "MobileNetSSD_deploy.caffemodel"
# اگه اینترنت سرور بازه یه بار خودش دانلود میکنه؛ نشد هم برنامه با HOG کار میکنه.
# چند «جفت» مدل (prototxt + caffemodel)؛ هر جفت فقط وقتی قبول میشه که واقعا اجرا بشه.
# (اگه prototxt و caffemodel از دو نسخه‌ی مختلف باشن، OpenCV خطای BatchNorm میده؛ جفت بعدی امتحان میشه.)
_RAW = "https://raw.githubusercontent.com/"
MODEL_SETS = [
    {"proto": [_RAW + "djmv/MobilNet_SSD_opencv/master/MobileNetSSD_deploy.prototxt"],
     "weights": [_RAW + "djmv/MobilNet_SSD_opencv/master/MobileNetSSD_deploy.caffemodel"]},
    {"proto": [_RAW + "PINTO0309/MobileNet-SSD-RealSense/master/caffemodel/MobileNetSSD/MobileNetSSD_deploy.prototxt"],
     "weights": ["https://github.com/PINTO0309/MobileNet-SSD-RealSense/raw/master/caffemodel/MobileNetSSD/MobileNetSSD_deploy.caffemodel",
                 _RAW + "PINTO0309/MobileNet-SSD-RealSense/master/caffemodel/MobileNetSSD/MobileNetSSD_deploy.caffemodel"]},
    {"proto": [_RAW + "chuanqi305/MobileNet-SSD/master/deploy.prototxt"],
     "weights": ["https://github.com/PINTO0309/MobileNet-SSD-RealSense/raw/master/caffemodel/MobileNetSSD/MobileNetSSD_deploy.caffemodel"]},
]
MIN_SIZE = {PROTO: 5_000, WEIGHTS: 5_000_000}
BROKEN_MARK = MODEL_DIR / ".broken"          # همه‌ی جفت‌ها خراب بودن؛ تا ۲۴ ساعت دوباره دانلود نکن

_prep_lock = threading.Lock()
_state = {"valid": None}


def models_ready():
    return all(p.exists() and p.stat().st_size >= MIN_SIZE[p] for p in (PROTO, WEIGHTS))


def model_works(proto, weights):
    """مدل رو لود میکنه و یه بار روی تصویر خالی اجراش میکنه (خطای BatchNorm همین‌جا معلوم میشه)"""
    try:
        net = cv2.dnn.readNetFromCaffe(str(proto), str(weights))
        net.setInput(cv2.dnn.blobFromImage(np.zeros((300, 300, 3), np.uint8), 0.007843, (300, 300), 127.5))
        out = net.forward()
        return out.ndim == 4 and out.shape[3] == 7
    except Exception as e:
        print("[human] این جفت مدل کار نکرد:", str(e)[:140].replace("\n", " "))
        return False


def validate():
    """آیا مدلِ موجود تو models/ سالمه؟ (نتیجه یه بار حساب و نگه داشته میشه)"""
    if _state["valid"] is None:
        _state["valid"] = bool(models_ready() and model_works(PROTO, WEIGHTS))
    return _state["valid"]


def _fetch(urls, dest, min_size):
    for url in urls:
        tmp = dest.with_suffix(dest.suffix + ".try")
        try:
            with urllib.request.urlopen(url, timeout=30) as r, open(tmp, "wb") as f:
                while True:
                    b = r.read(1 << 16)
                    if not b:
                        break
                    f.write(b)
            if tmp.stat().st_size >= min_size:
                tmp.replace(dest)
                return True
            tmp.unlink(missing_ok=True)
            print("[human] فایل دانلودشده ناقص بود:", url)
        except Exception as e:
            tmp.unlink(missing_ok=True)
            print("[human] دانلود نشد:", url, "->", str(e)[:100])
    return False


def prepare_models(verbose=True):
    """پوشه‌ی models/ رو میسازه، مدل تشخیص آدم رو (در صورت نیاز) دانلود و امتحان میکنه. نتیجه تو پنجره‌ی سرور چاپ میشه.
    برمیگردونه: True اگه یه مدل سالم داریم."""
    if not _prep_lock.acquire(blocking=False):      # یه دانلود دیگه در حال اجراست
        return bool(_state["valid"])
    try:
        return _prepare(verbose)
    finally:
        _prep_lock.release()


def _prepare(verbose):
    MODEL_DIR.mkdir(exist_ok=True)
    if validate():
        if verbose:
            print("[human] مدل تشخیص آدم (MobileNet-SSD) سالمه.")
        return True
    if BROKEN_MARK.exists() and time.time() - BROKEN_MARK.stat().st_mtime < 24 * 3600:
        print("[human] مدل قبلا امتحان شد و کار نکرد؛ فعلا با تشخیص ساده (HOG). (برای امتحان دوباره پوشه‌ی models رو خالی کن)")
        return False
    print("[human] دارم مدل تشخیص آدم رو تو پوشه‌ی models دانلود و امتحان میکنم (حدود ۲۳ مگابایت)...")
    for i, st in enumerate(MODEL_SETS, 1):
        tp, tw = MODEL_DIR / "p.try.prototxt", MODEL_DIR / "w.try.caffemodel"
        if _fetch(st["proto"], tp, MIN_SIZE[PROTO]) and _fetch(st["weights"], tw, MIN_SIZE[WEIGHTS]) and model_works(tp, tw):
            tp.replace(PROTO)
            tw.replace(WEIGHTS)
            BROKEN_MARK.unlink(missing_ok=True)
            _state["valid"] = True
            print(f"[human] ✅ مدل آماده شد (جفت {i}).")
            return True
    for f in (MODEL_DIR / "p.try.prototxt", MODEL_DIR / "w.try.caffemodel"):
        f.unlink(missing_ok=True)
    _state["valid"] = False
    BROKEN_MARK.write_text(str(time.time()))
    print("[human] ❌ هیچ مدلی کار نکرد/دانلود نشد (اینترنت/فیلترینگ؟). برنامه با تشخیص ساده‌تر (HOG) کار میکنه.\n"
          "         دستی: فایل‌های MobileNetSSD_deploy.prototxt و MobileNetSSD_deploy.caffemodel (از یه جفت) رو بذار تو پوشه‌ی models و پوشه‌ی models/.broken رو پاک کن.")
    return False


def detector_name():
    return "MobileNet-SSD" if os.environ.get("HUMAN_DNN", "1") != "0" and validate() else "HOG"


if __name__ == "__main__":
    prepare_models()
    input("Enter بزن تا بسته شه...")


def _iou(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


class HumanGate:
    W = 320                 # عرض تصویر پردازش حرکت
    HOLD = 8.0              # ثانیه: بعد از دیدن آدم هنوز «آدم هست» حساب میشه
    EVERY = float(os.environ.get("HUMAN_EVERY", "0.35"))        # ثانیه: حداقل فاصله‌ی دو اجرای تشخیص‌دهنده (کمتر = سریع‌تر، پردازنده بیشتر)
    TILE_SEC = float(os.environ.get("HUMAN_TILE_SEC", "1.5"))  # فاصله‌ی اجرای برش‌های بزرگ‌شده (آدم دور) برای NVR
    SHOW = 1.6              # ثانیه: کادر آدم بعد از آخرین دیدن این‌قدر روی تصویر میمونه
    SHOW_SCORE = 0.35       # از این امتیاز به بالا کادر زرد نشون میده
    UPSCALE = float(os.environ.get("HUMAN_UPSCALE", "1.5"))   # HOG رو روی تصویر بزرگ‌شده اجرا میکنه تا آدم دور هم دیده بشه

    STATIC_SEC = float(os.environ.get("HUMAN_STATIC_SEC", "120"))   # آدمِ دقیقا بی‌حرکت بیشتر از این‌قدر (تیر/مجسمه/سایه) نادیده گرفته میشه

    def __init__(self, sens=1000, tiles=False, allow_still=False):
        self.sens = sens
        self.tiles = tiles                  # تشخیص با برش‌های بزرگ‌شده (آدم دور/کوچیک؛ برای NVR)
        self.allow_still = allow_still      # آدمِ ایستاده (بدون حرکت) هم «آدم» حساب بشه (برای NVR)
        if tiles:
            self.EVERY = float(os.environ.get("HUMAN_NVR_EVERY", "0.7"))
        self.tracks = []
        self.det_hist = deque(maxlen=8)     # (زمان، بهترین امتیاز)
        self.best = 0.0                     # بهترین امتیاز آدم تو آخرین اجرا (برای عیب‌یابی)
        self._tile_t = 0.0
        self.bg = None
        self.warm = 30
        self.last_human = 0.0
        self.last_motion = 0.0
        self.last_person = 0.0
        self.motion_boxes = []          # مختصات تصویر کوچیک (عرض W)
        self.people = []                # [{"box": (x,y,w,h) مختصات تصویر اصلی, "t": زمان}]
        self.det_times = deque(maxlen=8)
        self.fail = 0
        self.err = ""
        self.det_ms = 0.0
        try:
            self.hog = cv2.HOGDescriptor()
            self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        except Exception as e:       # تو بعضی نسخه‌ها (OpenCV 5) HOG تو بسته‌ی اصلی نیست؛ فقط با مدل MobileNet-SSD کار میکنیم
            self.hog = None
            print("[human] HOG تو OpenCV %s نیست (%s). فقط با مدل MobileNet-SSD تو پوشه‌ی models کار میکنه." % (getattr(cv2, "__version__", "?"), e))
        self.net, self.net_tried = None, False
        self._next_net_check, self._dl_started = 0.0, False
        self._busy, self._last_det = False, 0.0

    # ------------------------------------------------------------ مدل شبکه (اختیاری)
    def _load_net(self):
        """مدل سالم بود لودش کن؛ نبود، یه بار تو پس‌زمینه دانلود/تعمیرش کن و هر ۳۰ ثانیه دوباره چک کن"""
        now = time.time()
        if now < self._next_net_check:
            return
        self._next_net_check = now + 30
        if os.environ.get("HUMAN_DNN", "1") == "0":
            self.net_tried = True
            return
        if not validate():
            if not self._dl_started:
                self._dl_started = True
                threading.Thread(target=prepare_models, daemon=True).start()
            elif BROKEN_MARK.exists() and not _prep_lock.locked():
                self.net_tried = True          # همه‌ی جفت‌ها خراب بودن؛ HOG
            return
        self.net_tried = True
        try:
            self.net = cv2.dnn.readNetFromCaffe(str(PROTO), str(WEIGHTS))
            print("human detector: MobileNet-SSD ready")
        except Exception as e:
            print("human detector: DNN unavailable, using HOG:", e)
            self.err = "MobileNet-SSD load failed: %s" % str(e)[:80]
            self.net = None

    def reset(self):
        self.bg = None
        self.warm = 30
        self.motion_boxes = []

    # ------------------------------------------------------------ تشخیص آدم رو کل تصویر (تو ریسه‌ی جدا)
    def _ssd(self, img):
        """یه بار شبکه روی تصویر یا برش (با حفظ نسبت، بدون له شدن) -> [(x, y, w, h, امتیاز)] مختصات همون تصویر"""
        H, W = img.shape[:2]
        s = 300.0 / max(H, W)
        nw, nh = max(int(W * s), 1), max(int(H * s), 1)
        canvas = np.full((300, 300, 3), 127, np.uint8)
        canvas[:nh, :nw] = cv2.resize(img, (nw, nh))
        self.net.setInput(cv2.dnn.blobFromImage(canvas, 0.007843, (300, 300), 127.5))
        out = self.net.forward()
        res = []
        for i in range(out.shape[2]):
            sc = float(out[0, 0, i, 2])
            if int(out[0, 0, i, 1]) == 15 and sc >= self.SHOW_SCORE:
                x0, y0, x1, y1 = (out[0, 0, i, 3:7] * 300.0 / s).astype(int)
                x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
                if x1 > x0 and y1 > y0:
                    res.append((int(x0), int(y0), int(x1 - x0), int(y1 - y0), sc))
        return res

    def _people_tiled(self, img):
        """کل تصویر (هر بار) + برش‌های بزرگ‌شده (هر ۲ ثانیه): آدم کوچیک/دور تو تصویر NVR هم پیدا میشه"""
        H, W = img.shape[:2]
        res = list(self._ssd(img))
        now = time.time()
        if now - self._tile_t >= self.TILE_SEC:
            self._tile_t = now
            ts = max(int(min(H, W) * 0.7), 160)
            nx = max(1, int(np.ceil((W - ts) / (ts * 0.7))) + 1) if W > ts else 1
            ny = max(1, int(np.ceil((H - ts) / (ts * 0.7))) + 1) if H > ts else 1
            for yi in range(ny):
                y0 = 0 if ny == 1 else int(round(yi * (H - ts) / (ny - 1)))
                for xi in range(nx):
                    x0 = 0 if nx == 1 else int(round(xi * (W - ts) / (nx - 1)))
                    for (bx, by, bw, bh, sc) in self._ssd(img[y0:y0 + ts, x0:x0 + ts]):
                        # آدمی که از لبه‌ی برش بریده شده رو ردش کن؛ برش همسایه (با همپوشانی) کاملش رو میبینه
                        if (bx <= 1 and x0 > 0) or (bx + bw >= ts - 1 and x0 + ts < W) or (by <= 1 and y0 > 0) or (by + bh >= ts - 1 and y0 + ts < H):
                            continue
                        res.append((bx + x0, by + y0, bw, bh, sc))
        res = [r for r in res if r[3] >= 0.04 * H]
        if not res:
            return []
        # امتیاز مساوی: کادر بزرگ‌تر برنده است
        sc2 = [r[4] + 0.01 * (r[2] * r[3]) / float(W * H) for r in res]
        idx = cv2.dnn.NMSBoxes([list(r[:4]) for r in res], sc2, self.SHOW_SCORE, 0.45)
        return [res[int(j)] for j in np.array(idx).reshape(-1)]

    def _drop_static(self, boxes, t):
        """آدمِ کاملا بی‌حرکتِ قدیمی (تیر، مجسمه، سایه) رو کنار میذاره؛ آدمی که حرکت کنه دوباره «تازه» حساب میشه"""
        tracks = [tr for tr in self.tracks if t - tr["last"] < 20.0]
        keep = []
        for b in boxes:
            x, y, w, h = b[:4]
            cx, cy = x + w / 2.0, y + h / 2.0
            best, hit = 0.0, None
            for tr in tracks:
                v = _iou((x, y, w, h), tr["box"])
                if v > best:
                    best, hit = v, tr
            if hit is not None and best >= 0.4:
                if abs(cx - hit["cx"]) > 0.6 * max(w, h) or abs(cy - hit["cy"]) > 0.6 * max(w, h):
                    hit["cx"], hit["cy"], hit["first"] = cx, cy, t          # جابجا شد: دوباره «تازه»
                hit["box"], hit["last"] = (x, y, w, h), t
                if t - hit["first"] > self.STATIC_SEC:
                    continue
            else:
                tracks.append({"box": (x, y, w, h), "cx": cx, "cy": cy, "first": t, "last": t})
            keep.append(b)
        self.tracks = tracks
        return keep

    def _people(self, img):
        """برمیگردونه [(x, y, w, h, امتیاز)] روی کل تصویر"""
        H, W = img.shape[:2]
        if self.net is not None and self.tiles:
            return self._people_tiled(img)
        if self.net is not None:
            try:
                blob = cv2.dnn.blobFromImage(cv2.resize(img, (300, 300)), 0.007843, (300, 300), 127.5)
                self.net.setInput(blob)
                out = self.net.forward()
                res = []
                for i in range(out.shape[2]):
                    sc = float(out[0, 0, i, 2])
                    if int(out[0, 0, i, 1]) == 15 and sc >= self.SHOW_SCORE:
                        x0, y0, x1, y1 = (out[0, 0, i, 3:7] * np.array([W, H, W, H])).astype(int)
                        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
                        if (y1 - y0) >= 0.05 * H and x1 > x0:
                            res.append((int(x0), int(y0), int(x1 - x0), int(y1 - y0), sc))
                return res
            except Exception as e:
                print("DNN detect failed, falling back to HOG:", e)
                self.net = None
        if self.hog is None:
            self.err = "no person detector (HOG missing, MobileNet model not loaded)"
            raise RuntimeError(self.err)
        gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4)).apply(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
        up = self.UPSCALE if self.UPSCALE > 1.0 else 1.0
        if up > 1.0:
            gray = cv2.resize(gray, None, fx=up, fy=up, interpolation=cv2.INTER_LINEAR)
        rects, weights = self.hog.detectMultiScale(gray, winStride=(8, 8), padding=(8, 8), scale=1.05, hitThreshold=0.0)
        boxes = [[int(x / up), int(y / up), int(w / up), int(h / up)] for (x, y, w, h) in rects]
        scores = [float(v) for v in np.ravel(weights)]
        keep = [i for i, sc in enumerate(scores) if sc >= self.SHOW_SCORE]
        if not keep:
            return []
        idx = cv2.dnn.NMSBoxes([boxes[i] for i in keep], [scores[i] for i in keep], 0.0, 0.4)
        return [tuple(boxes[keep[int(j)]]) + (scores[keep[int(j)]],) for j in np.array(idx).reshape(-1)]

    @property
    def confirm_score(self):
        return 0.5 if self.net is not None else 0.6

    def _detect(self, img):
        try:
            t0 = time.time()
            boxes = self._people(img)
            t = time.time()
            self.det_ms = (t - t0) * 1000
            if self.allow_still:
                boxes = self._drop_static(boxes, t)
            self.people = [{"box": b[:4], "score": b[4], "t": t} for b in boxes]
            self.best = max((b[4] for b in boxes), default=0.0)
            top = max((b[4] for b in boxes if b[4] >= self.confirm_score), default=None)
            if top is not None:
                self.det_times.append(t)
                self.det_hist.append((t, top))
                self.last_person = t
            self.fail = 0
        except Exception as e:
            self.fail += 1
            self.err = str(e)[:120]
            print("person detect:", e)
        finally:
            self._busy = False

    # ------------------------------------------------------------ هر فریم
    def update(self, img, now=None):
        """خروجی: 'idle' (چیزی نیست) | 'motion' (حرکت غیرانسانی) | 'human' (آدم)"""
        now = now or time.time()
        if not self.net_tried:
            self._load_net()
        h0, w0 = img.shape[:2]
        scale = w0 / self.W
        small = cv2.resize(img, (self.W, max(int(h0 / scale), 1)))
        if self.bg is None:
            self.bg = cv2.createBackgroundSubtractorMOG2(history=400, varThreshold=36, detectShadows=True)
        fg = self.bg.apply(small)
        if self.warm > 0:
            self.warm -= 1
            return "idle"
        fg = cv2.threshold(fg, 200, 255, cv2.THRESH_BINARY)[1]          # سایه (127) حذف میشه
        if fg.mean() / 255.0 > 0.4:                                      # تغییر ناگهانی نور، نه حرکت
            self.reset()
            return "idle"
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))   # باران/نویز
        fg = cv2.dilate(fg, np.ones((5, 5), np.uint8), iterations=2)
        cnts, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        min_area = max(120, self.sens * 0.35)
        loose = max(50, min_area * 0.25)           # برای «حرکتی هست»؛ آدم دور هم حرکتش کوچیکه
        areas = [(cv2.contourArea(c), cv2.boundingRect(c)) for c in cnts]
        if any(a >= loose for a, _ in areas):
            self.last_motion = now
        boxes = [b for a, b in areas if a >= min_area * 0.5]
        self.motion_boxes = sorted(boxes, key=lambda b: -b[2] * b[3])[:8]

        # تشخیص آدم رو کل تصویر: وقتی حرکتی هست یا تازه آدم دیده شده، حداکثر هر EVERY ثانیه، تو ریسه‌ی جدا
        # شبکه‌ی عصبی سبکه: همیشه اجرا میشه. HOG سنگینه: فقط وقتی حرکتی هست یا تازه آدم دیده شده.
        want = self.net is not None or now - self.last_motion < 2.0 or now - self.last_person < 6.0
        if want and not self._busy and now - self._last_det >= self.EVERY:
            self._busy, self._last_det = True, now
            threading.Thread(target=self._detect, args=(img.copy(),), daemon=True).start()

        # آدم: حداقل دو بار تو ۴ ثانیه دیده شده و تو ۸ ثانیه‌ی اخیر حرکت هم بوده
        need = 1 if self.net is not None else 2      # شبکه‌ی عصبی دقیقه: یه بار دیدن کافیه (سریع‌تر)
        recent = sum(1 for t in self.det_times if now - t < 4.0)
        moving = now - self.last_motion < 8.0
        # آدمِ ایستاده (NVR): بدون حرکت هم قبوله اگه چند بار پشت سر هم با امتیاز بالا دیده شد
        still = (self.allow_still and recent >= 2
                 and max((sc for (t, sc) in self.det_hist if now - t < 4.0), default=0.0) >= 0.55)
        if recent >= need and (moving or still):
            self.last_human = now
        if now - self.last_human < self.HOLD:
            return "human"
        return "motion" if boxes else "idle"

    @property
    def human_now(self):
        return time.time() - self.last_human < self.HOLD
