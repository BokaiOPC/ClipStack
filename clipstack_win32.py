# -*- coding: utf-8 -*-
"""
ClipStack —— 光标处弹出的多段剪贴板历史工具（Win32 原型，零 GUI 框架依赖）

功能：
- 后台自动记录每次复制的内容（文字 / 图片 / 文件），互不顶替
- Ctrl+Shift+V 在鼠标光标位置弹出历史窗口（不劫持 Ctrl+V 的正常粘贴）
- 点击任意条目：自动写入剪贴板并模拟 Ctrl+V 粘贴到目标程序
- 每条右侧 x 单独删除；底部有 [全部清除] [关闭] [退出] 按钮
- 条目按复制顺序排列，窗口内显示最近 12 条，最多保留 50 条

运行：pythonw clipstack_win32.py
依赖：pip install pillow
"""

import ctypes
import io
import os
import struct
import sys
import threading
import time
from ctypes import wintypes

from PIL import Image

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32
gdi32 = ctypes.windll.gdi32
winmm = ctypes.windll.winmm
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)  # 用于可靠的 GetLastError

# ---------- 基本类型 ----------
HWND = wintypes.HWND
UINT = ctypes.c_uint
INT = ctypes.c_int
DWORD = wintypes.DWORD
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
LRESULT = ctypes.c_ssize_t
HANDLE = wintypes.HANDLE
HINSTANCE = wintypes.HINSTANCE
HMENU = wintypes.HMENU
LPCWSTR = wintypes.LPCWSTR
LPVOID = ctypes.c_void_p
HBRUSH = wintypes.HBRUSH
HFONT = HANDLE

WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HWND, UINT, WPARAM, LPARAM)
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, INT, WPARAM, LPARAM)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", DWORD),
        ("scanCode", DWORD),
        ("flags", DWORD),
        ("time", DWORD),
        ("dwExtraInfo", LPVOID),
    ]

HICON = HANDLE
HCURSOR = HANDLE


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", INT),
        ("cbWndExtra", INT),
        ("hInstance", HINSTANCE),
        ("hIcon", HICON),
        ("hCursor", HCURSOR),
        ("hbrBackground", HBRUSH),
        ("lpszMenuName", LPCWSTR),
        ("lpszClassName", LPCWSTR),
    ]

# ---------- 常量 ----------
WS_POPUP = 0x80000000
WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
BS_LEFT = 0x100
SS_LEFT = 0x0
SS_CENTER = 0x1
WS_EX_TOPMOST = 0x8
WS_EX_TOOLWINDOW = 0x80

WM_SETTEXT = 0x0C
WM_SETFONT = 0x30
WM_COMMAND = 0x111
WM_KEYDOWN = 0x100
WM_DESTROY = 0x02
WM_CLOSE = 0x10
WM_ACTIVATE = 0x06
WM_HOTKEY = 0x312
WM_APP_REFRESH = 0x8000  # WM_APP

SW_HIDE = 0
SW_SHOW = 5
SWP_SHOWWINDOW = 0x40
SWP_NOMOVE = 0x0002
HWND_TOPMOST = -1

# ---------- ctypes 签名声明（避免 64 位句柄被截断） ----------
user32.CreateWindowExW.argtypes = [DWORD, LPCWSTR, LPCWSTR, DWORD,
                                   INT, INT, INT, INT, HWND, HMENU, HINSTANCE, LPVOID]
user32.CreateWindowExW.restype = HWND
user32.DefWindowProcW.argtypes = [HWND, UINT, WPARAM, LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.SetWindowPos.argtypes = [HWND, HWND, INT, INT, INT, INT, UINT]
user32.SetWindowPos.restype = wintypes.BOOL
user32.GetForegroundWindow.restype = HWND
user32.LoadCursorW.argtypes = [HINSTANCE, LPCWSTR]
user32.LoadCursorW.restype = HANDLE
user32.GetMessageW.restype = INT
user32.SendMessageW.argtypes = [HWND, UINT, WPARAM, LPARAM]
user32.IsWindowVisible.argtypes = [HWND]
user32.SetFocus.argtypes = [HWND]
user32.SetForegroundWindow.argtypes = [HWND]
user32.RegisterHotKey.argtypes = [HWND, INT, UINT, UINT]
user32.PostMessageW.argtypes = [HWND, UINT, WPARAM, LPARAM]
user32.GetClipboardData.argtypes = [UINT]
user32.GetClipboardData.restype = HANDLE
user32.SetClipboardData.argtypes = [UINT, HANDLE]
user32.SetClipboardData.restype = HANDLE
user32.IsClipboardFormatAvailable.argtypes = [UINT]
user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
user32.OpenClipboard.argtypes = [HWND]
kernel32.GetModuleHandleW.restype = HINSTANCE
kernel32.GlobalAlloc.argtypes = [UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = HANDLE
kernel32.GlobalLock.argtypes = [HANDLE]
kernel32.GlobalLock.restype = LPVOID
kernel32.GlobalUnlock.argtypes = [HANDLE]
kernel32.GlobalUnlock.restype = wintypes.BOOL
kernel32.GlobalSize.argtypes = [HANDLE]
kernel32.GlobalSize.restype = ctypes.c_size_t
shell32.DragQueryFileW.argtypes = [HANDLE, UINT, LPCWSTR, UINT]
gdi32.CreateFontW.restype = HFONT
gdi32.CreateSolidBrush.restype = HBRUSH
user32.SetWindowsHookExW.argtypes = [INT, HOOKPROC, HINSTANCE, DWORD]
user32.SetWindowsHookExW.restype = HANDLE
user32.UnhookWindowsHookEx.argtypes = [HANDLE]
user32.CallNextHookEx.argtypes = [HANDLE, INT, WPARAM, LPARAM]
user32.CallNextHookEx.restype = LRESULT
winmm.PlaySoundW.argtypes = [LPCWSTR, HINSTANCE, DWORD]
winmm.PlaySoundW.restype = wintypes.BOOL

VK_ESCAPE = 0x1B
VK_RETURN = 0x0D
VK_CONTROL = 0x11
VK_V = 0x56
KEYEVENTF_KEYUP = 0x0002
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
HOTKEY_ID = 1        # Ctrl+V -> 弹窗（主热键）
HOTKEY_ID_CSV = 2    # Ctrl+Shift+V -> 备用热键
WM_APP_REHOTKEY = 0x8001  # 模拟粘贴完成后，在 UI 线程重新注册 Ctrl+V 热键
WM_APP_TOGGLE = 0x8002    # 双击 Ctrl -> 在 UI 线程切换弹窗开关

# 低级键盘钩子
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3

SM_CXSCREEN, SM_CYSCREEN = 0, 1

# PlaySound 标志
SND_ASYNC = 0x0001
SND_NODEFAULT = 0x0002
SND_FILENAME = 0x20000
if getattr(sys, "frozen", False):  # PyInstaller 打包后：音效放在 exe 旁边
    SOUND_DIR = os.path.dirname(sys.executable)
else:
    SOUND_DIR = os.path.dirname(os.path.abspath(__file__))
SOUND_ON = os.path.join(SOUND_DIR, "复制开.wav")
SOUND_OFF = os.path.join(SOUND_DIR, "复制关.wav")

CF_UNICODETEXT, CF_DIB, CF_HDROP = 13, 8, 15
GMEM_MOVEABLE = 0x0002

# 控件 ID
ID_PASTE0 = 1000   # 条目点击（粘贴）
ID_DEL0 = 3000     # 条目删除
ID_CLEAR = 5000
ID_CLOSE = 5001
ID_QUIT = 5002

WIN_W = 430
ROW_H = 40
ROW_GAP = 3
MAX_ITEMS = 50
MAX_VISIBLE = 12

COL_BG = 0x00F8F7F6       # COLORREF 0x00BBGGRR
COL_ROW = 0x00FFFFFF
COL_HOVER = 0x00F5EFE0

# ---------- 剪贴板读写 ----------


class _ClipGuard:
    def __enter__(self):
        for _ in range(20):
            if user32.OpenClipboard(None):
                return True
            time.sleep(0.02)
        return False

    def __exit__(self, *a):
        user32.CloseClipboard()
        return False


def _read_text():
    h = user32.GetClipboardData(CF_UNICODETEXT)
    if not h:
        return None
    ptr = kernel32.GlobalLock(h)
    if not ptr:
        return None
    try:
        return ctypes.wstring_at(ptr)
    finally:
        kernel32.GlobalUnlock(h)


def _read_image():
    h = user32.GetClipboardData(CF_DIB)
    if not h:
        return None
    size = kernel32.GlobalSize(h)
    ptr = kernel32.GlobalLock(h)
    if not ptr:
        return None
    try:
        dib = ctypes.string_at(ptr, size)
    finally:
        kernel32.GlobalUnlock(h)
    if len(dib) < 40:
        return None
    bmp = b"BM" + struct.pack("<IHHI", 14 + len(dib), 0, 0, 14) + dib
    try:
        img = Image.open(io.BytesIO(bmp))
        img.load()
        return img
    except Exception:
        return None


def _read_files():
    h = user32.GetClipboardData(CF_HDROP)
    if not h:
        return None
    count = shell32.DragQueryFileW(h, 0xFFFFFFFF, None, 0)
    paths = []
    for i in range(count):
        buf = ctypes.create_unicode_buffer(1024)
        shell32.DragQueryFileW(h, i, buf, 1024)
        paths.append(buf.value)
    return paths or None


def read_clipboard():
    """返回 (sig, item) 或 None。item: {type, data, sig}"""
    with _ClipGuard() as ok:
        if not ok:
            return None
        if user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            text = _read_text()
            if text:
                item = {"type": "text", "data": text}
                item["sig"] = ("t", text)
                return (item["sig"], item)
        elif user32.IsClipboardFormatAvailable(CF_DIB):
            img = _read_image()
            if img is not None:
                try:
                    sig = ("i", hash(img.tobytes()))
                except Exception:
                    sig = ("i", time.time())
                item = {"type": "image", "data": img, "sig": sig}
                return (sig, item)
        elif user32.IsClipboardFormatAvailable(CF_HDROP):
            paths = _read_files()
            if paths:
                item = {"type": "files", "data": paths}
                item["sig"] = ("f", tuple(paths))
                return (item["sig"], item)
    return None


def set_clipboard(item):
    with _ClipGuard() as ok:
        if not ok:
            return False
        user32.EmptyClipboard()
        t = item["type"]
        if t == "text":
            raw = item["data"].encode("utf-16-le") + b"\x00\x00"
        elif t == "image":
            img = item["data"]
            if img.mode in ("RGBA", "LA", "P", "PA"):
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, "BMP")
            raw = buf.getvalue()[14:]  # CF_DIB = BMP 去掉 14 字节文件头
        else:  # files
            payload = "\0".join(item["data"]) + "\0\0"
            header = struct.pack("<IiiII", 20, 0, 0, 0, 1)  # DROPFILES, fWide=1
            raw = header + payload.encode("utf-16-le")
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(raw))
        ptr = kernel32.GlobalLock(h)
        ctypes.memmove(ptr, raw, len(raw))
        kernel32.GlobalUnlock(h)
        fmt = {"text": CF_UNICODETEXT, "image": CF_DIB, "files": CF_HDROP}[t]
        user32.SetClipboardData(fmt, h)
    return True


def send_ctrl_v():
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(VK_V, 0, 0, 0)
    time.sleep(0.03)
    user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


# ---------- 后台监控线程 ----------


def clipboard_monitor(app):
    last_seq = user32.GetClipboardSequenceNumber()
    while True:
        time.sleep(0.4)
        try:
            seq = user32.GetClipboardSequenceNumber()
            if seq == last_seq:
                continue
            last_seq = seq
            got = read_clipboard()
            if not got:
                continue
            sig, item = got
            if app.suppress_sig is not None:
                if sig == app.suppress_sig:
                    app.suppress_sig = None  # 跳过我们自己写入的那次
                    continue
                app.suppress_sig = None
            with app.lock:
                if app.history:
                    last = app.history[-1]
                    if last["type"] == item["type"] and last["sig"] == item["sig"]:
                        continue  # 连续重复
                app.history.append(item)
                if len(app.history) > MAX_ITEMS:
                    app.history.pop(0)
            user32.PostMessageW(app.hwnd, WM_APP_REFRESH, 0, 0)
        except Exception as e:
            print("[monitor]", e, flush=True)


def keyboard_hook_thread(app):
    """低级键盘钩子线程：检测双击 Ctrl，交给 UI 线程切换弹窗。"""
    def proc(n_code, wp, lp):
        if n_code == 0:
            try:
                kb = ctypes.cast(lp, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                app.on_key_event(int(wp), kb.vkCode)
            except Exception:
                pass
        return user32.CallNextHookEx(None, n_code, wp, lp)

    app._hook_proc = HOOKPROC(proc)
    app._hook = user32.SetWindowsHookExW(
        WH_KEYBOARD_LL, app._hook_proc, kernel32.GetModuleHandleW(None), 0)
    if not app._hook:
        print("[ClipStack] 警告: 键盘钩子安装失败，双击 Ctrl 不可用", flush=True)
        return
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
    user32.UnhookWindowsHookEx(app._hook)


# ---------- 主程序（UI 线程） ----------


class ClipStackApp:
    def __init__(self):
        self.history = []
        self.lock = threading.Lock()
        self.suppress_sig = None
        self.children = []
        self.hwnd = None
        self.prev_fore = None
        self._visible_gis = []
        # 双击 Ctrl 检测状态
        self._first_ctrl = 0.0
        self._last_ctrl = 0.0
        self._other_key = False
        self._awaiting = False
        self._hook = None
        self._hook_proc = None
        self.feature_on = True  # 双击 Ctrl 控制的总开关

    # ---- 双击 Ctrl 判定（钩子线程调用） ----
    def on_key_event(self, wp, vk):
        if wp not in (WM_KEYDOWN, WM_SYSKEYDOWN):
            return
        now = time.time() * 1000.0
        if vk in (VK_CONTROL, VK_LCONTROL, VK_RCONTROL):
            gap = now - self._last_ctrl
            self._last_ctrl = now
            if gap < 60:
                return  # 按住 Ctrl 的自动重复，忽略
            if self._awaiting and (now - self._first_ctrl) <= 400 and not self._other_key:
                self._awaiting = False
                if self.hwnd:
                    user32.PostMessageW(self.hwnd, WM_APP_TOGGLE, 0, 0)
            else:
                self._awaiting = True
                self._first_ctrl = now
                self._other_key = False
        else:
            self._other_key = True  # 两次 Ctrl 之间按了别的键，取消判定

    # ---- Win32 窗口搭建 ----
    def run(self):
        # 单实例保护：已有一个 ClipStack 在运行就直接退出
        _k32.CreateMutexW(None, False, "ClipStack_SingleInstance_Mutex")
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            print("[ClipStack] 已有实例在运行，本实例退出。", flush=True)
            return

        hinst = kernel32.GetModuleHandleW(None)
        self.hfont = gdi32.CreateFontW(
            -13, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, "Microsoft YaHei UI")
        self.hfont_small = gdi32.CreateFontW(
            -12, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, "Microsoft YaHei UI")
        hbr_bg = gdi32.CreateSolidBrush(COL_BG)

        self.wnd_proc = WNDPROC(self._wnd_proc)
        wc = WNDCLASSW()
        wc.lpfnWndProc = self.wnd_proc
        wc.hInstance = hinst
        wc.hCursor = user32.LoadCursorW(None, wintypes.LPCWSTR(32512))  # IDC_ARROW
        wc.hbrBackground = hbr_bg
        wc.lpszClassName = "ClipStackWnd"
        if not user32.RegisterClassW(ctypes.byref(wc)):
            raise OSError("RegisterClassW failed")

        self.hwnd = user32.CreateWindowExW(
            WS_EX_TOPMOST | WS_EX_TOOLWINDOW, "ClipStackWnd", "ClipStack",
            WS_POPUP, 0, 0, WIN_W, 300, None, None, hinst, None)
        if not self.hwnd:
            raise OSError("CreateWindowExW failed")

        if not user32.RegisterHotKey(self.hwnd, HOTKEY_ID, MOD_CONTROL, 0x56):
            print("[ClipStack] 警告: Ctrl+V 热键注册失败（可能被其他程序占用），"
                  "请用 Ctrl+Shift+V 备用热键", flush=True)
        user32.RegisterHotKey(self.hwnd, HOTKEY_ID_CSV,
                              MOD_CONTROL | MOD_SHIFT, 0x56)

        threading.Thread(target=clipboard_monitor, args=(self,), daemon=True).start()
        threading.Thread(target=keyboard_hook_thread, args=(self,), daemon=True).start()
        print("[ClipStack] 已启动：Ctrl+V（多条=弹窗选粘贴，单条=直接粘贴，"
              "双击Ctrl=功能总开关），Enter=粘最新，1-9=选第N条，Esc=取消。", flush=True)

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        user32.UnregisterHotKey(self.hwnd, HOTKEY_ID)
        user32.UnregisterHotKey(self.hwnd, HOTKEY_ID_CSV)

    def _wnd_proc(self, hwnd, msg, wp, lp):
        if msg == WM_HOTKEY and wp in (HOTKEY_ID, HOTKEY_ID_CSV):
            if wp == HOTKEY_ID and not user32.IsWindowVisible(self.hwnd):
                with self.lock:
                    n = len(self.history)
                # 功能关闭 或 历史 0/1 条：按普通 Ctrl+V 直接粘贴
                if (not self.feature_on) or n < 2:
                    self.direct_paste()
                    return 0
            self.toggle_popup()
            return 0
        if msg == WM_APP_REHOTKEY:
            # 模拟 Ctrl+V 已完成，恢复热键接管（必须回到 UI 线程注册）
            user32.RegisterHotKey(self.hwnd, HOTKEY_ID, MOD_CONTROL, 0x56)
            return 0
        if msg == WM_APP_TOGGLE:
            # 双击 Ctrl = 多条粘贴功能总开关（带提示音）
            self.feature_on = not self.feature_on
            self.play_sound(SOUND_ON if self.feature_on else SOUND_OFF)
            if self.feature_on:
                self.show_popup()  # 开启时弹一次窗作为反馈
            else:
                self.hide()        # 关闭后 Ctrl+V 始终为普通粘贴
            return 0
        if msg == WM_APP_REFRESH:
            if user32.IsWindowVisible(self.hwnd):
                self.rebuild()
            return 0
        if msg == WM_COMMAND:
            notif = (wp >> 16) & 0xFFFF
            cid = wp & 0xFFFF
            if notif == 0:  # BN_CLICKED
                self.on_command(cid)
            return 0
        if msg == WM_KEYDOWN:
            if wp == VK_ESCAPE:
                self.hide()
                return 0
            if wp == VK_RETURN:  # Enter = 粘贴最新一条
                with self.lock:
                    n = len(self.history)
                if n:
                    self.paste_item(n - 1)
                return 0
            if ord("1") <= wp <= ord("9"):  # 数字键选第 N 条
                idx = wp - ord("1")
                if 0 <= idx < len(self._visible_gis):
                    self.paste_item(self._visible_gis[idx])
                return 0
        if msg == WM_ACTIVATE and (wp & 0xFFFF) == 0:  # 失去激活 -> 关闭
            self.hide()
            return 0
        if msg == WM_CLOSE:
            self.hide()
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    # ---- 控件构建 ----
    def _ctrl(self, cls, text, style, x, y, w, h, cid):
        h = user32.CreateWindowExW(
            0, cls, text, WS_CHILD | WS_VISIBLE | style,
            x, y, w, h, self.hwnd, HMENU(cid), None, None)
        user32.SendMessageW(h, WM_SETFONT, WPARAM(self.hfont), 1)
        self.children.append(h)
        return h

    def _destroy_children(self):
        for h in self.children:
            if h:
                user32.DestroyWindow(h)
        self.children = []

    def visible_items(self):
        with self.lock:
            return list(self.history[-MAX_VISIBLE:]), len(self.history)

    def _item_label(self, item):
        if item["type"] == "text":
            txt = item["data"].replace("\r", "").replace("\n", " ↵ ")
            return ("  " + txt[:64] + ("…" if len(txt) > 64 else ""))
        if item["type"] == "image":
            w, h = item["data"].size
            return "  [图片]  %d×%d" % (w, h)
        files = item["data"]
        names = ", ".join(p.replace("/", "\\").split("\\")[-1] for p in files[:2])
        more = " 等%d个" % len(files) if len(files) > 2 else ""
        return "  [文件] %d 个%s: %s" % (len(files), more, names[:44])

    def rebuild(self):
        items, total = self.visible_items()
        self._destroy_children()
        self._visible_gis = []
        if not items:
            self._visible_gis = []
            user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, WIN_W, 90, SWP_NOMOVE)
            self._ctrl("STATIC", "  暂无记录，先复制点什么吧（Ctrl+C）",
                       SS_LEFT, 8, 32, WIN_W - 16, 26, 9001)
            return
        nd = len(items)
        H = 36 + nd * (ROW_H + ROW_GAP) + 38
        user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, WIN_W, H, SWP_NOMOVE)
        title = "  ClipStack · %d 条 · 点击/Enter/1-9=粘贴 · Esc=取消" % total
        if total > MAX_VISIBLE:
            title += "（显示最近 %d 条）" % MAX_VISIBLE
        self._ctrl("STATIC", title, SS_LEFT, 8, 9, WIN_W - 16, 20, 9002)
        y = 36
        base = len(self.history) - nd  # 全局索引
        for i, item in enumerate(items):
            gi = base + i
            self._visible_gis.append(gi)
            tag = str(i + 1) if i < 9 else " "
            self._ctrl("BUTTON", tag + self._item_label(item), BS_LEFT,
                       6, y, WIN_W - 66, ROW_H, ID_PASTE0 + gi)
            self._ctrl("BUTTON", "×", SS_CENTER,
                       WIN_W - 56, y, 30, ROW_H, ID_DEL0 + gi)
            y += ROW_H + ROW_GAP
        fy = H - 34
        self._ctrl("BUTTON", "全部清除", 0, 8, fy, 92, 26, ID_CLEAR)
        self._ctrl("BUTTON", "关闭", 0, WIN_W - 148, fy, 60, 26, ID_CLOSE)
        self._ctrl("BUTTON", "退出", 0, WIN_W - 80, fy, 60, 26, ID_QUIT)

    # ---- 显示 / 隐藏 ----
    def toggle_popup(self):
        if user32.IsWindowVisible(self.hwnd):
            self.hide()
        else:
            self.show_popup()

    def show_popup(self):
        if user32.IsWindowVisible(self.hwnd):
            return
        self.prev_fore = user32.GetForegroundWindow()
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        self.rebuild()
        # 先按目标尺寸算好高度再定位
        rect = wintypes.RECT()
        user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        sw = user32.GetSystemMetrics(SM_CXSCREEN)
        sh = user32.GetSystemMetrics(SM_CYSCREEN)
        x = min(max(pt.x, 0), max(sw - w, 0))
        y = min(max(pt.y, 0), max(sh - h, 0))
        user32.SetWindowPos(self.hwnd, HWND_TOPMOST, x, y, w, h,
                            SWP_SHOWWINDOW)
        user32.SetForegroundWindow(self.hwnd)
        user32.SetFocus(self.hwnd)

    def play_sound(self, path):
        try:
            if os.path.exists(path):
                winmm.PlaySoundW(path, None,
                                 SND_FILENAME | SND_ASYNC | SND_NODEFAULT)
        except Exception:
            pass

    def hide(self):
        user32.ShowWindow(self.hwnd, SW_HIDE)

    # ---- 交互 ----
    def on_command(self, cid):
        with self.lock:
            n = len(self.history)
        if ID_PASTE0 <= cid < ID_PASTE0 + n:
            self.paste_item(cid - ID_PASTE0)
        elif ID_DEL0 <= cid < ID_DEL0 + n:
            self.delete_item(cid - ID_DEL0)
        elif cid == ID_CLEAR:
            with self.lock:
                self.history.clear()
            self.rebuild()
        elif cid == ID_CLOSE:
            self.hide()
        elif cid == ID_QUIT:
            user32.DestroyWindow(self.hwnd)

    def direct_paste(self):
        """历史条目不足 2 条时，恢复普通 Ctrl+V 行为：原样转发粘贴。"""
        user32.UnregisterHotKey(self.hwnd, HOTKEY_ID)
        self.prev_fore = user32.GetForegroundWindow()
        threading.Thread(target=self._delayed_paste, daemon=True).start()

    def paste_item(self, gi):
        with self.lock:
            item = dict(self.history[gi]) if 0 <= gi < len(self.history) else None
        if item is None:
            return
        self.suppress_sig = item["sig"]
        set_clipboard(item)
        # 先解除 Ctrl+V 接管，防止我们模拟的 Ctrl+V 又触发自己的热键
        user32.UnregisterHotKey(self.hwnd, HOTKEY_ID)
        self.hide()
        threading.Thread(target=self._delayed_paste, daemon=True).start()

    def _delayed_paste(self):
        time.sleep(0.15)
        if self.prev_fore:
            user32.SetForegroundWindow(self.prev_fore)
            time.sleep(0.08)
        send_ctrl_v()
        time.sleep(0.15)
        # 回到 UI 线程重新注册热键
        user32.PostMessageW(self.hwnd, WM_APP_REHOTKEY, 0, 0)

    def delete_item(self, gi):
        with self.lock:
            if 0 <= gi < len(self.history):
                self.history.pop(gi)
        self.rebuild()
        user32.SetFocus(self.hwnd)


if __name__ == "__main__":
    app = ClipStackApp()
    app.run()
