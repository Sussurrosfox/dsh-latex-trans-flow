# -*- coding: utf-8 -*-
"""
batch_preprocess.py - 全书全卷批量预处理驱动（通用增强版）
对全部未改造（或指定）节运行 preprocess.py + 静态门禁（不编译），输出汇总表并支持结果导出。

特性：
1. 自动探查项目根目录与多卷结构（通过 config_utils）；
2. 支持命令行显式指定 --root、--dirs、--pattern；
3. 幂等保护：默认跳过已具有确定性 \\label 的成品节（可通过 --force 强制覆盖）；
4. 提供 --dry-run、--json 报告输出及定理扩展词表传递。
"""

import os
import re
import sys
import io
import json
import argparse

try:
    from config_utils import ensure_utf8_stdio, find_project_root, load_project_volumes, infer_chapter_section
    ensure_utf8_stdio()
except ImportError:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    find_project_root = lambda: os.getcwd()
    load_project_volumes = lambda r, c, d: [("Root", r or os.getcwd())]
    infer_chapter_section = lambda p: (None, None)

from preprocess import preprocess, infer_numbers
from gate_check import (check_clean_macros, check_label_format,
                        check_theorem_count, check_math_tokens, read_file_safely)

def run_batch_preprocess(root_dir=None, custom_dirs=None, file_pattern=r'\d+_Section_\d+\.tex$',
                         force=False, dry_run=False, extra_types=None, no_header_strip=False):
    project_root = find_project_root(root_dir)
    volumes = load_project_volumes(project_root=project_root, custom_dirs=custom_dirs)
    
    rows = []
    skipped = 0
    total_found = 0
    
    # 查找所有待处理节
    for vname, vdir in volumes:
        # 支持 chapters_translate 或 chapters 或直接在 vdir 下
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

        files_to_process = []
        for ch in sorted(os.listdir(target_root)):
            chdir = os.path.join(target_root, ch)
            if os.path.isdir(chdir):
                for fn in sorted(os.listdir(chdir)):
                    if re.search(file_pattern, fn):
                        files_to_process.append((ch, fn, os.path.join(chdir, fn)))
            elif os.path.isfile(chdir) and chdir.endswith('.tex'):
                fn = ch
                if not (fn.endswith('.pre.tex') or fn.endswith('.api.tex') or fn.startswith('compile') or fn.startswith('tmp')):
                    if re.search(file_pattern, fn) or (file_pattern == r'\d+_Section_\d+\.tex$' and (re.search(r'(?:chap|ch|Section|\d+)', fn, re.IGNORECASE) or fn.startswith('0'))):
                        files_to_process.append(('', fn, chdir))

        for ch, fn, path in files_to_process:
            total_found += 1
            chapter, section = infer_numbers(path)
            orig = read_file_safely(path)
            
            # 跳过已有确定性 label 的节（除非 --force）
            if not force and re.search(r'\\label\{(?:sec|thm|eq|ex):', orig):
                skipped += 1
                continue
                
            new, counters, flags = preprocess(
                orig, chapter or 0, section or 0,
                volume_roman=vname.split()[-1] if 'Vol' in vname else None,
                strip_headers=not no_header_strip,
                extra_thm_types=extra_types
            )
            
            out = path[:-4] + '.pre.tex'
            if not dry_run:
                with io.open(out, 'w', encoding='utf-8', newline='\n') as f:
                    f.write(new)
                    
            g2, _ = check_clean_macros(new)
            g5, _ = check_label_format(new)
            g3, m3 = check_theorem_count(orig, new)
            g4, m4 = check_math_tokens(orig, new)
            ratio_m = re.search(r'ratio: ([\d\.]+)%', str(m4))
            ratio_val = float(ratio_m.group(1)) if ratio_m else (100.0 if g4 else 0.0)
            
            rows.append(dict(
                id=f"{vname}/{ch + '/' if ch else ''}{fn.replace('.tex', '')}",
                path=path,
                out_path=out,
                b3=counters['B3'], b4=counters['B4'], b4b=counters['B4-block'],
                b4loose=counters['B4-loose'],
                b5=counters['B5'], b6=counters['B6'], c2=counters['C2'],
                checks=len(re.findall(r'% CHECK', new)),
                g2='P' if g2 else 'F', g3='P' if g3 else 'F',
                g5='P' if g5 else 'F',
                ratio=ratio_val,
                flags=len(flags)))
                    
    return rows, skipped, total_found

def main():
    parser = argparse.ArgumentParser(description="全书全卷 LaTeX 批量机械预处理与门禁巡检")
    parser.add_argument('--root', help='项目根目录路径（缺省时自动探查）', default=None)
    parser.add_argument('--dirs', nargs='+', help='指定待处理的卷或章目录列表', default=None)
    parser.add_argument('--pattern', help='匹配节文件的正则表达式（默认: \\d+_Section_\\d+\\.tex$）', default=r'\d+_Section_\d+\.tex$')
    parser.add_argument('--force', action='store_true', help='强制重新预处理（即便已有 \\label 标签）')
    parser.add_argument('--dry-run', action='store_true', help='演练模式，仅计算门禁与统计，不写入磁盘')
    parser.add_argument('--no-header-strip', action='store_true', help='跳过 OCR 眉页行删除规则')
    parser.add_argument('--extra-types', help='扩展定理类型映射，如 "性质:property,判据:criterion"', default=None)
    parser.add_argument('--json', help='将批量统计导出为 JSON 文件路径', default=None)
    args = parser.parse_args()

    rows, skipped, total_found = run_batch_preprocess(
        root_dir=args.root,
        custom_dirs=args.dirs,
        file_pattern=args.pattern,
        force=args.force,
        dry_run=args.dry_run,
        extra_types=args.extra_types,
        no_header_strip=args.no_header_strip
    )

    hdr = '%-34s %4s %6s %4s %4s %4s %5s %s %s %s %6s %5s' % (
        'file', 'eq', 'fn', 'thm', 'ex', 'eng', 'CHECK', 'G2', 'G3', 'G5', 'math%', 'warn')
    print(hdr)
    print('-' * len(hdr))
    tot = dict(b3=0, b4=0, b4b=0, b4loose=0, b5=0, b6=0, c2=0, checks=0, flags=0, g2fail=0, g3fail=0, n=0)
    for r in rows:
        print('%-34s %4d %2d/%-2d+%d %4d %4d %4d %5d %2s %2s %2s %6.2f %5d' % (
            r['id'], r['b3'], r['b4'], r['b4b'], r['b4loose'], r['b5'], r['b6'], r['c2'],
            r['checks'], r['g2'], r['g3'], r['g5'], r['ratio'], r['flags']))
        for k in ['b3', 'b4', 'b4b', 'b4loose', 'b5', 'b6', 'c2', 'checks', 'flags']:
            tot[k] += r[k]
        tot['n'] += 1
        if r['g2'] == 'F':
            tot['g2fail'] += 1
        if r['g3'] == 'F':
            tot['g3fail'] += 1
            
    print('-' * len(hdr))
    print('sections: %(n)d (skipped already-transformed: %(skipped)d) | eq: %(b3)d | fn: %(b4)d/%(b4b)d(+%(b4loose)d loose) | thm: %(b5)d | ex: %(b6)d | eng: %(c2)d | CHECK: %(checks)d | warns: %(flags)d | G2-fail: %(g2fail)d | G3-fail: %(g3fail)d' % dict(tot, skipped=skipped))

    if args.json:
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump({'rows': rows, 'summary': dict(tot, skipped=skipped, total_found=total_found)}, f, ensure_ascii=False, indent=2)
        print(f"已导出统计报告至: {args.json}")

if __name__ == '__main__':
    main()
