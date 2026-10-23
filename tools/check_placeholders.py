#!/usr/bin/env python3
"""扫描占位符残留（« »）。写文件时用 « 当反引号，收尾手滑会留下 »。

用法：python tools/check_placeholders.py <目录>
退出码：0 = 干净，1 = 有残留
"""
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BAD = ("\u00ab", "\u00bb")  # « »

# 这两类文件里出现 BAD 是正常的：
#   - 检测器自己的源码（必须写出这两个字符才能检测）
#   - 验收报告（历史证据，逐字保留，不许改）
SKIP = {"tools/check_placeholders.py"}
SKIP_HINTS = ("验收报告",)

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
hits = []
for p in sorted(root.rglob("*")):
    if not p.is_file() or p.suffix not in (".md", ".py"):
        continue
    rel = str(p.relative_to(root)).replace("\\", "/")
    if rel in SKIP or any(h in rel for h in SKIP_HINTS):
        continue
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        hits.append(f"{p.relative_to(root)}  (不是合法 UTF-8)")
        continue
    for i, line in enumerate(text.splitlines(), 1):
        if any(c in line for c in BAD):
            hits.append(f"{p.relative_to(root)}:{i}  {line.strip()[:60]}")

if hits:
    print(f"发现 {len(hits)} 处占位符残留：")
    for h in hits:
        print("  " + h)
    sys.exit(1)
print("占位符检查通过。")
