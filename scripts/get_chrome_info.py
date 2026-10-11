import subprocess

cmd = ["powershell", "-NoProfile", "-Command", "Get-CimInstance -ClassName Win32_Process -Filter \"Name = 'chrome.exe'\" | Select-Object -ExpandProperty CommandLine"]
try:
    out = subprocess.check_output(cmd, text=True, errors="replace")
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    for l in lines[:5]:
        print("CHROME:", l[:300])
except Exception as e:
    print("Error:", e)
