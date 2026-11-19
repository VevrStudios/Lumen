"""Look at a screen -- the one he is working on, unless he names another.

GDI through ctypes, PNG through zlib: stdlib only. What v1 measured on this machine,
kept as requirements: capture from the screen DC (PrintWindow reports success and hands
back black), scale while copying (StretchBlt with HALFTONE costs what a plain copy
costs), and number screens the way Windows does -- counting them yourself gives a
different order, and then "Bildschirm 2" means two different things to him and to her.
"""

import base64
import ctypes
import ctypes.wintypes as w
import re
import struct
import zlib
from typing import Any

from claude_agent_sdk import tool

from lumen import lang, log, observe

_user32 = ctypes.windll.user32
_gdi32 = ctypes.windll.gdi32

# The long edge an image is shrunk to while copying. The API scales anything larger
# down to this anyway; sending more only moves bytes.
MAX_EDGE = 1568

_DEFAULTTONEAREST = 2
_HALFTONE = 4
_SRCCOPY = 0x00CC0020
_DESKTOP = ("Progman", "WorkerW")  # the desktop is in front, not a window


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", w.DWORD), ("rcMonitor", w.RECT), ("rcWork", w.RECT),
                ("dwFlags", w.DWORD), ("szDevice", w.WCHAR * 32)]


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [("biSize", w.DWORD), ("biWidth", w.LONG), ("biHeight", w.LONG),
                ("biPlanes", w.WORD), ("biBitCount", w.WORD), ("biCompression", w.DWORD),
                ("biSizeImage", w.DWORD), ("biXPelsPerMeter", w.LONG),
                ("biYPelsPerMeter", w.LONG), ("biClrUsed", w.DWORD), ("biClrImportant", w.DWORD)]


_ENUM = ctypes.WINFUNCTYPE(w.BOOL, w.HMONITOR, w.HDC, ctypes.POINTER(w.RECT), w.LPARAM)


def _info(hmon: int) -> tuple[int, tuple[int, int, int, int]]:
    """(Windows' own screen number, rect on the virtual desktop)."""
    mi = _MonitorInfo(ctypes.sizeof(_MonitorInfo))
    _user32.GetMonitorInfoW(w.HMONITOR(hmon), ctypes.byref(mi))
    r = mi.rcMonitor
    return int(re.sub(r"\D", "", mi.szDevice) or 0), (r.left, r.top, r.right, r.bottom)


def screens() -> dict[int, tuple[int, int, int, int]]:
    found: dict[int, tuple[int, int, int, int]] = {}

    def visit(hmon, _hdc, _rect, _):
        n, rect = _info(hmon)
        found[n] = rect
        return True

    _user32.EnumDisplayMonitors(None, None, _ENUM(visit), 0)
    return dict(sorted(found.items()))


def focused() -> int:
    """The screen he is working on: the one holding the window in front.

    With the desktop in front there is no window to go by, so it is the screen under
    the mouse. Not the primary one -- v1 caught him working on DISPLAY3 while a video
    ran full screen on the main one.
    """
    hwnd = _user32.GetForegroundWindow()
    cls = ctypes.create_unicode_buffer(64)
    _user32.GetClassNameW(hwnd, cls, 64)
    if hwnd and cls.value not in _DESKTOP:
        return _info(_user32.MonitorFromWindow(hwnd, _DEFAULTTONEAREST))[0]
    pt = w.POINT()
    _user32.GetCursorPos(ctypes.byref(pt))
    return _info(_user32.MonitorFromPoint(pt, _DEFAULTTONEAREST))[0]


def _size(rect: tuple[int, int, int, int]) -> tuple[int, int]:
    """Image size for a screen. One place, because `to_screen` has to undo exactly this
    scaling -- two copies of the formula drift, and then she clicks next to the button."""
    sw, sh = rect[2] - rect[0], rect[3] - rect[1]
    f = min(1.0, MAX_EDGE / max(sw, sh))
    return max(1, round(sw * f)), max(1, round(sh * f))


def to_screen(n: int, x: int, y: int) -> tuple[int, int]:
    """Image coordinate -> screen coordinate. What she sees is the shrunk image, so
    that is the only frame she can name a point in; converts back from there
    rather than asking her to multiply."""
    rect = screens()[n]
    dw, dh = _size(rect)
    return (rect[0] + round(x * (rect[2] - rect[0]) / dw),
            rect[1] + round(y * (rect[3] - rect[1]) / dh))


def _grab(rect: tuple[int, int, int, int]) -> tuple[int, int, bytes]:
    """(width, height, BGRA rows top-down), already shrunk to MAX_EDGE."""
    x, y = rect[0], rect[1]
    sw, sh = rect[2] - rect[0], rect[3] - rect[1]
    dw, dh = _size(rect)

    screen = _user32.GetDC(None)
    mem = _gdi32.CreateCompatibleDC(screen)
    bmp = _gdi32.CreateCompatibleBitmap(screen, dw, dh)
    old = _gdi32.SelectObject(mem, bmp)
    try:
        _gdi32.SetStretchBltMode(mem, _HALFTONE)
        _gdi32.SetBrushOrgEx(mem, 0, 0, None)  # HALFTONE requires it, per the GDI docs
        _gdi32.StretchBlt(mem, 0, 0, dw, dh, screen, x, y, sw, sh, _SRCCOPY)
        head = _BitmapInfoHeader(ctypes.sizeof(_BitmapInfoHeader), dw, -dh, 1, 32, 0)
        buf = ctypes.create_string_buffer(dw * dh * 4)
        _gdi32.SelectObject(mem, old)  # GetDIBits wants the bitmap out of the DC
        _gdi32.GetDIBits(mem, bmp, 0, dh, buf, ctypes.byref(head), 0)
        return dw, dh, buf.raw
    finally:
        _gdi32.DeleteObject(bmp)
        _gdi32.DeleteDC(mem)
        _user32.ReleaseDC(None, screen)


def _png(width: int, height: int, bgra: bytes) -> bytes:
    rgb = bytearray(width * height * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = bgra[2::4], bgra[1::4], bgra[0::4]
    row = width * 3
    raw = b"".join(b"\x00" + rgb[i:i + row] for i in range(0, len(rgb), row))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6))
            + chunk(b"IEND", b""))


def _black(bgra: bytes) -> bool:
    """A protected video (DRM) copies as black. Better to say so than to describe it."""
    return max(bgra[::4001] or b"\x00") < 12


@tool(
    "screenshot",
    "tool.screenshot",
    {"type": "object",
     "properties": {"screen": {"type": "integer", "description": "Windows-Bildschirmnummer, weglassen = der fokussierte"}}},
)
async def screenshot(args: dict[str, Any]) -> dict[str, Any]:
    all_screens = screens()
    n = args.get("screen") or focused()
    if n not in all_screens:
        have = ", ".join(str(k) for k in all_screens)
        return {"content": [{"type": "text", "text": lang.t("reply.no_screen", n=n, have=have)}]}

    width, height, bgra = _grab(all_screens[n])
    observe.seen()  # a picture is a look too -- the nudge counts from here
    front = observe.foreground()[0] or lang.t("obs.nothing")
    said = lang.t("reply.screen", n=n, of=len(all_screens), w=width, h=height, front=front)
    log.info("act", f"screenshot {n} ({width}x{height})")
    if _black(bgra):
        return {"content": [{"type": "text", "text": said + lang.t("reply.black")}]}
    return {"content": [
        {"type": "text", "text": said},
        {"type": "image", "data": base64.b64encode(_png(width, height, bgra)).decode(),
         "mimeType": "image/png"},
    ]}


TOOL = screenshot


def _self_check() -> None:
    """A PNG is the one thing here that can be checked without a screen: a broken
    encoder fails silently on her side, as an image she cannot open."""
    png = _png(2, 1, bytes([0, 0, 255, 0, 255, 0, 0, 0]))  # one red, one blue pixel
    assert png.startswith(b"\x89PNG") and png.endswith(b"IEND\xaeB`\x82"), "not a png"
    raw = zlib.decompress(png[png.index(b"IDAT") + 4:-16])
    assert raw == b"\x00\xff\x00\x00\x00\x00\xff", f"channels swapped: {raw!r}"
    assert _black(bytes(4000)) and not _black(bytes([200]) * 4000)
    assert screens(), "no screen found"
    assert focused() in screens(), "the focused screen has to be one of them"

    # The mapping a click depends on: a corner in the image is that corner on the screen.
    for n, rect in screens().items():
        dw, dh = _size(rect)
        assert to_screen(n, 0, 0) == (rect[0], rect[1]), "the origin has to stay the origin"
        far = to_screen(n, dw, dh)
        assert far == (rect[2], rect[3]), f"screen {n}: {dw}x{dh} maps to {far}, not {rect[2:]}"
        assert max(dw, dh) <= MAX_EDGE, "an image wider than MAX_EDGE was not shrunk"
