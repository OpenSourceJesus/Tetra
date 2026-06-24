"""PIL-based sixel encoder and tiny-font text rasterization."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from store import SIXEL_DIR, ensure_dirs, sixel_cache_path

ENCODER_VERSION = 4
DCS_CLOSE = "\x1b\\"

DEFAULT_MAX_WIDTH = 160
DEFAULT_COLORS = 16
TEXT_FONT_SIZE = 8
HEADING_FONT_SIZE = 15
TITLE_FONT_SIZE = 20
HEADING_FONT_SIZES = {"h1": 13, "h2": 12, "h3": 11, "h4": 10, "h5": 9, "h6": 8}
TEXT_MAX_WIDTH_PX = 720
TEXT_FG = (0, 0, 0)
TEXT_BG = (255, 255, 255)

@dataclass(frozen=True)
class TextSegment:
    text: str
    font_size: int = TEXT_FONT_SIZE
    bold: bool = False


FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
)


@dataclass(frozen=True)
class SixelProfile:
    """Terminal-specific sixel quirks."""

    name: str
    dcs_open: str


PROFILES: dict[str, SixelProfile] = {
    "konsole": SixelProfile("konsole", "\x1bPq"),
    "xterm": SixelProfile("xterm", "\x1bP0;0;8q"),
    "libsixel": SixelProfile("libsixel", "\x1bPq"),
}


def _detect_profile_name() -> str:
    override = os.environ.get("SIXEL_PROFILE", "").strip().lower()
    if override in PROFILES:
        return override
    if os.environ.get("KONSOLE_VERSION"):
        return "konsole"
    if os.environ.get("WEZTERM_EXECUTABLE") or os.environ.get("WT_SESSION"):
        return "xterm"
    return "konsole"


def _active_profile() -> SixelProfile:
    return PROFILES[_detect_profile_name()]


def sixel_char(mask: int) -> str:
    """Map a 6-bit column mask to a DEC sixel character (? through ~)."""
    return chr(63 + (mask & 63))


def encode_rle(chars: str) -> str:
    if not chars:
        return ""
    parts: list[str] = []
    index = 0
    while index < len(chars):
        char = chars[index]
        count = 1
        while (
            index + count < len(chars)
            and chars[index + count] == char
            and count < 255
        ):
            count += 1
        if count > 3:
            parts.append(f"!{count}{char}")
        else:
            parts.append(char * count)
        index += count
    return "".join(parts)


def _rgb_to_sixel_percent(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    red, green, blue = rgb
    return (red * 100 + 127) // 255, (green * 100 + 127) // 255, (blue * 100 + 127) // 255


def _collect_colors(pixels: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    colors: list[tuple[int, int, int]] = []
    seen: set[tuple[int, int, int]] = set()
    for rgb in pixels:
        if rgb not in seen:
            seen.add(rgb)
            colors.append(rgb)
    return colors


def _band_column_chars(
    source,
    width: int,
    height: int,
    band: int,
    rgb: tuple[int, int, int],
) -> str:
    column_chars: list[str] = []
    for x in range(width):
        mask = 0
        for bit in range(6):
            y = band * 6 + bit
            if y < height and source[x, y] == rgb:
                mask |= 1 << bit
        column_chars.append(sixel_char(mask))
    return "".join(column_chars)


def _band_has_ink(chars: str) -> bool:
    return any(char != "?" for char in chars)


def _color_definition(register: int, rgb: tuple[int, int, int]) -> str:
    red, green, blue = _rgb_to_sixel_percent(rgb)
    return f"#{register};2;{red};{green};{blue}"


def encode_sixel(image: Image.Image, profile: SixelProfile | None = None) -> str:
    """Encode an image as a DEC sixel DCS string.

    Uses the kmiya/libsixel scan order:
    - ``$`` overlays the next color on the current 6px band
    - ``-`` advances to the next 6px band
    """
    profile = profile or _active_profile()
    rgb_image = image.convert("RGB")
    width, height = rgb_image.size
    if width < 1 or height < 1:
        raise ValueError("image must be at least 1x1")

    source = rgb_image.load()
    flat = [source[x, y] for y in range(height) for x in range(width)]
    colors = _collect_colors(flat)
    num_bands = (height + 5) // 6

    parts: list[str] = [profile.dcs_open, f'"1;1;{width};{height}']

    for register, rgb in enumerate(colors):
        parts.append(_color_definition(register, rgb))

    for band in range(num_bands):
        band_layers: list[tuple[int, str]] = []
        for register, rgb in enumerate(colors):
            chars = _band_column_chars(source, width, height, band, rgb)
            if _band_has_ink(chars):
                band_layers.append((register, chars))

        if not band_layers:
            continue

        if band > 0:
            parts.append("-")

        for index, (register, chars) in enumerate(band_layers):
            if index > 0:
                parts.append("$")
            parts.append(f"#{register}")
            parts.append(encode_rle(chars))

    parts.append(DCS_CLOSE)
    return "".join(parts)


def make_mono_palette_image(image: Image.Image) -> Image.Image:
    gray = image.convert("L")
    output = Image.new("P", gray.size)
    output.putpalette([0, 0, 0, 255, 255, 255] + [0] * 762)
    source = gray.load()
    target = output.load()
    for y in range(gray.height):
        for x in range(gray.width):
            target[x, y] = 0 if source[x, y] < 180 else 1
    return output


def load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    for template in FONT_CANDIDATES:
        path = Path(template)
        if bold and "DejaVuSans.ttf" in template:
            candidate = path.with_name("DejaVuSans-Bold.ttf")
            if candidate.exists():
                return ImageFont.truetype(str(candidate), size)
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _measure_text(font: ImageFont.ImageFont, text: str) -> tuple[int, int]:
    bbox = font.getbbox(text or " ")
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def heading_font_size(tag: str) -> int:
    return HEADING_FONT_SIZES.get(tag.lower(), HEADING_FONT_SIZE)


def _wrap_lines(text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        trial = " ".join(current + [word])
        width, _ = _measure_text(font, trial)
        if width <= max_width or not current:
            current.append(word)
        else:
            lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    return _wrap_lines(text, font, max_width)


def _render_upscale(font_size: int) -> int:
    return 4 if font_size <= 4 else 2


def _crop_to_ink(image: Image.Image, margin: int = 1) -> Image.Image:
    gray = image.convert("L")
    mask = gray.point(lambda value: 255 if value < 200 else 0, mode="1")
    bbox = mask.getbbox()
    if not bbox:
        return image
    left = max(0, bbox[0] - margin)
    top = max(0, bbox[1] - margin)
    right = min(image.width, bbox[2] + margin)
    bottom = min(image.height, bbox[3] + margin)
    return image.crop((left, top, right, bottom))


def render_text_image(
    text: str,
    font_size: int = TEXT_FONT_SIZE,
    bold: bool = False,
    max_width: int = TEXT_MAX_WIDTH_PX,
) -> Image.Image:
    text = " ".join(text.split())
    if not text:
        text = " "

    upscale = _render_upscale(font_size)
    render_size = max(font_size * upscale, 12)
    font = load_font(render_size, bold=bold)

    scratch = Image.new("RGB", (max_width * upscale, render_size * 8), TEXT_BG)
    draw = ImageDraw.Draw(scratch)
    lines = _wrap_lines(text, font, max_width * upscale)
    line_height = max(render_size + 2, _measure_text(font, "Ag")[1] + 2)
    y = 0
    for line in lines:
        draw.text((0, y), line, font=font, fill=TEXT_FG)
        y += line_height

    cropped = scratch.crop((0, 0, max_width * upscale, max(y, line_height)))
    cropped = _crop_to_ink(cropped, margin=upscale)
    target_width = max(1, cropped.width // upscale)
    target_height = max(1, cropped.height // upscale)
    resized = cropped.resize((target_width, target_height), Image.Resampling.LANCZOS)
    return make_mono_palette_image(resized)


def render_mixed_text_image(
    segments: list[TextSegment],
    max_width: int = TEXT_MAX_WIDTH_PX,
) -> Image.Image:
    upscale = 2
    max_w = max_width * upscale
    layout: list[tuple[str, ImageFont.ImageFont, int]] = []

    for segment_index, segment in enumerate(segments):
        render_size = max(segment.font_size * upscale, 12)
        font = load_font(render_size, bold=segment.bold)
        line_height = max(render_size + 2, _measure_text(font, "Ag")[1] + 2)
        paragraphs = segment.text.split("\n\n") if segment.text else [""]
        segment_started = False
        for para_index, paragraph in enumerate(paragraphs):
            paragraph = " ".join(paragraph.split())
            if paragraph:
                for line in _wrap_lines(paragraph, font, max_w):
                    layout.append((line, font, line_height))
                segment_started = True
            if para_index < len(paragraphs) - 1 and (paragraph or layout):
                layout.append(("", font, max(2, line_height // 2)))
        if segment_started and segment_index < len(segments) - 1:
            layout.append(("", font, max(2, line_height // 2)))

    while layout and not layout[-1][0]:
        layout.pop()
    if not layout:
        return make_mono_palette_image(Image.new("RGB", (1, 1), TEXT_BG))

    total_height = sum(line_height for _, _, line_height in layout)
    scratch = Image.new("RGB", (max_w, max(total_height, 1)), TEXT_BG)
    draw = ImageDraw.Draw(scratch)
    y = 0
    for line, font, line_height in layout:
        if line:
            draw.text((0, y), line, font=font, fill=TEXT_FG)
        y += line_height

    cropped = scratch.crop((0, 0, max_w, y))
    cropped = _crop_to_ink(cropped, margin=upscale)
    target_width = max(1, cropped.width // upscale)
    target_height = max(1, cropped.height // upscale)
    resized = cropped.resize((target_width, target_height), Image.Resampling.LANCZOS)
    return make_mono_palette_image(resized)


def mixed_text_cache_path(segments: list[TextSegment]) -> Path:
    ensure_dirs()
    profile = _detect_profile_name()
    payload = "\x1e".join(f"{segment.font_size}:{int(segment.bold)}:{segment.text}" for segment in segments)
    digest = hashlib.sha256(
        f"v{ENCODER_VERSION}:{profile}:mixed:{payload}".encode("utf-8")
    ).hexdigest()[:24]
    return SIXEL_DIR / f"mixed_{digest}.sixel"


def get_mixed_text_sixel(
    segments: list[TextSegment],
    use_cache: bool = True,
) -> tuple[str, int, int]:
    segments = [segment for segment in segments if segment.text or len(segments) == 1]
    if not segments:
        segments = [TextSegment(" ")]

    cache_path = mixed_text_cache_path(segments)
    if use_cache and cache_path.exists():
        data = cache_path.read_text(encoding="utf-8")
        return data, *_read_sixel_geometry(data)

    image = render_mixed_text_image(segments)
    sixel = encode_sixel(image)
    if use_cache:
        cache_path.write_text(sixel, encoding="utf-8")
    return sixel, image.width, image.height


def prepare_preview_image(
    image_path: Path,
    max_width: int = DEFAULT_MAX_WIDTH,
    colors: int = DEFAULT_COLORS,
) -> Image.Image:
    image = Image.open(image_path).convert("RGB")
    if image.width > max_width:
        ratio = max_width / image.width
        new_size = (max_width, max(1, int(image.height * ratio)))
        image = image.resize(new_size, Image.Resampling.BILINEAR)

    if image.width * image.height > 8_000:
        image = image.filter(ImageFilter.MedianFilter(size=3))

    return image.quantize(colors=colors, method=Image.Quantize.MEDIANCUT).convert("RGB")


def text_sixel_cache_path(text: str, font_size: int, bold: bool) -> Path:
    ensure_dirs()
    profile = _detect_profile_name()
    digest = hashlib.sha256(
        f"v{ENCODER_VERSION}:{profile}:text:{font_size}:{bold}:{text}".encode("utf-8")
    ).hexdigest()[:24]
    return SIXEL_DIR / f"text_{digest}.sixel"


def get_text_sixel(
    text: str,
    font_size: int = TEXT_FONT_SIZE,
    bold: bool = False,
    use_cache: bool = True,
) -> tuple[str, int, int]:
    cache_path = text_sixel_cache_path(text, font_size, bold)
    if use_cache and cache_path.exists():
        data = cache_path.read_text(encoding="utf-8")
        return data, *_read_sixel_geometry(data)

    image = render_text_image(text, font_size=font_size, bold=bold)
    sixel = encode_sixel(image)
    if use_cache:
        cache_path.write_text(sixel, encoding="utf-8")
    return sixel, image.width, image.height


def get_sixel_preview(
    image_path: Path,
    max_width: int = DEFAULT_MAX_WIDTH,
    colors: int = DEFAULT_COLORS,
    use_cache: bool = True,
) -> tuple[str, int, int]:
    image_path = image_path.resolve()
    if not image_path.exists():
        raise FileNotFoundError(image_path)

    cache_path = sixel_cache_path(image_path, max_width, colors, profile=_detect_profile_name())
    if use_cache and cache_path.exists():
        data = cache_path.read_text(encoding="utf-8")
        return data, *_read_sixel_geometry(data)

    preview = prepare_preview_image(image_path, max_width=max_width, colors=colors)
    sixel = encode_sixel(preview)
    if use_cache:
        cache_path.write_text(sixel, encoding="utf-8")
    return sixel, preview.width, preview.height


def _read_sixel_geometry(data: str) -> tuple[int, int]:
    marker = '"1;1;'
    start = data.find(marker)
    if start == -1:
        return TEXT_MAX_WIDTH_PX, TEXT_FONT_SIZE
    values = data[start + len(marker) :].split(";", 2)
    if len(values) < 2:
        return TEXT_MAX_WIDTH_PX, TEXT_FONT_SIZE
    try:
        width = int(values[0])
        height = int(values[1])
        return width, height
    except ValueError:
        return TEXT_MAX_WIDTH_PX, TEXT_FONT_SIZE


def sixel_terminal_rows(pixel_height: int) -> int:
    return max(1, (pixel_height + 5) // 6)
