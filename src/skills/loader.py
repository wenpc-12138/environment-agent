# -*- coding: utf-8 -*-
"""生态Agent - 技能加载:扫描 agents/skills/*/SKILL.md,注入系统提示

S2-M2 迁移（2026-08-20）：自根目录 `skills.py` 原样迁入；
根文件已转兼容重导出（`from src.skills.loader import *`）。
"""
import os
import re
from src.core import db_v12 as db

SKILLS_ROOT = os.path.join(db.DATA_DIR, "agents", "skills")
AGENTS_MD = os.path.join(db.DATA_DIR, "agents", "AGENTS.md")


def _parse_front_matter(text):
    """解析 SKILL.md 顶部 --- 分隔的 YAML 头(name/group/description)"""
    name, group, desc = "", "", ""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, re.S)
    if m:
        head = m.group(1)
        n = re.search(r"name:\s*(.+)", head)
        g = re.search(r"group:\s*(.+)", head)
        d = re.search(r"description:\s*(.+)", head)
        if n:
            name = n.group(1).strip()
        if g:
            group = g.group(1).strip().strip("'\"")
        if d:
            desc = d.group(1).strip().strip("'\"")
    return name, group, desc


def list_skills():
    skills = []
    if not os.path.isdir(SKILLS_ROOT):
        return skills
    for entry in sorted(os.listdir(SKILLS_ROOT)):
        path = os.path.join(SKILLS_ROOT, entry)
        md = os.path.join(path, "SKILL.md")
        if not os.path.isfile(md):
            continue
        with open(md, "r", encoding="utf-8") as f:
            text = f.read()
        name, group, desc = _parse_front_matter(text)
        enabled = db.skill_state(entry)
        body = re.sub(r"^---.*?---\s*", "", text, flags=re.S).strip()
        skills.append({
            "key": entry,
            "name": name or entry,
            "group": group or "通用",
            "description": desc or "生态环境特化技能",
            "enabled": enabled,
            "body_len": len(body),
        })
    return skills


def get_skill_body(key):
    md = os.path.join(SKILLS_ROOT, key, "SKILL.md")
    if not os.path.isfile(md):
        return ""
    with open(md, "r", encoding="utf-8") as f:
        text = f.read()
    return re.sub(r"^---.*?---\s*", "", text, flags=re.S).strip()


def create_skill(body):
    """快速导入:直接写入 SKILL.md,名称/描述取自 md 内的 front matter"""
    text = body.strip()
    if not text:
        raise ValueError("内容为空")
    name, group, desc = _parse_front_matter(text)
    if not name:
        raise ValueError("未在 md 中找到 name 字段")
    key = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff_-]+", "-", name).strip("-") or "skill"
    folder = os.path.join(SKILLS_ROOT, key)
    os.makedirs(folder, exist_ok=True)
    if not text.startswith("---"):
        text = f"---\nname: {name}\ngroup: {group or '通用'}\ndescription: {desc or '生态环境特化技能'}\n---\n\n{text}"
    with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    db.skill_set(key, True)
    return key


def delete_skill(key):
    """删除技能目录,并清除启用状态"""
    import shutil
    folder = os.path.join(SKILLS_ROOT, key)
    if os.path.isdir(folder):
        shutil.rmtree(folder, ignore_errors=True)
    db.skill_set(key, False)
    return True


def load_agents_md():
    if os.path.isfile(AGENTS_MD):
        with open(AGENTS_MD, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""


def build_skill_block():
    """已启用的技能正文拼接,供系统提示注入;按生态主题/行为(group)分组展示"""
    groups = {}
    for s in list_skills():
        if not s["enabled"]:
            continue
        body = get_skill_body(s["key"])
        if body:
            groups.setdefault(s["group"], []).append((s["name"], body))
    if not groups:
        return ""
    blocks = []
    for gname in sorted(groups):
        items = [f"#### 技能: {name}\n{body}" for name, body in groups[gname]]
        blocks.append(f"### 技能组: {gname}\n" + "\n\n".join(items))
    return "\n\n".join(blocks)
