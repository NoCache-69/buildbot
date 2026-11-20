#!/usr/bin/env python3
"""
AOSP Build Banner Generator (16:9 Aspect Ratio)
Generates high-aesthetic 1280x720 (16:9) modern banner images for Telegram build announcements.
Uses Google Sans & Inter fonts with generous breathing room and modern UI styling.
Layout:
  [ Left: ROM Logo ]     [ Status Badge ]
                         [ ROM Name (Google Sans) ]
                         [ Maintainer: NoEscape.exe(""); ]
                         [ Device: avicii ]
"""

import os
import sys
import argparse
from PIL import Image, ImageDraw, ImageFont, ImageFilter

BANNER_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = BANNER_DIR
ASSETS_DIR = os.path.join(ROOT_DIR, "assets")
LOGOS_DIR = os.path.join(ASSETS_DIR, "logos")
FONTS_DIR = os.path.join(ASSETS_DIR, "fonts")

# Premium Palette
BG_START = (11, 15, 23)        # Deep space obsidian
BG_END = (18, 25, 38)          # Midnight navy
CARD_BG = (22, 30, 46, 230)    # Glass card fill
BORDER_COLOR = (45, 60, 88, 200)

TEXT_WHITE = (255, 255, 255, 255)
TEXT_MUTED = (148, 163, 184, 255)    # Slate 400
TEXT_CYAN = (56, 189, 248, 255)     # Sky 400
TEXT_GLOW = (125, 211, 252, 255)    # Sky 300

STATUS_THEMES = {
    "PROGRESS": {
        "bg": (12, 74, 110, 230),
        "border": (14, 165, 233, 255),
        "text_color": (224, 242, 254, 255),
        "text": "⚙️ BUILD IN PROGRESS"
    },
    "COMPLETED": {
        "bg": (6, 78, 59, 230),
        "border": (34, 197, 94, 255),
        "text_color": (220, 252, 231, 255),
        "text": "✅ BUILD COMPLETED"
    },
    "FAILED": {
        "bg": (127, 29, 29, 230),
        "border": (239, 68, 68, 255),
        "text_color": (254, 226, 226, 255),
        "text": "❌ BUILD FAILED"
    },
}

def get_font(size, style="title"):
    font_map = {
        "title": os.path.join(FONTS_DIR, "GoogleSans.ttf"),
        "body": os.path.join(FONTS_DIR, "Inter.ttf"),
        "sub": os.path.join(FONTS_DIR, "GoogleSans.ttf"),
        "badge": os.path.join(FONTS_DIR, "Inter.ttf"),
    }
    primary = font_map.get(style, os.path.join(FONTS_DIR, "Inter.ttf"))
    
    candidates = [
        primary,
        os.path.join(FONTS_DIR, "GoogleSans.ttf"),
        os.path.join(FONTS_DIR, "Inter.ttf"),
        os.path.join(FONTS_DIR, "Manrope.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    ]
    for p in candidates:
        if os.path.isfile(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()

def draw_background(width, height):
    base = Image.new("RGBA", (width, height), BG_START)
    draw = ImageDraw.Draw(base)
    for y in range(height):
        ratio = y / height
        r = int(BG_START[0] * (1 - ratio) + BG_END[0] * ratio)
        g = int(BG_START[1] * (1 - ratio) + BG_END[1] * ratio)
        b = int(BG_START[2] * (1 - ratio) + BG_END[2] * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b, 255))
    
    # Atmospheric glows with soft diffusion
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse([width - 500, -200, width + 200, 450], fill=(56, 189, 248, 35))
    glow_draw.ellipse([-180, height - 380, 420, height + 180], fill=(99, 102, 241, 30))
    glow = glow.filter(ImageFilter.GaussianBlur(70))
    base.alpha_composite(glow)
    return base

def find_logo(rom_name, custom_logo_path=None):
    if custom_logo_path and os.path.isfile(custom_logo_path):
        return custom_logo_path
    
    try:
        from rom_registry import resolve_rom_logo
        logo = resolve_rom_logo(rom_name)
        if logo and os.path.isfile(logo):
            return logo
    except Exception:
        pass

    rom_clean = (rom_name or "").lower().replace("-", "").replace("_", "").replace(" ", "")
    candidates = [
        os.path.join(LOGOS_DIR, f"{rom_clean}.png"),
        os.path.join(LOGOS_DIR, "aospa.png"),
        os.path.join(LOGOS_DIR, "android.png")
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return os.path.join(LOGOS_DIR, "android.png")

def generate_banner(
    rom_name="AOSPA",
    device="avicii",
    maintainer='NoEscape.exe("");',
    status="PROGRESS",
    variant=None,
    build_type=None,
    release=None,
    custom_logo=None,
    output_path="/tmp/build_banner.png"
):
    # Strict 16:9 Aspect Ratio (1280 x 720)
    width, height = 1280, 720
    img = draw_background(width, height)
    
    # 1. Main Inner Card Container with generous breathing margins
    card_mx, card_my = 55, 45
    card_w = width - (card_mx * 2)
    card_h = height - (card_my * 2)

    card = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    card_draw = ImageDraw.Draw(card)
    card_draw.rounded_rectangle(
        [card_mx, card_my, card_mx + card_w, card_my + card_h],
        radius=30,
        fill=CARD_BG,
        outline=BORDER_COLOR,
        width=2
    )
    img.alpha_composite(card)
    draw = ImageDraw.Draw(img)

    # 2. Left Side: ROM Logo inside dedicated rounded container
    logo_box_size = 320
    logo_x = card_mx + 55
    logo_y = (height - logo_box_size) // 2

    # Draw Logo Container Box
    draw.rounded_rectangle(
        [logo_x, logo_y, logo_x + logo_box_size, logo_y + logo_box_size],
        radius=26,
        fill=(14, 19, 30, 220),
        outline=(56, 189, 248, 80),
        width=2
    )

    logo_path = find_logo(rom_name, custom_logo)
    if os.path.isfile(logo_path):
        try:
            logo_img = Image.open(logo_path).convert("RGBA")
            max_inner = logo_box_size - 64  # generous 32px padding on all sides
            logo_img.thumbnail((max_inner, max_inner), Image.Resampling.LANCZOS)
            
            actual_x = logo_x + (logo_box_size - logo_img.width) // 2
            actual_y = logo_y + (logo_box_size - logo_img.height) // 2
            img.paste(logo_img, (actual_x, actual_y), mask=logo_img)
        except Exception as e:
            print(f"[BANNER] Warning: Failed to load logo {logo_path}: {e}")

    # 3. Right Side: Typography & Information Hierarchy
    content_x = logo_x + logo_box_size + 65
    max_text_width = (card_mx + card_w) - content_x - 50

    # Status Pill Badge
    st_info = STATUS_THEMES.get((status or "PROGRESS").upper(), STATUS_THEMES["PROGRESS"])
    badge_text = st_info["text"]
    font_badge = get_font(22, style="badge")
    
    b_bbox = font_badge.getbbox(badge_text)
    badge_w = (b_bbox[2] - b_bbox[0]) + 36
    badge_h = 42

    # ROM Name Header (Google Sans, dynamically scaled)
    title_text = rom_name.strip()
    title_size = 72
    font_title = get_font(title_size, style="title")
    while title_size > 42:
        font_title = get_font(title_size, style="title")
        t_box = font_title.getbbox(title_text)
        if (t_box[2] - t_box[0]) <= max_text_width:
            break
        title_size -= 4
    
    t_bbox = font_title.getbbox(title_text)
    t_h = t_bbox[3] - t_bbox[1]

    # Subtitle Typography (Google Sans & Inter)
    font_label = get_font(26, style="body")
    font_val = get_font(28, style="sub")

    maintainer_str = maintainer.strip()
    device_str = device.strip()

    # Calculate Total Content Height for perfect vertical centering
    # Spacing hierarchy:
    #   Badge -> [30px space] -> Title -> [34px space] -> Maintainer -> [18px space] -> Device
    spacing_badge_to_title = 30
    spacing_title_to_maintainer = 34
    spacing_between_details = 18

    info_line_h = 32
    total_content_h = (
        badge_h +
        spacing_badge_to_title +
        t_h +
        spacing_title_to_maintainer +
        info_line_h +
        spacing_between_details +
        info_line_h
    )

    start_y = (height - total_content_h) // 2

    # Draw Status Pill Badge
    draw.rounded_rectangle(
        [content_x, start_y, content_x + badge_w, start_y + badge_h],
        radius=14,
        fill=st_info["bg"],
        outline=st_info["border"],
        width=2
    )
    draw.text((content_x + 18, start_y + 8), badge_text, font=font_badge, fill=st_info["text_color"])

    # Draw ROM Title
    title_y = start_y + badge_h + spacing_badge_to_title
    draw.text((content_x, title_y), title_text, font=font_title, fill=TEXT_WHITE)

    # Draw Maintainer Line:
    # "Maintainer: " (Cyan / Sky) + "<MaintainerName>" (White Bold)
    m_y = title_y + t_h + spacing_title_to_maintainer
    draw.text((content_x, m_y), "Maintainer: ", font=font_label, fill=TEXT_CYAN)
    m_label_w = font_label.getbbox("Maintainer: ")[2] - font_label.getbbox("Maintainer: ")[0]
    draw.text((content_x + m_label_w, m_y - 2), maintainer_str, font=font_val, fill=TEXT_WHITE)

    # Draw Device Line:
    # "Device: " (Cyan / Sky) + "<DeviceName>" (White Bold)
    d_y = m_y + info_line_h + spacing_between_details
    draw.text((content_x, d_y), "Device: ", font=font_label, fill=TEXT_CYAN)
    d_label_w = font_label.getbbox("Device: ")[2] - font_label.getbbox("Device: ")[0]
    draw.text((content_x + d_label_w, d_y - 2), device_str, font=font_val, fill=TEXT_WHITE)

    # Save finalized high-res banner
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    img.convert("RGB").save(output_path, "PNG", quality=95)
    return output_path

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", default="AOSPA")
    parser.add_argument("--device", default="avicii")
    parser.add_argument("--maintainer", default='NoEscape.exe("");')
    parser.add_argument("--status", default="PROGRESS", choices=["PROGRESS", "COMPLETED", "FAILED"])
    parser.add_argument("--output", default="/tmp/test_16_9_perfect.png")
    args = parser.parse_args()

    out = generate_banner(
        rom_name=args.rom,
        device=args.device,
        maintainer=args.maintainer,
        status=args.status,
        output_path=args.output
    )
    print(f"Generated 16:9 banner with Google Sans & Inter at {out}")
