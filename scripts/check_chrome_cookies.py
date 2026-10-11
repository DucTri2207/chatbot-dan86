import os
import sqlite3
import shutil

p = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data\Default\Network\Cookies")
print("Cookies file exists:", os.path.exists(p))
if os.path.exists(p):
    shutil.copy(p, "cookies_temp.db")
    con = sqlite3.connect("cookies_temp.db")
    cur = con.cursor()
    cur.execute("SELECT host_key, name FROM cookies WHERE host_key LIKE '%facebook%' OR host_key LIKE '%meta%'")
    rows = cur.fetchall()
    print("Found rows in user chrome:", len(rows))
    for r in rows:
        print(r)
    con.close()
    try:
        os.remove("cookies_temp.db")
    except Exception:
        pass
