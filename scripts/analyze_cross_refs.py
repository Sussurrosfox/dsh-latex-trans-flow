# -*- coding: utf-8 -*-
"""
analyze_cross_refs.py - 交叉引用现状普查与批量转换可行性分析工具（通用增强版）

特性：
1. 通用节文件遍历器 get_work_files()：多卷/单卷自适应，自动按 .api.tex -> .pre.tex -> .tex 优先级拾取；
2. 标签总库加载器 load_all_labels()：优先读取 label_targets.json，支持直接从各节文件动态提取；
3. 支持跨章、跨节定理/公式/习题/小节引用的多层正则检测与白名单比对；
4. CLI 支持 --root, --dirs, --labels, --json 输出。
"""

import os
import re
import json
import argparse
from collections import defaultdict, Counter

try:
    from config_utils import (ensure_utf8_stdio, find_project_root, load_project_volumes,
                              discover_work_files, infer_chapter_section, ROMAN_MAP, INT_TO_ROMAN,
                              DEFAULT_AMANN_VOLUMES)
    ensure_utf8_stdio()
except ImportError:
    import sys
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    find_project_root = lambda: os.getcwd()
    load_project_volumes = lambda r, c, d: [("Root", r or os.getcwd())]
    discover_work_files = lambda vols: []
    infer_chapter_section = lambda p: (0, 0)
    ROMAN_MAP = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6,
                 'VII': 7, 'VIII': 8, 'IX': 9, 'X': 10, 'XI': 11, 'XII': 12}
    INT_TO_ROMAN = {v: k for k, v in ROMAN_MAP.items()}
    DEFAULT_AMANN_VOLUMES = []

VOLUMES = DEFAULT_AMANN_VOLUMES

def get_work_files(root_dir=None, custom_dirs=None):
    """
    通用节文件枚举器：按优先级 (.api.tex > .pre.tex > .tex) 枚举全书全部工作节。
    返回: [(vol_name, chapter_num, section_num, fpath), ...]
    """
    project_root = find_project_root(root_dir)
    vols = load_project_volumes(project_root=project_root, custom_dirs=custom_dirs)
    
    # 使用 config_utils.discover_work_files
    files = discover_work_files(vols, priority_exts=('.api.tex', '.pre.tex', '.tex'))
    if files:
        return files
        
    # 兜底直接遍历
    res = []
    seen = set()
    for vname, vdir in vols:
        cand_roots = [os.path.join(vdir, 'chapters_translate'), os.path.join(vdir, 'chapters'), vdir]
        target_root = next((d for d in cand_roots if os.path.isdir(d)), None)
        if not target_root:
            continue
        for root, dirs, fnames in os.walk(target_root):
            for fn in sorted(fnames):
                if fn.startswith('compile') or fn.startswith('tmp'):
                    continue
                if not (fn.endswith('.api.tex') or fn.endswith('.pre.tex') or fn.endswith('.tex')):
                    continue
                full_p = os.path.join(root, fn)
                c_num, s_num = infer_chapter_section(full_p)
                if c_num is not None:
                    s_num = s_num if s_num is not None else 0
                    stem = re.sub(r'\.(?:api|pre)?\.tex$', '', fn)
                    key = (c_num, s_num, stem)
                    if key not in seen:
                        seen.add(key)
                        res.append((vname, c_num, s_num, full_p))
    return sorted(res, key=lambda x: (x[1], x[2]))

def load_all_labels(root_dir=None, label_json_path=None, custom_dirs=None):
    """
    读取全书规范标签：
    优先从 label_targets.json 读取，并补充实际工作节中出现的未登记合规标签。
    若 label_targets.json 不存在，则全量遍历工作节实时提取。
    """
    project_root = find_project_root(root_dir)
    target_json = label_json_path or os.path.join(project_root, 'label_targets.json')
    targets = []
    seen_labels = set()
    
    if os.path.exists(target_json):
        try:
            with open(target_json, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                for item in loaded:
                    targets.append(item)
                    seen_labels.add(item['label'])
        except Exception:
            pass

    # 扫描工作节，补充未入库标签
    work_files = get_work_files(root_dir=project_root, custom_dirs=custom_dirs)
    for vname, c_num, s_num, fpath in work_files:
        if not os.path.exists(fpath):
            continue
        with open(fpath, 'r', encoding='utf-8') as f:
            for lnum, line in enumerate(f, 1):
                for m in re.finditer(r'\\label\{([^}]+)\}', line):
                    lab = m.group(1)
                    if lab not in seen_labels:
                        seen_labels.add(lab)
                        pfx = lab.split(':')[0] if ':' in lab else ''
                        targets.append({
                            'label': lab,
                            'prefix': pfx,
                            'volume': vname,
                            'chapter': c_num,
                            'section': s_num,
                            'file': os.path.basename(fpath),
                            'rel_path': os.path.relpath(fpath, project_root),
                            'line': lnum
                        })
    return targets

def build_label_indices(all_targets):
    label_set = set()
    idx = {}
    for item in all_targets:
        lab = item['label']
        label_set.add(lab)
        pfx = item['prefix']
        c = item['chapter']
        s = item['section']
        m = re.match(r'^(?:thm|eq|ex):(\d+)-(\d+)\.(.+)$', lab)
        if m:
            lc, ls, ln = int(m.group(1)), int(m.group(2)), m.group(3)
            idx[(pfx, lc, ls, ln)] = lab
        sm = re.match(r'^sec:(\d+)-(\d+)$', lab)
        if sm:
            lc, ls = int(sm.group(1)), int(sm.group(2))
            idx[('sec', lc, ls)] = lab
    return label_set, idx

def main():
    parser = argparse.ArgumentParser(description="交叉引用现状普查与批量转换可行性分析")
    parser.add_argument('--root', help='项目根目录路径（缺省自动探测）', default=None)
    parser.add_argument('--dirs', nargs='+', help='指定待分析的一组目录', default=None)
    parser.add_argument('--labels', help='label_targets.json 路径（缺省自动在根目录下查找）', default=None)
    parser.add_argument('--json', help='导出分析结果至 JSON 文件路径', default=None)
    args = parser.parse_args()

    project_root = find_project_root(args.root)
    targets = load_all_labels(root_dir=project_root, label_json_path=args.labels, custom_dirs=args.dirs)
    print(f"Loaded {len(targets)} labels across all working sections.")
    label_set, idx = build_label_indices(targets)
    work_files = get_work_files(root_dir=project_root, custom_dirs=args.dirs)
    print(f"Found {len(work_files)} working section files.")
    
    THM_KW = r'(?:定理|命题|引理|推论|定义|例|例子|评注|注记|注|结论|公理|Theorem|Proposition|Lemma|Corollary|Definition|Example|Remark|Axiom)'
    RE_THM_CROSS = re.compile(rf'({THM_KW})\s*([IVXLCDM]+)\.(\d+)\.(\d+)(?:\(([a-z0-9]+)\))?')
    RE_THM_LOCAL = re.compile(rf'({THM_KW})\s*(\d+)\.(\d+)(?:\(([a-z0-9]+)\))?')
    RE_SEC_CROSS = re.compile(r'(?:第\s*([IVXLCDM]+)\.(\d+)\s*节|§\s*([IVXLCDM]+)\.(\d+)|Section\s*([IVXLCDM]+)\.(\d+))')
    RE_SEC_LOCAL = re.compile(r'(?:第\s*(\d+)\s*节|§\s*(\d+)|Section\s*(\d+))')
    RE_EX_CROSS = re.compile(r'(?:习题|练习|Exercise)\s*([IVXLCDM]+)\.(\d+)\.(\d+)')
    RE_EX_LOCAL = re.compile(r'(?:习题|练习|Exercise)\s*(\d+)\.(\d+)')
    RE_EQ_EXPLICIT_CROSS = re.compile(r'(?:式|公式)\s*\(([IVXLCDM]+)\.(\d+)\.(\d+)\)')
    RE_EQ_EXPLICIT_LOCAL = re.compile(r'(?:式|公式)\s*\((\d+)\.(\d+)\)')
    
    all_detections = []
    
    for vname, c_num, s_num, filepath in work_files:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            
        lines = content.split('\n')
        for lnum, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith('%'):
                continue
            if '\\label{' in line and len(line) < 60:
                continue
                
            for m in RE_THM_CROSS.finditer(line):
                kw, rom, sec, num, sub = m.group(1), m.group(2), int(m.group(3)), m.group(4), m.group(5)
                target_chap = ROMAN_MAP.get(rom, 0)
                target_lab = f"thm:{target_chap}-{sec}.{num}"
                hit = target_lab in label_set
                all_detections.append({
                    'type': 'thm_cross',
                    'file': f'{c_num}_{s_num}',
                    'line': lnum,
                    'raw': m.group(0),
                    'target_lab': target_lab,
                    'hit': hit
                })
                
            line_masked = RE_THM_CROSS.sub('XXX_THM_CROSS_XXX', line)
            line_masked = RE_SEC_CROSS.sub('XXX_SEC_CROSS_XXX', line_masked)
            line_masked = RE_EX_CROSS.sub('XXX_EX_CROSS_XXX', line_masked)
            line_masked = RE_EQ_EXPLICIT_CROSS.sub('XXX_EQ_CROSS_XXX', line_masked)
            
            for m in RE_THM_LOCAL.finditer(line_masked):
                kw, sec, num, sub = m.group(1), int(m.group(2)), m.group(3), m.group(4)
                target_lab = f"thm:{c_num}-{sec}.{num}"
                hit = target_lab in label_set
                all_detections.append({
                    'type': 'thm_local',
                    'file': f'{c_num}_{s_num}',
                    'line': lnum,
                    'raw': m.group(0),
                    'target_lab': target_lab,
                    'hit': hit
                })
                
            for m in RE_SEC_CROSS.finditer(line):
                rom = m.group(1) or m.group(3) or m.group(5)
                sec = int(m.group(2) or m.group(4) or m.group(6))
                target_chap = ROMAN_MAP.get(rom, 0)
                target_lab = f"sec:{target_chap}-{sec}"
                hit = target_lab in label_set
                all_detections.append({
                    'type': 'sec_cross',
                    'file': f'{c_num}_{s_num}',
                    'line': lnum,
                    'raw': m.group(0),
                    'target_lab': target_lab,
                    'hit': hit
                })
                
            for m in RE_SEC_LOCAL.finditer(line_masked):
                sec = int(m.group(1) or m.group(2) or m.group(3))
                target_lab = f"sec:{c_num}-{sec}"
                hit = target_lab in label_set
                all_detections.append({
                    'type': 'sec_local',
                    'file': f'{c_num}_{s_num}',
                    'line': lnum,
                    'raw': m.group(0),
                    'target_lab': target_lab,
                    'hit': hit
                })
                
            for m in RE_EQ_EXPLICIT_CROSS.finditer(line):
                rom, sec, num = m.group(1), int(m.group(2)), m.group(3)
                target_chap = ROMAN_MAP.get(rom, 0)
                target_lab = f"eq:{target_chap}-{sec}.{num}"
                hit = target_lab in label_set
                all_detections.append({
                    'type': 'eq_cross',
                    'file': f'{c_num}_{s_num}',
                    'line': lnum,
                    'raw': m.group(0),
                    'target_lab': target_lab,
                    'hit': hit
                })
                
            for m in RE_EQ_EXPLICIT_LOCAL.finditer(line_masked):
                sec, num = int(m.group(1)), m.group(2)
                target_lab = f"eq:{c_num}-{sec}.{num}"
                hit = target_lab in label_set
                all_detections.append({
                    'type': 'eq_local',
                    'file': f'{c_num}_{s_num}',
                    'line': lnum,
                    'raw': m.group(0),
                    'target_lab': target_lab,
                    'hit': hit
                })
                
            for m in RE_EX_CROSS.finditer(line):
                rom, sec, num = m.group(1), int(m.group(2)), m.group(3)
                target_chap = ROMAN_MAP.get(rom, 0)
                target_lab = f"ex:{target_chap}-{sec}.{num}"
                hit = target_lab in label_set
                all_detections.append({
                    'type': 'ex_cross',
                    'file': f'{c_num}_{s_num}',
                    'line': lnum,
                    'raw': m.group(0),
                    'target_lab': target_lab,
                    'hit': hit
                })
                
            for m in RE_EX_LOCAL.finditer(line_masked):
                sec, num = int(m.group(1)), m.group(2)
                target_lab = f"ex:{c_num}-{sec}.{num}"
                hit = target_lab in label_set
                all_detections.append({
                    'type': 'ex_local',
                    'file': f'{c_num}_{s_num}',
                    'line': lnum,
                    'raw': m.group(0),
                    'target_lab': target_lab,
                    'hit': hit
                })

    print(f"\n================ 全书交叉引用探测初步普查 ================")
    print(f"总计检测到引用候选: {len(all_detections)} 处")
    
    by_type = defaultdict(list)
    hit_count = 0
    miss_count = 0
    for d in all_detections:
        by_type[d['type']].append(d)
        if d['hit']:
            hit_count += 1
        else:
            miss_count += 1
            
    pct = (hit_count / len(all_detections) * 100) if all_detections else 0.0
    miss_pct = (miss_count / len(all_detections) * 100) if all_detections else 0.0
    print(f"标签库完全精准命中: {hit_count} 处 ({pct:.1f}%)")
    print(f"未直接命中/需对校: {miss_count} 处 ({miss_pct:.1f}%)")
    print("\n分类型明细统计：")
    for t, lst in sorted(by_type.items()):
        t_hits = sum(1 for x in lst if x['hit'])
        t_pct = (t_hits / len(lst) * 100) if lst else 0.0
        print(f"  {t:15s}: 总计 {len(lst):4d} 处 | 命中 {t_hits:4d} ({t_pct:.1f}%) | 未命中 {len(lst)-t_hits:3d}")

    if args.json:
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump({
                'total_candidates': len(all_detections),
                'hit_count': hit_count,
                'miss_count': miss_count,
                'detections': all_detections
            }, f, ensure_ascii=False, indent=2)
        print(f"\n[OK] 交叉引用分析数据已导出至: {args.json}")

if __name__ == '__main__':
    main()
