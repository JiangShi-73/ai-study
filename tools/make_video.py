#!/usr/bin/env python3
"""生成 ai-study 介绍视频（100 秒 / 1920x1080 / 30fps / mp4）。

不依赖 ffmpeg 命令行：用 OpenCV 自带的 VideoWriter 编码。
所有画面用 Pillow 逐帧绘制，中文用微软雅黑。
"""
import math
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1920, 1080, 30
BG = (11, 18, 32)
FG = (230, 237, 247)
MUTED = (148, 163, 184)
CYAN = (34, 211, 238)
AMBER = (245, 158, 11)
ROSE = (251, 113, 133)
GREEN = (52, 211, 153)
PANEL = (18, 27, 45)
LINE = (45, 60, 85)

FONT_DIR = Path("C:/Windows/Fonts")
BOLD = FONT_DIR / "msyhbd.ttc"
REG = FONT_DIR / "msyh.ttc"


def font(size, bold=True):
    return ImageFont.truetype(str(BOLD if bold else REG), size)


def tw(d, text, f):
    box = d.textbbox((0, 0), text, font=f)
    return box[2] - box[0], box[3] - box[1]


def center_text(d, text, f, y, color=FG, cx=W // 2):
    w, h = tw(d, text, f)
    d.text((cx - w / 2, y), text, font=f, fill=color)
    return w, h


def ease_out(t):
    return 1 - (1 - max(0.0, min(1.0, t))) ** 3


def clamp01(t):
    return max(0.0, min(1.0, t))


def with_alpha(color, a):
    return (color[0], color[1], color[2], int(255 * clamp01(a)))


def panel(d, x, y, w, h, radius=18, fill=PANEL, outline=LINE, width=2):
    d.rounded_rectangle([x, y, x + w, y + h], radius=radius, fill=fill,
                        outline=outline, width=width)


def check(d, x, y, color=GREEN, r=14):
    d.ellipse([x - r, y - r, x + r, y + r], fill=color)
    d.line([x - r * 0.45, y, x - r * 0.05, y + r * 0.45], fill=BG, width=4)
    d.line([x - r * 0.05, y + r * 0.45, x + r * 0.5, y - r * 0.4], fill=BG, width=4)


def bg_layer(progress=0.0):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    step = 80
    off = int((progress * 40) % step)
    for x in range(-step, W + step, step):
        d.line([(x + off, 0), (x + off, H)], fill=(15, 23, 40), width=1)
    for y in range(0, H, step):
        d.line([(0, y), (W, y)], fill=(15, 23, 40), width=1)
    return img


# ---------------- 场景 ----------------

def scene_title(d, t, dur):
    a = min(clamp01(t / 0.8), clamp01((dur - t) / 0.8))
    f1, f2, f3 = font(104), font(104), font(30, False)
    y = H // 2 - 130
    col = with_alpha(FG, a)
    center_text(d, "AI 可能骗你", f1, y, col)
    center_text(d, "档案不会。", f2, y + 130, with_alpha(CYAN, a))
    center_text(d, "a i - s t u d y", f3, y + 290, with_alpha(MUTED, a))


def scene_pain(d, t, dur):
    a = clamp01(t / 0.6) * clamp01((dur - t) / 0.5)
    # 左：对话窗口
    panel(d, 150, 250, 780, 420)
    d.text((190, 285), "对话", font=font(26, False), fill=MUTED)
    d.rounded_rectangle([190, 350, 890, 470], radius=16, fill=(22, 34, 56))
    d.text((215, 375), "你已经掌握了指针 ✨", font=font(38), fill=FG)
    d.text((215, 425), "（没有生成任何文件）", font=font(28, False), fill=MUTED)
    # 右：空文件夹
    panel(d, 1050, 250, 620, 420, fill=(14, 21, 36))
    d.text((1090, 285), "学习档案 /", font=font(26, False), fill=MUTED)
    d.rounded_rectangle([1090, 360, 1330, 500], radius=12, fill=(20, 30, 50), outline=LINE, width=2)
    d.text((1110, 405), "0 个文件", font=font(30, False), fill=MUTED)
    d.text((1380, 400), "← 空的", font=font(34), fill=ROSE)
    center_text(d, "聊完就忘。所谓「掌握了」，只是它的一句话。", font(40, False), 760, with_alpha(FG, a))


def scene_modes(d, t, dur):
    center_text(d, "三种带法，一个内核", font(58), 120, FG)
    rows = [
        ("教师", "从零教到会", CYAN),
        ("伴学", "随手接住卡壳", AMBER),
        ("突击", "只解析和整理", ROSE),
    ]
    for i, (name, desc, col) in enumerate(rows):
        p = clamp01((t - 0.5 - i * 0.9) / 0.6)
        if p <= 0:
            continue
        e = ease_out(p)
        x = 300 - (1 - e) * 60
        y = 300 + i * 130
        d.rounded_rectangle([x, y, x + 1320, y + 100], radius=16,
                            fill=(18, 27, 45), outline=col, width=2)
        d.text((x + 40, y + 28), name, font=font(44), fill=col)
        d.text((x + 260, y + 36), desc, font=font(36, False), fill=FG)
    p2 = clamp01((t - 3.6) / 0.8)
    if p2 > 0:
        d.rounded_rectangle([300, 760, 1620, 860], radius=16, fill=(14, 21, 36),
                            outline=LINE, width=2)
        d.text((340, 790), "共用内核：档案 · 真实性闸门 · 知识库 · 复习 · 画像 · 子代理",
               font=font(32, False), fill=with_alpha(MUTED, p2))


def scene_teacher(d, t, dur):
    center_text(d, "教师模式", font(56), 110, CYAN)
    center_text(d, "你带着「想系统学一门」来", font(34, False), 190, MUTED)
    steps = ["定位访谈", "定路径", "讲授", "实践", "出题", "讲评", "归档"]
    x0, y0 = 165, 430
    for i, s in enumerate(steps):
        lit = clamp01((t - 0.6 - i * 0.45) / 0.4)
        base = 0.22 if lit <= 0 else 0.22 + 0.78 * lit
        x = x0 + i * 235
        d.rounded_rectangle([x, y0, x + 200, y0 + 100], radius=14,
                            fill=(18, 27, 45), outline=with_alpha(CYAN, base), width=2)
        w, _ = tw(d, s, font(34))
        d.text((x + 100 - w / 2, y0 + 30), s, font=font(34), fill=with_alpha(FG, base))
        if i < len(steps) - 1:
            d.line([x + 205, y0 + 50, x + 230, y0 + 50], fill=with_alpha(CYAN, base), width=3)
    p = clamp01((t - 3.6) / 0.8)
    if p > 0:
        center_text(d, "每节课都留下一条记录：讲了什么 · 他答错什么 · 为什么错",
                    font(36, False), 660, with_alpha(FG, p))


def scene_companion(d, t, dur):
    center_text(d, "伴学模式", font(56), 90, AMBER)
    center_text(d, "你发题、发书、发作业", font(34, False), 170, MUTED)
    p = clamp01((t - 0.6) / 0.7)
    if p <= 0:
        return
    e = ease_out(p)
    panel(d, 200, 270, 1520, 520, fill=(16, 24, 40), outline=with_alpha(AMBER, e))
    d.text((250, 305), "Q-002 · 虚短套用错了", font=font(42), fill=with_alpha(AMBER, e))
    lines = [
        ("他答的", "「虚短就是两个输入端都是 0V」", FG),
        ("为什么他会错", "把「虚短」读成了「接地」", ROSE),
        ("补丁", "套虚短之前先问一句「共模电平在哪」", GREEN),
    ]
    for i, (k, v, col) in enumerate(lines):
        pp = clamp01((t - 1.4 - i * 0.8) / 0.6)
        if pp <= 0:
            continue
        y = 390 + i * 105
        d.text((250, y), k, font=font(30, False), fill=with_alpha(MUTED, pp))
        d.text((470, y - 6), v, font=font(36), fill=with_alpha(col, pp))
    pp = clamp01((t - 4.2) / 0.7)
    if pp > 0:
        d.text((250, 720), "→ 已提炼：03-板块笔记 / 运放 >> 虚短不是接地",
               font=font(32, False), fill=with_alpha(CYAN, pp))
    center_text(d, "答完一定问一句「要不要记」", font(38, False), 900, with_alpha(FG, clamp01((t - 5) / 0.8)))


def scene_cram(d, t, dur):
    center_text(d, "突击模式", font(56), 90, ROSE)
    center_text(d, "一堆卷子进去，三份东西出来", font(34, False), 170, MUTED)
    e = clamp01((t - 0.3) / 0.5)
    x0, y0, cw, ch = 440, 380, 520, 150
    heads = ["", "错得多", "错得少"]
    for i, h in enumerate(heads):
        if h:
            d.text((x0 + i * cw + 40, y0 - 50), h, font=font(32, False), fill=with_alpha(MUTED, e))
    rows = [
        ("分值高", [("立刻补", ROSE), ("保分，别丢", GREEN)]),
        ("分值低", [("最后看，或放弃", AMBER), ("不用管", MUTED)]),
    ]
    for r, (label, cells) in enumerate(rows):
        d.text((x0 - 210, y0 + r * ch + 50), label, font=font(36), fill=with_alpha(FG, max(e, 0.35)))
        for c, (text, col) in enumerate(cells):
            pp = clamp01((t - 1.0 - (r * 2 + c) * 0.35) / 0.45)
            base = 0.25 if pp <= 0 else 0.25 + 0.75 * pp
            x = x0 + c * cw
            y = y0 + r * ch
            d.rounded_rectangle([x, y, x + cw - 40, y + ch - 30], radius=14,
                                fill=(18, 27, 45), outline=with_alpha(col, base), width=2)
            w, _ = tw(d, text, font(36))
            d.text((x + (cw - 40 - w) / 2, y + 45), text, font=font(36), fill=with_alpha(col, base))
    pp = clamp01((t - 4.0) / 0.7)
    if pp > 0:
        center_text(d, "错题挂了考点，考点排了分值——先补哪里一目了然",
                    font(38, False), 780, with_alpha(FG, pp))


def scene_terminal(d, t, dur):
    center_text(d, "档案能抓假", font(56), 90, GREEN)
    panel(d, 260, 220, 1400, 620, fill=(8, 12, 20), outline=LINE)
    d.ellipse([292, 252, 312, 272], fill=(239, 68, 68))
    d.ellipse([324, 252, 344, 272], fill=(245, 158, 11))
    d.ellipse([356, 252, 376, 272], fill=(52, 211, 153))
    mono = font(30, False)
    d.text((300, 300), "PS> python ai-study/scripts/study.py selftest", font=mono, fill=MUTED)
    items = [
        "倒填历史（声称过去上过课）",
        "预支复习（笔记未建就已在复习）",
        "索引结果 ≠ 正文结果",
        "版本号超前于变更日志",
    ]
    y = 380
    for i, s in enumerate(items):
        pp = clamp01((t - 1.0 - i * 0.75) / 0.4)
        if pp <= 0:
            break
        check(d, 320, y + 18, with_alpha(GREEN, pp) if False else GREEN)
        d.text((360, y), s, font=mono, fill=with_alpha(FG, pp))
        d.text((1030, y), "抓到", font=mono, fill=with_alpha(GREEN, pp))
        y += 78
    pp = clamp01((t - 4.4) / 0.7)
    if pp > 0:
        d.text((360, y + 10), "4/4 条被抓到，检查器可信。", font=font(34), fill=with_alpha(GREEN, pp))


def scene_outro(d, t, dur):
    a = clamp01(t / 0.6)
    rules = ["不许编", "先教后考", "输出要能读", "主动权归学生"]
    for i, s in enumerate(rules):
        p = clamp01((t - 0.3 - i * 0.35) / 0.4)
        if p <= 0:
            continue
        y = 260 + i * 90
        w, _ = tw(d, s, font(40))
        d.text((W / 2 - w / 2, y), s, font=font(40), fill=with_alpha(FG, p))
    p2 = clamp01((t - 1.8) / 0.6)
    if p2 > 0:
        center_text(d, "AI 可能骗你，档案不会。", font(64), 680, with_alpha(CYAN, p2))
    p3 = clamp01((t - 2.4) / 0.6)
    if p3 > 0:
        center_text(d, "ai-study · 开源 · powershell -File install.ps1", font(30, False), 790,
                    with_alpha(MUTED, p3))


SCENES = [
    (8.0, scene_title),
    (10.0, scene_pain),
    (10.0, scene_modes),
    (16.0, scene_teacher),
    (16.0, scene_companion),
    (16.0, scene_cram),
    (14.0, scene_terminal),
    (8.0, scene_outro),
]


def render(out_path: Path, preview_dir: Path | None = None):
    total = sum(d for d, _ in SCENES)
    n_frames = int(total * FPS)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    vw = cv2.VideoWriter(str(out_path), fourcc, FPS, (W, H))
    if not vw.isOpened():
        raise SystemExit("VideoWriter 打开失败")

    t_global = 0.0
    bounds = []
    for dur, fn in SCENES:
        bounds.append((t_global, t_global + dur, fn, dur))
        t_global += dur

    grabs = {int(p): [] for p in (0.06, 0.2, 0.36, 0.52, 0.64, 0.78, 0.88, 0.96)}

    for idx in range(n_frames):
        tsec = idx / FPS
        for s0, s1, fn, dur in bounds:
            if s0 <= tsec < s1:
                chip = "ai-study"
                img = bg_layer(tsec * 0.02)
                d = ImageDraw.Draw(img, "RGBA")
                fn(d, tsec - s0, dur)
                # 角标
                d.text((60, 48), chip, font=font(26, False), fill=(70, 90, 120))
                d.text((W - 200, 48), f"{int(tsec):02d}s", font=font(26, False), fill=(60, 76, 100))
                # 底部进度条 + 场景刻度
                d.rectangle([0, H - 6, W, H], fill=(20, 30, 48))
                d.rectangle([0, H - 6, int(W * tsec / total), H], fill=(34, 211, 238))
                acc = 0.0
                for dur_i, _ in SCENES:
                    acc += dur_i
                    x = int(W * acc / total)
                    d.rectangle([x - 1, H - 12, x + 1, H], fill=(70, 90, 120))
                frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
                vw.write(frame)
                frac = idx / n_frames
                for p in grabs:
                    if abs(frac - p / 100) < 1.0 / n_frames:
                        grabs[p].append(idx)
                break

    vw.release()

    if preview_dir:
        preview_dir.mkdir(parents=True, exist_ok=True)
        cap = cv2.VideoCapture(str(out_path))
        want = sorted({int(p * n_frames / 100) for p in (6, 20, 36, 52, 64, 78, 88, 96)})
        got = set()
        i = 0
        while True:
            ok, fr = cap.read()
            if not ok:
                break
            if i in want and i not in got:
                cv2.imwrite(str(preview_dir / f"frame-{i:04d}.png"), fr)
                got.add(i)
            i += 1
        cap.release()
    return n_frames, total


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    out = root / "视频" / "ai-study-介绍.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    n, dur = render(out, root / "视频" / "_frames")
    print(f"完成：{out}  帧数={n}  时长={dur:.0f}s  大小={out.stat().st_size/1024/1024:.1f}MB")
