# --- START OF FILE media_sniffer.py ---

import subprocess
import yt_dlp  # type: ignore
from urllib.parse import urlparse
import urllib3  # type: ignore
from typing import Any, Dict, Optional, Tuple, List, cast, TypedDict, Protocol
from pathlib import Path
from datetime import datetime
import requests
import re
import time
import os
import json
import threading
import ttkbootstrap as ttk  # type: ignore
from tkinter import filedialog, messagebox
import tkinter as tk
import undetected_chromedriver as uc  # type: ignore
import warnings
from requests.exceptions import RequestsDependencyWarning  # type: ignore

warnings.filterwarnings("ignore", category=RequestsDependencyWarning)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
# 嚴格遵守：不使用萬用字元

# --- 型別與協定 (Types & Protocols) ---


class AppSettings(TypedDict, total=False):
    download_path: str
    browser_width: int
    browser_height: int
    debug_mode: bool
    theme: str
    hide_delay: int


class MediaItem(TypedDict, total=False):
    title: str
    m3u8: str
    original_url: str
    headers: Dict[str, str]
    checked: bool
    status: str


class LogCallback(Protocol):
    def __call__(self, msg: str) -> None: ...


class UpdateProgressCallback(Protocol):
    def __call__(self, title: str, val: float) -> None: ...


class SniffResultCallback(Protocol):
    def __call__(self, result: Optional[MediaItem], msg: str) -> None: ...


class UpdateRowCallback(Protocol):
    def __call__(
        self,
        idx: int,
        status: str,
        tag: Optional[str] = None,
        new_url: Optional[str] = None,
        new_headers: Optional[Dict[str, str]] = None
    ) -> None: ...


# --- 設定與常數 ---
APP_NAME: str = "MediaSniffer_Pro_Artist"
CONFIG_DIR: Path = Path.home() / APP_NAME
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_FILE: Path = CONFIG_DIR / "settings.json"

THEME_MAP: Dict[str, str] = {
    "Cosmo (現代白)": "cosmo",
    "Flatly (扁平化)": "flatly",
    "Journal (書卷氣)": "journal",
    "Litera (簡約風)": "litera",
    "Lumen (光亮)": "lumen",
    "Minty (薄荷綠)": "minty",
    "Darkly (暗黑模式)": "darkly",
    "Superhero (超人)": "superhero",
    "Solar (太陽能)": "solar",
    "Cyborg (賽博龐克)": "cyborg",
    "Vapor (蒸汽波)": "vapor"
}


def get_default_settings() -> AppSettings:
    return {
        "download_path": str(Path.home() / "Downloads"),
        "browser_width": 1280,
        "browser_height": 720,
        "debug_mode": False,
        "theme": "cosmo",
        "hide_delay": 5
    }


DEFAULT_SETTINGS: AppSettings = get_default_settings()

# --- M3U 處理器 ---


class M3UHandler:
    @staticmethod
    def parse_file(filepath: str) -> List[MediaItem]:
        items: List[MediaItem] = []
        current_item: MediaItem = {}
        lines: List[str] = []

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            with open(filepath, 'r', encoding='gbk') as f:
                lines = f.readlines()

        for line_raw in lines:
            line: str = line_raw.strip()
            if not line:
                continue

            if line.startswith("#EXT-ORI-URL:"):
                current_item["original_url"] = line.split(":", 1)[1].strip()

            elif line.startswith("#EXTINF:"):
                parts: List[str] = line.split(",", 1)
                if len(parts) > 1:
                    current_item["title"] = parts[1].strip()
                else:
                    current_item["title"] = "未命名影片"

            elif line.startswith("#EXTVLCOPT:"):
                opt: str = line.split(":", 1)[1]
                if "http-referrer=" in opt:
                    ref: str = opt.split("http-referrer=", 1)[1].strip()
                    headers: Dict[str, str] = current_item.get("headers", {})
                    headers["Referer"] = ref
                    current_item["headers"] = headers

            elif not line.startswith("#"):
                current_item["m3u8"] = line
                if "title" not in current_item:
                    current_item["title"] = f"Imported_{len(items)+1}"
                current_item["status"] = "已匯入"
                current_item["checked"] = True

                items.append(current_item)
                current_item = {}

        return items

    @staticmethod
    def save_file(filepath: str, data_list: List[MediaItem]) -> None:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write("#EXTM3U\n")
            for item in data_list:
                m3u8_url: str = item.get("m3u8", "")
                if not m3u8_url:
                    continue

                ori_url: str = item.get("original_url", "")
                if ori_url:
                    f.write(f"#EXT-ORI-URL:{ori_url}\n")

                title: str = item.get("title", "Unknown Title")
                title = title.replace("\n", " ").replace("\r", "")
                f.write(f"#EXTINF:-1,{title}\n")

                headers: Dict[str, str] = item.get("headers", {})
                referer: Optional[str] = None
                for k, v in headers.items():
                    if k.lower() == "referer":
                        referer = v
                        break

                if referer:
                    f.write(f"#EXTVLCOPT:http-referrer={referer}\n")

                f.write(f"{m3u8_url}\n")

# --- 輔助函式 ---


def load_settings() -> AppSettings:
    current: AppSettings = get_default_settings()
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                data: Dict[str, Any] = json.load(f)
                if "download_path" in data:
                    current["download_path"] = str(data["download_path"])
                if "browser_width" in data:
                    current["browser_width"] = int(data["browser_width"])
                if "browser_height" in data:
                    current["browser_height"] = int(data["browser_height"])
                if "debug_mode" in data:
                    current["debug_mode"] = bool(data["debug_mode"])
                if "theme" in data:
                    current["theme"] = str(data["theme"])
                if "hide_delay" in data:
                    current["hide_delay"] = int(data["hide_delay"])
        except Exception:
            pass
    return current


def save_settings(settings: AppSettings) -> None:
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=4)
    except Exception:
        pass


def get_headers(item_headers: Optional[Dict[str, str]] = None, referer_url: Optional[str] = None) -> Dict[str, str]:
    h: Dict[str, str] = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept": "*/*",
    }
    if item_headers:
        for key in ["User-Agent", "Referer", "Origin", "Cookie", "Authorization"]:
            for k, v in item_headers.items():
                if k.lower() == key.lower():
                    h[key] = v
        return h
    if referer_url:
        h["Referer"] = referer_url
        try:
            parsed = urlparse(referer_url)
            h["Origin"] = f"{parsed.scheme}://{parsed.netloc}"
        except Exception:
            pass
    return h


def get_chrome_main_version() -> Optional[int]:
    try:
        output_win: str = subprocess.check_output(
            r'reg query "HKEY_CURRENT_USER\Software\Google\Chrome\BLBeacon" /v version',
            shell=True, stderr=subprocess.DEVNULL
        ).decode('utf-8', errors='ignore')
        match_win = re.search(r'version\s+REG_SZ\s+(\d+)', output_win)
        if match_win:
            return int(match_win.group(1))
    except Exception:
        pass

    try:
        output_unix: str = subprocess.check_output(
            ["google-chrome", "--version"]).decode()
        match_unix = re.search(r'Chrome\s+(\d+)', output_unix)
        if match_unix:
            return int(match_unix.group(1))
    except Exception:
        pass
    return None

# --- 自定義 Logger ---


class MyLogger:
    def __init__(self, log_callback: LogCallback, debug_mode: bool = False) -> None:
        self.log_callback: LogCallback = log_callback
        self.debug_mode: bool = debug_mode

    def debug(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        if self.debug_mode:
            self.log_callback(f"⚠️ [下載警告] {msg}")

    def error(self, msg: str) -> None:
        self.log_callback(f"❌ [下載核心錯誤] {msg}")

# --- 核心邏輯 ---


def check_is_main_video(url: str, headers: Dict[str, str]) -> Tuple[bool, str]:
    try:
        response = requests.get(url, headers=headers, timeout=5, verify=False)
        if response.status_code != 200:
            return False, f"HTTP {response.status_code}"

        content: str = response.text
        if "#EXT-X-STREAM-INF" in content:
            return True, "Master Playlist"

        total_duration: float = 0.0
        for line in content.split('\n'):
            if line.startswith("#EXTINF:"):
                try:
                    duration_part: str = line.split(':')[1].split(',')[0]
                    total_duration += float(duration_part)
                except Exception:
                    pass

        if total_duration > 300:
            return True, f"長度 {int(total_duration)}s"
        else:
            return False, f"過短 ({int(total_duration)}s)"

    except Exception as e:
        return False, str(e)

# --- 瀏覽器邏輯 ---


class SafeChrome(uc.Chrome):  # type: ignore
    def quit(self) -> None:
        try:
            super().quit()
        except Exception:
            pass

    def __del__(self) -> None:
        try:
            self.quit()
        except Exception:
            pass


def create_driver(settings: AppSettings) -> Any:
    options = uc.ChromeOptions()
    options.add_argument("--disable-gpu")
    options.add_argument("--mute-audio")
    options.add_argument("--no-first-run")
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    chrome_main_ver: Optional[int] = get_chrome_main_version()
    driver: Any = SafeChrome(options=options, use_subprocess=True,
                             headless=False, version_main=chrome_main_ver)
    try:
        w: int = int(settings.get("browser_width", 1280))
        h: int = int(settings.get("browser_height", 720))
        driver.set_window_rect(50, 50, w, h)
    except Exception:
        pass
    try:
        driver.execute_cdp_cmd('Network.enable', {})
    except Exception:
        pass
    return driver


def core_sniff_logic(
    driver: Any,
    stop_event: threading.Event,
    log_callback: LogCallback,
    max_wait: int = 60
) -> Tuple[Optional[str], Optional[Dict[str, str]], str]:
    found_m3u8: Optional[str] = None
    captured_headers: Dict[str, str] = {}
    valid_reason: str = ""

    for i in range(max_wait):
        if stop_event.is_set():
            return None, None, "Stop"

        if i > 0 and i % 5 == 0:
            log_callback(f"⚡ 深度掃描中... ({i}/{max_wait}s)")

        try:
            logs: List[Dict[str, Any]] = driver.get_log("performance")
            for entry in logs:
                try:
                    msg_str: str = str(entry.get("message", "{}"))
                    msg_dict: Dict[str, Any] = json.loads(msg_str)
                    msg_inner: Dict[str, Any] = msg_dict.get("message", {})

                    if msg_inner.get("method") == "Network.requestWillBeSent":
                        params: Dict[str, Any] = msg_inner.get("params", {})
                        request: Dict[str, Any] = params.get("request", {})
                        u: str = str(request.get("url", ""))

                        if ".m3u8" in u:
                            if any(x in u for x in ["doubleclick", "adsr", "litix", "segment", "favicon"]):
                                continue

                            tmp_headers: Dict[str, str] = dict(
                                request.get("headers", {}))
                            if "Referer" not in tmp_headers and "referer" not in tmp_headers:
                                tmp_headers["Referer"] = str(
                                    params.get("documentURL", ""))

                            check_h: Dict[str, str] = get_headers(
                                tmp_headers, u)
                            is_main, reason = check_is_main_video(u, check_h)

                            if is_main:
                                found_m3u8 = u
                                captured_headers = tmp_headers
                                valid_reason = reason
                                break
                except Exception:
                    continue
        except Exception:
            pass

        if found_m3u8:
            return found_m3u8, captured_headers, valid_reason
        time.sleep(1)

    return None, None, "Timeout"

# --- 線程任務 ---


def single_sniff_thread(
    target_url: str,
    stop_event: threading.Event,
    update_callback: SniffResultCallback,
    log_callback: LogCallback,
    settings: AppSettings
) -> None:
    debug: bool = bool(settings.get("debug_mode", False))
    hide_delay: int = int(settings.get("hide_delay", 5))

    log_callback(f"🚀 啟動隱形瀏覽器...")
    driver: Any = None
    try:
        driver = create_driver(settings)
        log_callback(f"🌍 載入: {target_url[:40]}...")
        driver.get(target_url)

        raw_title: str = "未知標題"
        try:
            raw_title = str(driver.title).strip() or "未命名頁面"
        except Exception:
            pass

        if not debug:
            log_callback(f"⏳ 等待 {hide_delay} 秒...")
            for _ in range(hide_delay):
                if stop_event.is_set():
                    return
                time.sleep(1)
            try:
                driver.minimize_window()
            except Exception:
                pass
        else:
            time.sleep(2)

        m3u8, headers, reason = core_sniff_logic(
            driver, stop_event, log_callback)

        try:
            raw_title = str(driver.title).strip() or raw_title
        except Exception:
            pass

        if m3u8 and headers is not None:
            log_callback(f"🎉 發現目標 ({reason}): {raw_title}")
            result: MediaItem = {
                "title": raw_title,
                "m3u8": m3u8,
                "original_url": target_url,
                "headers": headers,
                "checked": True,
                "status": "OK"
            }
            update_callback(result, "Success")
        else:
            log_callback("❌ 逾時！未偵測到有效正片。")
            update_callback(None, "Timeout")

    except Exception as e:
        log_callback(f"❌ 錯誤: {e}")
        update_callback(None, str(e))
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def check_validity_thread(
    items_to_check: List[Tuple[int, MediaItem]],
    update_row_callback: UpdateRowCallback,
    log_callback: LogCallback,
    stop_event: threading.Event
) -> None:
    log_callback(f"🔍 開始檢查 {len(items_to_check)} 個連結...")
    with requests.Session():
        for idx, item in items_to_check:
            if stop_event.is_set():
                break
            url: str = item.get("m3u8", "")
            stored_headers: Dict[str, str] = item.get("headers", {})
            original_url: str = item.get("original_url", "")
            if not url:
                continue

            update_row_callback(idx, "檢查中...", None)
            req_headers: Dict[str, str] = get_headers(
                stored_headers, original_url)

            try:
                is_valid_video, reason = check_is_main_video(url, req_headers)
                status_text: str = f"✅ 有效 ({reason})" if is_valid_video else f"❌ 失效 ({reason})"
                tag: str = "completed" if is_valid_video else "invalid"
            except Exception:
                status_text = f"❌ 連線失敗"
                tag = "invalid"

            update_row_callback(idx, status_text, tag)
            time.sleep(0.1)
    log_callback("🏁 檢查完成")


def batch_repair_thread(
    items_to_repair: List[Tuple[int, MediaItem]],
    update_row_callback: UpdateRowCallback,
    log_callback: LogCallback,
    stop_event: threading.Event,
    settings: AppSettings
) -> None:
    hide_delay: int = int(settings.get("hide_delay", 5))
    driver: Any = None
    try:
        driver = create_driver(settings)
        for _, (idx, item) in enumerate(items_to_repair):
            if stop_event.is_set():
                break
            original_url: str = item.get("original_url", "")
            update_row_callback(idx, "正在修復...", "downloading")

            if not original_url:
                update_row_callback(idx, "無原始連結", "error")
                log_callback(f"⚠️ 無法修復 Index {idx}: 缺少原始網址")
                continue

            try:
                title: str = item.get('title', 'Unknown')
                log_callback(f"🔧 修復中: {title}")
                driver.get(original_url)
                for _ in range(hide_delay):
                    if stop_event.is_set():
                        raise Exception("Stop")
                    time.sleep(1)
                try:
                    driver.minimize_window()
                except Exception:
                    pass

                new_m3u8, new_headers, _ = core_sniff_logic(
                    driver, stop_event, log_callback, max_wait=45)

                if new_m3u8 and new_headers is not None:
                    log_callback(f"✅ 修復成功 (Index {idx})")
                    update_row_callback(
                        idx, "✅ 已修復", "repaired", new_url=new_m3u8, new_headers=new_headers)
                else:
                    update_row_callback(idx, "❌ 失敗", "error")
            except Exception as e:
                if str(e) == "Stop":
                    break
                update_row_callback(idx, "錯誤", "error")
                log_callback(f"❌ 修復錯誤: {e}")
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        log_callback("🏁 修復任務結束")


def download_task(
    url: str,
    title: str,
    save_path: str,
    progress_callback: UpdateProgressCallback,
    log_callback: LogCallback,
    stop_event: threading.Event,
    item_data: MediaItem,
    settings: AppSettings
) -> None:
    log_callback(f"⬇️ 開始下載: {title}")
    safe_title: str = re.sub(r'[\\/*?:"<>|]', "", title)
    output_template: str = os.path.join(save_path, f'{safe_title}.%(ext)s')

    debug_mode: bool = bool(settings.get("debug_mode", False))

    def hook(d: Dict[str, Any]) -> None:
        if stop_event.is_set():
            raise Exception("Download Cancelled")
        status: str = str(d.get('status', ''))
        if status == 'downloading':
            p_str: str = str(d.get('_percent_str', '0%')).replace('%', '')
            p_str = re.sub(r'\x1b\[[0-9;]*m', '', p_str).strip()
            try:
                progress_callback(title, float(p_str))
            except Exception:
                pass
        elif status == 'finished':
            progress_callback(title, 100.0)
            log_callback(f"✅ 下載完成: {safe_title}")

    stored_headers: Dict[str, str] = item_data.get("headers", {})
    original_url: str = item_data.get("original_url", "")
    req_headers: Dict[str, str] = get_headers(stored_headers, original_url)

    my_logger = MyLogger(log_callback, debug_mode)

    ydl_opts: Dict[str, Any] = {
        'format': 'bestvideo+bestaudio/best',
        'outtmpl': output_template,
        'progress_hooks': [hook],
        'nocheckcertificate': True,
        'http_headers': req_headers,
        'external_downloader_args': {'ffmpeg': ['-loglevel', 'error']},
        'continuedl': True,
        'quiet': True,
        'no_warnings': not debug_mode,
        'logger': my_logger,
        'retries': 10,
        'fragment_retries': 10,
        'skip_unavailable_fragments': False,
        'concurrent_fragment_downloads': 4,
        'hls_use_mpegts': True,
        'ignoreerrors': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        if "Download Cancelled" in str(e):
            log_callback(f"🛑 已停止下載: {title}")
            progress_callback(title, -1.0)
        else:
            log_callback(f"❌ 下載流程中斷: {str(e)[:50]}...")
            progress_callback(title, -2.0)

# --- 智慧標題編輯器 ---


class TitleEditorWindow:
    def __init__(self, parent: tk.Misc, old_title: str, callback: Callable[[str], None]) -> None:
        self.window: tk.Toplevel = ttk.Toplevel(parent)
        self.window.title("智慧標題編輯")
        self.window.geometry("600x480")
        self.callback: Callable[[str], None] = callback

        self.window.update_idletasks()
        x: int = (self.window.winfo_screenwidth() // 2) - 300
        y: int = (self.window.winfo_screenheight() // 2) - 240
        self.window.geometry(f'+{x}+{y}')

        frame = ttk.Frame(self.window, padding=20)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="原始標題:", bootstyle="secondary").pack(anchor="w")
        ttk.Label(frame, text=old_title, wraplength=550, bootstyle="inverse-secondary",
                  padding=5).pack(anchor="w", fill="x", pady=(5, 10))

        ttk.Label(frame, text="✨ 智慧選取 (括號內容優先):",
                  bootstyle="warning").pack(anchor="w")

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill="x", pady=5)

        brackets_pattern: str = r'[《【\[(「"“（](.*?)[》】\])」"”）]'
        matches: List[str] = [str(m)
                              for m in re.findall(brackets_pattern, old_title)]
        splits: List[str] = [str(s) for s in re.split(
            r'[|\-｜_：\[\]【】()（）《》\s]+', old_title)]

        parts: List[str] = []
        seen: set[str] = set()

        for clean_m in (m.strip() for m in matches):
            if clean_m and clean_m not in seen:
                parts.append(clean_m)
                seen.add(clean_m)

        for clean_s in (s.strip() for s in splits):
            if clean_s and clean_s not in seen:
                parts.append(clean_s)
                seen.add(clean_s)

        row: int = 0
        col: int = 0
        for part in parts:
            if len(part) < 1:
                continue
            btn = ttk.Button(btn_frame, text=part, bootstyle="info-outline",
                             command=lambda t=part: self.set_text(t))
            btn.grid(row=row, column=col, padx=4, pady=4, sticky="ew")
            col += 1
            if col > 3:
                col = 0
                row += 1

        ttk.Label(frame, text="最終標題:", bootstyle="success").pack(
            anchor="w", pady=(20, 5))
        self.entry: ttk.Entry = ttk.Entry(frame, font=("Arial", 12))
        self.entry.insert(0, old_title)
        self.entry.pack(fill="x", pady=5)

        def _on_return(e: tk.Event[tk.Misc]) -> None:
            self.save()
        self.entry.bind("<Return>", _on_return)

        btn_action = ttk.Frame(frame)
        btn_action.pack(fill="x", pady=20)

        ttk.Button(btn_action, text="取消", command=self.window.destroy,
                   bootstyle="secondary").pack(side="right", padx=5)
        ttk.Button(btn_action, text="確定修改", command=self.save,
                   bootstyle="success").pack(side="right", padx=5)

    def set_text(self, text: str) -> None:
        self.entry.delete(0, tk.END)
        self.entry.insert(0, text)
        self.entry.focus()

    def save(self) -> None:
        new_title: str = self.entry.get().strip()
        if new_title:
            self.callback(new_title)
        self.window.destroy()

# --- 設定視窗 ---


class SettingsWindow:
    def __init__(self, parent: tk.Misc, settings: AppSettings, on_save: Callable[[AppSettings], None]) -> None:
        self.window: tk.Toplevel = ttk.Toplevel(parent)
        self.window.title("⚙️ 詳細設定")
        self.window.geometry("500x520")
        self.settings: AppSettings = settings
        self.on_save: Callable[[AppSettings], None] = on_save
        self.center_window()
        self._init_ui()

    def center_window(self) -> None:
        self.window.update_idletasks()
        w: int = self.window.winfo_width()
        h: int = self.window.winfo_height()
        x: int = (self.window.winfo_screenwidth() // 2) - (w // 2)
        y: int = (self.window.winfo_screenheight() // 2) - (h // 2)
        self.window.geometry(f'+{x}+{y}')

    def _init_ui(self) -> None:
        main = ttk.Frame(self.window, padding=20)
        main.pack(fill="both", expand=True)

        ttk.Label(main, text="下載儲存位置", bootstyle="primary").pack(
            anchor="w", pady=(0, 5))
        path_frame = ttk.Frame(main)
        path_frame.pack(fill="x", pady=(0, 15))
        self.path_var: tk.StringVar = tk.StringVar(
            value=self.settings.get("download_path", ""))
        ttk.Entry(path_frame, textvariable=self.path_var).pack(
            side="left", fill="x", expand=True, padx=(0, 5))
        ttk.Button(path_frame, text="📂 瀏覽", command=self.browse_path,
                   bootstyle="secondary-outline").pack(side="right")

        ttk.Label(main, text="介面主題配色 (重啟後生效)", bootstyle="primary").pack(
            anchor="w", pady=(0, 5))
        current_code: str = str(self.settings.get("theme", "cosmo"))
        current_display: str = "Cosmo (現代白)"
        for k, v in THEME_MAP.items():
            if v == current_code:
                current_display = k
                break
        self.theme_var: tk.StringVar = tk.StringVar(value=current_display)
        cb = ttk.Combobox(main, textvariable=self.theme_var,
                          values=list(THEME_MAP.keys()), state="readonly")
        cb.pack(fill="x", pady=(0, 15))

        ttk.Label(main, text="瀏覽器自動隱藏延遲 (秒)", bootstyle="primary").pack(
            anchor="w", pady=(0, 5))
        self.delay_var: tk.IntVar = tk.IntVar(
            value=int(self.settings.get("hide_delay", 5)))
        ttk.Spinbox(main, from_=0, to=60, textvariable=self.delay_var).pack(
            fill="x", pady=(0, 15))

        ttk.Label(main, text="瀏覽器視窗大小 (寬 x 高)", bootstyle="primary").pack(
            anchor="w", pady=(0, 5))
        res_frame = ttk.Frame(main)
        res_frame.pack(fill="x", pady=(0, 15))
        self.w_var: tk.IntVar = tk.IntVar(
            value=int(self.settings.get("browser_width", 1280)))
        self.h_var: tk.IntVar = tk.IntVar(
            value=int(self.settings.get("browser_height", 720)))
        ttk.Entry(res_frame, textvariable=self.w_var,
                  width=10).pack(side="left")
        ttk.Label(res_frame, text=" x ").pack(side="left")
        ttk.Entry(res_frame, textvariable=self.h_var,
                  width=10).pack(side="left")
        ttk.Label(res_frame, text="px", bootstyle="secondary").pack(
            side="left", padx=5)

        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill="x", side="bottom")
        ttk.Button(btn_frame, text="儲存並關閉", command=self.save,
                   bootstyle="success").pack(fill="x")

    def browse_path(self) -> None:
        p: str = filedialog.askdirectory()
        if p:
            self.path_var.set(p)

    def save(self) -> None:
        theme_code: str = THEME_MAP.get(self.theme_var.get(), "cosmo")
        new_settings: AppSettings = {
            "download_path": self.path_var.get(),
            "browser_width": self.w_var.get(),
            "browser_height": self.h_var.get(),
            "theme": theme_code,
            "hide_delay": self.delay_var.get(),
            "debug_mode": bool(self.settings.get("debug_mode", False))
        }
        self.on_save(new_settings)
        self.window.destroy()

# --- 主程式 ---


class App:
    def __init__(self, root: tk.Misc) -> None:
        self.root: tk.Misc = root
        try:
            self.root.title("Media Sniffer Pro - Art Edition")  # type: ignore
            self.root.geometry("1280x850")  # type: ignore
        except Exception:
            pass

        self.settings: AppSettings = load_settings()
        current_theme: str = str(self.settings.get("theme", "cosmo"))
        self.style = ttk.Style(current_theme)

        self.data_list: List[MediaItem] = []
        self.stop_event: threading.Event = threading.Event()
        self.active_downloads: Dict[str, threading.Event] = {}
        self.url_var: tk.StringVar = tk.StringVar()
        self.debug_mode: tk.BooleanVar = tk.BooleanVar(
            value=bool(self.settings.get("debug_mode", False)))

        self._init_ui()
        self._apply_custom_styles()

    def _init_ui(self) -> None:
        toolbar = ttk.Frame(self.root, padding=(10, 5))
        toolbar.pack(fill="x")

        ttk.Label(toolbar, text="匯入:", bootstyle="secondary").pack(
            side="left", padx=(5, 2))
        ttk.Button(toolbar, text="JSON", command=self.import_json,
                   bootstyle="info-outline", width=6).pack(side="left", padx=2)
        ttk.Button(toolbar, text="M3U", command=self.import_m3u,
                   bootstyle="info-outline", width=6).pack(side="left", padx=2)

        ttk.Separator(toolbar, orient="vertical").pack(
            side="left", padx=10, fill="y")

        ttk.Label(toolbar, text="匯出:", bootstyle="secondary").pack(
            side="left", padx=(5, 2))
        ttk.Button(toolbar, text="JSON", command=self.export_json,
                   bootstyle="success-outline", width=6).pack(side="left", padx=2)
        ttk.Button(toolbar, text="M3U", command=self.export_m3u,
                   bootstyle="success-outline", width=6).pack(side="left", padx=2)

        ttk.Checkbutton(toolbar, text="除錯 (顯示詳細錯誤)", variable=self.debug_mode,
                        command=self.toggle_debug, bootstyle="warning-round-toggle").pack(side="right", padx=10)
        ttk.Button(toolbar, text="⚙️ 設定", command=self.open_settings,
                   bootstyle="secondary").pack(side="right", padx=5)
        ttk.Button(toolbar, text="📁 資料夾", command=self.open_download_folder,
                   bootstyle="info-outline").pack(side="right", padx=5)

        main_container = ttk.Frame(self.root, padding=20)
        main_container.pack(fill="both", expand=True)

        sniff_frame = ttk.Labelframe(main_container, text=" 嗅探控制 ", padding=15)
        sniff_frame.pack(fill="x", pady=(0, 20))
        input_frame = ttk.Frame(sniff_frame)
        input_frame.pack(fill="x")
        ttk.Label(input_frame, text="網址:", font=(
            "Microsoft JhengHei UI", 10, "bold")).pack(side="left")
        entry = ttk.Entry(input_frame, textvariable=self.url_var)
        entry.pack(side="left", fill="x", expand=True, padx=15)
        self.create_context_menu(entry, is_entry=True)
        self.btn_start = ttk.Button(
            input_frame, text="🔍 開始", command=self.start_sniff, bootstyle="primary", width=10)
        self.btn_start.pack(side="left", padx=2)
        self.btn_stop = ttk.Button(
            input_frame, text="⏹ 停止", command=self.stop_sniff, bootstyle="danger", state="disabled", width=10)
        self.btn_stop.pack(side="left", padx=2)
        ttk.Button(input_frame, text="✖", command=lambda: self.url_var.set(
            ""), bootstyle="secondary-outline", width=3).pack(side="left", padx=2)

        list_container = ttk.Frame(main_container)
        list_container.pack(fill="both", expand=True, pady=(0, 20))
        list_tools = ttk.Frame(list_container)
        list_tools.pack(fill="x", pady=(0, 5))
        ttk.Button(list_tools, text="⬇ 下載已選", command=self.download_selected,
                   bootstyle="success").pack(side="left", padx=(0, 5))
        ttk.Button(list_tools, text="🗑️ 刪除", command=self.delete_selected,
                   bootstyle="danger-outline").pack(side="left")
        ttk.Separator(list_tools, orient="vertical").pack(
            side="left", padx=5, fill="y")
        ttk.Button(list_tools, text="🔎 檢查有效性", command=self.check_validity_selected,
                   bootstyle="info-outline").pack(side="left", padx=2)
        ttk.Button(list_tools, text="🔧 修復已選 (死鏈復活)", command=self.repair_selected,
                   bootstyle="warning-outline").pack(side="left", padx=2)
        ttk.Label(list_tools, text="小提示: 勾選複選框即可操作，無需滑鼠反白", bootstyle="secondary", font=(
            "Microsoft JhengHei UI", 9)).pack(side="right")

        tree_frame = ttk.Frame(list_container)
        tree_frame.pack(fill="both", expand=True)
        sb_y = ttk.Scrollbar(tree_frame, orient="vertical")
        sb_x = ttk.Scrollbar(tree_frame, orient="horizontal")

        cols: Tuple[str, ...] = ("check", "title", "status", "m3u8")
        self.tree: ttk.Treeview = ttk.Treeview(
            tree_frame, columns=cols, show="headings", selectmode="extended",
            style="Custom.Treeview", yscrollcommand=sb_y.set, xscrollcommand=sb_x.set
        )

        sb_y.config(command=self.tree.yview)
        sb_x.config(command=self.tree.xview)

        self.tree.heading("check", text="✓", command=self.toggle_all_checks)
        self.tree.heading("title", text="影片標題 (Title)")
        self.tree.heading("status", text="狀態 (Status)")
        self.tree.heading("m3u8", text="M3U8 連結")

        self.tree.column("check", width=40, anchor="center", stretch=False)
        self.tree.column("title", width=400, anchor="center")
        self.tree.column("status", width=150, anchor="center", stretch=False)
        self.tree.column("m3u8", width=300, anchor="w")

        sb_y.pack(side="right", fill="y")
        sb_x.pack(side="bottom", fill="x")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Button-1>", self.on_tree_click)
        self.tree.bind("<Double-1>", self.on_tree_double_click)
        self.tree.bind("<Button-3>", self.show_tree_menu)

        log_outer_container = ttk.Frame(main_container)
        log_outer_container.pack(fill="x")
        ttk.Label(log_outer_container, text="系統日誌", font=(
            "Microsoft JhengHei UI", 9, "bold")).pack(anchor="w", pady=(0, 2))
        log_inner_frame = ttk.Frame(log_outer_container)
        log_inner_frame.pack(fill="x")
        log_sb = ttk.Scrollbar(log_inner_frame, orient="vertical")
        log_sb.pack(side="right", fill="y")
        self.log_text: tk.Text = tk.Text(
            log_inner_frame, height=6, state='disabled', font=("Consolas", 9),
            relief="flat", padx=5, pady=5, yscrollcommand=log_sb.set
        )
        log_sb.config(command=self.log_text.yview)

        _theme: Any = self.style.theme_use()
        theme_name: str = str(_theme) if _theme is not None else ""
        is_light: bool = theme_name in [
            "cosmo", "flatly", "journal", "litera", "minty", "lumen"] or "light" in theme_name
        self.log_text.config(
            bg="#f8f9fa" if is_light else "#2b2b2b",
            fg="#333333" if is_light else "#dddddd"
        )
        self.log_text.pack(side="left", fill="x", expand=True)
        self.create_context_menu(None, is_entry=False)

    def _apply_custom_styles(self) -> None:
        self.style.configure("Custom.Treeview", rowheight=30,
                             font=("Microsoft JhengHei UI", 10))
        self.style.configure("Custom.Treeview.Heading", font=(
            "Microsoft JhengHei UI", 10, "bold"), borderwidth=3, relief="raised")

        _theme: Any = self.style.theme_use()
        theme_name: str = str(_theme) if _theme is not None else ""
        is_light: bool = theme_name in [
            "cosmo", "flatly", "journal", "litera", "minty", "lumen"] or "light" in theme_name

        self.tree.tag_configure("downloading", foreground="#28a745")
        self.tree.tag_configure("error", foreground="#dc3545")
        self.tree.tag_configure("stopped", foreground="#fd7e14")
        self.tree.tag_configure("completed", foreground="#007bff")
        self.tree.tag_configure(
            "invalid", foreground="#dc3545", background="#ffe6e6" if is_light else "#4a1b1b")
        self.tree.tag_configure("repaired", foreground="#00bc8c")
        self.tree.tag_configure(
            "checked", background="#e9ecef" if is_light else "#444")

    def create_context_menu(self, widget: Optional[tk.Misc], is_entry: bool = False) -> None:
        if is_entry and widget is not None:
            menu = tk.Menu(self.root, tearoff=0)
            menu.add_command(
                label="貼上", command=lambda: widget.event_generate("<<Paste>>"))
            menu.add_command(
                label="全選", command=lambda: widget.event_generate("<<SelectAll>>"))

            def _post_menu(e: tk.Event[tk.Misc]) -> None:
                menu.post(e.x_root, e.y_root)
            widget.bind("<Button-3>", _post_menu)
        else:
            self.tree_menu: tk.Menu = tk.Menu(self.root, tearoff=0)
            self.tree_menu.add_command(
                label="⬇ 下載項目", command=self.download_selected)
            self.tree_menu.add_command(
                label="⏹ 停止下載", command=self.stop_download_selected)
            self.tree_menu.add_separator()
            self.tree_menu.add_command(
                label="🔎 檢查有效性", command=self.check_validity_selected)
            self.tree_menu.add_command(
                label="🔧 修復已選項目", command=self.repair_selected)
            self.tree_menu.add_separator()
            self.tree_menu.add_command(label="📄 複製標題", command=self.copy_title)
            self.tree_menu.add_command(
                label="🔗 複製 M3U8", command=self.copy_m3u8)
            self.tree_menu.add_separator()
            self.tree_menu.add_command(
                label="🗑️ 刪除", command=self.delete_selected)

    def show_tree_menu(self, event: tk.Event[tk.Misc]) -> None:
        item: str = self.tree.identify_row(event.y)
        if item:
            if item not in self.tree.selection():
                self.tree.selection_set(item)
            self.tree_menu.post(event.x_root, event.y_root)

    def open_settings(self) -> None:
        def on_save(new_settings: AppSettings) -> None:
            self.settings.update(new_settings)
            save_settings(self.settings)
            self.log("⚙️ 設定已更新")
            messagebox.showinfo("提示", "設定已儲存！")
        SettingsWindow(self.root, self.settings, on_save)

    def toggle_debug(self) -> None:
        self.settings["debug_mode"] = self.debug_mode.get()
        save_settings(self.settings)
        msg: str = "開啟" if self.debug_mode.get() else "關閉"
        self.log(f"🐞 除錯模式已{msg} (詳細錯誤將顯示於日誌)")

    def log(self, msg: str) -> None:
        def _update() -> None:
            ts: str = datetime.now().strftime("%H:%M:%S")
            self.log_text.config(state='normal')
            self.log_text.insert(tk.END, f"[{ts}] {msg}\n")
            self.log_text.see(tk.END)
            self.log_text.config(state='disabled')
        self.root.after(0, _update)

    def start_sniff(self) -> None:
        url: str = self.url_var.get().strip()
        if not url.startswith("http"):
            self.log("⚠️ 請輸入正確網址")
            return
        self.stop_event.clear()
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        threading.Thread(
            target=single_sniff_thread,
            args=(url, self.stop_event, self.on_sniff_result,
                  self.log, self.settings),
            daemon=True
        ).start()

    def stop_sniff(self) -> None:
        self.stop_event.set()
        self.log("🛑 發送停止訊號...")

    def on_sniff_result(self, result: Optional[MediaItem], msg: str) -> None:
        def _handle() -> None:
            self.btn_start.config(state="normal")
            self.btn_stop.config(state="disabled")
            if result:
                self.data_list.append(result)
                self.refresh_tree()
                self.log(f"✅ 加入: {result.get('title', 'Unknown')}")
                self.url_var.set("")
            elif msg != "Stop":
                self.log(f"⚠️ 結束: {msg}")
        self.root.after(0, _handle)

    def get_target_indices(self) -> List[int]:
        sel = self.tree.selection()
        if sel:
            return [int(iid) for iid in sel]
        checked_indices: List[int] = [
            i for i, d in enumerate(self.data_list) if d.get('checked')]
        return checked_indices

    def check_validity_selected(self) -> None:
        target_indices: List[int] = self.get_target_indices()
        if not target_indices:
            self.log("⚠️ 未選擇項目 (請反白或打勾)")
            return

        items_to_check: List[Tuple[int, MediaItem]] = []
        for idx in target_indices:
            if idx < len(self.data_list):
                items_to_check.append((idx, self.data_list[idx]))

        self.stop_event.clear()
        self.log(f"🚀 開始檢查 {len(items_to_check)} 個連結...")
        threading.Thread(
            target=check_validity_thread,
            args=(items_to_check, self.update_row_status,
                  self.log, self.stop_event),
            daemon=True
        ).start()

    def repair_selected(self) -> None:
        target_indices: List[int] = self.get_target_indices()
        if not target_indices:
            self.log("⚠️ 未選擇項目 (請反白或打勾)")
            return

        items_to_repair: List[Tuple[int, MediaItem]] = []
        for idx in target_indices:
            if idx < len(self.data_list):
                item: MediaItem = self.data_list[idx]
                if not item.get("original_url"):
                    title: str = item.get('title', 'Unknown')
                    self.log(f"⚠️ 項目 {title} 無法修復 (缺少原始網址)")
                else:
                    items_to_repair.append((idx, item))

        if not items_to_repair:
            messagebox.showwarning("無法修復", "所選項目均無原始網址紀錄，無法執行修復。")
            return

        if not messagebox.askyesno("確認修復", f"將對 {len(items_to_repair)} 個項目執行瀏覽器重抓。\n這需要一點時間，確定嗎？"):
            return

        self.stop_event.clear()
        self.btn_stop.config(state="normal")
        threading.Thread(
            target=batch_repair_thread,
            args=(items_to_repair, self.update_row_status,
                  self.log, self.stop_event, self.settings),
            daemon=True
        ).start()

    def update_row_status(
        self,
        idx: int,
        status: str,
        tag: Optional[str] = None,
        new_url: Optional[str] = None,
        new_headers: Optional[Dict[str, str]] = None
    ) -> None:
        def _u() -> None:
            if idx < len(self.data_list):
                self.data_list[idx]['status'] = status
                if new_url:
                    self.data_list[idx]['m3u8'] = new_url
                if new_headers:
                    self.data_list[idx]['headers'] = new_headers
                self.refresh_row(idx, tag)
            if "任務結束" in status:
                self.btn_stop.config(state="disabled")
        self.root.after(0, _u)

    def download_selected(self) -> None:
        target_indices: List[int] = self.get_target_indices()
        if not target_indices:
            self.log("⚠️ 未選擇項目 (請反白或打勾)")
            return

        path: str = str(self.settings.get(
            "download_path", str(Path.home() / "Downloads")))
        if not os.path.exists(path):
            try:
                os.makedirs(path)
            except Exception:
                pass
        for idx in target_indices:
            if idx >= len(self.data_list):
                continue
            data: MediaItem = self.data_list[idx]
            title: str = data.get('title', 'Unknown')
            if title in self.active_downloads:
                continue
            stop_evt = threading.Event()
            self.active_downloads[title] = stop_evt
            self.update_row_status(idx, "準備中...", None)

            m3u8_url: str = data.get('m3u8', '')
            if not m3u8_url:
                continue

            threading.Thread(
                target=download_task,
                args=(m3u8_url, title, path, self.update_progress,
                      self.log, stop_evt, data, self.settings),
                daemon=True
            ).start()

    def stop_download_selected(self) -> None:
        target_indices: List[int] = self.get_target_indices()
        for idx in target_indices:
            if idx >= len(self.data_list):
                continue
            title: str = self.data_list[idx].get('title', '')
            if title in self.active_downloads:
                self.active_downloads[title].set()

    def update_progress(self, title: str, val: float) -> None:
        def _u() -> None:
            idx: int = -1
            for i, d in enumerate(self.data_list):
                if d.get('title') == title:
                    idx = i
                    break
            if idx == -1:
                return
            if val == 100.0:
                self.data_list[idx]['status'] = "完成"
                self.active_downloads.pop(title, None)
                self.refresh_row(idx, "completed")
            elif val < 0.0:
                self.data_list[idx]['status'] = "停止" if val == -1.0 else "錯誤"
                self.active_downloads.pop(title, None)
                self.refresh_row(idx, "stopped" if val == -1.0 else "error")
            else:
                self.data_list[idx]['status'] = f"{val:.1f}%"
                self.refresh_row(idx, "downloading")
        self.root.after(0, _u)

    def on_tree_click(self, event: tk.Event[tk.Misc]) -> None:
        region: str = self.tree.identify_region(event.x, event.y)
        if region == "cell" and self.tree.identify_column(event.x) == "#1":
            iid = self.tree.identify_row(event.y)
            if iid:
                idx: int = int(iid)
                if 0 <= idx < len(self.data_list):
                    self.data_list[idx]['checked'] = not self.data_list[idx].get(
                        'checked', False)
                    self.refresh_row(idx)

    def on_tree_double_click(self, event: tk.Event[tk.Misc]) -> None:
        if self.tree.identify_column(event.x) == "#2":
            iid = self.tree.identify_row(event.y)
            if iid:
                idx: int = int(iid)
                if 0 <= idx < len(self.data_list):
                    title: str = self.data_list[idx].get('title', '')
                    TitleEditorWindow(self.root, title,
                                      lambda t: self.update_title(idx, t))

    def update_title(self, idx: int, t: str) -> None:
        if 0 <= idx < len(self.data_list):
            self.data_list[idx]['title'] = t
            self.refresh_row(idx)

    def refresh_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for i, item in enumerate(self.data_list):
            self.tree.insert("", "end", iid=str(
                i), values=self._get_vals(item))
            self._apply_tag(i, item.get('status', ''))

    def refresh_row(self, idx: int, tag: Optional[str] = None) -> None:
        if 0 <= idx < len(self.data_list):
            item: MediaItem = self.data_list[idx]
            self.tree.item(str(idx), values=self._get_vals(item))
            if tag:
                self.tree.item(str(idx), tags=(tag,))
            else:
                self._apply_tag(idx, item.get('status', ''))

    def _get_vals(self, item: MediaItem) -> Tuple[str, str, str, str]:
        return (
            "☑" if item.get("checked") else "☐",
            item.get("title", ""),
            item.get("status", ""),
            item.get("m3u8", "")
        )

    def _apply_tag(self, idx: int, status: str) -> None:
        t: List[str] = []
        if "完成" in status:
            t.append("completed")
        elif "失效" in status or "錯誤" in status:
            t.append("invalid")
        elif "已修復" in status:
            t.append("repaired")
        elif "%" in status or "正在" in status:
            t.append("downloading")
        elif "停止" in status:
            t.append("stopped")
        self.tree.item(str(idx), tags=tuple(t))

    def toggle_all_checks(self) -> None:
        if not self.data_list:
            return
        ns: bool = not bool(self.data_list[0].get('checked', False))
        for d in self.data_list:
            d['checked'] = ns
        self.refresh_tree()

    def delete_selected(self) -> None:
        target_indices: List[int] = self.get_target_indices()
        if not target_indices:
            self.log("⚠️ 未選擇刪除項目")
            return

        for i in sorted(target_indices, reverse=True):
            if i < len(self.data_list):
                del self.data_list[i]
        self.refresh_tree()

    def copy_title(self) -> None:
        s = self.tree.selection()
        if s:
            idx: int = int(s[0])
            if 0 <= idx < len(self.data_list):
                try:
                    self.root.clipboard_clear()  # type: ignore
                    self.root.clipboard_append(
                        self.data_list[idx].get('title', ''))  # type: ignore
                except Exception:
                    pass

    def copy_m3u8(self) -> None:
        s = self.tree.selection()
        if s:
            idx: int = int(s[0])
            if 0 <= idx < len(self.data_list):
                try:
                    self.root.clipboard_clear()  # type: ignore
                    self.root.clipboard_append(
                        self.data_list[idx].get('m3u8', ''))  # type: ignore
                except Exception:
                    pass

    def open_download_folder(self) -> None:
        p: str = str(self.settings.get(
            "download_path", str(Path.home() / "Downloads")))
        if os.path.exists(p):
            try:
                os.startfile(p)  # type: ignore
            except Exception:
                pass

    def import_json(self) -> None:
        p: str = filedialog.askopenfilename(
            filetypes=[("JSON Data", "*.json")])
        if not p:
            return
        try:
            with open(p, 'r', encoding='utf-8') as f:
                new_data: List[Dict[str, Any]] = json.load(f)
                parsed_data: List[MediaItem] = [
                    cast(MediaItem, item) for item in new_data]
                self.data_list.extend(parsed_data)
            self.refresh_tree()
            self.log(f"📂 JSON 匯入成功: {os.path.basename(p)}")
        except Exception as e:
            self.log(f"❌ JSON 載入失敗: {e}")
            messagebox.showerror("錯誤", f"JSON 載入失敗：\n{e}")

    def import_m3u(self) -> None:
        p: str = filedialog.askopenfilename(
            filetypes=[("M3U Playlist", "*.m3u;*.m3u8")])
        if not p:
            return
        try:
            items: List[MediaItem] = M3UHandler.parse_file(p)
            self.data_list.extend(items)
            self.refresh_tree()
            self.log(f"📂 M3U 匯入成功: {os.path.basename(p)} ({len(items)} 項目)")
        except Exception as e:
            self.log(f"❌ M3U 解析失敗: {e}")
            messagebox.showerror("錯誤", f"M3U 解析失敗：\n{e}")

    def export_json(self) -> None:
        if not self.data_list:
            messagebox.showinfo("提示", "列表為空")
            return
        p: str = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON Data", "*.json")])
        if not p:
            return
        try:
            with open(p, 'w', encoding='utf-8') as f:
                json.dump(self.data_list, f, ensure_ascii=False, indent=2)
            self.log("💾 JSON 匯出成功")
        except Exception as e:
            self.log(f"❌ JSON 儲存失敗: {e}")

    def export_m3u(self) -> None:
        if not self.data_list:
            messagebox.showinfo("提示", "列表為空")
            return
        p: str = filedialog.asksaveasfilename(
            defaultextension=".m3u", filetypes=[("M3U Playlist", "*.m3u")])
        if not p:
            return
        try:
            M3UHandler.save_file(p, self.data_list)
            self.log("💾 M3U 匯出成功 (含修復資訊)")
        except Exception as e:
            self.log(f"❌ M3U 儲存失敗: {e}")


if __name__ == "__main__":
    try:
        from ctypes import windll  # type: ignore
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    temp_settings: AppSettings = load_settings()
    theme: str = str(temp_settings.get("theme", "cosmo"))
    root_window = ttk.Window(themename=theme)
    app = App(root_window)
    root_window.mainloop()
# --- END OF FILE media_sniffer.py ---
