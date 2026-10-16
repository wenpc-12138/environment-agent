# -*- coding: utf-8 -*-
"""G8 技能打包/市场（本地技能目录 + 导出/导入，导入复用 P9 审核闸门）。

- `list_market()` / `browse_skill(key)`：技能目录浏览（v2 技能库 + v1.2 file 技能双源合并，
  含关联公式/标准引用清单）。
- `export_skill(key, include_related)`：技能 -> zip（SKILL.md + manifest.json + 关联公式定义）。
- `import_skill_zip(zip_path)`：zip -> v2 技能库（status=pending_review，created_by=market_import），
  进 P9 待审中心，R8 审批后 active 可执行（复用统一人工闸门）。
- `market_stats()`：技能市场统计。

导出物格式（format: 1）：
  SKILL.md                技能正文（front matter: name/group/description/version）
  manifest.json           {key,name,group,description,version,formula_ids,standard_refs,exported_at,format}
  formulas/<id>.json      关联公式完整定义（从 FormulaEngine 取）

实现完全自研（zipfile + json），零新增依赖；导入拒绝覆盖（先删后导）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import zipfile
from datetime import datetime

from src.core import db_v12 as v12_db  # S2-M6：数据层统一
from .loader import get_skill_body as _get_skill_body, list_skills as _list_skills  # v1.2 file 技能（S2-M2 迁入 loader）

from ..core.db import get_conn
from ..core.utils import now_iso
from ..memory.episodic import EpisodicMemory

MARKET_DIR = os.path.join(v12_db.DATA_DIR, 'agent_market', 'exports')
_STD_RE = re.compile(r'\b[A-Z]{1,4}\s*[-/]?\s*\d{3,5}(?:\.\d+)?(?:\s*[-–—]\s*\d{4})?\b')
_DOMAIN_KW = {
    'D1': ('水', '地表水', '污水', '水质'),
    'D2': ('空气', '大气', '废气', 'pm', 'voc'),
    'D3': ('噪声', '声', '振动'),
    'D4': ('土壤', '固废', '危废', '地块'),
    'D5': ('自行监测', '排污', '污染源'),
    'D6': ('环评', '报告', '验收', '规划'),
}
_DEFAULT_DOMAIN = 'D6'


def _formula_engine():
    from ..compute.engine import FormulaEngine
    return FormulaEngine()


def collect_related(text: str) -> tuple[list[str], list[str]]:
    """从技能文本提取：显式 formula_id 引用 + 标准号引用。

    返回 (formula_ids, standard_refs)。显式 `formula_id: xxx` / `formula: xxx`
    行优先；再按标准号扫描匹配公式库（standard 字段含该标准号）。
    """
    text = text or ''
    formula_ids: list[str] = []
    for m in re.finditer(r'formula_?id\s*[:：=]\s*([\w-]+)', text, re.I):
        fid = m.group(1).strip()
        if fid and fid not in formula_ids:
            formula_ids.append(fid)
    eng = _formula_engine()
    stds = [m.group(0).strip() for m in _STD_RE.finditer(text)]
    # 标准号 -> 匹配公式
    for std in stds:
        try:
            for f in eng.list(standard=std):
                if f['id'] not in formula_ids:
                    formula_ids.append(f['id'])
        except Exception:  # noqa: BLE001
            continue
    stds = list(dict.fromkeys(stds))
    return formula_ids[:20], stds[:20]


def _formula_defs(formula_ids: list[str]) -> list[dict]:
    eng = _formula_engine()
    return [eng._by_id[fid] for fid in formula_ids if fid in eng._by_id]


def _infer_domain(name_desc: str) -> str:
    s = (name_desc or '').lower()
    for d, kws in _DOMAIN_KW.items():
        if any(k in s for k in kws):
            return d
    return _DEFAULT_DOMAIN


def _v2_skills(status: str | None = None) -> list[dict]:
    """v2 技能库（含 id/name/domain/version/status/definition）。"""
    from ..memory.procedural import ProceduralMemory
    out = []
    for s in ProceduralMemory().list_skills(status):
        out.append({'id': s.id, 'name': s.name, 'domain': s.domain,
                    'version': s.version, 'status': s.status,
                    'definition': s.definition or '', 'source': 'v2',
                    'level': s.level, 'role': s.role, 'created_by': s.created_by})
    return out


def _file_skills() -> list[dict]:
    out = []
    for s in _list_skills():
        body = _get_skill_body(s['key'])
        out.append({'id': f"file:{s['key']}", 'name': s['name'], 'domain': '',
                    'version': '1.0.0', 'status': 'active' if s['enabled'] else 'disabled',
                    'definition': body, 'source': 'file',
                    'level': 'L1', 'role': '', 'created_by': 'file'})
    return out


# ---------------- 目录浏览 ----------------

def list_market(status: str = '', source: str = '') -> dict:
    """技能目录（v2 + file 合并），附关联公式/标准引用数。"""
    items = _v2_skills() + _file_skills()
    out: list[dict] = []
    for s in items:
        if status and s['status'] != status:
            continue
        if source and s['source'] != source:
            continue
        fids, stds = collect_related(s['definition'])
        out.append({'id': s['id'], 'name': s['name'], 'domain': s['domain'],
                    'version': s['version'], 'status': s['status'], 'source': s['source'],
                    'formula_ids': fids[:8], 'standard_refs': stds[:8],
                    'body_len': len(s['definition'] or ''),
                    'summary': (s['definition'] or '')[:80]})
    return {'items': out, 'count': len(out)}


def browse_skill(key: str) -> dict:
    """技能详情：正文 + front matter + 关联公式/标准引用。"""
    key = (key or '').strip()
    item = next((s for s in (_v2_skills() + _file_skills()) if s['id'] == key), None)
    if not item:
        # 兼容：v2 直接传 id / file 传 key
        item = next((s for s in _v2_skills() if s['id'] == key), None) or \
               next((s for s in _file_skills() if s['id'] == f"file:{key}"), None)
    if not item:
        return {'ok': False, 'error': f'技能不存在: {key}'}
    fids, stds = collect_related(item['definition'])
    return {'ok': True, **item, 'formula_ids': fids, 'standard_refs': stds}


def market_stats() -> dict:
    v2 = _v2_skills()
    return {'total': len(v2) + len(_file_skills()),
            'v2': len(v2), 'file': len(_file_skills()),
            'active': len([s for s in v2 if s['status'] == 'active']),
            'pending': len([s for s in v2 if s['status'] == 'pending_review']),
            'exports_dir': MARKET_DIR}


# ---------------- 导出 / 导入 ----------------

def export_skill(key: str, include_related: bool = True) -> dict:
    """技能导出为 zip（SKILL.md + manifest.json + 关联公式）。

    key 支持：v2 技能 id 或 file 技能 key（file:xxx 或裸 key）。
    """
    key = (key or '').strip()
    item = next((s for s in (_v2_skills() + _file_skills()) if s['id'] == key), None)
    if not item and not key.startswith('file:'):
        item = next((s for s in _file_skills() if s['id'] == f"file:{key}"), None)
    if not item:
        return {'ok': False, 'error': f'技能不存在: {key}'}

    body = item['definition'] or ''
    if not body:
        return {'ok': False, 'error': f'技能 {key} 正文为空'}
    # front matter
    name = item['name'] or key
    group = item.get('domain') or '通用'
    version = item.get('version') or '1.0.0'
    desc = item.get('summary') or (body[:80])
    front = (f"---\nname: {name}\ngroup: {group}\ndescription: "
             f"{desc or '生态环境特化技能'}\nversion: {version}\n---\n\n")
    md_text = front + body.strip() + '\n'
    # 关联内容
    fids, stds = collect_related(body)
    manifest = {'format': 1, 'key': key.split(':', 1)[-1], 'name': name,
                'group': group, 'description': desc or '',
                'version': version, 'formula_ids': fids, 'standard_refs': stds,
                'source': item.get('source', 'v2'), 'exported_at': now_iso()}
    os.makedirs(MARKET_DIR, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    safe = re.sub(r'[^0-9a-zA-Z\u4e00-\u9fff_-]+', '-', name).strip('-') or 'skill'
    zip_path = os.path.join(MARKET_DIR, f'{safe}-{ts}.zip')
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('SKILL.md', md_text.encode('utf-8'))
            zf.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
            if include_related:
                for fd in _formula_defs(fids):
                    zf.writestr(f"formulas/{fd['id']}.json",
                                json.dumps(fd, ensure_ascii=False, indent=2))
    except Exception as exc:  # noqa: BLE001
        return {'ok': False, 'error': f'{type(exc).__name__}: {exc}'}
    try:
        EpisodicMemory().add(entity=f'market:{name}', event='skill-exported',
                             payload={'key': key, 'path': zip_path,
                                      'formulas': len(fids), 'standards': len(stds)})
    except Exception:  # noqa: BLE001
        pass
    return {'ok': True, 'path': zip_path, 'size': os.path.getsize(zip_path),
            'name': name, 'key': key, 'formula_ids': fids, 'standard_refs': stds}


def import_skill_zip(zip_path: str) -> dict:
    """从 zip 导入技能 -> v2 技能库（status=pending_review，进 P9 待审，R8 审批后激活）。

    校验：zip 含 SKILL.md + manifest.json；name 必填；拒绝覆盖（同 id 已存在报错）。
    """
    zip_path = (zip_path or '').strip()
    if not zip_path or not os.path.isfile(zip_path):
        return {'ok': False, 'error': 'zip 文件不存在'}
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            names = set(zf.namelist())
            if 'SKILL.md' not in names:
                return {'ok': False, 'error': '包内缺少 SKILL.md'}
            if 'manifest.json' not in names:
                return {'ok': False, 'error': '包内缺少 manifest.json'}
            try:
                manifest = json.loads(zf.read('manifest.json').decode('utf-8'))
            except (ValueError, UnicodeDecodeError) as exc:
                return {'ok': False, 'error': f'manifest.json 解析失败: {exc}'}
            if not isinstance(manifest, dict) or not (manifest.get('name') or '').strip():
                return {'ok': False, 'error': 'manifest 缺少 name 字段'}
            body = zf.read('SKILL.md').decode('utf-8', errors='replace')
            body = re.sub(r'^---.*?---\s*', '', body, flags=re.S).strip()
    except zipfile.BadZipFile as exc:
        return {'ok': False, 'error': f'非法 zip 包: {exc}'}
    except Exception as exc:  # noqa: BLE001
        return {'ok': False, 'error': f'{type(exc).__name__}: {exc}'}
    if not body:
        return {'ok': False, 'error': 'SKILL.md 正文为空'}

    name = (manifest.get('name') or '').strip()
    # 防重复导入：同名技能已存在（active/pending）则拒绝
    from ..memory.procedural import ProceduralMemory
    existing = [s for s in ProceduralMemory().list_skills() if s.name == name]
    if existing:
        return {'ok': False, 'error': f'技能「{name}」已存在（{existing[0].id}，'
                                      f'状态 {existing[0].status}），请先删除再导入'}
    key = re.sub(r'[^0-9a-zA-Z\u4e00-\u9fff_-]+', '-', name).strip('-') or 'skill'
    # SkillDef 约束：id 形如 sk-mkt-<NNN>（3 字母 + 3 位序号）
    seq = 1
    try:
        rows = get_conn().execute("SELECT id FROM v2_skills WHERE id LIKE 'sk-mkt-%'").fetchall()
        nums = [int(m.group(1)) for r in rows
                if (m := re.search(r'sk-mkt-(\d{3})$', r['id']))]
        seq = (max(nums) + 1) if nums else 1
    except Exception:  # noqa: BLE001
        seq = 1
    skill_id = f'sk-mkt-{seq:03d}'
    domain = _infer_domain((manifest.get('name') or '') + ' ' + (manifest.get('group') or '')
                           + ' ' + (manifest.get('description') or ''))
    version = str(manifest.get('version') or '1.0.0')
    try:
        from ..models.core import SkillDef
        defn = SkillDef(id=skill_id, name=name, level=1, role='R4',
                        domain=domain, version=version,
                        status='pending_review', definition=body,
                        created_by='manual')
        ProceduralMemory().create_skill(defn)
    except Exception as exc:  # noqa: BLE001
        return {'ok': False, 'error': f'{type(exc).__name__}: {exc}'}
    try:
        EpisodicMemory().add(entity=f'market:{name}', event='skill-imported',
                             payload={'skill_id': skill_id, 'domain': domain,
                                      'version': version, 'status': 'pending_review'})
    except Exception:  # noqa: BLE001
        pass
    return {'ok': True, 'skill_id': skill_id, 'name': name, 'domain': domain,
            'version': version, 'status': 'pending_review',
            'note': '已进入 P9 待审中心，R8 审批后激活可用'}
