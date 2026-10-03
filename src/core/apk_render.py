"""PNG decoding and adaptive-icon compositing for APK icons."""

from __future__ import annotations

import io
from typing import List, Optional, Tuple
from .apk_format import _is_app_resource


def decode_to_png(data: bytes, destination: str, min_size: int = 24) -> bool:
    try:
        from PIL import Image
    except ImportError:
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            with open(destination, 'wb') as handle:
                handle.write(data)
            return True
        return False
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
        if image.width < min_size or image.height < min_size:
            return False
        if getattr(image, 'mode', '') == 'P':
            image = image.convert('RGBA')
        else:
            image = image.convert('RGBA')
        if path_is_nine_patch(data):
            image = image.crop((1, 1, image.width - 1, image.height - 1))
        image.save(destination, format='PNG')
        return True
    except Exception:
        return False


def path_is_nine_patch(data: bytes) -> bool:
    return b'npTc' in data[:64] or b'npTc' in data[:256]


def composite_adaptive_icon(
    foreground: Optional[bytes],
    background: Optional[bytes],
    background_color: Optional[Tuple[int, int, int, int]],
    destination: str,
    canvas_size: int = 432,
    inset: float = 0.0,
) -> bool:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        if foreground:
            return decode_to_png(foreground, destination)
        if background:
            return decode_to_png(background, destination)
        return False

    canvas = Image.new('RGBA', (canvas_size, canvas_size), (0, 0, 0, 0))
    if background_color:
        canvas.paste(background_color, (0, 0, canvas_size, canvas_size))
    if background:
        try:
            bg = Image.open(io.BytesIO(background)).convert('RGBA')
            bg = bg.resize((canvas_size, canvas_size), Image.Resampling.LANCZOS)
            canvas = Image.alpha_composite(canvas, bg)
        except Exception:
            pass
    if foreground:
        try:
            fg = Image.open(io.BytesIO(foreground)).convert('RGBA')
            if inset:
                inner = max(1, int(canvas_size * (1.0 - min(inset, 0.4))))
                pad = (canvas_size - inner) // 2
                fg = fg.resize((inner, inner), Image.Resampling.LANCZOS)
                layer = Image.new('RGBA', (canvas_size, canvas_size), (0, 0, 0, 0))
                layer.paste(fg, (pad, pad), fg)
                canvas = Image.alpha_composite(canvas, layer)
            else:
                fg = fg.resize((canvas_size, canvas_size), Image.Resampling.LANCZOS)
                canvas = Image.alpha_composite(canvas, fg)
        except Exception:
            pass

    mask = Image.new('L', (canvas_size, canvas_size), 0)
    draw = ImageDraw.Draw(mask)
    radius = int(canvas_size * 0.22)
    draw.rounded_rectangle((0, 0, canvas_size - 1, canvas_size - 1), radius=radius, fill=255)
    canvas.putalpha(mask)
    if max(canvas.size) < 24:
        return False
    canvas.save(destination, format='PNG')
    return True


def parse_icon_resource_ids_from_dumpsys(output: str) -> List[int]:
    ids: List[int] = []
    for line in output.splitlines():
        stripped = line.strip()
        for prefix in ('icon=0x', 'icon=0X', 'roundIcon=0x', 'roundIcon=0X'):
            if stripped.startswith(prefix) or f' {prefix}' in stripped:
                match_at = stripped.lower().find(prefix.lower())
                if match_at < 0:
                    continue
                raw = stripped[match_at:].split('=', 1)[1].split()[0]
                try:
                    value = int(raw, 16) if raw.lower().startswith('0x') else int(raw, 16)
                except ValueError:
                    continue
                if _is_app_resource(value) and value not in ids:
                    ids.append(value)
    return ids


def encode_display_png(source_path: str, destination: str, size: int = 512) -> bool:
    try:
        from PIL import Image
    except ImportError:
        if source_path != destination:
            with open(source_path, 'rb') as src, open(destination, 'wb') as dst:
                dst.write(src.read())
        return True
    try:
        image = Image.open(source_path).convert('RGBA')
        if image.width != size or image.height != size:
            image = image.resize((size, size), Image.Resampling.LANCZOS)
        image.save(destination, format='PNG')
        return True
    except Exception:
        return False
