#!/usr/bin/env python3
"""图片工具：从 PDF 取图、裁剪、标注。

给 ai-study 用。坐标一律是**原图像素**，输出文件写到哪里由调用方决定。

用法：
  python tools/img.py info   <图片>
  python tools/img.py crop   <输入> <输出> --box x0,y0,x1,y1 [--scale 2]
  python tools/img.py pdf    <PDF> <页码(1起)> <输出> [--box ...] [--dpi 200]
  python tools/img.py mark   <输入> <输出> [--rect x0,y0,x1,y1 ...] [--arrow x0,y0,x1,y1 ...]
                                           [--text x,y,文字 ...] [--color #FB7185] [--size 30]

示例：
  # 教材第 128 页，只要右边那半页的图
  python tools/img.py pdf 教材.pdf 128 assets/记录02-共射电路.png --box 760,200,1500,900

  # 在错题图上圈出关键点 + 一句话
  python tools/img.py mark q3.png q3-标注.png \
      --rect 420,300,700,480 --arrow 300,250,420,330 \
      --text 120,180,"这里共模电平不是 0"
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT_BOLD = Path("C:/Windows/Fonts/msyhbd.ttc")
FONT_REG = Path("C:/Windows/Fonts/msyh.ttc")
DEFAULT_COLOR = "#FB7185"


def parse_box(s):
    parts = [int(float(x)) for x in s.split(",")]
    if len(parts) != 4:
        raise SystemExit(f"--box 需要 x0,y0,x1,y1：{s}")
    return parts


def load_font(size):
    for p in (FONT_BOLD, FONT_REG):
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def cmd_info(args):
    im = Image.open(args.src)
    print(f"{args.src}\n  尺寸 {im.width}x{im.height}  模式 {im.mode}  格式 {im.format}")
    return 0


def cmd_crop(args):
    im = Image.open(args.src).convert("RGB")
    x0, y0, x1, y1 = parse_box(args.box)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(im.width, x1), min(im.height, y1)
    if x1 <= x0 or y1 <= y0:
        raise SystemExit(f"裁剪区域为空：{args.box}（原图 {im.width}x{im.height}）")
    out = im.crop((x0, y0, x1, y1))
    if args.scale != 1:
        out = out.resize((int(out.width * args.scale), int(out.height * args.scale)), Image.LANCZOS)
    Path(args.dst).parent.mkdir(parents=True, exist_ok=True)
    out.save(args.dst)
    print(f"裁剪 {x1-x0}x{y1-y0} → {args.dst}")
    return 0


def cmd_pdf(args):
    import fitz  # PyMuPDF

    doc = fitz.open(args.pdf)
    if not (1 <= args.page <= doc.page_count):
        raise SystemExit(f"页码超范围：PDF 共 {doc.page_count} 页")
    page = doc[args.page - 1]
    zoom = args.dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    if args.box:
        x0, y0, x1, y1 = parse_box(args.box)
        im = im.crop((x0, y0, min(x1, im.width), min(y1, im.height)))
    Path(args.dst).parent.mkdir(parents=True, exist_ok=True)
    im.save(args.dst)
    print(f"第 {args.page} 页 → {args.dst}（{im.width}x{im.height}，{args.dpi}dpi）")
    return 0


def cmd_mark(args):
    im = Image.open(args.src).convert("RGB")
    d = ImageDraw.Draw(im, "RGBA")
    col = args.color
    rgb = tuple(int(col[i:i + 2], 16) for i in (1, 3, 5))
    lw = max(3, im.width // 400)

    for spec in args.rect:
        x0, y0, x1, y1 = parse_box(spec)
        d.rectangle([x0, y0, x1, y1], outline=rgb + (255,), width=lw)

    for spec in args.arrow:
        x0, y0, x1, y1 = parse_box(spec)
        d.line([x0, y0, x1, y1], fill=rgb + (255,), width=lw)
        import math
        ang = math.atan2(y1 - y0, x1 - x0)
        L = max(14, im.width // 60)
        for da in (2.6, -2.6):
            d.line([x1, y1, x1 + L * math.cos(ang + da), y1 + L * math.sin(ang + da)],
                   fill=rgb + (255,), width=lw)

    font = load_font(args.size)
    for spec in args.text:
        pos, txt = spec.split(",", 2)[:2], spec.split(",", 2)[2]
        x, y = int(pos[0]), int(pos[1])
        # 描边，保证任何底色都能读
        for dx in (-2, -1, 0, 1, 2):
            for dy in (-2, -1, 0, 1, 2):
                d.text((x + dx, y + dy), txt, font=font, fill=(0, 0, 0, 200))
        d.text((x, y), txt, font=font, fill=rgb + (255,))

    Path(args.dst).parent.mkdir(parents=True, exist_ok=True)
    im.save(args.dst)
    n = len(args.rect) + len(args.arrow) + len(args.text)
    print(f"标注 {n} 处 → {args.dst}")
    return 0


def main():
    import argparse
    p = argparse.ArgumentParser(description="图片裁剪 / PDF 取图 / 标注")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("info"); a.add_argument("src"); a.set_defaults(fn=cmd_info)

    a = sub.add_parser("crop")
    a.add_argument("src"); a.add_argument("dst")
    a.add_argument("--box", required=True); a.add_argument("--scale", type=float, default=1)
    a.set_defaults(fn=cmd_crop)

    a = sub.add_parser("pdf")
    a.add_argument("pdf"); a.add_argument("page", type=int); a.add_argument("dst")
    a.add_argument("--box"); a.add_argument("--dpi", type=int, default=200)
    a.set_defaults(fn=cmd_pdf)

    a = sub.add_parser("mark")
    a.add_argument("src"); a.add_argument("dst")
    a.add_argument("--rect", action="append", default=[])
    a.add_argument("--arrow", action="append", default=[])
    a.add_argument("--text", action="append", default=[])
    a.add_argument("--color", default=DEFAULT_COLOR)
    a.add_argument("--size", type=int, default=30)
    a.set_defaults(fn=cmd_mark)

    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
