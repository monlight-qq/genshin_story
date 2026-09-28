"""Windows 原神对白连按工具。仅使用 Python 标准库。"""

import argparse
import atexit
import ctypes as C
from ctypes import wintypes as W
import math
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
import time

from story_guard import Marker, FixedPoint, PATCH_SIZE, StoryGuard, load_markers, save_markers, load_option, save_option
from story_guard import CloseGuard, load_close_markers, save_close_marker


def say(message, flush=True):
    print(message, flush=flush)
    logging.getLogger("story").info(message)


def configure_logging():
    logger = logging.getLogger("story")
    logger.setLevel(logging.INFO)
    try:
        handler = RotatingFileHandler(Path(__file__).with_name("auto_story.log"),
                                      maxBytes=500_000, backupCount=1, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger.addHandler(handler)
    except OSError as exc:
        print(f"无法写入日志，但仍可运行：{exc}", flush=True)


class BITMAPINFOHEADER(C.Structure):
    _fields_ = [("biSize", W.DWORD), ("biWidth", W.LONG), ("biHeight", W.LONG),
                ("biPlanes", W.WORD), ("biBitCount", W.WORD),
                ("biCompression", W.DWORD), ("biSizeImage", W.DWORD),
                ("biXPelsPerMeter", W.LONG), ("biYPelsPerMeter", W.LONG),
                ("biClrUsed", W.DWORD), ("biClrImportant", W.DWORD)]


class BITMAPINFO(C.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", W.DWORD * 1)]


class MSG(C.Structure):
    _fields_ = [("hwnd", W.HWND), ("message", W.UINT), ("wParam", W.WPARAM),
                ("lParam", W.LPARAM), ("time", W.DWORD), ("pt", W.POINT),
                ("lPrivate", W.DWORD)]


class MOUSEINPUT(C.Structure):
    _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("mouseData", W.DWORD),
                ("dwFlags", W.DWORD), ("time", W.DWORD),
                ("dwExtraInfo", C.c_size_t)]


class KEYBDINPUT(C.Structure):
    _fields_ = [("wVk", W.WORD), ("wScan", W.WORD),
                ("dwFlags", W.DWORD), ("time", W.DWORD),
                ("dwExtraInfo", C.c_size_t)]


class HARDWAREINPUT(C.Structure):
    _fields_ = [("uMsg", W.DWORD), ("wParamL", W.WORD), ("wParamH", W.WORD)]


class INPUTUNION(C.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(C.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", W.DWORD), ("data", INPUTUNION)]


def bind(dll, name, args, result):
    fn = getattr(dll, name)
    fn.argtypes, fn.restype = args, result
    return fn


class Windows:
    def __init__(self):
        self.bound_window = None
        self.hotkeys = {}
        u = C.WinDLL("user32", use_last_error=True)
        k = C.WinDLL("kernel32", use_last_error=True)
        # 使用物理坐标，避免 Windows 缩放使标定点偏移。
        try:
            aware = bind(u, "SetProcessDpiAwarenessContext", [W.HANDLE], W.BOOL)
            aware(C.c_void_p(-4))
        except AttributeError:
            bind(u, "SetProcessDPIAware", [], W.BOOL)()
        self.foreground = bind(u, "GetForegroundWindow", [], W.HWND)
        self.pid = bind(u, "GetWindowThreadProcessId", [W.HWND, C.POINTER(W.DWORD)], W.DWORD)
        self.open_process = bind(k, "OpenProcess", [W.DWORD, W.BOOL, W.DWORD], W.HANDLE)
        self.image_name = bind(k, "QueryFullProcessImageNameW",
                               [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)], W.BOOL)
        self.close = bind(k, "CloseHandle", [W.HANDLE], W.BOOL)
        self.key_state = bind(u, "GetAsyncKeyState", [C.c_int], W.SHORT)
        self.register_hotkey = bind(u, "RegisterHotKey", [W.HWND, C.c_int, W.UINT, W.UINT], W.BOOL)
        self.unregister_hotkey = bind(u, "UnregisterHotKey", [W.HWND, C.c_int], W.BOOL)
        self.peek_message = bind(u, "PeekMessageW", [C.POINTER(MSG), W.HWND, W.UINT, W.UINT, W.UINT], W.BOOL)
        self.cursor = bind(u, "GetCursorPos", [C.POINTER(W.POINT)], W.BOOL)
        self.rect = bind(u, "GetClientRect", [W.HWND, C.POINTER(W.RECT)], W.BOOL)
        self.to_client = bind(u, "ScreenToClient", [W.HWND, C.POINTER(W.POINT)], W.BOOL)
        self.to_screen = bind(u, "ClientToScreen", [W.HWND, C.POINTER(W.POINT)], W.BOOL)
        self.move = bind(u, "SetCursorPos", [C.c_int, C.c_int], W.BOOL)
        self.send = bind(u, "SendInput", [W.UINT, C.POINTER(INPUT), C.c_int], W.UINT)
        g = C.WinDLL("gdi32", use_last_error=True)
        self.get_dc = bind(u, "GetDC", [W.HWND], W.HDC)
        self.release_dc = bind(u, "ReleaseDC", [W.HWND, W.HDC], C.c_int)
        self.create_dc = bind(g, "CreateCompatibleDC", [W.HDC], W.HDC)
        self.create_bitmap = bind(g, "CreateDIBSection",
                                  [W.HDC, C.POINTER(BITMAPINFO), W.UINT,
                                   C.POINTER(C.c_void_p), W.HANDLE, W.DWORD], W.HANDLE)
        self.select_object = bind(g, "SelectObject", [W.HDC, W.HANDLE], W.HANDLE)
        self.blit = bind(g, "BitBlt", [W.HDC, C.c_int, C.c_int, C.c_int, C.c_int,
                                      W.HDC, C.c_int, C.c_int, W.DWORD], W.BOOL)
        self.flush = bind(g, "GdiFlush", [], W.BOOL)
        self.delete_object = bind(g, "DeleteObject", [W.HANDLE], W.BOOL)
        self.delete_dc = bind(g, "DeleteDC", [W.HDC], W.BOOL)

    def register_keys(self, keys):
        for name, vk in keys.items():
            if not self.register_hotkey(None, vk, 0x4000, vk):  # MOD_NOREPEAT
                error = C.get_last_error()
                self.unregister_keys()
                raise RuntimeError(f"无法注册 {name} 热键（错误 {error}）。请先关闭旧脚本或占用热键的程序，再启动。")
            self.hotkeys[vk] = name
        atexit.register(self.unregister_keys)

    def unregister_keys(self):
        for identifier in self.hotkeys:
            self.unregister_hotkey(None, identifier)
        self.hotkeys.clear()

    def hotkey_events(self):
        pressed = set()
        message = MSG()
        while self.peek_message(C.byref(message), None, 0x0312, 0x0312, 1):
            name = self.hotkeys.get(message.wParam)
            if name:
                pressed.add(name)
        return pressed

    def bind_foreground(self):
        hwnd = self.foreground()
        if not hwnd:
            raise ValueError("没有前台窗口，请先点击云原神游戏画面。")
        width, height = self.size(hwnd)
        if width < 320 or height < 240:
            raise ValueError("窗口过小，请展开云原神画面后再绑定。")
        pid = W.DWORD()
        if not self.pid(hwnd, C.byref(pid)) or not pid.value:
            raise ValueError("无法读取窗口身份，请重新点击游戏画面。")
        self.bound_window = hwnd, pid.value
        return hwnd, width, height

    def foreground_name(self):
        hwnd = self.foreground()
        if not hwnd:
            return "无前台窗口"
        pid = W.DWORD()
        self.pid(hwnd, C.byref(pid))
        handle = self.open_process(0x1000, False, pid.value)
        if not handle:
            return f"PID={pid.value}（无法读取进程名，错误 {C.get_last_error()}）"
        try:
            buf, size = C.create_unicode_buffer(32768), W.DWORD(32768)
            if self.image_name(handle, 0, buf, C.byref(size)):
                return f"{Path(buf.value).name}，PID={pid.value}"
            return f"PID={pid.value}（进程名读取失败）"
        finally:
            self.close(handle)

    def report_diagnostics(self, executables, dialogue, gameplay, threshold, option=None, end_mode="auto"):
        say(f"[诊断] Python：{sys.executable}")
        say(f"[诊断] 前台进程：{self.foreground_name()}")
        say(f"[诊断] 窗口模式：{'F2 手动绑定' if self.bound_window else '本地原神自动识别'}")
        hwnd = self.game_window(executables)
        say(f"[诊断] 游戏窗口：{'已识别' if hwnd else '未识别；云原神请先点击画面再按 F2'}")
        say(f"[诊断] 结束模式：{end_mode}；选项目标：{'已保存' if option else '未保存；默认按 F 确认无需图标，F7 可记录位置'}")
        for name, marker in (("对白", dialogue), ("探索", gameplay)):
            if marker is None:
                say(f"[诊断] {name}图标：未标定")
            elif hwnd:
                say(f"[诊断] {name}图标匹配：{self.marker_score(hwnd, marker):.1%}，阈值 {threshold:.1%}")
        if hwnd and option:
            say(f"[诊断] 当前选项位置：{self.find_option(hwnd, option, threshold)}")
        say("[诊断] 查看控制台与同目录 auto_story.log；若功能键没有提示，可尝试 Fn+功能键。")

    def game_window(self, executables):
        hwnd = self.foreground()
        if not hwnd:
            return None
        pid = W.DWORD()
        self.pid(hwnd, C.byref(pid))
        if self.bound_window is not None:
            # 云客户端/浏览器只认可用户主动绑定的这一窗口和进程。
            # 不将整个浏览器进程下的其他窗口当作游戏。
            return hwnd if (hwnd, pid.value) == self.bound_window else None
        handle = self.open_process(0x1000, False, pid.value)
        if not handle:
            return None
        try:
            buf, size = C.create_unicode_buffer(32768), W.DWORD(32768)
            if self.image_name(handle, 0, buf, C.byref(size)):
                if Path(buf.value).name.casefold() in executables:
                    return hwnd
        finally:
            self.close(handle)
        return None

    def size(self, hwnd):
        rect = W.RECT()
        if not self.rect(hwnd, C.byref(rect)):
            raise C.WinError(C.get_last_error())
        return rect.right - rect.left, rect.bottom - rect.top

    def capture_option(self, hwnd):
        point = W.POINT()
        if not self.cursor(C.byref(point)) or not self.to_client(hwnd, C.byref(point)):
            raise C.WinError(C.get_last_error())
        width, height = self.size(hwnd)
        if not (0 <= point.x < width and 0 <= point.y < height):
            raise ValueError("鼠标必须放在游戏画面中的选项上。")
        return hwnd, width, height, point.x, point.y

    def patch(self, hwnd, width, height, x, y, region_width=PATCH_SIZE, region_height=PATCH_SIZE):
        if self.foreground() != hwnd:
            raise ValueError("游戏失去焦点。")
        if self.size(hwnd) != (width, height):
            raise ValueError("分辨率已改变，请用 F5/F4 重新标定结束检测。")
        if not (0 <= x <= width - region_width and 0 <= y <= height - region_height
                and region_width > 0 and region_height > 0):
            raise ValueError("截图区域超出窗口。")
        point = W.POINT(x, y)
        if not self.to_screen(hwnd, C.byref(point)):
            raise C.WinError(C.get_last_error())
        screen = memory = bitmap = previous = None
        try:
            screen = self.get_dc(None)
            if not screen:
                raise C.WinError(C.get_last_error())
            memory = self.create_dc(screen)
            if not memory:
                raise C.WinError(C.get_last_error())
            info = BITMAPINFO()
            info.bmiHeader = BITMAPINFOHEADER(
                biSize=C.sizeof(BITMAPINFOHEADER), biWidth=region_width,
                biHeight=-region_height, biPlanes=1, biBitCount=32)
            bits = C.c_void_p()
            bitmap = self.create_bitmap(screen, C.byref(info), 0, C.byref(bits), None, 0)
            if not bitmap or not bits.value:
                raise C.WinError(C.get_last_error())
            previous = self.select_object(memory, bitmap)
            if not previous or previous == C.c_void_p(-1).value:
                previous = None
                raise C.WinError(C.get_last_error())
            if (not self.blit(memory, 0, 0, region_width, region_height, screen,
                              point.x, point.y, 0x00CC0020 | 0x40000000)
                    or not self.flush()):
                raise C.WinError(C.get_last_error())
            if self.foreground() != hwnd:
                raise ValueError("截图时游戏失去焦点。")
            return C.string_at(bits, region_width * region_height * 4)
        finally:
            if previous:
                self.select_object(memory, previous)
            if bitmap:
                self.delete_object(bitmap)
            if memory:
                self.delete_dc(memory)
            if screen:
                self.release_dc(None, screen)

    def capture_marker(self, hwnd, neutral=True):
        _, width, height, x, y = self.capture_option(hwnd)
        x, y = x - PATCH_SIZE // 2, y - PATCH_SIZE // 2
        if not (0 <= x <= width - PATCH_SIZE and 0 <= y <= height - PATCH_SIZE):
            raise ValueError("标定点离窗口边缘太近。")
        return Marker.calibrate(width, height, x, y, self.patch(hwnd, width, height, x, y), neutral)

    def marker_score(self, hwnd, marker):
        x, y = max(0, marker.x - 2), max(0, marker.y - 2)
        right = min(marker.width, marker.x + PATCH_SIZE + 2)
        bottom = min(marker.height, marker.y + PATCH_SIZE + 2)
        pixels = self.patch(hwnd, marker.width, marker.height, x, y, right - x, bottom - y)
        return marker.best_score(pixels, right - x, bottom - y)

    def marker_visible(self, hwnd, marker, threshold):
        return self.marker_score(hwnd, marker) >= threshold

    def find_option(self, hwnd, marker, threshold):
        if isinstance(marker, FixedPoint):
            if self.foreground() != hwnd:
                return None
            if self.size(hwnd) != (marker.width, marker.height):
                raise ValueError("分辨率已改变，请用 F7 重新记录固定选项位置。")
            return hwnd, marker.width, marker.height, marker.x, marker.y
        # 同一列附近横向容错 16 px，纵向寻找不同数量的选项。
        x = max(0, marker.x - 16)
        right = min(marker.width, marker.x + PATCH_SIZE + 16)
        y = max(0, min(int(marker.height * 0.2), marker.y))
        bottom = min(marker.height, max(int(marker.height * 0.9), marker.y + PATCH_SIZE))
        pixels = self.patch(hwnd, marker.width, marker.height, x, y, right - x, bottom - y)
        hits = marker.scan(pixels, right - x, bottom - y, max(0.9, threshold))
        if not hits:
            return None
        hit_x, hit_y, _ = hits[0]  # 默认选最上方的一个，不根据文字做分支判断。
        return hwnd, marker.width, marker.height, x + hit_x + PATCH_SIZE // 2, y + hit_y + PATCH_SIZE // 2

    def find_close(self, hwnd, markers, threshold):
        for marker in markers:
            # 只在用户标定过的游戏按钮附近寻找，避免把字幕中的 X 当关闭按钮。
            radius = 32
            x, y = max(0, marker.x - radius), max(0, marker.y - radius)
            right = min(marker.width, marker.x + PATCH_SIZE + radius)
            bottom = min(marker.height, marker.y + PATCH_SIZE + radius)
            pixels = self.patch(hwnd, marker.width, marker.height, x, y, right - x, bottom - y)
            hits = marker.scan(pixels, right - x, bottom - y, threshold, limit=1)
            if hits:
                hit_x, hit_y, _ = hits[0]
                return hwnd, marker.width, marker.height, x + hit_x + PATCH_SIZE // 2, y + hit_y + PATCH_SIZE // 2
        return None

    def inject(self, events):
        batch = (INPUT * len(events))(*events)
        sent = self.send(len(batch), batch, C.sizeof(INPUT))
        if sent != len(batch):
            # 尽量释放可能只发送了按下事件的按键/鼠标。
            release = (INPUT * 2)(
                INPUT(type=1, ki=KEYBDINPUT(wScan=0x39, dwFlags=0x0A)),
                INPUT(type=0, mi=MOUSEINPUT(dwFlags=4)),
            )
            self.send(2, release, C.sizeof(INPUT))
            release_f = (INPUT * 1)(INPUT(type=1, ki=KEYBDINPUT(wScan=0x21, dwFlags=0x0A)))
            self.send(1, release_f, C.sizeof(INPUT))
            raise RuntimeError("输入发送失败，已暂停。若游戏以管理员运行，脚本也需同等权限。")

    def press_key(self, hwnd, key, dry_run):
        if self.foreground() != hwnd:
            return
        if dry_run:
            say(f"[演练] 发送{'空格' if key == 'space' else key.upper()}", flush=True)
            return
        scan = {"space": 0x39, "f": 0x21}[key]
        self.inject([INPUT(type=1, ki=KEYBDINPUT(wScan=scan, dwFlags=0x08))])
        try:
            time.sleep(0.08)
        finally:
            # 即便短按期间切出窗口或 Ctrl+C，也要松开按键。
            self.inject([INPUT(type=1, ki=KEYBDINPUT(wScan=scan, dwFlags=0x0A))])

    def advance(self, hwnd, dry_run):
        self.press_key(hwnd, "space", dry_run)

    def select_option(self, hwnd, option, action, dry_run):
        if action == "mouse":
            self.click_option(hwnd, option, dry_run)
            return
        saved_hwnd, width, height, x, y = option
        if hwnd != saved_hwnd or self.size(hwnd) != (width, height):
            raise ValueError("窗口或分辨率已改变，请用 F7 重新标定。")
        if self.foreground() != hwnd:
            return
        if dry_run:
            say(f"[演练] 将鼠标移到固定选项 ({x}, {y})，按 F 确认。")
            return
        point = W.POINT(x, y)
        if not self.to_screen(hwnd, C.byref(point)) or not self.move(point.x, point.y):
            raise C.WinError(C.get_last_error())
        self.press_key(hwnd, "f", False)

    def click_option(self, hwnd, option, dry_run):
        saved_hwnd, width, height, x, y = option
        if hwnd != saved_hwnd or self.size(hwnd) != (width, height):
            raise ValueError("窗口或分辨率已改变，请暂停后用 F7 重新标定。")
        if self.foreground() != hwnd:
            return
        if dry_run:
            say(f"[演练] 点击选项：({x}, {y})", flush=True)
            return
        point = W.POINT(x, y)
        if not self.to_screen(hwnd, C.byref(point)):
            raise C.WinError(C.get_last_error())
        if self.foreground() != hwnd:
            return
        if not self.move(point.x, point.y):
            raise C.WinError(C.get_last_error())
        if self.foreground() == hwnd:
            self.inject([INPUT(type=0, mi=MOUSEINPUT(dwFlags=2))])
            try:
                time.sleep(0.05)
            finally:
                self.inject([INPUT(type=0, mi=MOUSEINPUT(dwFlags=4))])


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number < 0.2:
        raise argparse.ArgumentTypeError("间隔必须是至少 0.2 秒的有限数字。")
    return number


def confidence(value):
    number = float(value)
    if not math.isfinite(number) or not 0.5 <= number <= 1:
        raise argparse.ArgumentTypeError("匹配阈值必须在 0.5 到 1 之间。")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=positive, default=0.7, help="对白间隔，默认 0.7 秒")
    parser.add_argument("--option-interval", type=positive, default=1.8, help="选项点击间隔")
    parser.add_argument("--exe", action="append", help="游戏进程名，可重复指定")
    parser.add_argument("--dry-run", action="store_true", help="只显示动作，不发送输入")
    parser.add_argument("--end-delay", type=positive, default=2.0, help="对白标记消失多久后暂停，默认 2 秒；期间不发送输入")
    parser.add_argument("--match-threshold", type=confidence, default=0.9, help="UI 边缘匹配比例，默认 0.9")
    parser.add_argument("--end-mode", choices=("auto", "gameplay", "dialogue"), default="auto",
                        help="auto 优先用探索图标判断结束；gameplay 无需对白图标；dialogue 使用原对白检测")
    parser.add_argument("--option-mode", choices=("fixed", "detect"), default="fixed", help="fixed 固定选项位置；detect 图标搜索")
    parser.add_argument("--option-key", choices=("f", "mouse"), default="f", help="选项确认方式，默认 F")
    parser.add_argument("--advance-key", choices=("space", "f"), default="space", help="普通对白推进键，默认空格")
    parser.add_argument("--interact-key", choices=("f", "none"), default="f", help="在探索中按 F8 时用 F 开始交互；none 关闭")
    parser.add_argument("--interaction-timeout", type=positive, default=8.0, help="NPC 交互后等待对白的超时秒数")
    parser.add_argument("--close-threshold", type=confidence, default=0.92, help="关闭按钮匹配比例，默认 0.92")
    parser.add_argument("--close-cooldown", type=positive, default=1.5, help="同一个 × 按钮重试间隔，默认 1.5 秒")
    parser.add_argument("--no-auto-close", action="store_true", help="禁用 × 自动点击")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("此脚本仅支持 Windows。")
    api = Windows()
    calibration_path = Path(__file__).resolve().with_name("story_markers.json")
    option_path = Path(__file__).resolve().with_name("story_option.json")
    close_path = Path(__file__).resolve().with_name("story_close.json")
    close_markers = []
    try:
        close_markers = load_close_markers(close_path)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        say(f"关闭按钮标定不可用，请用 F3 重新标定：{exc}")
    dialogue = gameplay = None
    try:
        dialogue, gameplay = load_markers(calibration_path)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        say(f"标定文件不可用，请重新标定：{exc}", flush=True)
    executables = {name.casefold() for name in (args.exe or ["YuanShen.exe", "GenshinImpact.exe"])}
    option = None
    try:
        option = load_option(option_path)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        say(f"选项图标标定不可用，请用 F7 重新标定：{exc}")
    if option and isinstance(option, FixedPoint) != (args.option_mode == "fixed"):
        option = None
        say("已忽略另一选项模式的旧标定；固定模式可直接按 F 确认，F7 可选。")
    running, auto_option, active_hwnd = False, bool(option) or (args.option_key == "f" and args.option_mode == "fixed"), None
    opening, opening_deadline, opening_ready_since = False, 0.0, None
    close_guard = CloseGuard(args.close_cooldown)
    close_next_check = close_settle_until = close_grace_deadline = 0.0
    close_target = None
    keys = {"F2": 0x71, "F3": 0x72, "F4": 0x73, "F5": 0x74, "F6": 0x75, "F7": 0x76, "F8": 0x77, "F9": 0x78, "F10": 0x79}
    api.register_keys(keys)
    previous = {name: bool(api.key_state(vk) & 0x8000) for name, vk in keys.items()}
    next_advance = next_option = 0.0
    guard, next_check, last_state = StoryGuard(args.end_delay), 0.0, "active"
    say("原神对白连按工具（启动时暂停）\n"
          "F8：开始/暂停  F9：退出\n"
          "F2：绑定当前云原神客户端/浏览器窗口  F10：显示诊断信息\n"
          "F3：标定游戏内 × 关闭按钮（暂停时，保存后自动检测）\n"
          "F7：记录固定选项位置（可选）  F6：开关自动选择\n"
          "F4：标定探索图标（推荐，一次即可）  F5：标定对白图标（备用）\n"
          "已有探索标定时，不因对白图标变化而暂停；探索图标重新出现才结束。\n"
          "切出游戏会停止，切回后需再按 F8。", flush=True)
    say(f"普通对白：{args.advance_key.upper()}；选项：{'F 确认' if args.option_key == 'f' else '鼠标点击'}；选项模式：{args.option_mode}。")
    say("在 NPC 旁出现交互提示后按 F8：先按一次 F，等待进入对白，再自动推进。结束后自动暂停。")
    if dialogue:
        say("已载入对白标定。若改变分辨率、缩放或界面布局，请重新标定。", flush=True)
    if gameplay:
        say("已载入探索标定，默认不需要反复 F5。")
    if option:
        say("已载入固定选项位置。" if isinstance(option, FixedPoint) else "已载入选项图标；会选择最上方匹配项。")
    elif auto_option:
        say("自动按 F 确认已开启，无需标定图标；F7 可记录固定选项位置，F6 可关闭。")
    if close_markers:
        say(f"已载入 {len(close_markers)} 个 × 关闭按钮标定，自动关闭{'已禁用' if args.no_auto_close else '已开启'}。")
    if args.dry_run:
        say("演练模式：不会发送按键或点击。", flush=True)
    while True:
        pressed = api.hotkey_events()
        for name, vk in keys.items():
            down = bool(api.key_state(vk) & 0x8000)
            previous[name] = down
        if "F9" in pressed:
            say("已退出。", flush=True)
            return
        hwnd = api.game_window(executables)
        if (running or opening or close_grace_deadline > time.monotonic()) and hwnd != active_hwnd:
            running = opening = False
            close_grace_deadline = 0.0
            close_target = None
            say("游戏失去焦点，已暂停。切回游戏后按 F8 继续。", flush=True)
        try:
            if "F2" in pressed:
                running = opening = False
                close_grace_deadline = close_settle_until = 0.0
                close_target = None
                close_guard = CloseGuard(args.close_cooldown)
                hwnd, width, height = api.bind_foreground()
                active_hwnd = None
                # 同尺寸重绑/重启保留已保存的图标，不再强制每次 F5。
                if dialogue and (dialogue.width, dialogue.height) != (width, height):
                    dialogue = None
                if gameplay and (gameplay.width, gameplay.height) != (width, height):
                    gameplay = None
                if option and (option.width, option.height) != (width, height):
                    option = None
                    auto_option = auto_option and args.option_mode == "fixed" and args.option_key == "f"
                close_markers = [item for item in close_markers if (item.width, item.height) == (width, height)]
                say(f"已绑定当前窗口（{width}×{height}），保留同尺寸标定。首次使用推荐在探索界面按 F4，再在对白中 F8 开始。")
            if "F10" in pressed:
                say(f"[诊断] 普通对白键：{args.advance_key}；选项模式：{args.option_mode}；确认方式：{args.option_key}；自动确认：{auto_option}")
                api.report_diagnostics(executables, dialogue, gameplay, args.match_threshold, option,
                                       "gameplay" if args.end_mode == "auto" and gameplay else args.end_mode)
                say(f"[诊断] × 模板：{len(close_markers)}；自动关闭：{not args.no_auto_close}；收尾检测：{close_grace_deadline > time.monotonic()}")
                if hwnd and close_markers:
                    say(f"[诊断] 当前 × 位置：{api.find_close(hwnd, close_markers, args.close_threshold)}")
            if "F3" in pressed:
                if running or opening or close_grace_deadline > time.monotonic():
                    say("请先按 F8 暂停，再将鼠标放到游戏内 × 按钮中央，按 F3。")
                elif not hwnd:
                    say("未识别游戏窗口，云原神请先 F2 绑定。")
                else:
                    candidate = api.capture_marker(hwnd, neutral=False)
                    close_markers = save_close_marker(close_path, close_markers, candidate)
                    say(f"已保存 × 关闭按钮（共 {len(close_markers)} 个）。运行时检测到标定区域内的 × 会自动点击。")
            for key in ("F4", "F5"):
                if key not in pressed:
                    continue
                if running or opening or close_grace_deadline > time.monotonic():
                    say("请先按 F8 暂停，再标定界面图标。", flush=True)
                elif not hwnd:
                    say("未识别游戏窗口。云原神请先点击画面按 F2 绑定，再标定。", flush=True)
                else:
                    marker = api.capture_marker(hwnd)
                    new_dialogue = marker if key == "F5" else dialogue
                    new_gameplay = marker if key == "F4" else gameplay
                    # 两个模板必须属于相同分辨率；旧的另一模板失效时清除它。
                    other = new_gameplay if key == "F5" else new_dialogue
                    if other and (other.width, other.height) != (marker.width, marker.height):
                        if key == "F5":
                            new_gameplay = None
                        else:
                            new_dialogue = None
                        say("已清除旧分辨率的另一界面标定。", flush=True)
                    save_markers(calibration_path, new_dialogue, new_gameplay)
                    dialogue, gameplay = new_dialogue, new_gameplay
                    close_markers = [item for item in close_markers
                                     if (item.width, item.height) == (marker.width, marker.height)]
                    if option and (option.width, option.height) != (marker.width, marker.height):
                        option = None
                        auto_option = auto_option and args.option_mode == "fixed" and args.option_key == "f"
                        say("已禁用旧分辨率的选项模板，请用 F7 重新标定。")
                    say(f"已保存{'对白' if key == 'F5' else '探索'}图标标定。", flush=True)
                    if key == "F4" and args.end_mode == "auto":
                        say("默认改用探索界面判断结束：对白/选项图标切换时继续运行，无需反复 F5。")
            if "F7" in pressed:
                if running or opening or close_grace_deadline > time.monotonic():
                    say("请先按 F8 暂停，再标定选项。", flush=True)
                elif hwnd:
                    if args.option_mode == "fixed":
                        _, width, height, x, y = api.capture_option(hwnd)
                        candidate = FixedPoint(width, height, x, y)
                    else:
                        candidate = api.capture_marker(hwnd, neutral=False)
                    save_option(option_path, candidate)
                    option, auto_option = candidate, True
                    say("已保存固定选项位置，后续在此位置确认，无需图标标定。" if isinstance(option, FixedPoint)
                        else "已保存选项图标，自动选择已开启，会寻找最上方匹配项。")
                else:
                    say("未识别游戏窗口。云原神请先点击游戏画面，按 F2 绑定后再标定。", flush=True)
            if "F6" in pressed:
                if auto_option:
                    auto_option = False
                elif option or (args.option_mode == "fixed" and args.option_key == "f"):
                    auto_option = True
                else:
                    say("请将鼠标移到选项左侧固定小图标（不是文字）上，按 F7 标定一次。", flush=True)
                say(f"自动选择：{'开启' if auto_option else '关闭'}", flush=True)
            if "F8" in pressed:
                if running or opening or close_grace_deadline > time.monotonic():
                    running = opening = False
                    close_grace_deadline = close_settle_until = 0.0
                    close_target = None
                    say("已暂停。", flush=True)
                elif hwnd:
                    mode = "gameplay" if args.end_mode == "auto" and gameplay else (
                        "dialogue" if args.end_mode == "auto" else args.end_mode)
                    start_close = (api.find_close(hwnd, close_markers, args.close_threshold)
                                   if close_markers and not args.no_auto_close else None)
                    close_guard = CloseGuard(args.close_cooldown)
                    close_target = None
                    close_next_check = close_settle_until = 0.0
                    if start_close:
                        active_hwnd = hwnd
                        running = bool(gameplay if mode == "gameplay" else dialogue)
                        guard, last_state = StoryGuard(args.end_delay, mode), "active"
                        close_grace_deadline = time.monotonic() + 5.0
                        close_target = start_close
                        close_settle_until = time.monotonic() + 0.3
                        next_advance = next_option = time.monotonic() + 0.3
                        next_check = 0.0
                        say("检测到 ×，将优先点击关闭按钮，再继续对白或暂停收尾。")
                    elif mode == "gameplay" and not gameplay:
                        say("请先在探索界面按 F4 标定固定白色图标，再进入对白按 F8。")
                    elif mode == "dialogue" and not dialogue:
                        say("请先在探索界面按 F4（推荐），或在对白中按 F5 标定。", flush=True)
                    elif gameplay and api.marker_visible(hwnd, gameplay, args.match_threshold):
                        if args.interact_key == "f":
                            api.press_key(hwnd, "f", args.dry_run)
                            opening, active_hwnd = True, hwnd
                            opening_ready_since = None
                            opening_deadline = time.monotonic() + args.interaction_timeout
                            guard = StoryGuard(args.end_delay, mode)
                            next_check = time.monotonic() + 0.2
                            say("已按 F 开始交互，正在等待进入对白；请站在有对话提示的 NPC 旁。")
                        else:
                            say("检测到探索界面，不启动。可用 --interact-key f 启用 NPC 交互。")
                    elif (mode == "dialogue" and not api.marker_visible(hwnd, dialogue, args.match_threshold)
                          and not (auto_option and isinstance(option, Marker) and api.find_option(hwnd, option, args.match_threshold))):
                        say("未检测到对白界面或检测到探索界面，不启动。必要时用 F5/F4 重新标定。", flush=True)
                    else:
                        running, active_hwnd = True, hwnd
                        guard, last_state = StoryGuard(args.end_delay, mode), "active"
                        next_check = 0.0
                        next_advance = next_option = time.monotonic() + 0.3
                        say(f"开始推进对白，结束模式：{'探索界面恢复' if mode == 'gameplay' else '对白标记消失'}。", flush=True)
                else:
                    say("未识别前台游戏窗口。云原神请先按 F2 绑定；本地版请切回游戏。F10 可查看诊断。", flush=True)
            now = time.monotonic()
            blocked = any(previous.values()) or any(
                api.key_state(vk) & 0x8000 for vk in (0x10, 0x11, 0x12, 0x5B, 0x5C))
            close_active = running or opening or close_grace_deadline > now
            if close_active and close_markers and not args.no_auto_close:
                if now >= close_next_check and not blocked:
                    close_target = api.find_close(hwnd, close_markers, args.close_threshold)
                    close_next_check = time.monotonic() + 0.15
                    if close_target:
                        close_settle_until = max(close_settle_until, now + 0.3)
                    if close_guard.update(time.monotonic(), close_target):
                        api.click_option(hwnd, close_target, args.dry_run)
                        say(f"已{'模拟点击' if args.dry_run else '点击'} × 关闭按钮。")
                        close_settle_until = time.monotonic() + 0.6
                        next_advance = next_option = close_settle_until
                if close_target or now < close_settle_until:
                    # 弹窗遮住对白时，优先关闭，不发送 F/空格，也不提前判断剧情结束。
                    time.sleep(0.025)
                    continue
            if opening and now >= next_check:
                gameplay_visible = api.marker_visible(hwnd, gameplay, args.match_threshold)
                ready = not gameplay_visible and (guard.mode == "gameplay" or api.marker_visible(hwnd, dialogue, args.match_threshold))
                if ready:
                    if opening_ready_since is None:
                        opening_ready_since = now
                    elif now - opening_ready_since >= 0.2:
                        opening, running, last_state = False, True, "active"
                        next_advance = next_option = time.monotonic() + 0.3
                        say(f"已进入对白，开始 {args.advance_key.upper()} 推进和 {args.option_key.upper()} 确认。")
                else:
                    opening_ready_since = None
                if opening and now >= opening_deadline:
                    opening = False
                    say("F 交互后未进入对白，已暂停；确认 NPC 对话提示出现后再按 F8。")
                next_check = time.monotonic() + 0.1
            option_due = bool(auto_option and (option or (args.option_mode == "fixed" and args.option_key == "f"))
                              and now >= next_option and not blocked)
            action_due = now >= next_advance or option_due
            detected_option = None
            # 定期检测，并在每次计划发送输入前重新读画面，避免使用旧检测结果。
            if running and (now >= next_check or (last_state == "active" and action_due)):
                gameplay_visible = bool(gameplay and api.marker_visible(hwnd, gameplay, args.match_threshold))
                dialogue_visible = bool(guard.mode == "gameplay" or (dialogue and not gameplay_visible
                                       and api.marker_visible(hwnd, dialogue, args.match_threshold)))
                if not gameplay_visible and auto_option and option and (option_due or not dialogue_visible):
                    detected_option = api.find_option(hwnd, option, args.match_threshold)
                    # 固定坐标只是操作目标，不能作为“对白仍存在”的视觉证据。
                    dialogue_visible = dialogue_visible or (bool(detected_option) and isinstance(option, Marker))
                    # 搜索期间可能已回到探索；发送输入前再确认一次。
                    gameplay_visible = bool(gameplay and api.marker_visible(hwnd, gameplay, args.match_threshold))
                if option_due:
                    next_option = time.monotonic() + args.option_interval
                state = guard.update(time.monotonic(), dialogue_visible, gameplay_visible)
                next_check = time.monotonic() + 0.1
                if state == "ended":
                    running = False
                    if close_markers and not args.no_auto_close:
                        close_grace_deadline = time.monotonic() + 5.0
                    say("检测到剧情结束，已自动暂停。下一段对白只需 F8，不需要重新标定。", flush=True)
                    if close_grace_deadline > time.monotonic():
                        say("继续检测 × 收尾 5 秒；期间不会发送 F/空格，F8 可立即停止收尾。")
                elif state == "hold" and last_state != "hold":
                    say("对白标记消失，已停止输入，正在确认剧情结束。", flush=True)
                elif state == "active" and last_state == "hold":
                    next_advance = time.monotonic() + 0.3
                    say("对白标记恢复，继续。", flush=True)
                last_state = state
            if running and last_state == "active" and not blocked:
                if option_due and (detected_option or (args.option_mode == "fixed" and args.option_key == "f")):
                    if detected_option:
                        api.select_option(hwnd, detected_option, args.option_key, args.dry_run)
                    else:
                        api.press_key(hwnd, "f", args.dry_run)
                    say(f"已{'模拟' if args.dry_run else '自动'}确认选项（{args.option_key.upper()}）。")
                    next_advance = time.monotonic() + 0.5
                elif now >= next_advance:
                    if args.advance_key == "space":
                        api.advance(hwnd, args.dry_run)
                    else:
                        api.press_key(hwnd, args.advance_key, args.dry_run)
                    next_advance = now + args.interval
        except (OSError, ValueError, RuntimeError) as exc:
            running = opening = False
            close_grace_deadline = close_settle_until = 0.0
            close_target = None
            say(f"已暂停：{exc}", flush=True)
        time.sleep(0.025)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    configure_logging()
    try:
        main()
    except KeyboardInterrupt:
        say("\n已退出。")
    except Exception:
        logging.getLogger("story").exception("脚本异常退出")
        raise
