"""اتصال به NVR / دوربین IP با RTSP (بدون نیاز به دونستن برند).
اول با یه درخواست خیلی سریع RTSP (DESCRIBE) آدرس‌های رایج رو چک میکنه، بعد فقط آدرس سالم رو با OpenCV باز میکنه."""
import base64
import hashlib
import json
import os
import re
import socket
import threading
import time
from pathlib import Path

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

IP = os.environ.get("NVR_IP", "").strip()
USER = os.environ.get("NVR_USER", "admin")
PASS = os.environ.get("NVR_PASS", "admin")
URL = os.environ.get("CAMERA_URL", "").strip()
try:
    CHANNEL = int(os.environ.get("NVR_CHANNEL", "1") or 1)
except ValueError:
    CHANNEL = 1
try:
    PORT = int(os.environ.get("NVR_RTSP_PORT", "554") or 554)
except ValueError:
    PORT = 554
CACHE = Path(__file__).parent / "nvr_cache.json"


def _envnum(name, default, lo, hi):
    try:
        return min(hi, max(lo, float(os.environ.get(name, default))))
    except ValueError:
        return default


DECODE_FPS = _envnum("NVR_DECODE_FPS", 30, 2, 30)          # فقط این‌قدر فریم در ثانیه رنگی/کپی میشه (CPU کمتر)
STREAM_FPS = _envnum("NVR_STREAM_FPS", 30, 1, 30)          # سقف فریم پخش زنده (پهنای باند)
STREAM_W = int(_envnum("NVR_STREAM_WIDTH", 960, 320, 1280))
STREAM_Q = int(_envnum("NVR_STREAM_QUALITY", 70, 30, 90))
HI_W = int(_envnum("NVR_FULL_WIDTH", 1920, 960, 3840))      # پخش «تمام‌صفحه/افقی» (از اپ): عرض تصویر (فقط وقتی کسی اینو میبینه ساخته میشه)
HI_Q = int(_envnum("NVR_FULL_QUALITY", 85, 50, 95))
HI_FPS = _envnum("NVR_FULL_FPS", 20, 3, 30)
ENH_FPS = _envnum("NVR_ENHANCE_FPS", 15, 3, 30)           # وقتی «بهبود کیفیت» روشنه، فریم‌ریت پخش حداکثر این‌قدره (CPU)
_fail = {}          # {کانال: (زمان شکست، پیام)}
REPORTS = {}        # {کانال: خطوط گزارش آخرین اسکن}


def _parse_channels():
    out = []
    for x in re.split(r"[,\s]+", os.environ.get("NVR_CHANNELS", "1,2")):
        if x.isdigit() and 1 <= int(x) <= 16 and int(x) not in out:
            out.append(int(x))
    return out[:4] or [1]


CHANNELS = _parse_channels()


def enabled():
    return bool(IP or URL)


def port_open(host, port, t=1.5):
    try:
        with socket.create_connection((host, port), timeout=t):
            return True
    except OSError:
        return False


def _md5(s):
    return hashlib.md5(s.encode("utf-8", "replace")).hexdigest()


def candidates(ip, user, pw, ch, port):
    """(name, آدرس برای تست، آدرس برای OpenCV، آیا با هدر لاگین میشه، رمز)"""
    from urllib.parse import quote
    base = f"rtsp://{ip}:{port}"
    ui = f"{quote(user, safe='')}:{quote(pw, safe='')}@"
    out = []
    for nm, st in (("xmeye-sub", 1), ("xmeye-main", 0)):
        u = f"{base}/user={user}&password={pw}&channel={ch}&stream={st}.sdp?real_stream"
        out.append((nm, u, u, False, pw))
    u = f"{base}/user={user}_password={pw}_channel={ch}_stream=0.sdp?real_stream"
    out.append(("xmeye-alt", u, u, False, pw))
    paths = [
        ("dahua-sub", f"/cam/realmonitor?channel={ch}&subtype=1"),
        ("dahua-main", f"/cam/realmonitor?channel={ch}&subtype=0"),
        ("hik-sub", f"/Streaming/Channels/{ch}02"),
        ("hik-main", f"/Streaming/Channels/{ch}01"),
        ("h264-sub", f"/h264/ch{ch}/sub/av_stream"),
        ("h264-main", f"/h264/ch{ch}/main/av_stream"),
        ("reolink-sub", f"/h264Preview_{ch:02d}_sub"),
        ("reolink-main", f"/h264Preview_{ch:02d}_main"),
        ("live-ch", f"/live/ch{ch:02d}_1"),
        ("ch-1", f"/ch{ch:02d}/1"),
        ("num", f"/{ch}"),
        ("num-1", f"/{ch}1"),
        ("stream", f"/stream{ch}"),
        ("num-2", f"/{ch}2"),
        ("ch-0", f"/ch{ch:02d}/0"),
        ("av0", f"/av0_{ch - 1}"),
        ("live-ch0", f"/live/ch{ch:02d}_0"),
        ("media-video", f"/media/video{ch}"),
        ("samsung", f"/profile{ch}/media.smp"),
        ("cam-h264", f"/cam{ch}/h264"),
        ("video", f"/video{ch}"),
        ("onvif-path", f"/onvif{ch}"),
        ("live-sdp", f"/live{ch}.sdp"),
        ("mpeg4", f"/mpeg4/ch{ch}/main/av_stream"),
        ("tiandy", f"/{ch}/1"),
        ("tiandy-sub", f"/{ch}/2"),
        ("uniview", f"/unicast/c{ch}/s1/live"),
        ("uniview-main", f"/unicast/c{ch}/s0/live"),
        ("tvt", f"/chID={ch}&streamType=main&linkType=tcp"),
        ("tvt-sub", f"/chID={ch}&streamType=sub&linkType=tcp"),
        ("sunell", f"/ch{ch:02d}.264"),
        ("geo", f"/CH{ch:03d}.sdp"),
        ("live-main", "/live/main"),
        ("live-0-sub", "/live/0/SUB"),
        ("live-0-main", "/live/0/MAIN"),
        ("dahua-onvif", f"/cam/realmonitor?channel={ch}&subtype=0&unicast=true&proto=Onvif"),
        ("hik-q", f"/Streaming/Channels/{ch}01?transportmode=unicast&profile=Profile_1"),
        ("ch-main", f"/ch{ch}/main/av_stream"),
        ("ch-sub", f"/ch{ch}/sub/av_stream"),
        ("udp-av0", f"/udp/av0_{ch - 1}"),
        ("root", "/"),
    ]
    for nm, p in paths:
        out.append((nm, base + p, f"rtsp://{ui}{ip}:{port}{p}", True, pw))
    return out


def _read_response(s):
    data = b""
    while b"\r\n\r\n" not in data and len(data) < 65536:
        c = s.recv(4096)
        if not c:
            break
        data += c
    lines = data.split(b"\r\n\r\n", 1)[0].decode("latin1", "replace").split("\r\n")
    m = re.match(r"RTSP/\d\.\d\s+(\d+)", lines[0]) if lines and lines[0] else None
    if not m:
        return None, {}
    hdr = {}
    for ln in lines[1:]:
        if ":" in ln:
            k, v = ln.split(":", 1)
            hdr.setdefault(k.strip().lower(), []).append(v.strip())
    return int(m.group(1)), hdr


def _auth_header(method, uri, user, pw, www):
    for v in www:
        if v.lower().startswith("digest"):
            p = {}
            for k, a, b in re.findall(r'(\w+)=(?:"([^"]*)"|([^,\s]*))', v[6:]):
                p[k.lower()] = a or b
            ha1 = _md5(f"{user}:{p.get('realm', '')}:{pw}")
            ha2 = _md5(f"{method}:{uri}")
            nonce = p.get("nonce", "")
            qop = (p.get("qop", "").split(",")[0]).strip()
            h = f'Digest username="{user}", realm="{p.get("realm", "")}", nonce="{nonce}", uri="{uri}"'
            if qop:
                nc, cn = "00000001", os.urandom(8).hex()
                resp = _md5(f"{ha1}:{nonce}:{nc}:{cn}:{qop}:{ha2}")
                h += f', response="{resp}", qop={qop}, nc={nc}, cnonce="{cn}"'
            else:
                h += f', response="{_md5(f"{ha1}:{nonce}:{ha2}")}"'
            return h
    for v in www:
        if v.lower().startswith("basic"):
            return "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()
    return None


def _describe(host, port, uri, auth=None, timeout=2.0):
    try:
        with socket.create_connection((host, port), timeout=timeout) as s:
            s.settimeout(timeout)
            h = f"DESCRIBE {uri} RTSP/1.0\r\nCSeq: 1\r\nUser-Agent: HomePlayer\r\nAccept: application/sdp\r\n"
            if auth:
                h += f"Authorization: {auth}\r\n"
            s.sendall((h + "\r\n").encode("latin1", "replace"))
            return _read_response(s)
    except OSError:
        return None, {}


def probe(ip, port, req_url, user, pw, header_auth):
    """وضعیت RTSP آدرس رو برمیگردونه (200 = سالم، 401 = یوزر/رمز، 404 = آدرس اشتباه، None = جواب نداد) و اینکه لاگین فرستاده شد یا نه."""
    st, hdr = _describe(ip, port, req_url)
    if st == 401 and header_auth:
        a = _auth_header("DESCRIBE", req_url, user, pw, hdr.get("www-authenticate", []))
        if a:
            st2, _ = _describe(ip, port, req_url, a)
            return st2, True
    return st, False


# ---------------- ONVIF: از خود NVR آدرس RTSP رو میپرسه (وقتی برندش معلوم نیست) ----------------
def _esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _wsse(user, pw, digest, offset=0.0):
    created = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + offset))
    nonce = os.urandom(16)
    pre = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#"
    if digest:
        pwd = base64.b64encode(hashlib.sha1(nonce + created.encode() + pw.encode("utf-8")).digest()).decode()
        ptype = pre + "PasswordDigest"
    else:
        pwd, ptype = _esc(pw), pre + "PasswordText"
    return ('<s:Header><Security s:mustUnderstand="1" xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">'
            f'<UsernameToken><Username>{_esc(user)}</Username><Password Type="{ptype}">{pwd}</Password>'
            f'<Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">{base64.b64encode(nonce).decode()}</Nonce>'
            f'<Created xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">{created}</Created>'
            '</UsernameToken></Security></s:Header>')


def _soap(url, body, user, pw, timeout=3.0, offset=0.0, noauth=False):
    import urllib.request
    import urllib.error
    for digest in ((True,) if noauth else (True, False)):
        env = ('<?xml version="1.0" encoding="utf-8"?><s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
               f'{"" if noauth else _wsse(user, pw, digest, offset)}<s:Body>{body}</s:Body></s:Envelope>')
        req = urllib.request.Request(url, env.encode("utf-8"), {"Content-Type": "application/soap+xml; charset=utf-8"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                txt = r.read().decode("utf-8", "replace")
                if "Fault" not in txt[:2000]:
                    return txt
        except urllib.error.HTTPError as e:
            if e.code not in (400, 401, 403, 500):
                return None
        except Exception:
            return None
    return None


def _onvif_offset(base):
    """اختلاف ساعت NVR با کامپیوتر (ثانیه)؛ ONVIF اگه ساعت‌ها خیلی فرق کنه رمز درست رو هم رد میکنه."""
    import calendar
    r = _soap(base + "/onvif/device_service", '<GetSystemDateAndTime xmlns="http://www.onvif.org/ver10/device/wsdl"/>', "", "", noauth=True)
    if not r:
        return 0.0
    m = re.search(r"UTCDateTime>.*?Hour>(\d+)<.*?Minute>(\d+)<.*?Second>(\d+)<.*?Year>(\d+)<.*?Month>(\d+)<.*?Day>(\d+)<", r, re.S)
    if not m:
        return 0.0
    h, mi, se, y, mo, d = map(int, m.groups())
    try:
        return calendar.timegm((y, mo, d, h, mi, se)) - time.time()
    except Exception:
        return 0.0


def onvif_streams(ip, user, pw, ports=(80, 8080, 8000, 8899, 2020, 5000, 8081, 888, 8999), log=None, ch=1, hd=False):
    """[(name, rtsp_url_with_login)] از ONVIF؛ خالی اگه NVR ONVIF نداشت یا رمز غلط بود."""
    from urllib.parse import quote
    say = log or (lambda *a: None)
    out = []
    for port in ports:
        if not port_open(ip, port, 0.7):
            continue
        base = f"http://{ip}:{port}"
        off = _onvif_offset(base)
        if abs(off) > 60:
            say(f"  onvif: ساعت NVR {int(off)} ثانیه با کامپیوتر فرق داره (جبران شد)")
        caps = _soap(base + "/onvif/device_service",
                     '<GetCapabilities xmlns="http://www.onvif.org/ver10/device/wsdl"><Category>Media</Category></GetCapabilities>', user, pw, offset=off)
        media = None
        if caps:
            for x in re.findall(r"<[\w:]*XAddr>\s*(https?://[^<\s]+)\s*</", caps):
                if "media" in x.lower():
                    media = re.sub(r"^https?://[^/]+", base, x)
                    break
        for m in ([media] if media else []) + [base + "/onvif/media_service", base + "/onvif/Media", base + "/onvif/device_service"]:
            prof = _soap(m, '<GetProfiles xmlns="http://www.onvif.org/ver10/media/wsdl"/>', user, pw, offset=off)
            toks = re.findall(r'<[\w:]*Profiles[^>]*\btoken="([^"]+)"', prof or "")
            say(f"  onvif {base} {m.split(base)[-1]}: {len(toks)} پروفایل")
            if not toks:
                continue
            if ch <= 1:
                order = (toks[:1] + toks[1:2] + toks[2:4]) if hd else (toks[1:2] + toks[:1] + toks[2:4])   # عادی: اول زیراستریم (سبک‌تر)؛ HD: اول اصلی
            else:                                              # هر کانال معمولا دو پروفایل داره (اصلی + فرعی)
                per = 2 if len(toks) >= 2 * ch else 1
                off = (ch - 1) * per
                if per == 2:
                    order = (toks[off:off + 1] + toks[off + 1:off + 2]) if hd else (toks[off + 1:off + 2] + toks[off:off + 1])
                else:
                    order = toks[off:off + 1]
                if not order:
                    say(f"  onvif: کانال {ch} پروفایلی نداره")
                    continue
            for tok in order:
                r = _soap(m, '<GetStreamUri xmlns="http://www.onvif.org/ver10/media/wsdl"><StreamSetup>'
                             '<Stream xmlns="http://www.onvif.org/ver10/schema">RTP-Unicast</Stream>'
                             '<Transport xmlns="http://www.onvif.org/ver10/schema"><Protocol>RTSP</Protocol></Transport>'
                             f'</StreamSetup><ProfileToken>{_esc(tok)}</ProfileToken></GetStreamUri>', user, pw, offset=off)
                mm = re.search(r"<[\w:]*Uri>\s*(rtsp://[^<\s]+)\s*</", r or "")
                if mm:
                    uri = mm.group(1).replace("&amp;", "&")
                    uri = re.sub(r"^rtsp://(?:[^@/]*@)?[^/:]+", f"rtsp://{quote(user, safe='')}:{quote(pw, safe='')}@{ip}", uri)
                    out.append((f"onvif-{tok}", uri))
            if out:
                return out
    return out


def _cache_all():
    try:
        d = json.loads(CACHE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _cached(ch, hd=False):
    d = _cache_all()
    if hd:
        return d.get(f"{ch}:hd") or next((v for k, v in d.items() if k.endswith(":hd") and isinstance(v, str)), None)
    return d.get(str(ch)) or d.get("name") or next((v for k, v in d.items() if k != "name" and not k.endswith(":hd") and isinstance(v, str)), None)


def remember(name, ch=1, hd=False):
    try:
        d = _cache_all()
        d[f"{ch}:hd" if hd else str(ch)] = name
        CACHE.write_text(json.dumps(d), encoding="utf-8")
    except Exception:
        pass


LAST_REPORT = []
HTTP_PORTS = (80, 8080)


def fingerprint(ip, port, say):
    """چند خط اطلاعات از خود دستگاه (مدل/نرم‌افزار سرور) تا بشه برندش رو فهمید."""
    try:
        with socket.create_connection((ip, port), timeout=2) as s:
            s.settimeout(2)
            s.sendall(f"OPTIONS rtsp://{ip}:{port}/ RTSP/1.0\r\nCSeq: 1\r\nUser-Agent: HomePlayer\r\n\r\n".encode())
            st, h = _read_response(s)
        say(f"RTSP OPTIONS -> {st} | server={h.get('server', [''])[0][:50]} | public={h.get('public', [''])[0][:70]}")
    except OSError:
        say("RTSP OPTIONS -> بی‌جواب")
    import urllib.request
    for hp in HTTP_PORTS:
        if port_open(ip, hp, 0.7):
            try:
                with urllib.request.urlopen(f"http://{ip}:{hp}/", timeout=3) as r:
                    body = r.read(4000).decode("latin1", "replace")
                    srv = r.headers.get("Server", "")
                t = re.search(r"<title>(.*?)</title>", body, re.I | re.S)
                say(f"HTTP :{hp} server={srv[:40]} title={(t.group(1).strip()[:50] if t else '-')}")
            except Exception as e:
                say(f"HTTP :{hp} -> {str(e)[:60]}")


def fetch_jpeg(url, user, pw, timeout=4.0):
    """(bytes|None, http_code|None): یه عکس JPEG از آدرس HTTP (با لاگین Basic/Digest)."""
    import urllib.request
    import urllib.error
    pm = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    pm.add_password(None, url, user, pw)
    op = urllib.request.build_opener(urllib.request.HTTPBasicAuthHandler(pm), urllib.request.HTTPDigestAuthHandler(pm))
    try:
        with op.open(url, timeout=timeout) as r:
            data = r.read(3_000_000)
        return (data if data[:2] == b"\xff\xd8" else None), 200
    except urllib.error.HTTPError as e:
        return None, e.code
    except Exception:
        return None, None


def snapshot_scan(ip, user, pw, ch, say):
    """آدرس عکس لحظه‌ای (HTTP) رایج: وقتی RTSP/ONVIF نبود، تصویر رو با عکس پشت‌سرهم میگیریم."""
    from urllib.parse import quote
    cred = f"user={quote(user, safe='')}&password={quote(pw, safe='')}"
    paths = [
        f"/webcapture.jpg?command=snap&channel={ch}&{cred}",
        f"/cgi-bin/snapshot.cgi?channel={ch}",
        "/cgi-bin/snapshot.cgi",
        f"/Streaming/channels/{ch}01/picture",
        f"/ISAPI/Streaming/channels/{ch}01/picture",
        f"/webcapture.jpg?command=snap&channel={ch}",
        "/snapshot.jpg", "/snap.jpg", "/tmpfs/auto.jpg", "/image/jpeg.cgi", "/jpg/image.jpg", "/axis-cgi/jpg/image.cgi",
        f"/cgi-bin/api.cgi?cmd=Snap&channel={ch - 1}&rs=hp&{cred}",
        f"/cgi-bin/snapshot.cgi?chn={ch}&u={quote(user, safe='')}&p={quote(pw, safe='')}",
    ]
    t0, denied, rows = time.time(), 0, []
    for port in HTTP_PORTS:
        if not port_open(ip, port, 0.7):
            continue
        for p in paths:
            if time.time() - t0 > 20 or denied >= 2:
                break
            url = f"http://{ip}:{port}{p}"
            data, code = fetch_jpeg(url, user, pw, 3.0)
            rows.append(f"{p.split('?')[0].split('/')[-1] or '/'}={code}{'*' if data else ''}")
            if data:
                say("HTTP snapshots: " + " ".join(rows))
                return url
            if code == 401:
                denied += 1
    if rows:
        say("HTTP snapshots: " + " ".join(rows))
    return None


def scan(ip, user, pw, ch, port, url="", log=None, max_hits=3, onvif_ports=(80, 8080, 8000, 8899, 2020, 5000, 8081, 888, 8999), force=False, hd=False):
    """برمیگردونه (لیست [(name, url)] منبع‌های سالم، پیام خطا). url که با http شروع بشه یعنی «عکس لحظه‌ای».
    گزارش کامل (برای نمایش تو صفحه) تو LAST_REPORT میمونه."""
    global LAST_REPORT
    rep = []

    def say(*a):
        line = " ".join(str(x) for x in a)
        rep.append(line)
        if log:
            log(line)

    def done(hits, msg):
        global LAST_REPORT
        LAST_REPORT = rep
        REPORTS[ch] = rep
        return hits, msg

    if url:
        return done([("custom", url)], "")
    if not port_open(ip, port):
        others = [p for p in (80, 8000, 37777, 34567, 5000, 443) if port_open(ip, p, 0.7)]
        msg = (f"NVR ({ip}) روی پورت RTSP {port} جواب نمیده" +
               (f" (پورت‌های باز: {others})؛ تو منوی شبکه‌ی NVR گزینه‌ی RTSP رو فعال کن یا پورتش رو با NVR_RTSP_PORT بذار."
                if others else "؛ IP، کابل شبکه و روشن بودن NVR رو چک کن."))
        say("RTSP port closed; open ports:", others)
        try:                                   # شاید RTSP رو روی پورت دیگه‌ای گذاشته؛ ONVIF پورت درست رو میگه
            ov = onvif_streams(ip, user, pw, onvif_ports, log=say, ch=ch, hd=hd)
        except Exception:
            ov = []
        return done(ov, "") if ov else done([], msg)
    last = _cached(ch, hd)
    ft = _fail.get(ch)
    if not last and not force and ft and time.time() - ft[0] < 120:
        return [], ft[1]              # تازه شکست خورده: بی‌خودی رمز غلط رو تکرار نکنیم (قفل نشه)
    cands = []
    for p in dict.fromkeys([pw, ""]):
        for c in candidates(ip, user, p, ch, port):
            cands.append((c[0] + ("" if p == pw else "+nopass"),) + c[1:])
    if hd:                                                 # HD = استریم اصلی (main) اول
        def _rank(nm):
            n = nm.lower()
            return 0 if "main" in n else (2 if "sub" in n else 1)
        cands.sort(key=lambda c: (c[0].endswith("+nopass"), _rank(c[0])))
    cands.sort(key=lambda c: c[0] != last)
    hits, stats, auth_fail, t0, rows, seen401 = [], {}, 0, time.time(), [], False
    for name, req, opn, hauth, p in cands:
        if time.time() - t0 > 25 or (name.endswith("+nopass") and (hits or not seen401)):
            break
        st, sent = probe(ip, port, req, user, p, hauth)
        stats[st] = stats.get(st, 0) + 1
        rows.append(f"{name}={st}")
        seen401 = seen401 or st == 401
        if st == 200:
            hits.append((name, opn))
            if len(hits) >= max_hits:
                break
        elif st == 401 and sent:
            auth_fail += 1
            if auth_fail >= 3:
                break
    say("RTSP: " + (" ".join(rows) if len(rows) <= 14 else " ".join(rows[:8]) + f" … ({len(rows)} آدرس امتحان شد؛ نتیجه‌ها: {stats})"))
    if hits:
        _fail.pop(ch, None)
        return done(hits, "")
    if auth_fail < 3:
        try:
            ov = onvif_streams(ip, user, pw, onvif_ports, log=say, ch=ch, hd=hd)
        except Exception as e:
            say("onvif error:", e)
            ov = []
        if ov:
            _fail.pop(ch, None)
            return done(ov, "")
        try:
            sn = snapshot_scan(ip, user, pw, ch, say)
        except Exception as e:
            say("snapshot error:", e)
            sn = None
        if sn:
            _fail.pop(ch, None)
            return done([("snapshot", sn)], "")
    try:
        fingerprint(ip, port, say)
    except Exception:
        pass
    if auth_fail >= 3:
        msg = "NVR یوزر/رمز رو قبول نکرد (سه بار امتحان کردم و ایستادم تا NVR قفل نشه). NVR_USER و NVR_PASS رو تو start.bat چک کن."
    elif set(stats) == {None}:
        msg = "NVR به درخواست RTSP هیچ جوابی نداد (RTSP تو دستگاه خاموشه یا مدل خیلی قدیمیه). آدرس دقیق رو با VLC پیدا کن و با CAMERA_URL بذار."
    else:
        msg = (f"NVR جواب میده ولی هیچ آدرس RTSP/ONVIF/عکس شناخته‌شده‌ای پیدا نشد (نتیجه‌ی RTSP: {stats}؛ 451/404 یعنی آدرس رو نمیشناسه). "
               "گزارش پایین رو برای من بفرست یا آدرس دقیق رو با CAMERA_URL تو start.bat بذار.")
    _fail[ch] = (time.time(), msg)
    return done([], msg)


class NetCap:
    """خوندن RTSP تو یه ترد جدا و نگه داشتن فقط آخرین فریم (بدون تاخیر انباشته). مثل VideoCapture: read/isOpened/release.
    release فقط علامت میذاره؛ خود ترد بعد از تموم شدن read دوربین رو میبنده (بستن همزمان باعث کرش OpenCV میشد)."""

    def __init__(self, cap):
        self.cap, self.img, self.seq, self.seen = cap, None, 0, 0
        self.stop = self.dead = False
        self.cv = threading.Condition()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            last_r, gap = 0.0, 1.0 / DECODE_FPS
            while not self.stop:
                try:
                    ok = self.cap.grab()
                    img = None
                    if ok:
                        if time.time() - last_r < gap:
                            continue                    # این فریم فقط رد میشه (دیکد شده ولی رنگی/کپی نمیشه)
                        ok, img = self.cap.retrieve()
                        last_r = time.time()
                except Exception:
                    ok, img = False, None
                if not ok or img is None:
                    break
                with self.cv:
                    self.img, self.seq = img, self.seq + 1
                    self.cv.notify_all()
        finally:
            self.dead = True
            try:
                self.cap.release()
            except Exception:
                pass
            with self.cv:
                self.cv.notify_all()

    def isOpened(self):
        return not self.dead

    def read(self):
        with self.cv:
            if self.seq == self.seen and not self.dead:
                self.cv.wait(0.3)
            if self.seq == self.seen or self.img is None:
                return False, None
            self.seen = self.seq
            return True, self.img.copy()

    def release(self):
        self.stop = True


class SnapCap:
    """مثل VideoCapture ولی با عکس‌های پشت‌سرهم از آدرس HTTP (حدود ۲ فریم در ثانیه)."""

    def __init__(self, url, user, pw):
        self.url, self.user, self.pw, self.t = url, user, pw, 0.0

    def isOpened(self):
        return True

    def read(self):
        import numpy as np
        import cv2
        wait = 0.5 - (time.time() - self.t)
        if wait > 0:
            time.sleep(wait)
        self.t = time.time()
        data, _ = fetch_jpeg(self.url, self.user, self.pw, 5.0)
        if not data:
            return False, None
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        return (img is not None), img

    def release(self):
        pass


class NvrFeed:
    """پخش/تحلیل یه کانال NVR جدا از وب‌کم. فقط وقتی کسی تماشا میکنه یا تشخیص آدم روشنه وصل میشه.
    دلیل خطا رو نگه میداره تا تو صفحه نشون بدیم."""

    def __init__(self, ch=1):
        from collections import deque
        self.ch = ch
        self.lock = threading.Lock()
        self.users, self.thread = 0, None
        self.jpg, self.view, self.ts = None, None, 0.0     # jpg: تمیز (عکس/ویدیو)، view: با کادر تشخیص (فقط پخش زنده)
        self.raw, self.seq = None, 0                       # آخرین تصویر خام (برای تحلیل آدم)
        self.boxes, self.boxes_t = [], 0.0                 # کادرهای تحلیل‌گر: [(x, y, w, h, label, (b, g, r))]
        self.keep_ring, self.ring = False, deque(maxlen=48)   # چند ثانیه‌ی قبل از رویداد (برای ویدیو)
        self.hd, self.enhance, self.hd_active = False, False, False   # HD = استریم اصلی؛ بهبود = روشن/کنتراست/نویز/تیزی
        self.enh, self.reconnect = None, False
        self.viewers = 0                                    # چند نفر پخش زنده میبینن (بدون بیننده JPEG ساخته نمیشه)
        self.hi_viewers, self.jpg_hi = 0, None              # بیننده‌های تمام‌صفحه: استریم اصلی + JPEG بزرگ‌تر
        self.state, self.err, self.name, self.report = "idle", "", "", []

    def acquire(self):
        with self.lock:
            self.users += 1
            if self.thread is None:
                self.thread = threading.Thread(target=self._loop, daemon=True)
                self.thread.start()

    def release(self):
        with self.lock:
            self.users = max(0, self.users - 1)

    def snapshot_jpg(self, q=88):
        """عکس باکیفیت از آخرین فریم"""
        import cv2
        img = self.raw
        if img is None:
            return None
        if self.enhance:
            try:
                import enhance
                img = enhance.still(img)
            except Exception:
                pass
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
        return buf.tobytes() if ok else None

    def set_hd(self, on):
        on = bool(on)
        if on != self.hd:
            self.hd = on
            self.reconnect = True                           # دوباره وصل شو با استریم دیگه

    def status(self):
        return {"ch": self.ch, "hd": self.hd, "hd_active": self.hd_active, "enhance": self.enhance, "state": self.state, "err": self.err, "name": self.name, "report": self.report[-14:],
                "age": (round(time.time() - self.ts, 1) if self.ts else None)}

    def _connect(self):
        try:
            import cv2
        except ImportError:
            self.state, self.err = "error", "opencv نصب نیست"
            return None
        self.state, self.err = "connecting", ""
        last_msg, tried_hd = "", self.hd
        for q in ([True, False] if self.hd else [False]):
            hits, msg = scan(IP, USER, PASS, self.ch, PORT, URL, hd=q)
            self.report = list(REPORTS.get(self.ch, []))
            if not hits:
                last_msg = msg
                continue
            for name, url in hits:
                cap, ok = None, False
                try:
                    if url.startswith("http"):
                        cap = SnapCap(url, USER, PASS)
                        ok, _ = cap.read()
                    else:
                        try:
                            cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG, [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000])
                        except Exception:
                            cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
                        if cap.isOpened():
                            for _ in range(5):
                                ok, img = cap.read()
                                if ok and img is not None:
                                    break
                                ok = False
                except Exception as e:
                    self.report.append(f"open {name}: {str(e)[:80]}")
                if ok:
                    remember(name, self.ch, q)
                    self.name, self.state, self.err = name, "ok", ""
                    self.hd_active = bool(q and "sub" not in name.lower())
                    if tried_hd and not q:
                        self.report.append("HD کار نکرد (شاید H.265 یا استریم اصلی نداره)؛ استریم عادی نشون داده میشه")
                    return cap if url.startswith("http") else NetCap(cap)
                self.report.append(f"{name}: آدرس جواب داد ولی تصویر نیومد")
                try:
                    if cap is not None:
                        cap.release()
                except Exception:
                    pass
            last_msg = ("آدرس جواب داد ولی تصویر نیومد (شاید کدک H.265 ـه یا NVR تعداد اتصال رو محدود کرده). "
                        "تو NVR استریم فرعی رو روی H.264 بذار.")
        self.state, self.err, self.hd_active = "error", last_msg, False
        return None

    def _draw(self, img):
        """کادرهای تشخیص روی تصویر پخش زنده (فقط تا ۱.۵ ثانیه بعد از آخرین تشخیص)"""
        import cv2
        if not self.boxes or time.time() - self.boxes_t > 1.5:
            return None
        out = img.copy()
        for (x, y, w, h, label, col) in list(self.boxes):
            cv2.rectangle(out, (x, y), (x + w, y + h), col, 3)
            cv2.putText(out, label, (x, max(16, y - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2, cv2.LINE_AA)
        return out

    def _loop(self):
        import cv2
        cap, fails, retry, last_ring, last_enc, last_hi = None, 0, 0.0, 0.0, 0.0, 0.0
        while True:
            with self.lock:
                if self.users <= 0:
                    self.thread, self.jpg, self.view, self.raw, self.state = None, None, None, None, "idle"
                    self.jpg_hi = None
                    self.ring.clear()
                    break
            try:
                if self.reconnect:                                  # HD عوض شد: دوباره وصل شو
                    self.reconnect = False
                    if cap is not None:
                        try:
                            cap.release()
                        except Exception:
                            pass
                    cap, retry = None, 0.0
                if cap is None:
                    if time.time() < retry:
                        time.sleep(0.5)
                        continue
                    cap = self._connect()
                    if cap is None:
                        retry = time.time() + 20
                        continue
                    fails = 0
                ok, img = cap.read()
                if not ok:
                    fails += 1
                    if fails > 40:
                        cap.release()
                        cap, retry, self.state = None, time.time() + 3, "connecting"
                    time.sleep(0.05)
                    continue
                fails = 0
                h, w = img.shape[:2]
                full = img                                           # تصویر اصلی (بزرگ) فقط برای پخش تمام‌صفحه
                if w > 960:
                    img = cv2.resize(img, (960, int(h * 960 / w)))
                now = time.time()
                self.raw, self.seq, self.ts = img, self.seq + 1, now
                if self.keep_ring and now - last_ring >= 0.2:        # چند ثانیه‌ی قبل از رویداد (برای ویدیو)
                    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 75])
                    if ok:
                        last_ring = now
                        self.ring.append((now, buf.tobytes()))
                if self.viewers > 0 and now - last_enc >= 1.0 / (min(STREAM_FPS, ENH_FPS) if self.enhance else STREAM_FPS):   # پخش زنده: فقط وقتی کسی میبینه
                    last_enc = now
                    base = img
                    if self.enhance:                                  # «✨ بهبود کیفیت»
                        try:
                            if self.enh is None:
                                import enhance
                                self.enh = enhance.Enhancer()
                            base = self.enh.apply(img)
                        except Exception as e:
                            self.report.append(f"enhance: {str(e)[:60]}")
                            self.enhance = False
                    ov = self._draw(base)
                    src = ov if ov is not None else base
                    if src.shape[1] > STREAM_W:
                        src = cv2.resize(src, (STREAM_W, int(src.shape[0] * STREAM_W / src.shape[1])))
                    ok, buf = cv2.imencode(".jpg", src, [cv2.IMWRITE_JPEG_QUALITY, STREAM_Q])
                    if ok:
                        self.jpg = self.view = buf.tobytes()
                if self.hi_viewers > 0 and now - last_hi >= 1.0 / HI_FPS:     # پخش تمام‌صفحه: بدون کادر/بهبود، با بیشترین جزئیات
                    last_hi = now
                    fs = full
                    if fs.shape[1] > HI_W:
                        fs = cv2.resize(fs, (HI_W, int(fs.shape[0] * HI_W / fs.shape[1])), interpolation=cv2.INTER_AREA)
                    ok, buf = cv2.imencode(".jpg", fs, [cv2.IMWRITE_JPEG_QUALITY, HI_Q])
                    if ok:
                        self.jpg_hi = buf.tobytes()
                elif self.hi_viewers <= 0:
                    self.jpg_hi = None
            except Exception as e:
                self.report.append(f"loop: {str(e)[:80]}")
                self.report = self.report[-30:]
                time.sleep(0.5)
            time.sleep(0.03)
        if cap is not None:
            cap.release()
