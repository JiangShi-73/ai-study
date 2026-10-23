#!/usr/bin/env python3
"""用 GitHub 的 Git Data API 推送仓库内容。

为什么需要它：这台机器上 github.com:443 不通（DNS 解析到被墙的 IP），
但 api.github.com 通。git push 走不了，API 可以。

用法：
    python tools/push_via_api.py JiangShi-73/ai-study

行为：
- 把当前 git 索引里的文件整体推成一个提交（远程历史会被压平）
- 远程已有 main 时，新提交接在它后面
- 凭据从 git credential store 读，不打印、不落盘
"""
import base64
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = sys.argv[1] if len(sys.argv) > 1 else "JiangShi-73/ai-study"
API = "https://api.github.com"


def token() -> str:
    p = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    for line in p.stdout.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1]
    raise SystemExit("拿不到 GitHub 凭据（先跑一次 git push 让凭据管理器记住）")


TOK = token()


def call(method, path, payload=None, allow404=False):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Authorization", "token " + TOK)
    req.add_header("Accept", "application/vnd.github+json")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if allow404 and e.code == 404:
            return None
        raise SystemExit(f"{method} {path} -> {e.code}: {e.read().decode()[:300]}")


def main() -> int:
    ref = call("GET", f"/repos/{REPO}/git/ref/heads/main", allow404=True)
    if ref:
        parent = ref["object"]["sha"]
        print("已有 main:", parent[:8])
    else:
        boot = call("PUT", f"/repos/{REPO}/contents/README.md", {
            "message": "init", "content": base64.b64encode(b"# " + REPO.split("/")[-1].encode() + b"\n").decode()})
        parent = boot["commit"]["sha"]
        print("初始提交:", parent[:8])

    files = [f.decode("utf-8") for f in subprocess.run(
        ["git", "ls-files", "-z"], capture_output=True).stdout.split(b"\0") if f]
    print(f"待推送 {len(files)} 个文件")

    tree = []
    for i, f in enumerate(files, 1):
        blob = call("POST", f"/repos/{REPO}/git/blobs", {
            "content": base64.b64encode(Path(f).read_bytes()).decode(), "encoding": "base64"})
        tree.append({"path": f, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        if i % 30 == 0 or i == len(files):
            print(f"  已上传 {i}/{len(files)}")

    t = call("POST", f"/repos/{REPO}/git/trees", {"tree": tree})
    msg = subprocess.run(["git", "log", "-1", "--pretty=%B"], capture_output=True,
                         text=True, encoding="utf-8", errors="replace").stdout.strip()
    commit = call("POST", f"/repos/{REPO}/git/commits", {
        "message": msg or "update", "tree": t["sha"], "parents": [parent]})
    call("PATCH", f"/repos/{REPO}/git/refs/heads/main", {"sha": commit["sha"], "force": True})
    print("完成:", commit["sha"][:8], "|", (msg or "").splitlines()[0] if msg else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
