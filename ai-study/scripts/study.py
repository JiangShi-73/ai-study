#!/usr/bin/env python3
"""ai-study 辅助脚本 v2

用法：
  python study.py init <学习目录> --subject 学科名 [--goal "一句话"]
  python study.py demo-init <演示目录> --subject 学科名 [--today YYYY-MM-DD]
  python study.py next-n <学习目录>
  python study.py review-list <学习目录> [--limit N] [--per-board 2] [--board 板块] [--all]
  python study.py index <学习目录>
  python study.py brief <学习目录>
  python study.py lint <学习目录> [--today YYYY-MM-DD]

设计底线：lint 必须能分辨"真发生过"和"编出来的"。
演示档案靠 front-matter 的 demo: true 声明自己是假的，真实档案里永远不许出现它。
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

KB_DIR = "04-知识库"
CUR_DIR = "_进行中"
CUR_FILE = "当前课.md"
BOARD_DIR = "03-板块笔记"
DAY_DIR = "02-每日笔记"
ARCHIVE = "00-学习档案.md"
ROADMAP = "01-学习路径.md"

HEADING_RE = re.compile(r"^##\s*知识点[：:]\s*(.+?)\s*$")
REC_FILE_RE = re.compile(r"^记录\s*(\d+)\s*-\s*(\d{4}-\d{2}-\d{2})\s*-\s*(.+?)\.md$")
KV_RE = re.compile(r"^\*\*([^*]+)\*\*\s*[：:]\s*(.*?)\s*$")
RESULT_RE = re.compile(r"^\*\*结果\*\*\s*[：:]\s*(.+?)\s*$", re.M)
FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)

STATUS_ALLOWED = {"🔴", "🟡", "🟢"}
REQUIRED_META = ("状态", "上次复习", "次数", "来源")
TODAY_PLACEHOLDER = "待观察"
MODES = ("教师", "伴学", "突击")


def die(msg: str) -> None:
    print(f"错误：{msg}", file=sys.stderr)
    sys.exit(2)


def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def parse_front_matter(text: str) -> dict:
    m = FRONT_RE.match(text)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def is_demo(root: Path) -> bool:
    ap = root / ARCHIVE
    if not ap.exists():
        return False
    return parse_front_matter(read_text(ap)).get("demo", "").lower() == "true"


def parse_kv_block(text: str, limit: int = 40) -> dict:
    """抓记录头部 **键**：值 行"""
    out = {}
    for line in text.splitlines()[:limit]:
        m = KV_RE.match(line.strip())
        if m:
            out[m.group(1).strip()] = m.group(2).strip()
    return out


def parse_meta_line(line: str):
    """解析知识点元数据行，容忍 4 段或 6 段。"""
    s = line.strip()
    if not s.startswith(">"):
        return None
    body = s[1:].strip()
    if "｜" not in body:
        return None
    out = {}
    for part in body.split("｜"):
        part = part.strip()
        if not part:
            continue
        bits = part.split(None, 1)
        if len(bits) == 2:
            out[bits[0]] = bits[1].strip()
        elif len(bits) == 1:
            out[bits[0]] = ""
    if not any(k in out for k in ("状态", "次数", "来源")):
        return None
    return out


INTERVALS = {1: 1, 2: 3, 3: 7, 4: 16}
INTERVAL_MAX = 35


def _interval_days(count: int, status: str):
    """按复习次数给建议间隔，再按状态微调。返回 None 表示还没讲过。"""
    if count <= 0:
        return None
    base = INTERVALS.get(count, INTERVAL_MAX)
    if status == "🔴":
        base = max(1, base // 2)
    elif status == "🟢":
        base = int(base * 1.5)
    return base


def _due(last: str, count: int, status: str):
    """返回 (建议日期, 逾期天数或 None)。"""
    if not last or last in ("—", "") or count <= 0:
        return None, None
    days = _interval_days(count, status)
    if days is None:
        return None, None
    try:
        d = dt.date.fromisoformat(last)
    except ValueError:
        return None, None
    due = d + dt.timedelta(days=days)
    overdue = (dt.date.today() - due).days
    return due, (overdue if overdue > 0 else None)


def collect_entries(root: Path):
    """[(板块, {name,status,last,count,solid,source,line}, 文件)]"""
    board_dir = root / BOARD_DIR
    if not board_dir.exists():
        return []
    entries = []
    for f in sorted(board_dir.glob("*.md")):
        board = f.stem
        cur = None
        for i, line in enumerate(read_text(f).splitlines()):
            m = HEADING_RE.match(line)
            if m:
                cur = {"name": m.group(1), "status": None, "line": i + 1}
                entries.append((board, cur, f))
                continue
            if cur is not None and cur.get("status") is None:
                meta = parse_meta_line(line)
                if meta is not None:
                    cur["status"] = meta.get("状态", "")
                    cur["last"] = meta.get("上次复习", "—")
                    try:
                        cur["count"] = int(meta.get("次数", "0") or 0)
                    except ValueError:
                        cur["count"] = 0
                    try:
                        cur["solid"] = int(meta.get("连对", "0") or 0)
                    except ValueError:
                        cur["solid"] = 0
                    cur["frozen"] = meta.get("固化", "—")
                    cur["source"] = meta.get("来源", "")
                    cur["raw"] = meta
    return entries


def collect_records(root: Path):
    """[(n, date, title, path, header)]"""
    day = root / DAY_DIR
    out = []
    if not day.exists():
        return out
    for f in sorted(day.glob("记录*.md")):
        m = REC_FILE_RE.match(f.name)
        if not m:
            out.append((None, None, f.stem, f, {}))
            continue
        text = read_text(f)
        out.append((int(m.group(1)), m.group(2), m.group(3), f, parse_kv_block(text)))
    out.sort(key=lambda x: (x[0] is None, x[0] or 0))
    return out


def fill_template(text: str, subject: str, today: dt.date) -> str:
    return (
        text.replace("{{学科}}", subject)
        .replace("{{名称}}", "待命名")
        .replace("{{日期}}", today.isoformat())
        .replace("{{七天后}}", (today + dt.timedelta(days=7)).isoformat())
    )


def make_skeleton(root: Path, subject: str, today: dt.date, demo: bool) -> None:
    tpl = Path(__file__).resolve().parent.parent / "templates"
    root.mkdir(parents=True, exist_ok=True)
    for d in (root / DAY_DIR, root / BOARD_DIR, root / KB_DIR / "资料", root / "assets"):
        d.mkdir(parents=True, exist_ok=True)

    banner = ""
    if demo:
        banner = (
            "---\n"
            "demo: true\n"
            f"基准日期: {today.isoformat()}\n"
            "学生: 虚构\n"
            "---\n\n"
            "> ⚠️ **这是一份演示档案，不是真实学习记录。**\n"
            "> 顶部的 front-matter 已声明 demo: true，所有日期都是虚构的，不得作为真实档案的起点。\n"
            "> 真实档案里出现 demo: true 会被 lint 判为污染。\n\n"
        )

    for rel, tplname in ((ARCHIVE, ARCHIVE), (ROADMAP, ROADMAP)):
        dst = root / rel
        if dst.exists():
            print(f"跳过（已存在）：{rel}")
            continue
        body = fill_template(read_text(tpl / tplname), subject, today)
        dst.write_text(banner + body if rel == ARCHIVE else body, encoding="utf-8")

    kb_src = tpl / "04-知识库-索引.md"
    kb_dst = root / KB_DIR / "索引.md"
    if kb_src.exists() and not kb_dst.exists():
        kb_dst.write_text(fill_template(read_text(kb_src), subject, today), encoding="utf-8")

    assets = root / "assets" / "README.md"
    if not assets.exists():
        assets.write_text(
            "# assets\n\n存放截图、波形、代码片段。命名：<记录号>-<用途>.png，例如 01-ltspice-传输特性.png\n",
            encoding="utf-8",
        )


def cmd_init(args) -> int:
    root = Path(args.dir).expanduser().resolve()
    make_skeleton(root, args.subject, dt.date.today(), demo=False)
    if args.goal:
        ap = root / ARCHIVE
        t = read_text(ap).replace("| 学到什么程度算完 | |", f"| 学到什么程度算完 | {args.goal} |")
        ap.write_text(t, encoding="utf-8")
    print(f"已初始化（真实档案）：{root}")
    return 0


def cmd_demo_init(args) -> int:
    root = Path(args.dir).expanduser().resolve()
    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    make_skeleton(root, args.subject, today, demo=True)
    print(f"已初始化（演示档案，已声明 demo: true）：{root}")
    return 0


def _next_n(root: Path) -> int:
    nums = []
    for n, date, title, f, h in collect_records(root):
        if n is None:
            continue
        typ = (h or {}).get("类型", "正课")
        if typ.startswith("正课"):
            nums.append(n)
    return (max(nums) + 1) if nums else 1


def cmd_next_n(args) -> int:
    print(_next_n(Path(args.dir).expanduser().resolve()))
    return 0


def cmd_review_list(args) -> int:
    root = Path(args.dir).expanduser().resolve()
    entries = collect_entries(root)
    if not entries:
        print(f"没有找到知识点。先建 {BOARD_DIR}/<主题>.md")
        return 1
    if args.board:
        entries = [e for e in entries if args.board in e[0]]
        if not entries:
            die(f"没有板块匹配「{args.board}」")

    frozen = [e for e in entries if e[1].get("status") == "🟢" and (e[1].get("frozen") or "—").startswith("✅")]
    # 次数 0 = 只备了课、还没讲过。复习是防遗忘，不是预习。
    untaught = [e for e in entries if (e[1].get("count") or 0) == 0]
    if not args.all:
        entries = [e for e in entries if e not in frozen and e not in untaught]

    def rank(v):
        return {"🔴": 0, "🟡": 1, "🟢": 2}.get(v, 0)

    def sort_key(e):
        cur = e[1]
        last = cur.get("last") or "—"
        last = "0000-00-00" if last in ("—", "", "None") else last
        _, overdue = _due(cur.get("last") or "", cur.get("count", 0), cur.get("status"))
        # 逾期越久越靠前；没逾期按状态、再按最久没复习
        return (0 if overdue else 1, -(overdue or 0), rank(cur.get("status")), last, cur.get("count", 0))

    entries.sort(key=sort_key)

    # 跨板块配额：同一板块最多 N 条
    limit = args.limit or 0
    per = args.per_board or 0
    picked = []
    seen = {}
    for e in entries:
        b = e[0]
        if per and seen.get(b, 0) >= per:
            continue
        picked.append(e)
        seen[b] = seen.get(b, 0) + 1
        if limit and len(picked) >= limit:
            break
    if not per and limit:
        picked = entries[:limit]

    n_overdue = sum(1 for e in picked if _due(e[1].get("last") or "", e[1].get("count", 0), e[1].get("status"))[1])
    print(f"可复习 {len(picked)} 条（逾期 {n_overdue} 条；排序：逾期优先 → 状态低 → 最久没复习）")
    if frozen and not args.all:
        print(f"（{len(frozen)} 条已固化，已移出货架；--all 可看）")
    if untaught and not args.all:
        print(f"（{len(untaught)} 条备而未学，次数 0——还没讲过，不进复习；--all 可看）")
    print()
    grouped = {}
    for board, cur, f in picked:
        grouped.setdefault(board, []).append((cur, f))
    for board, items in grouped.items():
        print(f"**{board}**")
        for cur, f in items:
            last = cur.get("last") or "—"
            due, overdue = _due(last, cur.get("count", 0), cur.get("status"))
            if overdue:
                tail = f"　⏰ 逾期 {overdue} 天（建议 {due.isoformat()}）"
            elif due:
                tail = f"　建议 {due.isoformat()}"
            else:
                tail = ""
            print(f"  - {cur['name']}　{cur.get('status') or '❓'}　上次 {last}　{cur.get('count', 0)} 次{tail}")
            print(f"      ({f.name}:{cur.get('line')})")
        print()
    return 0


BATCH_RE = re.compile(r"批次-(\d+)")


def _batches(root: Path):
    """已压缩的批次：[(批次号, 记录范围, 日期范围, 说明, 目录名)]"""
    out = []
    arch = root / DAY_DIR / "_归档"
    if not arch.exists():
        return out
    for d in sorted(arch.iterdir()):
        if not d.is_dir():
            continue
        s = d / "SUMMARY.md"
        if not s.exists():
            continue
        m = BATCH_RE.search(d.name)
        no = int(m.group(1)) if m else 0
        info = parse_kv_block(read_text(s), limit=20)
        out.append((no, info.get("记录范围", "?"), info.get("日期范围", "?"),
                    f"第 {no} 批（已压缩）", d.name))
    return sorted(out)


def cmd_index(args) -> int:
    root = Path(args.dir).expanduser().resolve()
    ap = root / ARCHIVE
    if not ap.exists():
        die(f"找不到 {ARCHIVE}")
    rows = []
    for n, date, title, f, header in collect_records(root):
        if n is None:
            continue
        m = RESULT_RE.search(read_text(f))
        typ = (header or {}).get("类型", "正课")
        rows.append(f"| {n} | {date} | {title} | {m.group(1) if m else '—'} | {typ} | {DAY_DIR}/{f.name} |")
    batch_rows = [
        f"| {rng} | {dates} | {note} | — | — | {DAY_DIR}/_归档/{dirname}/ |"
        for _, rng, dates, note, dirname in _batches(root)
    ]
    text = read_text(ap)
    block = ("<!-- index:begin -->\n| # | 日期 | 标题 | 结果 | 类型 | 文件 |\n|---|---|---|---|---|---|\n"
             + ("\n".join(batch_rows) + "\n" if batch_rows else "")
             + ("\n".join(rows) + "\n" if rows else "") + "<!-- index:end -->")
    new = re.sub(r"<!-- index:begin -->.*?<!-- index:end -->", lambda _: block, text, flags=re.S)
    ap.write_text(new, encoding="utf-8")
    print(f"索引已更新：{len(rows)} 条" if new != text else "索引无变化")
    return 0


def cmd_brief(args) -> int:
    root = Path(args.dir).expanduser().resolve()
    ap = root / ARCHIVE
    if not ap.exists():
        die(f"找不到 {ARCHIVE}")
    board = {}
    for line in read_text(ap).splitlines():
        m = re.match(r"^\|\s*\*{0,2}([^|]+?)\*{0,2}\s*\|\s*(.*?)\s*\|\s*$", line)
        if m and not set(m.group(1)) <= set("-: "):
            board[m.group(1).strip()] = m.group(2).strip()
    n = _next_n(root)
    cur = _parse_cur(root)
    if cur:
        info = cur["info"]
        print("⚠️  有一节没归档的课")
        print(f"   {info.get('日期', '?')} · 第 {info.get('第 N 次课', '?')} 次课 · "
              f"停在 {info.get('当前步骤', '?')}")
        print(f"   最后更新 {info.get('最后更新', '?')}")
        print(f"   先问学生：接着上，还是重新开始？")
        print("")

    print(f"今天 {dt.date.today().isoformat()} · 第 {n} 次课" + ("（演示档案）" if is_demo(root) else ""))
    print("")
    for key in ("模式", "当前大点", "计划位置", "实际位置", "进度判断", "决策权重", "错题待重考",
                "上次暴露的薄弱点", "学生画像版本", "画像下次自动更新", "画像最后核对", "苏格拉底档位", "基线来源"):
        if key in board:
            print(f"  {key}：{board[key]}")
    entries = collect_entries(root)
    print(f"  可复习知识点：{len(entries)} 条")
    print("")
    print("下一步：daily.md §1 开课——报日期、报状态、报进度判断，再问学生今天做什么。")
    return 0


def cmd_lint(args) -> int:
    root = Path(args.dir).expanduser().resolve()
    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    demo = is_demo(root)
    errors, warns = [], []

    if not (root / ARCHIVE).exists():
        die(f"缺少 {ARCHIVE}")
    if not (root / ROADMAP).exists():
        errors.append(f"缺少 {ROADMAP}")

    for rel in (ARCHIVE, ROADMAP):
        p = root / rel
        if not p.exists():
            continue
        t = read_text(p)
        if "待填" in t:
            errors.append(f"{rel} 出现「待填」（合法占位只允许「{TODAY_PLACEHOLDER}（…）」）")

    records = collect_records(root)
    nums, dates = [], {}
    for n, date, title, f, h in records:
        rel = f"{DAY_DIR}/{f.name}"
        if n is None:
            errors.append(f"{rel} 文件名不合规，应为 记录NN-YYYY-MM-DD-标题.md")
            continue
        nums.append(n)
        dates[n] = date

        typ = (h.get("类型") or "").strip()
        truth = (h.get("真实性") or "").strip()
        raw_date = (h.get("日期") or "").strip()
        dm = re.search(r"\d{4}-\d{2}-\d{2}", raw_date)
        body_date = dm.group(0) if dm else ""
        body_txt = read_text(f)[:1200]
        nm = re.search(r"第\s*(\d+)\s*次课", body_txt)
        body_n = nm.group(1) if nm else ""

        if not typ:
            errors.append(f"{rel} 缺「类型」字段（正课/复习/演示）")
        if not truth:
            errors.append(f"{rel} 缺「真实性」字段（真实/演示）")
        if body_date and body_date != date:
            errors.append(f"{rel} 文件名日期 {date} ≠ 正文日期 {body_date}")
        if body_n and body_n != str(n):
            errors.append(f"{rel} 文件名编号 {n} ≠ 正文编号 {body_n}")

        try:
            d = dt.date.fromisoformat(date)
        except ValueError:
            errors.append(f"{rel} 日期无法解析：{date}")
            d = None
        if d and d > today:
            errors.append(f"{rel} 记录日期 {date} 晚于今天（{today}）——预支未来")
        if d and not demo and not args.allow_backdate:
            created = dt.datetime.fromtimestamp(os.stat(f).st_ctime).date()
            if d < created - dt.timedelta(days=2):
                errors.append(
                    f"{rel} 声称 {date} 上过课，但文件本身是 {created} 创建的——"
                    f"倒填历史（若确属迁移旧档案，加 --allow-backdate）")

        if truth.startswith("演示"):
            if not parse_front_matter(read_text(f)).get("demo") and not demo:
                errors.append(f"{rel} 声明「演示」但没有 demo: true front-matter")

    if nums:
        dup = {x for x in nums if nums.count(x) > 1}
        if dup:
            errors.append(f"记录编号重复：{sorted(dup)}")

    # 索引一致性
    ap = root / ARCHIVE
    text = read_text(ap)
    idx = re.findall(r"^\|\s*(\d+)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|", text, re.M)
    idx_map = {int(a): (b.strip(), d.strip()) for a, b, c, d in idx}
    missing_idx = set(nums) - set(idx_map)
    if missing_idx:
        errors.append(f"索引缺行：记录 {sorted(missing_idx)}（跑 index 修）")
    for n, date, title, f, h in records:
        if n is None or n not in idx_map:
            continue
        i_date, i_res = idx_map[n]
        m = RESULT_RE.search(read_text(f))
        body_res = m.group(1) if m else "—"
        if i_res != body_res:
            errors.append(f"记录 {n}：索引结果「{i_res}」≠ 正文结果「{body_res}」（跑 index 修）")
        if i_date != date:
            errors.append(f"记录 {n}：索引日期「{i_date}」≠ 文件名日期「{date}」")

    # 看板「最近一次记录」 vs 索引最后一行
    m = re.search(r"^\|\s*\**最近一次记录\**\s*\|\s*(.*?)\s*\|\s*$", text, re.M)
    if m and idx_map and nums:
        last_n = max(idx_map)
        claimed = m.group(1)
        got = re.search(r"记录\s*(\d+)", claimed)
        if got and int(got.group(1)) != last_n:
            errors.append(f"看板「最近一次记录」写的是记录 {got.group(1)}，索引最后一条是记录 {last_n}")

    # 画像：版本日期、日志一致性、逾期（profile.md §2/§4/§8）
    ver = re.search(r"^\|\s*\**学生画像版本\**\s*\|\s*(.*?)\s*\|\s*$", text, re.M)
    due = re.search(r"^\|\s*\**画像下次自动更新\**\s*\|\s*(.*?)\s*\|\s*$", text, re.M)
    logs = [int(x) for x in re.findall(r"^####\s*v(\d+)", text, re.M)]
    if ver:
        vm = re.search(r"v(\d+)", ver.group(1))
        vd = re.search(r"(\d{4}-\d{2}-\d{2})", ver.group(1))
        if not vm:
            errors.append("看板「学生画像版本」缺版本号（应形如 v1 · 2026-10-22）")
        elif logs and vm and int(vm.group(1)) > max(logs):
            errors.append(
                f"看板写着 v{vm.group(1)}，但变更日志只到 v{max(logs)}——"
                f"改了版本号却没写日志（profile.md §5：日志只追加，快照可重写）")
        if vd:
            try:
                d = dt.date.fromisoformat(vd.group(1))
                if d > today:
                    errors.append(f"学生画像版本日期 {vd.group(1)} 晚于今天——预支")
            except ValueError:
                pass
    if due and not demo:
        dm = re.search(r"(\d{4}-\d{2}-\d{2})", due.group(1))
        if dm:
            try:
                d = dt.date.fromisoformat(dm.group(1))
                if d < today:
                    warns.append(
                        f"画像逾期 {(today - d).days} 天（下次自动更新 {dm.group(1)}）——"
                        f"开课前按 profile.md T1 补一版")
            except ValueError:
                warns.append(f"看板「画像下次自动更新」不是日期：{due.group(1)}")

    # 进行中的课：超过 24 小时没动 → 多半忘了归档
    cur = _parse_cur(root)
    if cur:
        lu = cur["info"].get("最后更新", "")
        try:
            t = dt.datetime.strptime(lu.strip(), "%Y-%m-%d %H:%M")
            if (dt.datetime.now() - t).total_seconds() > 24 * 3600:
                warns.append(
                    f"「{CUR_DIR}/{CUR_FILE}」停在 {lu}，超过 24 小时没动——"
                    f"这节课多半忘了归档（checkpoint --clear 前先写记录）")
        except ValueError:
            warns.append(f"「{CUR_DIR}/{CUR_FILE}」的最后更新时间无法解析：{lu}")

    # 引用的图片必须存在（visuals.md §5）
    for sub in (DAY_DIR, BOARD_DIR):
        d = root / sub
        if not d.exists():
            continue
        for f in d.glob("*.md"):
            for m in re.finditer(r"!\[[^\]]*\]\(([^)\s]+)\)", read_text(f)):
                target = m.group(1)
                if target.startswith(("http://", "https://")):
                    continue
                if not (f.parent / target).exists() and not (root / target).exists():
                    errors.append(f"{sub}/{f.name} 引用的图不存在：{target}")

    # 知识库一致性
    kb_index = root / KB_DIR / "索引.md"
    kb_ids = {}
    if kb_index.exists():
        anchors_unprocessed = 0
        for line in read_text(kb_index).splitlines():
            m = re.match(r"^\|\s*(KB\d+)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|", line)
            if not m:
                continue
            kid, name, typ, role, use, cover, avail, st = (x.strip() for x in m.groups())
            if kid in kb_ids:
                errors.append(f"{KB_DIR}/索引.md 编号重复：{kid}")
            kb_ids[kid] = {"name": name, "role": role, "status": st}
            if name and role.startswith("锚点") and not st.startswith("✅"):
                anchors_unprocessed += 1
        if anchors_unprocessed:
            warns.append(
                f"知识库有 {anchors_unprocessed} 条锚点资料还没处理到 ✅——"
                f"大点的「学什么」会写不出来（knowledge-base.md §5）")

        rp_html = read_text(root / ROADMAP) if (root / ROADMAP).exists() else ""
        for kid in sorted(set(re.findall(r"\bKB\d+\b", rp_html))):
            if kid not in kb_ids:
                errors.append(f"{ROADMAP} 引用了 {kid}，但知识库里没有这条")

    # 大点的「学什么」不能是空表
    rp2 = root / ROADMAP
    if rp2.exists():
        txt = read_text(rp2)
        for sec in re.split(r"(?=^###\s*大点)", txt, flags=re.M):
            hm = re.match(r"###\s*(大点\s*\d+[^\n]*)", sec)
            if not hm:
                continue
            head = hm.group(1).strip()
            if "待命名" in head:
                continue
            if "| |" in sec and "内容" in sec:
                warns.append(f"{ROADMAP}「{head}」的「学什么」表还是空的")

    # 模式必须是已知值之一（references/modes/README.md §4）
    md = re.search(r"^\|\s*\**模式\**\s*\|\s*(.*?)\s*\|\s*$", text, re.M)
    if md:
        mv = md.group(1).strip()
        if mv and not any(mv.startswith(m) for m in MODES + (TODAY_PLACEHOLDER,)):
            errors.append(f"契约「模式」取值非法：{mv}（只允许 {' / '.join(MODES)}）")
    elif not demo:
        warns.append("契约没有「模式」一行——按旧版档案处理，默认教师模式（跑 migrate 补上）")

    # 考核频率必须是三个可执行值之一（daily.md §5.1 靠它分支）
    kx = re.search(r"^\|\s*\**考核频率\**\s*\|\s*(.*?)\s*\|\s*$", text, re.M)
    if kx:
        kv = kx.group(1).strip()
        if kv and not any(kv.startswith(p) for p in ("每次课", "大点验收", "不要", TODAY_PLACEHOLDER)):
            errors.append(f"契约「考核频率」取值非法：{kv}（只允许 每次课 / 大点验收 / 不要）")

    # 上完课没核对画像（profile.md T0）
    hb = re.search(r"^\|\s*\**画像最后核对\**\s*\|\s*(.*?)\s*\|\s*$", text, re.M)
    if hb and dates and not demo:
        hm = re.search(r"(\d{4}-\d{2}-\d{2})", hb.group(1))
        if not hm:
            warns.append("看板「画像最后核对」不是日期")
        else:
            try:
                hd = dt.date.fromisoformat(hm.group(1))
                valid = []
                for d in dates.values():
                    try:
                        valid.append(dt.date.fromisoformat(d))
                    except ValueError:
                        pass
                if valid and max(valid) > hd:
                    warns.append(
                        f"最后一次记录（{max(valid)}）晚于「画像最后核对」（{hm.group(1)}）——"
                        f"上完课没核对画像（profile.md T0）")
            except ValueError:
                warns.append("看板「画像最后核对」日期无法解析")

    # 勾选数 vs 看板实际位置（仅警告）
    cur_big = re.search(r"^\|\s*\**当前大点\**\s*\|\s*(.*?)\s*\|\s*$", text, re.M)
    pos = re.search(r"^\|\s*\**实际位置\**\s*\|\s*(.*?)\s*\|\s*$", text, re.M)
    rp = root / ROADMAP
    if cur_big and pos and rp.exists():
        bm = re.search(r"(大点\s*\d+)", cur_big.group(1))
        pm = re.search(r"(\d+)\s*/\s*(\d+)", pos.group(1))
        if bm and pm:
            body = read_text(rp)
            sec = re.search(r"###\s*" + re.escape(bm.group(1)) + r".*?(?=\n###\s*大点|\Z)", body, re.S)
            if sec:
                done = len(re.findall(r"^-\s*\[x\]", sec.group(0), re.M))
                total = len(re.findall(r"^-\s*\[[ x]\]", sec.group(0), re.M))
                claim = int(pm.group(1))
                if total and done != claim:
                    warns.append(
                        f"{ROADMAP} 的「{bm.group(1)}」已勾选 {done}/{total}，"
                        f"但看板「实际位置」写着 {pm.group(1)}/{pm.group(2)}")

    # 基线可追溯（P0-3）
    base = re.search(r"^\|\s*\**现在水平基线\**\s*\|\s*(.*?)\s*\|\s*$", text, re.M)
    src = re.search(r"^\|\s*\**基线来源\**\s*\|\s*(.*?)\s*\|\s*$", text, re.M)
    if base and base.group(1).strip() and not base.group(1).strip().startswith(TODAY_PLACEHOLDER) and not demo:
        src_val = (src.group(1).strip() if src else "")
        if not src_val:
            errors.append("契约有「现在水平基线」但缺「基线来源」——基线必须是考出来的")
        elif not src_val.startswith(TODAY_PLACEHOLDER):
            has00 = any(r[0] == 0 for r in records)
            if not has00:
                errors.append("基线来源声称来自「记录00（定位访谈）」，但 02-每日笔记/ 里没有记录00")

    # 知识点
    for board, cur, f in collect_entries(root):
        rel = f"{BOARD_DIR}/{f.name}:{cur.get('line')}"
        if cur.get("status") is None:
            errors.append(f"{rel} 知识点「{cur['name']}」缺元数据行")
            continue
        if cur["status"] not in STATUS_ALLOWED:
            errors.append(f"{rel} 状态非法：{cur['status']}（只允许 🔴/🟡/🟢）")
        miss = [k for k in REQUIRED_META if k not in (cur.get("raw") or {})]
        if miss:
            errors.append(f"{rel} 元数据缺字段：{'、'.join(miss)}")
        src_v = (cur.get("source") or "").strip()
        # 来源可以是「记录 N」（教师/突击）或「错题 Q-00N」（伴学/突击），或 —（无来源）
        if "错题" in src_v:
            qn = re.search(r"Q-?(\d+)", src_v)
            wrong_book = root / "05-错题.md"
            if qn:
                want = f"Q-{int(qn.group(1)):03d}"
                if not wrong_book.exists():
                    errors.append(f"{rel} 来源写了 {want}，但没有 05-错题.md")
                elif want not in read_text(wrong_book):
                    errors.append(f"{rel}「来源 {want}」不存在")
            elif not wrong_book.exists():
                errors.append(f"{rel} 来源写了错题，但没有 05-错题.md")
        elif "记录" in src_v:
            sn = re.search(r"(\d+)", src_v)
            if sn and int(sn.group(1)) > 0 and int(sn.group(1)) not in nums:
                errors.append(f"{rel}「来源 记录 {sn.group(1)}」不存在")
        last = (cur.get("last") or "—").strip()
        if last not in ("—", "") and not demo:
            try:
                d = dt.date.fromisoformat(last)
                if d > today:
                    errors.append(f"{rel} 上次复习 {last} 晚于今天——预支复习")
                elif not args.allow_backdate:
                    created = dt.datetime.fromtimestamp(os.stat(f).st_ctime).date()
                    if d < created - dt.timedelta(days=2):
                        errors.append(
                            f"{rel} 上次复习写着 {last}，但板块笔记是 {created} 才建的——预支复习")
            except ValueError:
                warns.append(f"{rel} 上次复习不是日期也不是「—」：{last}")

    # 演示污染
    if not demo and re.search(r"demo:\s*true", text):
        errors.append("真实档案里出现 demo: true（演示档案必须放在 示例/_demo/ 下）")

    title = "演示档案" if demo else "真实档案"
    if not errors and not warns:
        print(f"体检通过（{title}）：没有发现问题。")
        return 0
    print(f"体检结果（{title}）：错误 {len(errors)} / 警告 {len(warns)}\n")
    for e in errors:
        print(f"  ✗ {e}")
    for w in warns:
        print(f"  ! {w}")
    return 1 if errors else 0




def _cur_path(root: Path) -> Path:
    return root / CUR_DIR / CUR_FILE


def _parse_cur(root: Path):
    f = _cur_path(root)
    if not f.exists():
        return None
    text = read_text(f)
    info = parse_kv_block(text, limit=15)
    return {"path": f, "text": text, "info": info}




def cmd_projects(args) -> int:
    """列出根目录下所有学习计划（一个计划一个文件夹）。"""
    root = Path(args.dir).expanduser().resolve()
    if not root.exists():
        die(f"目录不存在：{root}")
    plans = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        ap = d / ARCHIVE
        if not ap.exists():
            continue
        board = {}
        for line in read_text(ap).splitlines():
            m = re.match(r"^\|\s*\**([^|]+?)\**\s*\|\s*(.*?)\s*\|\s*$", line)
            if m and not set(m.group(1)) <= set("-: "):
                board[m.group(1).strip()] = m.group(2).strip()
        recs = [r for r in collect_records(d) if r[0] is not None and r[0] >= 1]
        last = max((r[1] for r in recs), default="—")
        plans.append({
            "name": d.name,
            "big": board.get("当前大点", "—"),
            "pos": board.get("实际位置", "—"),
            "pace": board.get("进度判断", "—"),
            "n": len(recs),
            "last": last,
            "demo": is_demo(d),
        })

    if not plans:
        print(f"{root} 下没有找到学习计划（需要 <计划>/00-学习档案.md）")
        return 0

    print(f"{root} 下共 {len(plans)} 个学习计划\n")
    print(f"  {'计划':<12} {'记录':>4}  {'最后上课':<12} 当前大点")
    for x in plans:
        flag = " (演示)" if x["demo"] else ""
        print(f"  {x['name']:<12} {x['n']:>4}  {x['last']:<12} {x['big']}{flag}")

    if args.write:
        lines = ["# 学习计划索引", "",
                 "> 一个计划一个文件夹。这份表由 scripts/study.py projects --write 生成。", "",
                 "| 计划 | 记录数 | 最后上课 | 当前大点 | 实际位置 | 进度 |",
                 "|---|---|---|---|---|---|"]
        for x in plans:
            lines.append(f"| {x['name']} | {x['n']} | {x['last']} | {x['big']} | {x['pos']} | {x['pace']} |")
        out = root / "索引.md"
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\n已写入 {out}")
    return 0


def cmd_compact(args) -> int:
    """压缩：最近 N 条保持完整；满了就把最远的 N 条移进 _归档，留一份总结。"""
    root = Path(args.dir).expanduser().resolve()
    if not (root / ARCHIVE).exists():
        die(f"找不到 {ARCHIVE}")
    keep, trigger = args.keep, args.trigger
    recs = [r for r in collect_records(root) if r[0] is not None]
    total = len(recs)

    print(f"当前记录 {total} 条（保留 {keep} 条完整，满 {trigger} 条触发）")
    if total < trigger and not args.force:
        print(f"还没到 {trigger} 条，不用压缩。要强制加 --force。")
        return 0

    batch = recs[:keep]
    if not batch:
        print("没有可压缩的记录。")
        return 0

    arch = root / DAY_DIR / "_归档"
    arch.mkdir(parents=True, exist_ok=True)
    nums_existing = []
    for d in arch.iterdir():
        if d.is_dir():
            m = BATCH_RE.search(d.name)
            if m:
                nums_existing.append(int(m.group(1)))
    no = (max(nums_existing) + 1) if nums_existing else 1
    dest = arch / f"批次-{no:02d}"

    nums = [r[0] for r in batch]
    dates = [r[1] for r in batch]
    rng = f"{min(nums)}–{max(nums)}"
    dr = f"{min(dates)} ~ {max(dates)}"

    if args.dry_run:
        print(f"[dry-run] 会把记录 {rng}（{dr}）移到 {DAY_DIR}/_归档/批次-{no:02d}/")
        return 0

    dest.mkdir(parents=True, exist_ok=True)
    for n, date, title, f, h in batch:
        f.rename(dest / f.name)

    big, got, tot, res = {}, 0, 0, []
    for n, date, title, f, h in batch:
        b = (h or {}).get("所属大点", "").strip()
        if b:
            big[b] = big.get(b, 0) + 1
        m = RESULT_RE.search(read_text(dest / f.name))
        if m:
            r2 = re.search(r"(\d+)\s*/\s*(\d+)", m.group(1))
            if r2:
                got += int(r2.group(1)); tot += int(r2.group(2))
                res.append((n, int(r2.group(1)), int(r2.group(2)), title))

    worst = sorted([x for x in res if x[2] and x[1] / x[2] <= 0.5], key=lambda x: x[1] / x[2])[:3]

    lines = [
        f"# 批次 {no:02d} · 记录 {rng}（已压缩）", "",
        f"**批次**：{no:02d}", f"**记录范围**：{rng}", f"**日期范围**：{dr}",
        f"**条数**：{len(batch)}", "", "## 统计（自动生成，未推断）", "",
        "- 涉及大点：" + ("、".join(f"{k}（{v}）" for k, v in big.items()) or "记录未填"),
    ]
    if tot:
        lines.append(f"- 考核合计：{tot} 题，答对 {got}，正确率 {got / tot * 100:.0f}%")
    else:
        lines.append("- 考核合计：这些记录没有填写结果")
    if worst:
        lines.append("- 正确率最低的：" + "、".join(
            f"记录 {n}（{a}/{b}，{t}）" for n, a, b, t in worst))
    lines += [
        "", "## 综述（AI 填，3–5 行）", "",
        "> 只写上面统计能支撑的结论。没证据就写「无」。", "",
        "- 反复出现的薄弱点：", "- 已经消化掉的：", "- 还欠着的：", "",
        "## 原始文件", "",
        f"本目录下的 {len(batch)} 个记录文件，一字未改。",
    ]
    (dest / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    cmd_index(argparse.Namespace(dir=str(root)))
    print(f"已压缩：记录 {rng} → {DAY_DIR}/_归档/批次-{no:02d}/（{len(batch)} 个文件，原样保留）")
    print(f"  索引换成一行：{rng} · {dr}")
    print(f"  总结已生成：{DAY_DIR}/_归档/批次-{no:02d}/SUMMARY.md（统计自动算，「综述」留给 AI 填）")
    return 0


def cmd_checkpoint(args) -> int:
    """记录/更新「进行中的课」。归档完成后用 --clear 清掉。"""
    root = Path(args.dir).expanduser().resolve()
    f = _cur_path(root)
    now = dt.datetime.now()
    stamp = now.strftime("%H:%M")
    today = now.date().isoformat()

    if args.clear:
        if f.exists():
            f.unlink()
            print("已清除「进行中的课」——这节课归档完了。")
        else:
            print("没有进行中的课。")
        return 0

    f.parent.mkdir(parents=True, exist_ok=True)
    if not f.exists():
        if args.step is None:
            die("第一次记录需要 --step（例：--step \"⑤ 讲授\"）")
        body = (
            f"# 进行中的课\n\n"
            f"> 这节课**还没归档**。每走完一步更新一次。归档完成后删掉这个文件"
            f"（checkpoint --clear）。\n\n"
            f"**日期**：{today}\n"
            f"**第 N 次课**：{args.n or '?'}\n"
            f"**所属大点**：{args.big or '?'}\n"
            f"**当前步骤**：{args.step}\n"
            f"**开始**：{stamp}\n"
            f"**最后更新**：{today} {stamp}\n\n---\n\n"
            f"## 进度\n\n- {stamp} {args.step}"
            + (f" —— {args.note}" if args.note else "") + "\n\n## 待续\n\n- \n"
        )
        f.write_text(body, encoding="utf-8")
        print(f"已开始记录：{args.step}")
        return 0

    text = read_text(f)
    if args.step:
        text = re.sub(r"^\*\*当前步骤\*\*：.*$", f"**当前步骤**：{args.step}", text, flags=re.M)
        text = re.sub(r"^\*\*最后更新\*\*：.*$", f"**最后更新**：{today} {stamp}", text, flags=re.M)
        line = f"- {stamp} {args.step}" + (f" —— {args.note}" if args.note else "")
        text = text.replace("\n## 待续", f"{line}\n\n## 待续", 1)
    f.write_text(text, encoding="utf-8")
    print(f"已更新：{args.step or '（无变化）'}")
    return 0


def cmd_selftest(args) -> int:
    """造 4 条违法档案，验证 lint 真的能抓到。检查器自己也要被检查。"""
    import shutil
    import subprocess
    import tempfile

    today = dt.date.today()
    back = (today - dt.timedelta(days=17)).isoformat()
    root = Path(tempfile.mkdtemp(prefix="aistudy-selftest-"))
    make_skeleton(root, "自检", today, demo=False)

    def rec(n, date, title, result, extra=""):
        f = root / DAY_DIR / f"记录{n:02d}-{date}-{title}.md"
        f.write_text(
            f"# 记录 {n} · {title}\n\n"
            f"**日期**：{date}\n**第 N 次课**：{n}\n**类型**：正课\n**真实性**：真实\n"
            f"**所属大点**：大点 0\n**本节状态**：✅ 已完成\n\n**结果**：{result}\n{extra}",
            encoding="utf-8")

    # ① 倒填历史：声称 17 天前上过课，文件却是今天建的
    rec(1, back, "倒填出来的课", "1 / 4")
    # ② 预支复习：板块笔记今天才建，却写着很久以前复习过
    (root / BOARD_DIR / "自检板块.md").write_text(
        "# 板块：自检\n\n## 知识点：预支复习的那条\n\n"
        f"> 状态 🟡 ｜ 上次复习 {back} ｜ 次数 2 ｜ 连对 1 ｜ 固化 — ｜ 来源 记录 1\n\n"
        "**一句话**：故意写成很久以前复习过。\n", encoding="utf-8")

    # 先让 index 写出正确行，再手改一处，造出「索引 ≠ 正文」
    subprocess.run([sys.executable, __file__, "index", str(root)],
                   capture_output=True, text=True, encoding="utf-8")
    ap = root / ARCHIVE
    t = ap.read_text(encoding="utf-8")
    t = t.replace("| 1 | %s | 倒填出来的课 | 1 / 4 |" % back,
                  "| 1 | %s | 倒填出来的课 | 4 / 4 |" % back)
    # ④ 版本号 v7，但变更日志只到 v1
    t = t.replace("| 学生画像版本 | v1 ·", "| 学生画像版本 | v7 ·")
    ap.write_text(t, encoding="utf-8")

    proc = subprocess.run([sys.executable, __file__, "lint", str(root)],
                          capture_output=True, text=True, encoding="utf-8")
    out = (proc.stdout or "") + (proc.stderr or "")

    cases = [
        ("倒填历史（声称过去上过课）", "倒填历史"),
        ("预支复习（笔记未建就已在复习）", "预支复习"),
        ("索引结果 ≠ 正文结果", "索引结果"),
        ("版本号超前于变更日志", "变更日志只到"),
    ]
    print("自检：造 4 条违法档案，看 lint 抓不抓得到\n")
    ok = 0
    for name, keyword in cases:
        hit = keyword in out
        ok += 1 if hit else 0
        print(f"  {'✓' if hit else '✗'} {name} —— {'抓到' if hit else '没抓到'}")

    print(f"\n{ok}/{len(cases)} 条被抓到" + ("，检查器可信。" if ok == len(cases) else "，检查器有漏！"))
    if not args.keep:
        shutil.rmtree(root, ignore_errors=True)
    else:
        print(f"现场保留在：{root}")
    return 0 if ok == len(cases) else 1


def cmd_migrate(args) -> int:
    """把旧结构档案升级到当前结构：只做能确定的事，改不动的列成待办。"""
    root = Path(args.dir).expanduser().resolve()
    if not (root / ARCHIVE).exists():
        die(f"找不到 {ARCHIVE}")
    today = dt.date.today()
    tpl = Path(__file__).resolve().parent.parent / "templates"
    changes, manual = [], []

    # ① 补 04-知识库
    kb = root / KB_DIR / "索引.md"
    if not kb.exists():
        kb.parent.mkdir(parents=True, exist_ok=True)
        (root / KB_DIR / "资料").mkdir(exist_ok=True)
        src = tpl / "04-知识库-索引.md"
        kb.write_text(fill_template(read_text(src), root.name, today), encoding="utf-8")
        changes.append(f"新建 {KB_DIR}/索引.md（KB01–03 为空，需按实际资料填）")

    # ② 看板补字段
    ap = root / ARCHIVE
    text = read_text(ap)
    board_defaults = [
        ("模式", "教师"),
        ("决策权重", "共同（学生主导 / 共同 / AI 主导）"),
        ("画像最后核对", today.isoformat()),
        ("基线来源", f"{TODAY_PLACEHOLDER}（第 1 次课补齐）"),
    ]
    for key, val in board_defaults:
        if not re.search(r"^\|\s*\**" + re.escape(key) + r"\**\s*\|", text, re.M):
            text = re.sub(r"(^\|\s*\**决策权重.*$|^\|\s*\**苏格拉底档位.*$)",
                          lambda m: m.group(0) + f"\n| {key} | {val} |", text, count=1, flags=re.M) \
                if key != "决策权重" else text
            if key != "决策权重" and f"| {key} |" not in text:
                text += ""
                changes.append(f"看板缺「{key}」——请手工补一行")
            elif key != "决策权重":
                changes.append(f"看板补「{key}」")
    ap.write_text(text, encoding="utf-8")

    # ③ 记录补 类型 / 真实性
    for n, date, title, f, h in collect_records(root):
        if n is None:
            continue
        body = read_text(f)
        if "**类型**" in body and "**真实性**" in body:
            continue
        lines = body.split("\n")
        idx = next((i for i, l in enumerate(lines) if l.startswith("**日期**")), None)
        if idx is None:
            manual.append(f"{f.name} 找不到日期行，需手工补类型/真实性")
            continue
        is_review = "复习" in title
        lines.insert(idx + 1, f"**类型**：{'复习' if is_review else '正课'}\n**真实性**：真实")
        f.write_text("\n".join(lines), encoding="utf-8")
        changes.append(f"{f.name} 补「类型/真实性」")

    # ④ 重建索引
    cmd_index(argparse.Namespace(dir=str(root)))

    # ⑤ 改不动的
    rp = root / ROADMAP
    if rp.exists():
        rt = read_text(rp)
        if "资源锚点" in rt and "知识库编号" not in rt:
            manual.append("01 的「资源锚点」表还是旧格式——需手工改成引用 KB 编号"
                          "（把资料详情搬进 04-知识库/索引.md）")

    print(f"迁移 {root}")
    for c in changes:
        print(f"  ✓ {c}")
    if manual:
        print("\n需要手工处理的：")
        for m in manual:
            print(f"  ! {m}")
    print("\n跑一次 lint 确认：" + f"python {sys.argv[0]} lint \"{root}\"")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="study.py", description="ai-study 辅助脚本 v2")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="初始化真实档案")
    p.add_argument("dir"); p.add_argument("--subject", required=True); p.add_argument("--goal", default="")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("demo-init", help="初始化演示档案（自动声明 demo: true）")
    p.add_argument("dir"); p.add_argument("--subject", required=True); p.add_argument("--today", default="")
    p.set_defaults(func=cmd_demo_init)

    p = sub.add_parser("next-n", help="下一次正课的编号")
    p.add_argument("dir"); p.set_defaults(func=cmd_next_n)

    p = sub.add_parser("review-list", help="派生复习清单")
    p.add_argument("dir"); p.add_argument("--limit", type=int, default=0)
    p.add_argument("--per-board", type=int, default=2)
    p.add_argument("--board", default=""); p.add_argument("--all", action="store_true")
    p.set_defaults(func=cmd_review_list)

    p = sub.add_parser("index", help="重建记录索引")
    p.add_argument("dir"); p.set_defaults(func=cmd_index)

    p = sub.add_parser("brief", help="开课卡片")
    p.add_argument("dir"); p.set_defaults(func=cmd_brief)

    p = sub.add_parser("projects", help="列出所有学习计划（一个计划一个文件夹）")
    p.add_argument("dir", help="计划所在的根目录，如 ~/学习档案")
    p.add_argument("--write", action="store_true", help="写一份 索引.md 到该目录")
    p.set_defaults(func=cmd_projects)

    p = sub.add_parser("compact", help="压缩：满 N 条时把最远的若干条移进 _归档并留总结")
    p.add_argument("dir")
    p.add_argument("--keep", type=int, default=40, help="保留多少条完整（默认 40）")
    p.add_argument("--trigger", type=int, default=80, help="满多少条触发（默认 80）")
    p.add_argument("--force", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_compact)

    p = sub.add_parser("checkpoint", help="记录/更新「进行中的课」检查点")
    p.add_argument("dir")
    p.add_argument("--step", default=None, help="例：\"⑤ 讲授\"")
    p.add_argument("--note", default="")
    p.add_argument("--n", default="", help="第 N 次课")
    p.add_argument("--big", default="", help="所属大点")
    p.add_argument("--clear", action="store_true", help="归档完成后清除")
    p.set_defaults(func=cmd_checkpoint)

    p = sub.add_parser("selftest", help="自检：造违法档案，验证 lint 抓不抓得到")
    p.add_argument("--keep", action="store_true", help="保留现场目录")
    p.set_defaults(func=cmd_selftest)

    p = sub.add_parser("migrate", help="把旧结构档案升级到当前结构")
    p.add_argument("dir")
    p.set_defaults(func=cmd_migrate)

    p = sub.add_parser("lint", help="体检档案（含真实性检查）")
    p.add_argument("dir"); p.add_argument("--today", default="")
    p.add_argument("--allow-backdate", action="store_true", help="允许倒填历史（仅迁移旧档案时用）")
    p.set_defaults(func=cmd_lint)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
