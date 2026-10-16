# -*- coding: utf-8 -*-
"""
list_residual_footnotes.py - 全书残余悬置脚注与断裂脚注块快速普查工具（通用增强版）。
"""
import os
import re
import sys
import json
import argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

try:
    from config_utils import ensure_utf8_stdio, find_project_root
    ensure_utf8_stdio()
except ImportError:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    find_project_root = lambda r=None: r or os.getcwd()

from analyze_cross_refs import get_work_files


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


def scan_footnotes(root_dir=None, custom_dirs=None, check_ext=None):
    """
    普查全书工作节中的残余悬置脚注与待人工重接的断裂脚注块。
    支持指定文件后缀 check_ext（.tex / .pre.tex / .api.tex）；
    缺省默认优先检查 .tex 文件，回退至当前工作文件。
    """
    project_root = find_project_root(root_dir)
    work_files = get_work_files(root_dir=project_root, custom_dirs=custom_dirs)
    norm_ext = normalize_ext(check_ext)
    residual = []

    for vname, c_num, s_num, filepath in work_files:
        base = filepath
        for suf in ('.api.tex', '.pre.tex', '.tex'):
            if filepath.endswith(suf):
                base = filepath[:-len(suf)]
                break

        if norm_ext:
            target_path = base + norm_ext
            if not os.path.exists(target_path):
                continue
        else:
            # 默认优先检查 .tex 文件（保持向后兼容），若不存在则回退至工作文件
            cand_tex = base + '.tex'
            if os.path.exists(cand_tex):
                target_path = cand_tex
            elif os.path.exists(filepath):
                target_path = filepath
            else:
                continue

        with open(target_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        for idx, line in enumerate(lines, 1):
            if '% CHECK: 悬置脚注' in line or '% CHECK: 待人工重接的断裂脚注块' in line:
                residual.append({
                    'vol': vname,
                    'ch': c_num,
                    'sec': s_num,
                    'file': os.path.basename(target_path),
                    'path': target_path,
                    'line': idx,
                    'text': line.strip()
                })
    return residual


def main():
    parser = argparse.ArgumentParser(description="全书残余悬置脚注与断裂脚注块快速普查")
    parser.add_argument('--root', help='项目根目录（缺省自动探测）', default=None)
    parser.add_argument('--dirs', nargs='+', help='指定待统计的一组目录', default=None)
    parser.add_argument('--ext', help='指定检查的文件扩展名（如 .tex, .pre.tex, .api.tex；缺省优先检查 .tex）', default=None)
    parser.add_argument('--json', help='导出结果为 JSON 文件路径', default=None)
    args = parser.parse_args()

    residual = scan_footnotes(root_dir=args.root, custom_dirs=args.dirs, check_ext=args.ext)

    print(f"当前全书残余悬置脚注数量: {len(residual)} 处")
    for r in residual:
        print(f"  [{r['vol']} §{r['ch']}.{r['sec']}] {r['file']}:L{r['line']} -> {r['text'][:70]}...")

    if args.json:
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump(residual, f, ensure_ascii=False, indent=2)
        print(f"\n已导出报告至: {args.json}")


if __name__ == '__main__':
    main()
