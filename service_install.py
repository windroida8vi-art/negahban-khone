"""نصب / حذف / وضعیت سرویس ویندوز (با Task Scheduler؛ بدون نیاز به برنامه‌ی اضافه).
  install   : سرویس قبل از ورود (SYSTEM) + اجرای کامل بعد از ورود + قانون فایروال
  uninstall : همه رو برمیداره
  status    : وضعیت"""
import os
import subprocess
import sys
import tempfile
from xml.sax.saxutils import escape

import service_main

BASE = os.path.dirname(os.path.abspath(__file__))
TASK_SVC = "HomePlayer-Service"
TASK_DESK = "HomePlayer-Desktop"
OLD_TASK = "HomeMusicPlayer"
DRY = "--dry-run" in sys.argv


def sh(args):
    if DRY:
        print("   $", " ".join(args))
        return 0, ""
    r = subprocess.run(args, capture_output=True, text=True, errors="replace")
    return r.returncode, (r.stdout + r.stderr).strip()


def svc_xml(pythonw, script):
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Home Player core service: runs at boot BEFORE Windows login (NVR, people detection, Telegram, files). The full app takes over after login.</Description>
  </RegistrationInfo>
  <Triggers>
    <BootTrigger>
      <Enabled>true</Enabled>
      <Delay>PT20S</Delay>
    </BootTrigger>
    <TimeTrigger>
      <Repetition>
        <Interval>PT1M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>2020-01-01T00:00:00</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>S-1-5-18</UserId>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>6</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(pythonw)}</Command>
      <Arguments>"{escape(script)}"</Arguments>
      <WorkingDirectory>{escape(BASE)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def firewall(env):
    port = env.get("PLAYER_PORT", os.environ.get("PLAYER_PORT", "8080"))
    sh(["netsh", "advfirewall", "firewall", "delete", "rule", "name=HomeMusicPlayer"])
    args = ["netsh", "advfirewall", "firewall", "add", "rule", "name=HomeMusicPlayer", "dir=in", "action=allow", "protocol=TCP", f"localport={port}"]
    if not env.get("ALLOW_INTERNET"):
        args.append("remoteip=LocalSubnet,100.64.0.0/10")
    sh(args)


def install():
    pythonw = os.path.join(BASE, "venv", "Scripts", "pythonw.exe")
    script = os.path.join(BASE, "service_main.py")
    if not DRY and not os.path.exists(pythonw):
        print("❌ اول یه بار start.bat رو اجرا کن تا پایتون و کتابخونه‌ها نصب بشن.")
        return 1
    if not DRY and not (os.path.exists(os.path.join(BASE, "password.hash")) or service_main.load_bat_env().get("PLAYER_PASSWORD")):
        print("❌ هنوز رمزی ساخته نشده: start.bat رو یه بار اجرا کن (رمز اولیه رو اونجا نشون میده) و بعد اینو بزن.")
        return 1
    env = service_main.load_bat_env()
    print("• قانون فایروال…")
    firewall(env)

    print("• سرویس قبل از ورود (SYSTEM)…")
    xml_path = os.path.join(tempfile.gettempdir(), "homeplayer-service.xml")
    with open(xml_path, "w", encoding="utf-16") as f:
        f.write(svc_xml(pythonw, script))
    code, out = sh(["schtasks", "/Create", "/TN", TASK_SVC, "/XML", xml_path, "/F"])
    if code != 0:
        print("  (روش XML نشد: " + out[:160] + ")\n  روش ساده‌تر…")
        code, out = sh(["schtasks", "/Create", "/TN", TASK_SVC, "/TR", f'"{pythonw}" "{script}"', "/SC", "MINUTE", "/MO", "1",
                        "/RU", "SYSTEM", "/RL", "HIGHEST", "/F"])
    if code != 0:
        print("❌ سرویس ساخته نشد:", out)
        return 1

    print("• اجرای کامل بعد از ورود به ویندوز…")
    code, out = sh(["schtasks", "/Create", "/TN", TASK_DESK, "/TR", f'"{os.path.join(BASE, "start.bat")}"', "/SC", "ONLOGON", "/RL", "HIGHEST", "/F"])
    if code != 0:
        print("❌ کار «بعد از ورود» ساخته نشد:", out)
        return 1
    sh(["schtasks", "/Delete", "/TN", OLD_TASK, "/F"])        # نسخه‌ی قدیمی install-autostart.bat
    if not DRY:
        sh(["schtasks", "/Run", "/TN", TASK_SVC])
    print("""
✅ نصب شد.
  • قبل از ورود به ویندوز (سرویس): سرور وب و ورود، NVR (تصویر/HD/بهبود)، تشخیص آدم NVR + عکس/ویدیو، ربات تلگرام/ntfy،
    مدیریت فایل، آمار سیستم، خواب/ری‌استارت/خاموش، اپ اندروید و کاربر «فقط‌تماشا».
  • بعد از ورود به ویندوز (نسخه‌ی کامل، خودکار جای سرویس رو میگیره): موزیک و صدا، وب‌کم، دسکتاپ و موس/کیبورد،
    میکروفون/صدای سیستم، کلیپ‌بورد، اجرای برنامه، قفل ویندوز، شبیه‌ساز حضور.
  • خروج از ویندوز یا بستن نسخه‌ی کامل: حداکثر تا یک دقیقه بعد سرویس دوباره پورت رو میگیره.
  • لاگ سرویس: service.log   |   وضعیت: service-status.bat   |   حذف: uninstall-service.bat""")
    return 0


def uninstall():
    for t in (TASK_SVC, TASK_DESK, OLD_TASK):
        sh(["schtasks", "/End", "/TN", t])
        code, out = sh(["schtasks", "/Delete", "/TN", t, "/F"])
        print(("✓ حذف شد: " if code == 0 else "— نبود: ") + t)
    try:
        os.remove(os.path.join(BASE, ".service_token"))
    except OSError:
        pass
    print("\nسرویس حذف شد. برای اجرای دستی هنوز start.bat هست؛ اگه فقط اجرای خودکار بعد از ورود رو میخوای install-autostart.bat رو بزن.")
    return 0


def status():
    for t in (TASK_SVC, TASK_DESK):
        code, out = sh(["schtasks", "/Query", "/TN", t, "/FO", "LIST"])
        st = next((l.split(":", 1)[1].strip() for l in out.splitlines() if l.lower().startswith(("status", "وضعیت"))), "؟")
        print(f"{t}: " + ("نصب نیست" if code != 0 else f"نصب‌شده (وضعیت: {st})"))
    port = int(service_main.load_bat_env().get("PLAYER_PORT", "8080"))
    print(f"پورت {port}: " + ("یه نسخه داره جواب میده ✓" if service_main.port_busy(port) else "هیچ نسخه‌ای کار نمیکنه ✗"))
    p = os.path.join(BASE, "service.log")
    if os.path.exists(p):
        print("\nآخرین خط‌های service.log:")
        for l in open(p, encoding="utf-8", errors="replace").read().splitlines()[-8:]:
            print("   " + l[:150])
    return 0


if __name__ == "__main__":
    cmd = next((a for a in sys.argv[1:] if not a.startswith("--")), "")
    sys.exit({"install": install, "uninstall": uninstall, "status": status}.get(cmd, lambda: print(__doc__) or 0)())
