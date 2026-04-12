"""Widget tile and background display rendering for streamdockd."""

import datetime as dt
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from PIL import Image, ImageDraw, ImageFont

from icon_manager import IconManager


__all__ = ["WidgetRenderer"]

_BASE_DIR = Path(__file__).resolve().parent


class WidgetRenderer:
    def __init__(self, icon_manager: IconManager):
        self.icon_manager = icon_manager
        self._touchscreen_temp = Path(tempfile.gettempdir()) / "streamdockd_touchscreen.png"

    @staticmethod
    def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
        candidates = [
            "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/TTF/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
        for path in candidates:
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue
        return ImageFont.load_default()

    @staticmethod
    def _center_x(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int = 80) -> int:
        left, _, right, _ = draw.textbbox((0, 0), text, font=font)
        tw = right - left
        return (width - tw) // 2

    @staticmethod
    def _progress(draw: ImageDraw.ImageDraw, pct: float, y: int, fg: tuple[int, int, int], bg: tuple[int, int, int]):
        x0, y0, x1, y1 = 8, y, 72, y + 10
        draw.rounded_rectangle((x0, y0, x1, y1), radius=4, fill=bg)
        fill_w = int((x1 - x0) * max(0.0, min(100.0, pct)) / 100.0)
        if fill_w > 0:
            draw.rounded_rectangle((x0, y0, x0 + fill_w, y1), radius=4, fill=fg)

    @staticmethod
    def _style_palette(style: str) -> Dict[str, tuple[int, int, int]]:
        palettes: Dict[str, Dict[str, tuple[int, int, int]]] = {
            "bold":    {"bg": (0,0,0), "head": (0,0,0), "ink": (235,242,255), "muted": (189,205,245), "bar_fg": (110,165,255), "bar_bg": (45,45,45)},
            "minimal": {"bg": (0,0,0), "head": (0,0,0), "ink": (237,237,237), "muted": (186,186,186), "bar_fg": (206,206,206), "bar_bg": (45,45,45)},
            "neon":    {"bg": (0,0,0), "head": (0,0,0), "ink": (156,255,240), "muted": (123,224,255), "bar_fg": (0,255,196),   "bar_bg": (35,35,35)},
            "amber":   {"bg": (0,0,0), "head": (0,0,0), "ink": (255,199,95),  "muted": (230,166,72),  "bar_fg": (255,182,64),  "bar_bg": (45,45,45)},
            "lcd":     {"bg": (0,0,0), "head": (0,0,0), "ink": (191,255,173), "muted": (151,216,134), "bar_fg": (150,248,124), "bar_bg": (40,40,40)},
            "mono":    {"bg": (0,0,0), "head": (0,0,0), "ink": (245,245,245), "muted": (180,180,180), "bar_fg": (220,220,220), "bar_bg": (45,45,45)},
        }
        return palettes.get(style, palettes["bold"])

    @staticmethod
    def _memory_percent() -> float:
        try:
            meminfo = {}
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                for line in f:
                    if ":" not in line:
                        continue
                    key, value = line.split(":", 1)
                    meminfo[key.strip()] = int(value.strip().split()[0])
            total = float(meminfo.get("MemTotal", 0))
            avail = float(meminfo.get("MemAvailable", 0))
            if total <= 0:
                return 0.0
            used = total - avail
            return max(0.0, min(100.0, (used / total) * 100.0))
        except Exception:
            return 0.0

    @staticmethod
    def _uptime_string() -> str:
        try:
            with open("/proc/uptime", "r", encoding="utf-8") as f:
                total = int(float(f.read().split()[0]))
            h = total // 3600
            m = (total % 3600) // 60
            return f"{h:02d}:{m:02d}"
        except Exception:
            return "--:--"

    def render_touchscreen_image(self, mode: str, size: tuple[int, int]) -> Optional[Path]:
        """Render a full-panel background image for non-293s devices (time or stats mode)."""
        out_path = self._touchscreen_temp
        font_title = ImageFont.load_default()
        font_body = ImageFont.load_default()

        if mode == "time":
            now = dt.datetime.now()
            img = Image.new("RGB", size, (8, 18, 23))
            draw = ImageDraw.Draw(img)
            draw.rectangle((0, 0, size[0], 72), fill=(20, 83, 45))
            draw.text((20, 22), "StreamDock Clock", fill=(230, 245, 235), font=font_title)
            draw.text((20, 110), now.strftime("%H:%M:%S"), fill=(255, 255, 255), font=font_body)
            draw.text((20, 150), now.strftime("%A, %Y-%m-%d"), fill=(182, 215, 198), font=font_body)
            img.save(out_path, "PNG")
            return out_path

        if mode == "stats":
            now = dt.datetime.now()
            load1, load5, load15 = os.getloadavg()
            mem = self._memory_percent()
            img = Image.new("RGB", size, (16, 16, 30))
            draw = ImageDraw.Draw(img)
            draw.rectangle((0, 0, size[0], 72), fill=(42, 63, 128))
            draw.text((20, 22), "Linux Stats", fill=(235, 240, 255), font=font_title)
            draw.text((20, 100), now.strftime("%H:%M:%S"), fill=(220, 220, 240), font=font_body)
            draw.text((20, 140), f"Load 1/5/15: {load1:.2f} / {load5:.2f} / {load15:.2f}", fill=(201, 214, 255), font=font_body)
            draw.text((20, 180), f"Memory used: {mem:.1f}%", fill=(201, 214, 255), font=font_body)
            img.save(out_path, "PNG")
            return out_path

        return None

    @staticmethod
    def _parse_color(hex_str: str, default):
        c = hex_str.strip().lstrip("#").lower()
        if len(c) == 6 and all(ch in "0123456789abcdef" for ch in c):
            return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))
        return default

    def _overlay_text(self, img: Image.Image, draw: ImageDraw.ImageDraw, cfg: Dict[str, Any], pal: Dict[str, tuple]) -> None:
        """Overlay label text onto img if text and label_pos are set."""
        text = str(cfg.get("text", "")).strip()
        label_pos = str(cfg.get("label_pos", "off")).strip() or "off"
        if not text or label_pos == "off":
            return
        raw_color = str(cfg.get("icon_color", "")).strip()
        text_color = self._parse_color(raw_color, pal["ink"])

        font_small = self._font(9)
        font_mid   = self._font(11)
        try:
            bbox = draw.textbbox((0, 0), text[:12], font=font_mid)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            font_use = font_mid if tw <= 72 else font_small
            if font_use is font_small:
                bbox = draw.textbbox((0, 0), text[:12], font=font_small)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
        except Exception:
            font_use = font_small
            tw, th = 40, 9

        x = max(1, (80 - tw) // 2)
        if label_pos == "top":
            y = 2
        elif label_pos == "middle":
            y = (80 - th) // 2
        else:  # bottom
            y = 80 - th - 3

        pad = 2
        draw.rectangle((0, y - pad, 80, y + th + pad), fill=(0, 0, 0))
        draw.text((x, y), text[:12], fill=text_color, font=font_use)

    def render_widget_tile_293s(self, slot: str, cfg: Dict[str, Any]) -> Image.Image:
        """Render an 80x80 tile for a 293s secondary display slot (16, 17, or 18)."""
        mode = str(cfg.get("mode", "off")).lower()
        style = str(cfg.get("style", "bold")).lower()
        if mode == "off":
            return Image.new("RGB", (80, 80), (0, 0, 0))
        pal = self._style_palette(style)
        # If icon_color is set, override the palette ink color with it
        custom_ink = self._parse_color(str(cfg.get("icon_color", "")), None)
        if custom_ink is not None:
            pal = dict(pal)
            pal["ink"] = custom_ink
        img = Image.new("RGB", (80, 80), pal["bg"])
        draw = ImageDraw.Draw(img)
        if style == "minimal":
            font_small = self._font(9)
            font_mid = self._font(12, bold=False)
            font_big = self._font(18, bold=False)
            header_h = 12
        elif style == "amber":
            font_small = self._font(10)
            font_mid = self._font(14, bold=True)
            font_big = self._font(24, bold=True)
            header_h = 16
        elif style == "lcd":
            font_small = self._font(10)
            font_mid = self._font(13, bold=False)
            font_big = self._font(22, bold=True)
            header_h = 14
        elif style == "neon":
            font_small = self._font(10)
            font_mid = self._font(15, bold=True)
            font_big = self._font(28, bold=True)
            header_h = 20
        elif style == "mono":
            font_small = self._font(10)
            font_mid = self._font(14, bold=True)
            font_big = self._font(24, bold=True)
            header_h = 16
        else:
            font_small = self._font(10)
            font_mid = self._font(14, bold=True)
            font_big = self._font(26, bold=True)
            header_h = 18
        now = dt.datetime.now()
        if style in {"neon", "amber", "lcd"}:
            draw.rectangle((0, 0, 79, 79), outline=pal["bar_fg"], width=1)

        def hdr(label: str):
            if style == "minimal":
                draw.text((5, 2), label, fill=pal["muted"], font=font_small)
            else:
                draw.rectangle((0, 0, 80, header_h), fill=pal["head"])
                draw.text((6, 3), label, fill=pal["ink"], font=font_small)

        if mode == "clock":
            draw.rectangle((0, 0, 80, 80), fill=pal["bg"])
            t = now.strftime("%H:%M")
            draw.text((self._center_x(draw, t, font_big), 26), t, fill=pal["ink"], font=font_big)
            self._overlay_text(img, draw, cfg, pal)
            return img
        if mode == "seconds":
            draw.rectangle((0, 0, 80, 80), fill=pal["bg"])
            t = now.strftime("%S")
            draw.text((self._center_x(draw, t, font_big), 26), t, fill=pal["ink"], font=font_big)
            self._overlay_text(img, draw, cfg, pal)
            return img
        if mode == "date":
            draw.rectangle((0, 0, 80, 80), fill=pal["bg"])
            t = now.strftime("%m-%d")
            draw.text((self._center_x(draw, t, font_mid), 22), t, fill=pal["ink"], font=font_mid)
            draw.text((self._center_x(draw, now.strftime("%Y"), font_small), 48), now.strftime("%Y"), fill=pal["muted"], font=font_small)
            self._overlay_text(img, draw, cfg, pal)
            return img
        if mode == "stats":
            load1, _, _ = os.getloadavg()
            mem = self._memory_percent()
            draw.rectangle((0, 0, 80, 80), fill=pal["bg"])
            hdr("STATS")
            y0 = 16 if style == "minimal" else header_h + 2
            draw.text((7, y0), f"L1 {load1:.1f}", fill=pal["muted"], font=font_small)
            self._progress(draw, min(load1 * 100.0 / 8.0, 100.0), y0 + 11, pal["bar_fg"], pal["bar_bg"])
            draw.text((7, y0 + 28), f"RAM {mem:.0f}%", fill=pal["muted"], font=font_small)
            self._progress(draw, mem, y0 + 39, pal["bar_fg"], pal["bar_bg"])
            self._overlay_text(img, draw, cfg, pal)
            return img
        if mode == "cpu_ram":
            load1, _, _ = os.getloadavg()
            cpu = min(load1 * 100.0 / 8.0, 100.0)
            mem = self._memory_percent()
            draw.rectangle((0, 0, 80, 80), fill=pal["bg"])
            draw.line((4, 40, 76, 40), fill=pal["bar_bg"], width=1)
            cpu_txt = f"{cpu:.0f}%"
            draw.text((self._center_x(draw, cpu_txt, font_mid), 10), cpu_txt, fill=pal["ink"], font=font_mid)
            self._progress(draw, cpu, 27, pal["bar_fg"], pal["bar_bg"])
            mem_txt = f"{mem:.0f}%"
            draw.text((self._center_x(draw, mem_txt, font_mid), 50), mem_txt, fill=pal["ink"], font=font_mid)
            self._progress(draw, mem, 67, pal["bar_fg"], pal["bar_bg"])
            self._overlay_text(img, draw, cfg, pal)
            return img
        if mode == "cpu":
            load1, _, _ = os.getloadavg()
            pct = min(load1 * 100.0 / 8.0, 100.0)
            draw.rectangle((0, 0, 80, 80), fill=pal["bg"])
            hdr("CPU")
            t = f"{pct:.0f}%"
            y = 28 if style == "minimal" else 20
            draw.text((self._center_x(draw, t, font_big), y), t, fill=pal["ink"], font=font_big)
            self._progress(draw, pct, 64 if style == "minimal" else 62, pal["bar_fg"], pal["bar_bg"])
            self._overlay_text(img, draw, cfg, pal)
            return img
        if mode == "memory":
            mem = self._memory_percent()
            draw.rectangle((0, 0, 80, 80), fill=pal["bg"])
            hdr("MEM")
            t = f"{mem:.0f}%"
            y = 28 if style == "minimal" else 20
            draw.text((self._center_x(draw, t, font_big), y), t, fill=pal["ink"], font=font_big)
            self._progress(draw, mem, 64 if style == "minimal" else 62, pal["bar_fg"], pal["bar_bg"])
            self._overlay_text(img, draw, cfg, pal)
            return img
        if mode == "uptime":
            up = self._uptime_string()
            draw.rectangle((0, 0, 80, 80), fill=pal["bg"])
            hdr("UPTIME")
            draw.text((self._center_x(draw, up, font_mid), 34 if style == "minimal" else 30), up, fill=pal["ink"], font=font_mid)
            self._overlay_text(img, draw, cfg, pal)
            return img
        if mode == "hostname":
            host = os.uname().nodename[:12]
            draw.rectangle((0, 0, 80, 80), fill=pal["bg"])
            hdr("HOST")
            draw.text((6, 34 if style == "minimal" else 30), host, fill=pal["muted"], font=font_small)
            self._overlay_text(img, draw, cfg, pal)
            return img
        if mode == "text":
            # In text mode the TXT field is the primary content; use label_pos for positioning.
            text = str(cfg.get("text", "")).strip() or f"SLOT {slot}"
            text_color = self._parse_color(str(cfg.get("icon_color", "")), pal["ink"])
            label_pos = str(cfg.get("label_pos", "off")).strip() or "off"
            draw.rectangle((0, 0, 80, 80), fill=pal["bg"])
            try:
                bbox = draw.textbbox((0, 0), text[:12], font=font_big)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
                font_use = font_big if tw <= 72 else font_mid
                if font_use is font_mid:
                    bbox = draw.textbbox((0, 0), text[:12], font=font_mid)
                    tw = bbox[2] - bbox[0]
                    th = bbox[3] - bbox[1]
            except Exception:
                font_use = font_mid
                tw, th = 40, 14
            x = max(2, (80 - tw) // 2)
            if label_pos == "top":
                y = 3
            elif label_pos == "bottom":
                y = 80 - th - 3
            else:  # middle or off (center by default for text mode)
                y = max(2, (80 - th) // 2)
            draw.text((x, y), text[:12], fill=text_color, font=font_use)
            return img
        if mode == "image":
            raw = str(cfg.get("image", "")).strip()
            if not raw:
                return Image.new("RGB", (80, 80), (0, 0, 0))
            p = Path(raw).expanduser()
            if not p.is_absolute():
                p = (_BASE_DIR / p).resolve()
            try:
                src = Image.open(p).convert("RGB")
                sw, sh = src.size
                if sw == 0 or sh == 0:
                    return Image.new("RGB", (80, 80), (0, 0, 0))
                scale = max(80 / sw, 80 / sh)
                rw, rh = int(sw * scale), int(sh * scale)
                resized = src.resize((rw, rh), Image.LANCZOS)
                left = (rw - 80) // 2
                top = (rh - 80) // 2
                img = resized.crop((left, top, left + 80, top + 80))
                draw = ImageDraw.Draw(img)
                self._overlay_text(img, draw, cfg, pal)
                return img
            except Exception:
                return Image.new("RGB", (80, 80), (0, 0, 0))
        if mode == "icon":
            icon_name = str(cfg.get("icon", "")).strip()
            icon_color = str(cfg.get("icon_color", "ffffff")).strip()
            icon = self.icon_manager.load_tile_icon(icon_name, icon_color, size=72)
            if icon is None:
                draw.text((self._center_x(draw, "ICON", font_mid), 28), "ICON", fill=pal["muted"], font=font_mid)
                self._overlay_text(img, draw, cfg, pal)
                return img
            w, h = icon.size
            x = (80 - w) // 2
            y = (80 - h) // 2
            img.paste(icon, (x, y), icon)
            self._overlay_text(img, draw, cfg, pal)
            return img
        return Image.new("RGB", (80, 80), (0, 0, 0))
