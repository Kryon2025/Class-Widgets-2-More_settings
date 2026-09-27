#!/usr/bin/env python3
"""从 CHANGELOG.md 摘出与当前 git 标签对应的那一节，作为 GitHub Release 正文。

为什么需要它：
    Release 正文应该来自仓库里人写的 CHANGELOG.md（可追溯、可 review），
    而不是每次由 GitHub 从 commit 里现编。要让这一步可靠，就必须有一条
    确定的「标签 → 小节」对应规则，这个脚本就是那条规则的唯一实现。

匹配规则（写得宽松，避免因为标题写法不同找不到）：
    git 标签  v1.3.3.20260916
    以上都能匹配到：
        ## [1.3.3.20260916] - 2026-09-16
        ## [v1.3.3.20260916]
        ## 1.3.3.20260916
    故意不匹配：
        ## [Unreleased]    —— 免得把还没发布的改动当成已发布内容发出去

    一节的范围：从它的标题开始，到下一个二级标题（`## `）为止，原文整段搬运。

用法：
    # 正常：找到就写出正文；找不到就告警 + 写一份兜底正文（不中断发布）
    python tools/make_release_notes.py --tag v1.3.3.20260916 --out dist/RELEASE_NOTES.md

    # 严格：找不到对应小节直接退出码 1（想让「必须写 changelog」变成硬约束时用）
    python tools/make_release_notes.py --tag v1.3.3.20260916 --out dist/RELEASE_NOTES.md --strict
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

_H2 = re.compile(r"^##\s+(.+?)\s*$")
_TRAILING_DATE = re.compile(r"\s*[-–—]\s*\d{4}-\d{2}-\d{2}\s*$")


def norm_ver(text: str) -> str:
    """把标题或标签归一成可比较的形式。

    去掉结尾的 `- 2026-09-16`、去掉方括号、去掉开头的 v、统一小写。
    """
    s = str(text or "").strip()
    s = _TRAILING_DATE.sub("", s)
    s = s.strip().strip("[]").strip()
    s = re.sub(r"^[vV]\s*", "", s)
    return s.strip().lower()


def parse_sections(text: str):
    """把 CHANGELOG 拆成 [(标题原文, 归一化版本, 小节正文), ...]，保持顺序。"""
    lines = text.splitlines()
    sections = []
    cur_title = None
    cur_norm = None
    cur_body = []

    for ln in lines:
        m = _H2.match(ln)
        if m:
            if cur_title is not None:
                sections.append((cur_title, cur_norm, "\n".join(cur_body).strip()))
            cur_title = m.group(1)
            cur_norm = norm_ver(cur_title)
            cur_body = []
        elif cur_title is not None:
            cur_body.append(ln)
    if cur_title is not None:
        sections.append((cur_title, cur_norm, "\n".join(cur_body).strip()))
    return sections


def repo_from_policy(root: pathlib.Path) -> str:
    try:
        pol = json.loads((root / "tools" / "features.json").read_text(encoding="utf-8"))
        return str(pol.get("installer", {}).get("repo", "")).strip()
    except Exception:
        return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True, help="git 标签，如 v1.3.3.20260916")
    ap.add_argument("--changelog", default="CHANGELOG.md")
    ap.add_argument("--out", required=True, help="正文输出路径")
    ap.add_argument("--strict", action="store_true",
                    help="找不到对应小节就退出码 1")
    args = ap.parse_args()

    root = pathlib.Path(__file__).resolve().parent.parent
    cl_path = (root / args.changelog) if not pathlib.Path(args.changelog).is_absolute() \
        else pathlib.Path(args.changelog)
    out_path = (root / args.out) if not pathlib.Path(args.out).is_absolute() \
        else pathlib.Path(args.out)

    ver = norm_ver(args.tag)
    repo = repo_from_policy(root)
    # 链接里必须用仓库内的相对路径：--changelog 允许传绝对路径，
    # 直接塞进去会拼出 .../blob/<tag>/C:\Users\...\CHANGELOG.md 这种坏链接。
    try:
        link_name = cl_path.relative_to(root).as_posix()
    except ValueError:
        link_name = cl_path.name
    link = (f"https://github.com/{repo}/blob/{args.tag}/{link_name}"
            if repo else "")
    footer = f"**完整变更记录**：[{link_name}]({link})" if link \
        else f"**完整变更记录**：见仓库里的 {link_name}"

    raw = ""
    if cl_path.is_file():
        raw = cl_path.read_text(encoding="utf-8", errors="replace")

    if not raw.strip():
        print(f"警告：{args.changelog} 是空的（或不存在），无法摘出发布正文。")
        print("      请在仓库里补上 CHANGELOG.md 并写上对应版本的小节。")
        sections = []
    else:
        sections = parse_sections(raw)

    hit = next((s for s in sections if s[1] == ver), None)

    out_path.parent.mkdir(parents=True, exist_ok=True)

    if hit:
        title, _norm, body = hit
        body = body or "_（这一节还是空的，记得补充内容。）_"
        text = f"{body}\n\n---\n\n{footer}\n"
        out_path.write_text(text, encoding="utf-8")
        print(f"已摘出小节：## {title}")
        print(f"正文 {len(text)} 字符 -> {out_path}")
        return 0

    # 没找到：给出足够的信息让人一眼知道该怎么改
    known = [t for t, _n, _b in sections if norm_ver(t) != "unreleased"]
    print(f"警告：{args.changelog} 里没有与标签 {args.tag} 对应的小节。")
    if known:
        print("      现有小节：" + "、".join(known))
    else:
        print("      （文件里一个小节都没有）")
    print(f"      期望看到形如：## [{norm_ver(args.tag)}] - YYYY-MM-DD")

    if args.strict:
        print("      --strict 已开启，按失败处理。")
        return 1

    text = (
        f"> 本次发布对应的变更记录尚未写入 `{args.changelog}`。\n"
        f">\n"
        f"> 在仓库的 `{args.changelog}` 里补一节标题为 `## [{norm_ver(args.tag)}]` "
        f"的内容，下次发布就会自动出现在这里。\n\n"
        f"---\n\n{footer}\n"
    )
    out_path.write_text(text, encoding="utf-8")
    print(f"      已写出兜底正文 -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
