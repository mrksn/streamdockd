"""Icon fetching, SVG conversion, caching, and button image rendering for streamdockd."""

import functools
import hashlib
import json
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont


_BASE_DIR = Path(__file__).resolve().parent

__all__ = ["IconManager"]


class IconManager:
    def __init__(self):
        self.last_icon_error: str = ""

    @staticmethod
    @functools.lru_cache(maxsize=1)
    def _icon_cache_dir() -> Path:
        candidates = [
            Path.home() / ".cache" / "streamdockd" / "icons",
            Path(tempfile.gettempdir()) / "streamdockd" / "icons",
            _BASE_DIR / ".streamdockd-icons",
        ]
        for base in candidates:
            try:
                base.mkdir(parents=True, exist_ok=True)
                probe = base / ".write_probe"
                probe.write_bytes(b"ok")
                probe.unlink(missing_ok=True)
                return base
            except OSError:
                continue
        fallback = Path(tempfile.mkdtemp(prefix="streamdockd_icons_"))
        return fallback

    @staticmethod
    def is_iconify_name(value: str) -> bool:
        s = value.strip()
        if not s or ":" not in s:
            return False
        p = Path(s).expanduser()
        if p.exists():
            return False
        return True

    @staticmethod
    def _iconify_ids_with_fallbacks(icon_name: str) -> list[str]:
        icon_ids = [icon_name]
        if ":" in icon_name:
            prefix, name = icon_name.split(":", 1)
            if prefix == "mdi":
                if name.endswith("-outline"):
                    icon_ids.append(f"{prefix}:{name[:-8]}")
                if "-outline-" in name:
                    icon_ids.append(f"{prefix}:{name.replace('-outline-', '-')}")
                if "-circle-outline" in name:
                    icon_ids.append(f"{prefix}:{name.replace('-circle-outline', '-circle')}")
                if "-box-outline" in name:
                    icon_ids.append(f"{prefix}:{name.replace('-box-outline', '-box')}")
                if "-outline" in name:
                    icon_ids.append(f"{prefix}:{name.replace('-outline', '')}")
        dedup = []
        seen = set()
        for iid in icon_ids:
            if iid not in seen:
                dedup.append(iid)
                seen.add(iid)
        return dedup

    @staticmethod
    def _svg_to_png_bytes(svg_data: bytes, size: int) -> bytes:
        with tempfile.TemporaryDirectory(prefix="streamdockd_icon_") as td:
            in_svg = Path(td) / "icon.svg"
            out_png = Path(td) / "icon.png"
            in_svg.write_bytes(svg_data)

            if shutil.which("rsvg-convert"):
                cmd = ["rsvg-convert", "-w", str(size), "-h", str(size), "-f", "png", str(in_svg), "-o", str(out_png)]
            elif shutil.which("magick"):
                cmd = ["magick", "-background", "none", f"svg:{in_svg}", "-resize", f"{size}x{size}", f"png32:{out_png}"]
            elif shutil.which("convert"):
                cmd = ["convert", "-background", "none", f"svg:{in_svg}", "-resize", f"{size}x{size}", f"png32:{out_png}"]
            elif shutil.which("inkscape"):
                cmd = ["inkscape", str(in_svg), "--export-type=png", f"--export-filename={out_png}", f"--export-width={size}", f"--export-height={size}"]
            else:
                raise RuntimeError("No SVG rasterizer found (need rsvg-convert, magick/convert, or inkscape)")

            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0 or not out_png.exists():
                raise RuntimeError((proc.stderr or proc.stdout or "SVG conversion failed").strip())
            return out_png.read_bytes()

    @staticmethod
    def _build_svg_from_iconify_json(icon_body: str, width: int, height: int, color: str, size: int) -> bytes:
        safe_body = icon_body.replace("currentColor", f"#{color}")
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
            f'viewBox="0 0 {width} {height}">'
            f'<g fill="#{color}">{safe_body}</g>'
            "</svg>"
        )
        return svg.encode("utf-8")

    def _load_icon_png(self, icon_name: str, color_hex: str, size: int = 72) -> Optional[Image.Image]:
        icon_name = icon_name.strip()
        if not icon_name:
            return None

        color = color_hex.strip().lstrip("#").lower()
        if len(color) != 6 or any(c not in "0123456789abcdef" for c in color):
            color = "ffffff"

        cache_key = hashlib.sha1(f"v2|{icon_name}|{color}|{size}".encode("utf-8")).hexdigest()
        cache_file = self._icon_cache_dir() / f"{cache_key}.png"
        if cache_file.exists():
            try:
                return Image.open(cache_file).convert("RGBA")
            except Exception:
                pass

        query = urllib.parse.urlencode({"color": f"#{color}", "width": size, "height": size})

        candidates = []
        for iid in self._iconify_ids_with_fallbacks(icon_name):
            candidates.append(f"https://api.iconify.design/{urllib.parse.quote(iid, safe='')}.svg?{query}")
            if ":" in iid:
                pfx, nm = iid.split(":", 1)
                candidates.append(f"https://api.iconify.design/{urllib.parse.quote(pfx, safe='')}/{urllib.parse.quote(nm, safe='')}.svg?{query}")
            candidates.append(f"https://api.iconify.design/{iid}.svg?{query}")

        errors = []
        for url in candidates:
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "streamdockd/1.0 (+https://iconify.design/)",
                        "Accept": "image/svg+xml,image/*,*/*",
                    },
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = resp.read()
                png_data = self._svg_to_png_bytes(data, size)
                img = Image.open(BytesIO(png_data)).convert("RGBA")
                try:
                    cache_file.write_bytes(png_data)
                except Exception:
                    pass
                return img
            except Exception as exc:
                errors.append(f"{url} -> {exc}")
                continue

        if ":" in icon_name:
            try:
                prefix, name = icon_name.split(":", 1)
                collection_url = (
                    f"https://api.iconify.design/{urllib.parse.quote(prefix, safe='')}.json?"
                    + urllib.parse.urlencode({"icons": name})
                )
                req = urllib.request.Request(
                    collection_url,
                    headers={
                        "User-Agent": "streamdockd/1.0 (+https://iconify.design/)",
                        "Accept": "application/json,*/*",
                    },
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                icon_data = payload.get("icons", {}).get(name)
                if icon_data and icon_data.get("body"):
                    width = int(icon_data.get("width", 24))
                    height = int(icon_data.get("height", 24))
                    svg_data = self._build_svg_from_iconify_json(
                        icon_data["body"], width, height, color, size
                    )
                    png_data = self._svg_to_png_bytes(svg_data, size)
                    img = Image.open(BytesIO(png_data)).convert("RGBA")
                    try:
                        cache_file.write_bytes(png_data)
                    except Exception:
                        pass
                    return img
                errors.append(f"{collection_url} -> icon not found in collection payload")
            except Exception as exc:
                errors.append(f"collection api fallback -> {exc}")

        self.last_icon_error = "; ".join(errors[-3:])
        return None

    def materialize_button_icon(self, icon_name: str, color_hex: str) -> Optional[Path]:
        icon = self._load_icon_png(icon_name, color_hex, size=180)
        if icon is None:
            return None
        canvas = Image.new("RGB", (256, 256), (0, 0, 0))
        icon.thumbnail((180, 180), Image.LANCZOS)
        x = (256 - icon.width) // 2
        y = (256 - icon.height) // 2
        canvas.paste(icon, (x, y), icon)
        key = hashlib.sha1(f"btn-v2|{icon_name}|{color_hex}".encode("utf-8")).hexdigest()
        out = self._icon_cache_dir() / f"button_{key}.png"
        try:
            canvas.save(out, "PNG")
            return out
        except Exception as exc:
            self.last_icon_error = f"materialize failed: {exc}"
            return None

    def blank_button_image_path(self) -> Optional[Path]:
        out = self._icon_cache_dir() / "button_blank.png"
        if out.exists():
            return out
        try:
            Image.new("RGB", (256, 256), (0, 0, 0)).save(out, "PNG")
            return out
        except Exception as exc:
            self.last_icon_error = f"blank icon failed: {exc}"
            return None

    def load_tile_icon(self, icon_name: str, color_hex: str, size: int = 72) -> Optional[Image.Image]:
        """Public interface for loading an icon image for widget tile rendering."""
        return self._load_icon_png(icon_name, color_hex, size=size)

    @staticmethod
    def _resolve_icon_source_path(raw_value: str) -> Path:
        p = Path(raw_value).expanduser()
        if not p.is_absolute():
            p = (_BASE_DIR / p).resolve()
        return p

    def build_button_preview_bytes(self, icon_value: str, color_hex: str, size: int = 84) -> bytes:
        value = icon_value.strip()
        color = color_hex.strip()
        canvas = Image.new("RGB", (size, size), (0, 0, 0))
        if not value:
            bio = BytesIO()
            canvas.save(bio, "PNG")
            return bio.getvalue()

        if self.is_iconify_name(value):
            icon = self._load_icon_png(value, color, size=max(32, size - 10))
            if icon is not None:
                x = (size - icon.width) // 2
                y = (size - icon.height) // 2
                canvas.paste(icon, (x, y), icon)
        else:
            try:
                p = self._resolve_icon_source_path(value)
                if p.exists():
                    src = Image.open(p).convert("RGB")
                    sw, sh = src.size
                    if sw > 0 and sh > 0:
                        scale = max(size / sw, size / sh)
                        rw, rh = int(sw * scale), int(sh * scale)
                        resized = src.resize((rw, rh), Image.LANCZOS)
                        left = (rw - size) // 2
                        top = (rh - size) // 2
                        canvas = resized.crop((left, top, left + size, top + size))
            except Exception as exc:
                self.last_icon_error = f"local icon load failed: {exc}"

        bio = BytesIO()
        canvas.save(bio, "PNG")
        return bio.getvalue()

    @staticmethod
    def _parse_color(hex_str: str, default):
        """Parse a hex color string (with or without #) into an RGB tuple, or return default."""
        c = hex_str.strip().lstrip("#").lower()
        if len(c) == 6 and all(ch in "0123456789abcdef" for ch in c):
            return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))
        return default

    def render_button_image(
        self,
        base_path: Optional[Path],
        label: str,
        label_pos: str,
        label_color: str = "ffffff",
    ) -> Path:
        """Composite a text label onto a button image and return the path to the result.

        base_path: existing 256×256 PNG to use as base, or None for black background.
        label: text to overlay (empty string = no text, return base_path as-is).
        label_pos: 'top' | 'middle' | 'bottom' | 'off'.
        label_color: hex color string for the text (default white).
        Returns a path to the composited image (may be base_path itself if no label).
        """
        if not label or label_pos == "off":
            if base_path is not None:
                return base_path
            blank = self.blank_button_image_path()
            return blank if blank is not None else base_path  # type: ignore[return-value]

        # Load base image
        try:
            img = Image.open(base_path).convert("RGB") if base_path else Image.new("RGB", (256, 256), (0, 0, 0))
        except Exception:
            img = Image.new("RGB", (256, 256), (0, 0, 0))

        draw = ImageDraw.Draw(img)

        # Use a large truetype font so text is visible when the 256×256 image
        # is downscaled to the physical button size (~84px).
        font_candidates = [
            "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/TTF/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
        font = ImageFont.load_default()
        for fc in font_candidates:
            try:
                font = ImageFont.truetype(fc, size=36)
                break
            except Exception:
                continue

        text_fill = self._parse_color(label_color, (255, 255, 255))
        text = label[:20]
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
        except Exception:
            tw, th = len(text) * 18, 36

        x = max(4, (256 - tw) // 2)

        if label_pos == "top":
            y = 8
        elif label_pos == "middle":
            y = (256 - th) // 2
        else:  # bottom
            y = 256 - th - 12

        # Draw a dark backing strip for readability
        pad = 6
        draw.rectangle((0, y - pad, 256, y + th + pad), fill=(0, 0, 0))
        draw.text((x, y), text, fill=text_fill, font=font)

        # Save to cache with a unique key
        key = hashlib.sha1(
            f"lbl-v3|{base_path}|{label}|{label_pos}|{label_color}".encode("utf-8")
        ).hexdigest()
        out = self._icon_cache_dir() / f"button_lbl_{key}.png"
        try:
            img.save(out, "PNG")
            return out
        except Exception as exc:
            self.last_icon_error = f"render_button_image save failed: {exc}"
            return base_path or out
