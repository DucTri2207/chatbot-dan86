#!/usr/bin/env python3
"""
scripts/connect_vn_vpn.py
Tự động kết nối OpenVPN Việt Nam miễn phí qua API VPN Gate (ĐH Tsukuba, Nhật Bản).
- Tải danh sách OpenVPN từ http://www.vpngate.net/api/iphone/
- Lọc các server có CountryShort == 'VN'
- Giải mã Base64 file cấu hình .ovpn và khởi chạy OpenVPN ngầm không chặn luồng
- Timeout an toàn: Nếu trong 20s không lấy được IP VN, fallback tiếp tục với IP thường (không làm sập workflow).
"""

import base64
import csv
import io
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [VPN_VN] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("connect_vn_vpn")

VPN_GATE_API_URL = "http://www.vpngate.net/api/iphone/"
MAX_CONNECT_TIMEOUT_SEC = 20
CHECK_INTERVAL_SEC = 2.0


def get_current_ip_info() -> dict:
    """Truy vấn thông tin IP hiện tại từ các dịch vụ IP lookup công cộng với timeout ngắn."""
    urls = [
        "https://api.ipify.org?format=json",
        "https://ipinfo.io/json",
        "http://ip-api.com/json",
    ]
    for url in urls:
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "curl/7.68.0"},
            )
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                ip = data.get("ip") or data.get("query")
                country = data.get("country") or data.get("countryCode")
                city = data.get("city", "Unknown")
                org = data.get("org") or data.get("isp", "Unknown")
                if ip:
                    return {
                        "ip": ip,
                        "country": (country or "").upper(),
                        "city": city,
                        "org": org,
                    }
        except Exception:
            continue
    return {"ip": "Unknown", "country": "Unknown", "city": "Unknown", "org": "Unknown"}


def fetch_vn_vpn_servers() -> list:
    """Tải và phân tích danh sách server OpenVPN từ VPN Gate API, lọc CountryShort == 'VN'."""
    logger.info("Đang truy vấn danh sách server OpenVPN từ VPN Gate (%s)...", VPN_GATE_API_URL)
    try:
        req = urllib.request.Request(
            VPN_GATE_API_URL,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            content = resp.read().decode("utf-8", errors="ignore")
    except Exception as e_fetch:
        logger.warning("Không thể kết nối tới API VPN Gate: %s", e_fetch)
        return []

    lines = content.splitlines()
    data_lines = [l for l in lines if not l.startswith("*")]
    if not data_lines:
        logger.warning("API VPN Gate trả về dữ liệu rỗng.")
        return []

    header_line = data_lines[0].lstrip("#")
    csv_text = "\n".join([header_line] + data_lines[1:])

    reader = csv.DictReader(io.StringIO(csv_text))
    vn_servers = []
    for row in reader:
        c_short = (row.get("CountryShort") or "").strip().upper()
        c_long = (row.get("CountryLong") or "").strip().upper()
        if c_short == "VN" or "VIET" in c_long:
            ovpn_b64 = (row.get("OpenVPN_ConfigData_Base64") or "").strip()
            if ovpn_b64:
                try:
                    score = int(row.get("Score", 0) or 0)
                except ValueError:
                    score = 0
                try:
                    ping = int(row.get("Ping", 9999) or 9999)
                except ValueError:
                    ping = 9999
                try:
                    speed = int(row.get("Speed", 0) or 0)
                except ValueError:
                    speed = 0

                vn_servers.append({
                    "ip": row.get("IP", ""),
                    "hostname": row.get("HostName", ""),
                    "country": c_short,
                    "score": score,
                    "ping": ping,
                    "speed": speed,
                    "ovpn_b64": ovpn_b64,
                })

    # Sắp xếp ưu tiên: Ping thấp nhất, Speed cao nhất, Score cao nhất
    vn_servers.sort(key=lambda x: (x["ping"], -x["speed"], -x["score"]))
    logger.info("Tìm thấy %d server OpenVPN Việt Nam trên VPN Gate.", len(vn_servers))
    return vn_servers


def setup_ovpn_file(server: dict, config_path: str, auth_path: str) -> bool:
    """Giải mã file .ovpn và thêm các tùy chọn đăng nhập/timeout an toàn."""
    try:
        ovpn_content = base64.b64decode(server["ovpn_b64"]).decode("utf-8", errors="ignore")
    except Exception as e_b64:
        logger.warning("Lỗi giải mã cấu hình OpenVPN Base64: %s", e_b64)
        return False

    with open(auth_path, "w", encoding="utf-8") as f_auth:
        f_auth.write("vpn\nvpn\n")

    # Loại bỏ các directive auth-user-pass hoặc auth-nocache trùng lặp
    cleaned_lines = []
    for line in ovpn_content.splitlines():
        st = line.strip().lower()
        if st.startswith("auth-user-pass") or st.startswith("auth-nocache"):
            continue
        cleaned_lines.append(line)

    extra_opts = [
        "",
        "# DAN86 Auto-Config Options",
        f"auth-user-pass {auth_path}",
        "auth-nocache",
        "script-security 2",
        "connect-retry-max 1",
        "connect-timeout 6",
        "",
    ]
    ovpn_full = "\n".join(cleaned_lines) + "\n" + "\n".join(extra_opts)

    with open(config_path, "w", encoding="utf-8") as f_conf:
        f_conf.write(ovpn_full)

    return True


def connect_vpn(server: dict) -> bool:
    """Khởi chạy OpenVPN ngầm và kiểm tra IP trong 20 giây."""
    is_linux = platform.system().lower() == "linux"
    tmp_dir = "/tmp" if is_linux else os.environ.get("TEMP", os.getcwd())
    config_path = os.path.join(tmp_dir, "dan86_vpn_vn.ovpn")
    auth_path = os.path.join(tmp_dir, "dan86_vpn_auth.txt")

    if not setup_ovpn_file(server, config_path, auth_path):
        return False

    logger.info(
        "Đang thử kết nối OpenVPN Việt Nam: %s (Ping: %sms, Speed: %.1f Mbps)...",
        server["ip"],
        server["ping"],
        server["speed"] / 1_000_000 if server["speed"] else 0.0,
    )

    openvpn_bin = shutil.which("openvpn")
    if not openvpn_bin:
        logger.warning("Chưa cài đặt OpenVPN trên hệ thống. Bỏ qua kết nối VPN.")
        return False

    cmd = []
    if is_linux:
        # Trên Linux Ubuntu runner, cần quyền sudo để tạo tun interface
        if shutil.which("sudo"):
            cmd.append("sudo")
        cmd.extend([
            openvpn_bin,
            "--config",
            config_path,
            "--daemon",
            "--verb",
            "1",
            "--log",
            os.path.join(tmp_dir, "dan86_vpn.log"),
        ])
    else:
        # Trên Windows (nếu chạy local)
        cmd.extend([openvpn_bin, "--config", config_path])

    try:
        # Sử dụng Popen với stdin=DEVNULL để tuyệt đối không block tiến trình
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Chờ 1.5s để daemon khởi tạo
        time.sleep(1.5)
    except Exception as e_launch:
        logger.warning("Không thể khởi động OpenVPN: %s", e_launch)
        return False

    logger.info("OpenVPN daemon đã khởi chạy. Đang kiểm tra IP chuyển đổi (tối đa %ds)...", MAX_CONNECT_TIMEOUT_SEC)
    start_time = time.time()
    while time.time() - start_time < MAX_CONNECT_TIMEOUT_SEC:
        time.sleep(CHECK_INTERVAL_SEC)
        info = get_current_ip_info()
        logger.info("IP hiện tại: %s | Quốc gia: %s (%s)", info["ip"], info["country"], info["city"])
        if info["country"] == "VN":
            logger.info(
                "ĐỔI IP THÀNH CÔNG! Đã kết nối OpenVPN Việt Nam: %s (%s - %s)",
                info["ip"],
                info["city"],
                info["org"],
            )
            return True

    logger.warning("Hết thời gian chờ (%ds) nhưng IP chưa chuyển sang Việt Nam.", MAX_CONNECT_TIMEOUT_SEC)
    if is_linux:
        # Dừng daemon nếu kết nối không thành công để trả lại mạng sạch
        try:
            subprocess.run(["sudo", "pkill", "openvpn"], check=False, timeout=3, stdin=subprocess.DEVNULL)
        except Exception:
            pass
    return False


def main():
    logger.info("=== BẮT ĐẦU KIỂM TRA & TỐI ƯU HÓA IP VIỆT NAM (VPN GATE) ===")
    initial_ip_info = get_current_ip_info()
    logger.info(
        "IP ban đầu: %s | Quốc gia: %s (%s, %s)",
        initial_ip_info["ip"],
        initial_ip_info["country"],
        initial_ip_info["city"],
        initial_ip_info["org"],
    )

    if initial_ip_info["country"] == "VN":
        logger.info("Hệ thống đã có sẵn IP Việt Nam (%s). Không cần kết nối VPN.", initial_ip_info["ip"])
        return 0

    servers = fetch_vn_vpn_servers()
    if not servers:
        logger.warning("Không có server Việt Nam nào khả dụng trên VPN Gate lúc này. Tiếp tục chạy với IP mặc định (Fallback).")
        return 0

    # Thử server tốt nhất
    for idx, srv in enumerate(servers[:1], start=1):
        logger.info("Thử kết nối server Việt Nam #%d (%s)...", idx, srv["ip"])
        if connect_vpn(srv):
            return 0
        logger.warning("Server #%d kết nối thất bại hoặc timeout.", idx)

    logger.warning("Server VPN Việt Nam không kết nối được. Fallback tiếp tục với IP thông thường.")
    final_ip_info = get_current_ip_info()
    logger.info("IP hoạt động cuối cùng: %s | Quốc gia: %s", final_ip_info["ip"], final_ip_info["country"])
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e_main:
        logger.error("Lỗi ngoài dự kiến trong connect_vn_vpn (Fallback an toàn): %s", e_main)
        sys.exit(0)
