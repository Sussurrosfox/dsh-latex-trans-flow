# -*- coding: utf-8 -*-
"""
collect_residual.py - 统计各节残余工作量，生成派工清单数据源（通用增强版）。
统计项包括：
  - FIXME-env: 环境标记
  - FIXME-ex: 习题标记
  - 边界CHECK: 环境/证明结束位置推断与最后一道习题
  - 悬置脚注: 悬置脚注与待重接断裂脚注块
  - adopted: 是否已与 .pre.tex / .tex 采纳合稿
"""
import os
import re
import sys
import io
import json
import argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

try:
    from config_utils import (
        ensure_utf8_stdio,
        find_project_root,
        load_project_volumes,
        infer_chapter_section,
        INT_TO_ROMAN,
    )
    ensure_utf8_stdio()
except ImportError:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    find_project_root = lambda r=None: r or os.getcwd()
    load_project_volumes = lambda r=None, c=None, d=None: [("Root", r or os.getcwd())]
    infer_chapter_section = lambda p: (None, None)
    INT_TO_ROMAN = {}


def normalize_ext(ext):
    """规范化扩展名输入，支持缩写如 api, pre, tex 等"""
    if not ext:
        return None
    e = ext.strip().lower()
    if e in ('api', '.api', 'api.tex', '.api.tex'):
        return '.api.tex'
    if e in ('pre', '.pre', 'pre.tex', '.pre.tex'):
        return '.pre.tex'
    if e in ('tex', '.tex'):
        return '.tex'
    if not e.startswith('.'):
        return '.' + e
    return e


def collect_residuals(root_dir=None, custom_dirs=None, target_ext=None):
    """
    扫描各卷各章节文件，统计各节残余工作量。
    若 target_ext 指定，则精确扫描该扩展名文件；
    若 target_ext 为空，则优先匹配各节现有的 .api.tex，缺失时回退至活跃文件（.pre.tex > .tex）。
    返回: (rows, project_root)
    """
    project_root = find_project_root(root_dir)
    volumes = load_project_volumes(project_root=project_root, custom_dirs=custom_dirs)
    norm_ext = normalize_ext(target_ext)

    rows = []
    for vname, vdir in volumes:
        cand_roots = [
            os.path.join(vdir, 'chapters_translate'),
            os.path.join(vdir, 'chapters'),
            vdir
        ]
        target_root = next((cr for cr in cand_roots if os.path.isdir(cr)), None)
        if not target_root:
            continue

        book_label = vname[4:].strip() if vname.startswith('Vol ') else vname

        for cur_root, dirs, files in os.walk(target_root):
            dirs.sort()
            dirs[:] = [d for d in dirs if not d.startswith('.') and not d.startswith('compile') and not d.startswith('tmp')]

            base_info = {}
            for f in sorted(files):
                if f.startswith('.') or f.startswith('compile') or f.startswith('tmp'):
                    continue
                for ext_candidate in ('.api.tex', '.pre.tex', '.tex'):
                    if f.endswith(ext_candidate):
                        b = f[:-len(ext_candidate)]
                        full_p = os.path.join(cur_root, f)
                        c_num, s_num = infer_chapter_section(full_p)
                        if s_num is None:
                            m_sec = re.search(r'(?:sec|section)[_-]?(\d+)', b, re.IGNORECASE)
                            if m_sec:
                                s_num = int(m_sec.group(1))
                        if s_num is not None:
                            if b not in base_info:
                                base_info[b] = (c_num, s_num)
                        break

            sorted_bases = sorted(base_info.keys(), key=lambda b: (
                base_info[b][0] if base_info[b][0] is not None else 0,
                base_info[b][1] if base_info[b][1] is not None else 0,
                b
            ))

            for b in sorted_bases:
                c_num, s_num = base_info[b]
                base_path = os.path.join(cur_root, b)

                chosen_file = None
                chosen_ext = None

                if norm_ext:
                    cand = base_path + norm_ext
                    if os.path.exists(cand):
                        chosen_file = cand
                        chosen_ext = norm_ext
                else:
                    # 默认优先级：.api.tex -> .pre.tex -> .tex
                    for ext_candidate in ('.api.tex', '.pre.tex', '.tex'):
                        cand = base_path + ext_candidate
                        if os.path.exists(cand):
                            chosen_file = cand
                            chosen_ext = ext_candidate
                            break

                if not chosen_file or not os.path.exists(chosen_file):
                    continue

                t = io.open(chosen_file, encoding='utf-8').read()
                n_fixme_env = len(re.findall(r'% FIXME-env', t))
                n_fixme_ex = len(re.findall(r'% FIXME-ex', t))
                n_boundary = len(re.findall(
                    r'% CHECK: (?:环境|证明)结束位置为启发式推断', t))
                n_last_ex = len(re.findall(r'% CHECK: 最后一道习题', t))
                n_orphan_fn = len(re.findall(r'% CHECK: 悬置脚注', t))
                n_orphan_block = len(re.findall(r'% CHECK: 待人工重接的断裂脚注块', t))

                adopted = False
                if chosen_ext == '.api.tex':
                    if os.path.exists(base_path + '.pre.tex'):
                        adopted = io.open(base_path + '.pre.tex', encoding='utf-8').read() == t
                    elif os.path.exists(base_path + '.tex'):
                        adopted = io.open(base_path + '.tex', encoding='utf-8').read() == t
                elif chosen_ext == '.pre.tex':
                    if os.path.exists(base_path + '.tex'):
                        adopted = io.open(base_path + '.tex', encoding='utf-8').read() == t
                else:
                    # 活跃文件为 .tex，视为已采纳生效
                    adopted = True

                ch_label = INT_TO_ROMAN.get(c_num, str(c_num)) if c_num is not None else os.path.basename(cur_root)[:2]
                sec = s_num if s_num is not None else 0

                rows.append(dict(
                    book=book_label,
                    ch=ch_label,
                    sec=sec,
                    name=os.path.basename(chosen_file),
                    path=chosen_file,
                    n_env=n_fixme_env,
                    n_ex=n_fixme_ex,
                    n_bd=n_boundary + n_last_ex,
                    n_fn=n_orphan_fn + n_orphan_block,
                    adopted=adopted,
                    lines=t.count('\n') + 1
                ))

    return rows, project_root


def main():
    parser = argparse.ArgumentParser(description="统计各节残余工作量，生成派工清单数据源。")
    parser.add_argument('--root', help='项目根目录（缺省自动探测）', default=None)
    parser.add_argument('--dirs', nargs='+', help='指定待统计的一组目录', default=None)
    parser.add_argument('--ext', help='扫描的目标后缀（如 .api.tex, .pre.tex, .tex；默认匹配现有的 .api.tex 或回退至活跃文件）', default=None)
    parser.add_argument('--out', help='统计输出的 JSON 路径（默认: residual_stats.json）', default='residual_stats.json')
    args = parser.parse_args()

    rows, project_root = collect_residuals(root_dir=args.root, custom_dirs=args.dirs, target_ext=args.ext)

    out_path = args.out
    if not os.path.isabs(out_path):
        out_path = os.path.join(project_root, out_path)

    tot = {k: sum(r[k] for r in rows) for k in ('n_env', 'n_ex', 'n_bd', 'n_fn')}
    print('总数：节 %d | 已采纳 %d | 待处理 %d' % (
        len(rows), sum(1 for r in rows if r['adopted']),
        sum(1 for r in rows if not r['adopted'])))
    print('FIXME-env %(n_env)d | FIXME-ex %(n_ex)d | 边界CHECK %(n_bd)d | 悬置脚注 %(n_fn)d' % tot)
    print()

    hdr = '%-5s %-4s %-3s %5s %5s %5s %5s %5s %s' % (
        '卷', '章', '节', 'env', 'ex', 'bd', 'fn', '行数', '采纳')
    print(hdr)
    print('-' * len(hdr))
    for r in rows:
        print('%-5s %-4s %-3s %5d %5d %5d %5d %5d %s' % (
            r['book'], r['ch'], str(r['sec']), r['n_env'], r['n_ex'], r['n_bd'], r['n_fn'],
            r['lines'], 'Y' if r['adopted'] else '-'))

    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with io.open(out_path, 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    print(f'\n已写 {out_path}')


if __name__ == '__main__':
    main()
