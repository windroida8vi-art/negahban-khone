"""بهبود سبک کیفیت تصویر دوربین‌های قدیمی (فقط CPU، بدون کارت گرافیک): روشن کردن تاریکی‌ها، کم کردن نویز،
کنتراست محلی (CLAHE) و تیز کردن. جزئیاتِ وجود‌نداشته رو نمیسازه؛ فقط اون‌چه هست رو واضح‌تر نشون میده."""
import cv2
import numpy as np


class Enhancer:
    """برای پخش زنده (حالت‌دار: نویز رو بین فریم‌ها کم میکنه)؛ هر کانال یکی"""

    def __init__(self):
        self.clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))
        self.prev = None
        self._lut = {}

    def _gamma(self, g):
        lut = self._lut.get(g)
        if lut is None:
            lut = self._lut[g] = ((np.arange(256) / 255.0) ** g * 255).astype(np.uint8)
        return lut

    def apply(self, img, temporal=True):
        small = cv2.resize(img, (64, 36), interpolation=cv2.INTER_AREA)
        m = float(small.mean())
        g = 0.72 if m < 55 else (0.85 if m < 85 else 1.0)           # صحنه‌ی تاریک رو روشن‌تر کن
        if g != 1.0:
            img = cv2.LUT(img, self._gamma(g))
        if temporal:                                                 # نویز زمانی: فقط جاهای ثابت (آدم/حرکت محو نمیشه)
            p = self.prev
            if p is not None and p.shape == img.shape:
                d = cv2.absdiff(img, p)
                still = cv2.max(cv2.max(d[:, :, 0], d[:, :, 1]), d[:, :, 2]) < 18
                img = np.where(still[:, :, None], cv2.addWeighted(img, 0.55, p, 0.45, 0), img)
            self.prev = img
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)                    # کنتراست محلی روی روشنایی
        lab[:, :, 0] = self.clahe.apply(lab[:, :, 0])
        img = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        blur = cv2.GaussianBlur(img, (0, 0), 1.2)                     # تیز کردن
        return cv2.addWeighted(img, 1.6, blur, -0.6, 0)


_still = Enhancer()


def still(img):
    """برای عکس‌های تکی (رویداد/اسنپ‌شات): قوی‌تر چون وقت داریم"""
    try:
        den = cv2.fastNlMeansDenoisingColored(img, None, 5, 5, 5, 15)
    except Exception:
        den = img
    return _still.apply(den, temporal=False)
