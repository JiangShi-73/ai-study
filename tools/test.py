#!/usr/bin/env python3
"""ai-study 回归测试。

把这些轮手工验过的东西固化成一条命令：python tools/test.py
退出码 0 = 全过。
"""
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import tempfile
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STUDY = ROOT / "ai-study" / "scripts" / "study.py"
PY = sys.executable

results = []


ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


def run(*args):
    p = subprocess.run([PY, str(STUDY), *args], capture_output=True, text=True,
                       encoding="utf-8", env=ENV)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def case(name, fn):
    try:
        ok, detail = fn()
    except Exception as e:
        ok, detail = False, f"异常：{e}"
    results.append((ok, name, detail))


def t_clean():
    d = Path(tempfile.mkdtemp())
    try:
        run("init", str(d), "--subject", "干净")
        code, out = run("lint", str(d))
        return code == 0 and "体检通过" in out, "全新档案应通过"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def t_demo():
    d = Path(tempfile.mkdtemp())
    try:
        run("demo-init", str(d), "--subject", "演示")
        code, out = run("lint", str(d))
        has_flag = "demo: true" in (d / "00-学习档案.md").read_text(encoding="utf-8")
        return code == 0 and has_flag, "演示档案应通过且带 demo 标记"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def t_selftest():
    code, out = run("selftest")
    return code == 0 and "4/4" in out, "检查器自检 4/4"


def t_untaught():
    d = Path(tempfile.mkdtemp())
    try:
        run("init", str(d), "--subject", "x")
        (d / "03-板块笔记").mkdir(exist_ok=True)
        (d / "03-板块笔记" / "a.md").write_text(
            "# 板块：a\n\n## 知识点：没讲过\n\n"
            "> 状态 🔴 ｜ 上次复习 — ｜ 次数 0 ｜ 连对 0 ｜ 固化 — ｜ 来源 —\n",
            encoding="utf-8")
        code, out = run("review-list", str(d))
        return "可复习 0 条" in out and "备而未学" in out, "次数 0 不进复习货架"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def t_checkpoint():
    d = Path(tempfile.mkdtemp())
    try:
        run("init", str(d), "--subject", "x")
        run("checkpoint", str(d), "--step", "⑤ 讲授", "--n", "2")
        code, out = run("brief", str(d))
        has_banner = "没归档的课" in out and "⑤ 讲授" in out
        run("checkpoint", str(d), "--clear")
        code2, out2 = run("brief", str(d))
        cleared = "没归档的课" not in out2
        return has_banner and cleared, "检查点：brief 提示 + 归档后清除"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def t_interval():
    d = Path(tempfile.mkdtemp())
    try:
        run("init", str(d), "--subject", "x")
        import datetime as dt
        today = dt.date.today()
        back = (today - dt.timedelta(days=30)).isoformat()
        (d / "03-板块笔记" / "a.md").write_text(
            "# 板块：a\n\n## 知识点：久未复习\n\n"
            f"> 状态 🔴 ｜ 上次复习 {back} ｜ 次数 3 ｜ 连对 0 ｜ 固化 — ｜ 来源 —\n",
            encoding="utf-8")
        code, out = run("review-list", str(d), "--all", "--per-board", "0")
        return "逾期" in out and "建议" in out, "逾期标记与建议日期"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def t_compact():
    d = Path(tempfile.mkdtemp())
    try:
        import datetime as dt
        run("init", str(d), "--subject", "x")
        base = dt.date(2026, 1, 1)
        for i in range(1, 81):
            day = (base + dt.timedelta(days=i)).isoformat()
            (d / "02-每日笔记" / f"记录{i:02d}-{day}-第{i}课.md").write_text(
                f"# 记录 {i}\n\n**日期**：{day}\n**第 N 次课**：{i}\n**类型**：正课\n"
                f"**真实性**：真实\n\n**结果**：1 / 4\n", encoding="utf-8")
        run("index", str(d))
        run("compact", str(d))
        kept = len(list((d / "02-每日笔记").glob("记录*.md")))
        batch = list((d / "02-每日笔记" / "_归档").glob("批次-*"))
        summary = batch and (batch[0] / "SUMMARY.md").exists()
        idx = (d / "00-学习档案.md").read_text(encoding="utf-8")
        return kept == 40 and len(batch) == 1 and summary and "已压缩" in idx, \
            "满 80 条压走最远 40 条并留总结"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def t_mode():
    d = Path(tempfile.mkdtemp())
    try:
        run("init", str(d), "--subject", "x")
        ap = d / "00-学习档案.md"
        good = ap.read_text(encoding="utf-8")
        # 合法值
        bad_val = good.replace("| 模式 | 教师", "| 模式 | 看心情")
        ap.write_text(bad_val, encoding="utf-8")
        code, out = run("lint", str(d))
        caught = code != 0 and "模式" in out
        # 旧档案缺这一行 → 只警告
        import re as _re
        no_row = _re.sub(r"^\| 模式 \|.*$\n", "", good, flags=_re.M)
        ap.write_text(no_row, encoding="utf-8")
        code2, out2 = run("lint", str(d))
        return caught and "模式" in out2, "模式取值校验 + 缺字段警告"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def t_manual():
    d = ROOT / "说明书"
    need = ["00-先读我.md", "01-三种模式怎么选.md", "02-教师模式.md",
            "03-伴学模式.md", "04-突击模式.md", "05-笔记与档案.md",
            "06-复习与遗忘.md", "07-常见问题.md"]
    missing = [f for f in need if not (d / f).exists()]
    if missing:
        return False, "缺 " + "、".join(missing)
    total = sum(len((d / f).read_text(encoding="utf-8").splitlines()) for f in need)
    return total > 400, f"{len(need)} 份 / {total} 行"


def t_img():
    d = Path(tempfile.mkdtemp())
    try:
        import subprocess
        img = d / "t.png"
        make = (
            "from PIL import Image, ImageDraw;"
            f"im=Image.new('RGB',(400,300),'white');"
            "ImageDraw.Draw(im).rectangle([50,50,200,200],outline='black',width=2);"
            f"im.save(r'{img}')"
        )
        subprocess.run([PY, "-c", make], check=True, capture_output=True)
        crop = subprocess.run([PY, str(ROOT / "tools" / "img.py"), "crop", str(img),
                               str(d / "c.png"), "--box", "40,40,210,210"],
                              capture_output=True)
        mark = subprocess.run([PY, str(ROOT / "tools" / "img.py"), "mark", str(img),
                               str(d / "m.png"), "--rect", "50,50,200,200",
                               "--text", "10,10,测试"], capture_output=True)
        ok = crop.returncode == 0 and mark.returncode == 0 \
            and (d / "c.png").exists() and (d / "m.png").exists()
        return ok, "裁剪 + 标注"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def t_resume():
    d = Path(tempfile.mkdtemp())
    try:
        run("init", str(d), "--subject", "x")
        entry = (d / "从这里开始.md").exists()
        run("tail", str(d), "--note", "聊到 A", "--last", "先这样",
            "--next", "今天开大点 0")
        code, out = run("brief", str(d))
        has_tail = "上次对话：聊到 A" in out
        code2, pack = run("resume", str(d))
        ok_pack = "我要继续学" in pack and "不要问我" in pack
        # 追加式 + 只留最近 5 条
        for i in range(2, 8):
            run("tail", str(d), "--note", f"第 {i} 次", "--next", f"开场 {i}")
        body = (d / "_进行中" / "对话尾巴.md").read_text(encoding="utf-8")
        n_entries = body.count("\n## ")
        newest = body.split("\n## ")[1].splitlines()[0]
        rotated = n_entries == 5 and "第 7 次" in body and newest.strip()[:4] == "2026"
        code3, out3 = run("brief", str(d))
        latest_ok = "第 7 次" in out3
        return entry and has_tail and ok_pack and rotated and latest_ok, \
            "入口 + 尾巴 + 交接卡 + 轮转（留 5 条）"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def t_robust():
    d = Path(tempfile.mkdtemp())
    outs = []
    try:
        run("init", str(d), "--subject", "x")
        # ① 次数写成非数字必须报错（以前静默当 0，知识点会悄悄掉出复习）
        (d / "03-板块笔记").mkdir(exist_ok=True)
        (d / "03-板块笔记" / "bad.md").write_text(
            "# 板块\n\n## 知识点：坏次数\n\n"
            "> 状态 🔴 ｜ 上次复习 — ｜ 次数 abc ｜ 连对 0 ｜ 固化 — ｜ 来源 —\n",
            encoding="utf-8")
        code, out = run("lint", str(d))
        outs.append(code != 0 and "不是数字" in out)
        (d / "03-板块笔记" / "bad.md").unlink()
        # ② 坏编码文件不能吐 traceback
        (d / "00-学习档案.md").write_bytes(b"\xff\xfe\x00bad")
        code2, out2 = run("brief", str(d))
        outs.append(code2 != 0 and "Traceback" not in out2 and "✗" in out2)
        return all(outs), "元数据校验 + 坏文件不崩"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def t_version():
    code, out = run("--version")
    return code == 0 and "ai-study" in out, "版本号可打印"


def t_branch():
    base = Path(tempfile.mkdtemp())
    try:
        parent = base / "FPGA"
        child = base / "HDL"
        run("init", str(parent), "--subject", "FPGA")
        run("init", str(child), "--subject", "Verilog")
        code1, _ = run("link", str(child), "--parent", str(parent), "--big", "大点 0")
        linked = code1 == 0 and (child / "00-学习档案.md").read_text(encoding="utf-8").count("| 上级档案") == 1
        run("link", str(child), "--parent", str(parent), "--big", "大点 0")
        idem = (child / "00-学习档案.md").read_text(encoding="utf-8").count("| 上级档案") == 1
        (child / "02-每日笔记").mkdir(exist_ok=True)
        (child / "02-每日笔记" / "记录01-2026-10-28-x.md").write_text(
            "# 记录 1\n\n**日期**：2026-10-28\n**第 N 次课**：1\n**类型**：正课\n"
            "**真实性**：真实\n\n**结果**：3 / 4\n", encoding="utf-8")
        rp = child / "01-学习路径.md"
        rp.write_text(rp.read_text(encoding="utf-8").replace("- [ ] ", "- [x] ", 1), encoding="utf-8")
        code2, _ = run("sync", str(child))
        ptext = (parent / "00-学习档案.md").read_text(encoding="utf-8")
        synced = code2 == 0 and "分支动态" in ptext and "HDL" in ptext
        _, out3 = run("branches", str(parent))
        return linked and idem and synced and ("HDL" in out3), "link / 幂等 / sync / branches"
    finally:
        shutil.rmtree(base, ignore_errors=True)


def t_merge():
    base = Path(tempfile.mkdtemp())
    try:
        parent = base / "P"
        child = base / "C"
        run("init", str(parent), "--subject", "P")
        run("init", str(child), "--subject", "C")
        run("link", str(child), "--parent", str(parent), "--big", "大点 0")
        (child / "02-每日笔记").mkdir(exist_ok=True)
        (child / "02-每日笔记" / "记录01-2026-10-26-a.md").write_text(
            "# 记录 1\n\n**日期**：2026-10-26\n**第 N 次课**：1\n**类型**：正课\n"
            "**真实性**：真实\n\n**结果**：3 / 4\n", encoding="utf-8")
        (child / "05-错题.md").write_text("# 错题本\n\n## Q-001 · x\n\n**错因**：概念不清\n", encoding="utf-8")
        dry_ok = "合并预览" in run("merge", str(child), "--dry-run")[1]
        code, out = run("merge", str(child))
        merged_rec = len(list((parent / "02-每日笔记").glob("记录*.md"))) == 1
        merged_wrong = (parent / "05-错题.md").exists()
        marked = "并入状态" in (child / "00-学习档案.md").read_text(encoding="utf-8")
        again = run("merge", str(child))[0] != 0
        return dry_ok and code == 0 and merged_rec and merged_wrong and marked and again, \
            "预览 / 记录与错题并入 / 子档案封存 / 拒绝重复合并"
    finally:
        shutil.rmtree(base, ignore_errors=True)


def t_placeholder():
    p = subprocess.run([PY, str(ROOT / "tools" / "check_placeholders.py"), str(ROOT / "ai-study")],
                       capture_output=True, text=True, encoding="utf-8")
    return p.returncode == 0, "源码无占位符残留"


def t_refs():
    p = subprocess.run([PY, str(ROOT / "tools" / "check_refs.py"), str(ROOT / "ai-study")],
                       capture_output=True, text=True, encoding="utf-8")
    return p.returncode == 0, "文档交叉引用无断链"


case("全新档案 lint 通过", t_clean)
case("演示档案 lint 通过", t_demo)
case("selftest 4/4", t_selftest)
case("次数 0 不进复习", t_untaught)
case("检查点可恢复", t_checkpoint)
case("复习间隔与逾期", t_interval)
case("压缩机制", t_compact)
case("模式字段", t_mode)
case("说明书齐全", t_manual)
case("图片工具", t_img)
case("坏输入不崩", t_robust)
case("版本号", t_version)
case("分支档案", t_branch)
case("分支合并", t_merge)
case("跨对话继承", t_resume)
case("无占位符残留", t_placeholder)
case("无断链", t_refs)

print("ai-study 回归测试\n")
for ok, name, detail in results:
    print(f"  {'✓' if ok else '✗'} {name}  —— {detail}")
bad = sum(1 for ok, _, _ in results if not ok)
print(f"\n{len(results) - bad}/{len(results)} 通过")
sys.exit(0 if bad == 0 else 1)
