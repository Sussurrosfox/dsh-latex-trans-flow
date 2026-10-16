# -*- coding: utf-8 -*-
"""
canonicalize_numbering.py - 全量编号规范化与标签总台账构建工具（通用增强版）
用于验证全书各节定理、公式、习题标签的一致性，并生成 label_targets.md 与 label_targets.json。

特性：
1. 自动适配单卷或多卷结构，支持命令行指定项目根目录与卷路径；
2. 计数器模拟校验（验证模拟显示编号与 \\label 后缀是否一致）；
3. 豁免规则解耦：支持通过命令行或配置文件注入白名单豁免，默认保留 Amann 项目基线；
4. 输出支持自定义 Markdown 与 JSON 报告路径。
"""

import os
import re
import io
import sys
import json
import argparse
from collections import defaultdict

try:
    from config_utils import ensure_utf8_stdio, find_project_root, load_project_volumes, infer_chapter_section
    ensure_utf8_stdio()
except ImportError:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    find_project_root = lambda: os.getcwd()
    load_project_volumes = lambda r, c, d: [("Root", r or os.getcwd())]
    infer_chapter_section = lambda p: (0, 0)

# 共享计数器的定理类环境
THM_ENVS = {
    'theorem', 'lemma', 'proposition', 'corollary',
    'definition', 'remark', 'example', 'conclusion'
}

THM_BEGIN = re.compile(r'\\begin\{(theorem|lemma|proposition|corollary|definition|remark|example|conclusion)\}(?:\[[^\]]*\])?(?:\s*\\label\{([^}]+)\})?')
LABEL_RE = re.compile(r'\\label\{([^}]+)\}')
EQ_LABEL = re.compile(r'\\label\{(eq:[^}]+)\}')
EX_LABEL = re.compile(r'\\label\{(ex:[^}]+)\}')
SEC_LABEL = re.compile(r'\\label\{(sec:[^}]+)\}')

# 裸头模式
BARE_PATTERN = re.compile(r'^\s*(\d+\.\d+)\s+(定理|引理|命题|推论|定义|注记|说明|例子|例|结论)')

# 默认豁免项（向后兼容 Amann 基线）
DEFAULT_EXEMPTIONS = {
    (3, 3, 'thm:3-3.8'),    # EX-01: I.3.3 [8]
    (6, 4, 'thm:6-4.13'),   # EX-02: II.6.4 [13]
}

def get_active_files(volumes):
    active = []
    seen = set()
    for vname, vdir in volumes:
        if not os.path.exists(vdir):
            continue
        cand_roots = [
            os.path.join(vdir, 'chapters_translate'),
            os.path.join(vdir, 'chapters'),
            vdir
        ]
        target_root = None
        for cr in cand_roots:
            if os.path.isdir(cr):
                target_root = cr
                break
        if not target_root:
            continue

        for root, dirs, files in os.walk(target_root):
            for f in sorted(files):
                # 优先匹配 .api.tex 与 .pre.tex，若都不存在则匹配 .tex
                if not (f.endswith('.api.tex') or f.endswith('.pre.tex') or f.endswith('.tex')):
                    continue
                if f.startswith('compile') or f.startswith('tmp'):
                    continue
                stem = re.sub(r'\.(?:(?:api|pre)\.)?tex$', '', f)
                api_path = os.path.join(root, stem + '.api.tex')
                pre_path = os.path.join(root, stem + '.pre.tex')
                raw_path = os.path.join(root, stem + '.tex')
                
                target = api_path if os.path.exists(api_path) else (pre_path if os.path.exists(pre_path) else raw_path)
                if target in seen:
                    continue
                seen.add(target)
                active.append((vname, vdir, target))
    return active

def parse_sec_meta(file_path):
    c_num, s_num = infer_chapter_section(file_path)
    if c_num is not None:
        return c_num, s_num if s_num is not None else 0
    # 兜底匹配
    base = os.path.basename(file_path)
    parent = os.path.basename(os.path.dirname(file_path))
    chap_m = re.search(r'Chapter_([IVXLCDM]+|\d+)', parent)
    sec_m = re.search(r'Section_(\d+)', base)
    if chap_m and sec_m:
        raw_c = chap_m.group(1)
        roman_map = {'I':1, 'II':2, 'III':3, 'IV':4, 'V':5, 'VI':6, 'VII':7, 'VIII':8, 'IX':9, 'X':10, 'XI':11, 'XII':12}
        c = roman_map.get(raw_c, int(raw_c) if raw_c.isdigit() else 0)
        s = int(sec_m.group(1))
        return c, s
    return 0, 0

def scan_section(filepath, c_num, s_num):
    content = io.open(filepath, encoding='utf-8').read()
    lines = content.split('\n')
    
    thm_labels = []
    eq_labels = []
    ex_labels = []
    sec_labels = []
    all_labels = []
    bare_headers = []
    
    counter = 1
    mismatches = []
    
    for i, line in enumerate(lines, 1):
        bm = BARE_PATTERN.search(line)
        if bm and not ('\\begin{' in line):
            bare_headers.append((i, bm.group(1), line.strip()[:60]))
            
        for lm in LABEL_RE.finditer(line):
            lab = lm.group(1)
            all_labels.append((i, lab))
            if lab.startswith('thm:'):
                thm_labels.append((i, lab))
            elif lab.startswith('eq:'):
                eq_labels.append((i, lab))
            elif lab.startswith('ex:'):
                ex_labels.append((i, lab))
            elif lab.startswith('sec:'):
                sec_labels.append((i, lab))

    # 模拟定理计数器比对
    for m in re.finditer(r'\\begin\{(theorem|lemma|proposition|corollary|definition|remark|example|conclusion)\}(?:\[[^\]]*\])?(?:\s*\\label\{([^}]+)\})?', content):
        env = m.group(1)
        lab = m.group(2)
        if not lab:
            after = content[m.end():m.end()+150]
            lm = LABEL_RE.search(after)
            if lm:
                lab = lm.group(1)
        
        sim_id = f"{c_num}-{s_num}.{counter}"
        if lab:
            expected_prefix = f"thm:{c_num}-{s_num}."
            if not lab.startswith(expected_prefix):
                mismatches.append((counter, lab, sim_id, "format_error"))
            else:
                label_idx = lab[len(expected_prefix):]
                if str(counter) != label_idx:
                    mismatches.append((counter, lab, sim_id, "index_drift"))
        else:
            mismatches.append((counter, None, sim_id, "missing_label"))
        counter += 1

    return {
        'thm_labels': thm_labels,
        'eq_labels': eq_labels,
        'ex_labels': ex_labels,
        'sec_labels': sec_labels,
        'all_labels': all_labels,
        'bare_headers': bare_headers,
        'mismatches': mismatches,
        'thm_count': counter - 1
    }

def main():
    parser = argparse.ArgumentParser(description="全书编号规范化与标签总台账构建工具")
    parser.add_argument('--root', help='项目根目录路径（缺省自动探测）', default=None)
    parser.add_argument('--dirs', nargs='+', help='指定待处理的一组目录', default=None)
    parser.add_argument('--out-md', help='Markdown 格式台账输出路径（默认 label_targets.md）', default=None)
    parser.add_argument('--out-json', help='JSON 格式台账输出路径（默认 label_targets.json）', default=None)
    parser.add_argument('--exemptions', help='自定义豁免文件路径或逗号分隔列表（如 "3.3:thm:3-3.8,6.4:thm:6-4.13"）', default=None)
    parser.add_argument('--no-exemptions', action='store_true', help='清空所有默认豁免项')
    parser.add_argument('--title', help='台账文档主标题', default="全书引用目标总台账 (label_targets.md)")
    args = parser.parse_args()

    project_root = find_project_root(args.root)
    volumes = load_project_volumes(project_root=project_root, custom_dirs=args.dirs)
    
    out_md_path = args.out_md or os.path.join(project_root, 'label_targets.md')
    out_json_path = args.out_json or os.path.join(project_root, 'label_targets.json')

    # 解析豁免列表
    exemptions = set() if args.no_exemptions else set(DEFAULT_EXEMPTIONS)
    if args.exemptions:
        if os.path.exists(args.exemptions):
            with open(args.exemptions, 'r', encoding='utf-8') as f:
                ex_data = json.load(f)
                for item in ex_data:
                    exemptions.add((item['chapter'], item['section'], item['label']))
        else:
            for pair in args.exemptions.split(','):
                # 格式: c.s:label
                m = re.match(r'(\d+)\.(\d+):(.+)', pair.strip())
                if m:
                    exemptions.add((int(m.group(1)), int(m.group(2)), m.group(3).strip()))

    active_files = get_active_files(volumes)
    print(f"=== 找到活跃节文件 {len(active_files)} 个 ===")
    
    all_label_set = defaultdict(list)
    results = []
    
    total_thm = 0
    total_eq = 0
    total_ex = 0
    total_sec = 0
    
    global_mismatches = 0
    global_bare = 0
    
    for vname, vdir, fpath in active_files:
        c_num, s_num = parse_sec_meta(fpath)
        rel = os.path.relpath(fpath, vdir)
        info = scan_section(fpath, c_num, s_num)
        
        for ln, lab in info['all_labels']:
            all_label_set[lab].append((rel, ln))
            
        total_thm += len(info['thm_labels'])
        total_eq += len(info['eq_labels'])
        total_ex += len(info['ex_labels'])
        total_sec += len(info['sec_labels'])
        
        valid_mismatches = []
        for m in info['mismatches']:
            if (c_num, s_num, m[1]) in exemptions:
                continue
            valid_mismatches.append(m)
            
        if valid_mismatches:
            global_mismatches += len(valid_mismatches)
            print(f"[MISMATCH] {vname} {rel}: {valid_mismatches}")
            
        if info['bare_headers']:
            global_bare += len(info['bare_headers'])
            print(f"[BARE] {vname} {rel}: {info['bare_headers']}")
            
        results.append((vname, c_num, s_num, rel, info))
        
    duplicates = {k: v for k, v in all_label_set.items() if len(v) > 1}
    
    print("\n=== 全书标签普查汇总 ===")
    print(f"定理标签 (thm): {total_thm}")
    print(f"公式标签 (eq):  {total_eq}")
    print(f"习题标签 (ex):  {total_ex}")
    print(f"节级标签 (sec): {total_sec}")
    print(f"标签总数:       {len(all_label_set)}")
    print(f"重复标签:       {len(duplicates)}")
    print(f"未豁免错位:     {global_mismatches}")
    print(f"未包装裸头:     {global_bare}")
    
    if duplicates:
        print("\n[DUPLICATE LABELS]:")
        for k, v in duplicates.items():
            print(f"  {k}: {v}")
            
    md_lines = [
        f"# {args.title}",
        "",
        "> 本文件由 canonicalize_numbering.py 自动生成，作为全书跨节、跨章交叉引用（cleveref / cref）的基准台账。",
        "> 铁律：所有标签严格遵循统一机械生成规则，严禁人工自创新规则。",
        "",
        "## 统计概要",
        f"- **定理类标签 (thm)**: {total_thm}",
        f"- **公式标签 (eq)**: {total_eq}",
        f"- **习题标签 (ex)**: {total_ex}",
        f"- **章节标签 (sec)**: {total_sec}",
        f"- **重复标签数**: {len(duplicates)}",
        f"- **未豁免错位数**: {global_mismatches}",
        "",
        "---",
        ""
    ]
    
    curr_vol = None
    curr_chap = None
    
    for vname, c_num, s_num, rel, info in results:
        if vname != curr_vol:
            curr_vol = vname
            md_lines.append(f"## {curr_vol}")
            md_lines.append("")
        if c_num != curr_chap:
            curr_chap = c_num
            md_lines.append(f"### 第 {curr_chap} 章")
            md_lines.append("")
            
        md_lines.append(f"#### 第 {curr_chap} 章 第 {s_num} 节 (`{os.path.basename(rel)}`)")
        md_lines.append(f"- **节标签**: `{[lab for _, lab in info['sec_labels']]}`")
        md_lines.append(f"- **定理标签 ({len(info['thm_labels'])} 个)**: " + ", ".join(f"`{lab}`" for _, lab in info['thm_labels']))
        if info['eq_labels']:
            md_lines.append(f"- **公式标签 ({len(info['eq_labels'])} 个)**: " + ", ".join(f"`{lab}`" for _, lab in info['eq_labels']))
        if info['ex_labels']:
            md_lines.append(f"- **习题标签 ({len(info['ex_labels'])} 个)**: " + ", ".join(f"`{lab}`" for _, lab in info['ex_labels']))
        md_lines.append("")
        
    io.open(out_md_path, 'w', encoding='utf-8').write("\n".join(md_lines))
    print(f"\n[OK] 总台账已成功输出至: {out_md_path}")

    json_records = []
    for vname, c_num, s_num, rel, info in results:
        fname = os.path.basename(rel)
        for ln, lab in info['all_labels']:
            pfx = lab.split(':')[0] if ':' in lab else 'other'
            json_records.append({
                'label': lab,
                'prefix': pfx,
                'volume': vname,
                'chapter': c_num,
                'section': s_num,
                'file': fname,
                'rel_path': rel,
                'line': ln
            })
    json.dump(json_records, io.open(out_json_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f"[OK] 结构化 JSON 台账已成功输出至: {out_json_path}")

if __name__ == '__main__':
    main()
