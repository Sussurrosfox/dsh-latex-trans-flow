# -*- coding: utf-8 -*-
r"""
批量 API 复核驱动 (batch_api_refine.py) v2：对全部待处理节运行 api_refine 分段复核。

- 断点续跑：只处理【无 .api.tex】或【.api.tex 仍有 % CHECK 残留】的节；
  中断后重跑不重复劳动，失败的节自动重试。
- 段级并发（--workers，默认 10），汇编+五门禁并发（--final-workers，默认 3）。
- 产物：<节>.api.tex + <节>.api.report.md；
  门禁全过且 CHECK 清零的节自动采纳（写入 .pre.tex）。
- 编译产物在通过门禁后自动清理，失败保留日志。
- 汇总表 + 需关注清单写入 batch_api_refine.log。

用法：
    python batch_api_refine.py                    # 全量（三卷）
    python batch_api_refine.py --book II          # 只跑卷 II
    python batch_api_refine.py --workers 10       # 段并发 10（默认）
    python batch_api_refine.py --dirs path/to/v1  # 指定处理目录
"""

import os
import re
import sys
import io
import time
import argparse
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from config_utils import (ensure_utf8_stdio, find_project_root,
                          load_project_volumes, load_llm_config,
                          parse_roman_or_int)
ensure_utf8_stdio()

import api_refine
from api_refine import (split_segments, process_segment, read,
                        sweep_residual_checks)
from gate_check import (check_clean_macros, check_label_format,
                        check_theorem_count, check_math_tokens,
                        check_compilation)


def resolve_book_volumes(project_root=None, custom_dirs=None):
    """
    通过 load_project_volumes() 动态获取各卷 chapters_translate 目录。
    返回列表: [(book_tag, chapters_translate_path), ...]
    保持向后兼容。
    """
    if project_root is None:
        project_root = find_project_root()
    vols = load_project_volumes(project_root=project_root, custom_dirs=custom_dirs)
    books = []
    for vname, vdir in vols:
        # 寻找 chapters_translate 目录
        ct_dir = None
        for cand in [
            os.path.join(vdir, 'chapters_translate'),
            os.path.join(vdir, 'chapters'),
            vdir
        ]:
            if os.path.isdir(cand):
                ct_dir = cand
                break
        if not ct_dir:
            ct_dir = os.path.join(vdir, 'chapters_translate')

        # 提取简写卷标（例如 'Vol I' -> 'I'，'Vol II' -> 'II'）
        m = re.search(r'Vol(?:ume)?\s*([IVXLCDM\d]+)', vname, re.IGNORECASE)
        b_id = m.group(1).upper() if m else vname
        books.append((b_id, ct_dir))
    return books


# 保持模块级 BOOKS 变量向后兼容
BOOKS = resolve_book_volumes()
SEG_LINES = 180
TAIL_LINES = 12

_print_lock = threading.Lock()


def log(*a):
    with _print_lock:
        print(*a)
        sys.stdout.flush()


def match_book(book_tag, filter_val):
    if not filter_val:
        return True
    f = str(filter_val).strip().upper()
    b = str(book_tag).strip().upper()
    if f == b:
        return True
    rf = parse_roman_or_int(f)
    rb = parse_roman_or_int(b)
    if rf is not None and rb is not None and rf == rb:
        return True
    return False


def collect_sections(book_filter=None, books=None, project_root=None, custom_dirs=None):
    if books is None:
        books = resolve_book_volumes(project_root=project_root, custom_dirs=custom_dirs)
    secs = []
    for book, root in books:
        if book_filter and not match_book(book, book_filter):
            continue
        if not os.path.isdir(root):
            continue
        entries = sorted(os.listdir(root))
        has_subdirs = any(os.path.isdir(os.path.join(root, e)) for e in entries)
        if has_subdirs:
            for ch in entries:
                d = os.path.join(root, ch)
                if not os.path.isdir(d):
                    continue
                for f in sorted(os.listdir(d)):
                    if not f.endswith('.tex') or f.endswith('.pre.tex') or f.endswith('.api.tex') or f.startswith('compile'):
                        continue
                    base = os.path.join(d, f[:-4])
                    pre = base + '.pre.tex'
                    if not os.path.exists(pre):
                        continue
                    api = base + '.api.tex'
                    if os.path.exists(api):
                        left = len(re.findall(r'% CHECK', read(api)))
                        if left == 0:
                            continue
                        log('重试（上批次残余 %d 个 CHECK，从 .api.tex 继续）: %s/%s' % (left, ch, f))
                    secs.append((book, ch, f[:-4], base))
        else:
            for f in entries:
                if not f.endswith('.tex') or f.endswith('.pre.tex') or f.endswith('.api.tex') or f.startswith('compile') or f.startswith('_tmp'):
                    continue
                base = os.path.join(root, f[:-4])
                pre = base + '.pre.tex'
                if not os.path.exists(pre):
                    continue
                api = base + '.api.tex'
                if os.path.exists(api):
                    left = len(re.findall(r'% CHECK', read(api)))
                    if left == 0:
                        continue
                    log('重试（上批次残余 %d 个 CHECK，从 .api.tex 继续）: %s' % (left, f))
                secs.append((book, 'chapters', f[:-4], base))
    return secs


def finalize_section(book, ch, name, base, results, segs, preamble_path=None):
    """组装 + 五门禁 + 写文件 + 自动采纳；返回汇总 dict。"""
    orig_text = read(base + '.tex')
    src_path = base + '.api.tex' if os.path.exists(base + '.api.tex') else base + '.pre.tex'
    lines = read(src_path).split('\n')
    out_lines, reports = [], []
    for k, (out, report, note, dt) in enumerate(results):
        s, e = segs[k]
        out_lines.extend(out)
        reports.append('## 段 %d/%d（原 %d–%d 行，%.1fs，%s）\n\n%s'
                       % (k + 1, len(segs), s + 1, e, dt, note, report))
    api_text = '\n'.join(out_lines)
    if not api_text.endswith('\n'):
        api_text += '\n'
    left_check = len(re.findall(r'% CHECK', api_text))

    # 残余 CHECK 清扫（小窗二选一确认）
    sweep_notes = []
    if left_check > 0:
        api_text, resolved, sweep_notes = sweep_residual_checks(api_text)
        left_check = len(re.findall(r'% CHECK', api_text))
        log('[节清扫] %s/%s：解决 %d，残余 %d' % (ch, name, resolved, left_check))

    api_path = base + '.api.tex'
    with io.open(api_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(api_text)
    report_path = base + '.api.report.md'
    with io.open(report_path, 'w', encoding='utf-8', newline='\n') as f:
        sweep_md = ('\n\n## 清扫 pass（残余 CHECK 处理）\n\n' + '\n'.join('- ' + n for n in sweep_notes)) if sweep_notes else ''
        f.write('# 复核报告（批量分段模式 v2）：%s\n\n%s%s\n' % (name, '\n\n'.join(reports), sweep_md))

    wrap = os.path.join(os.path.dirname(api_path), 'compile_' + os.path.basename(api_path))
    if r'\documentclass' not in api_text:
        if preamble_path:
            try:
                preamble_ref = os.path.relpath(os.path.abspath(preamble_path), os.path.dirname(os.path.abspath(api_path))).replace('\\', '/')
            except Exception:
                preamble_ref = os.path.abspath(preamble_path).replace('\\', '/')
        else:
            preamble_ref = '../preamble.tex'

        with io.open(wrap, 'w', encoding='utf-8', newline='\n') as f:
            f.write('\\input{%s}\n\\begin{document}\n\\input{%s.tex}\n\\end{document}\n'
                    % (preamble_ref, os.path.basename(api_path)[:-4]))
    g1, m1 = check_compilation(api_path, preamble_path=preamble_path)
    g2, m2 = check_clean_macros(api_text)
    g3, m3 = check_theorem_count(orig_text, api_text)
    g4, m4 = check_math_tokens(orig_text, api_text)
    g5, m5 = check_label_format(api_text)
    all_ok = all([g1, g2, g3, g4, g5]) and left_check == 0

    # 编译产物清理（通过后删除临时文件；失败保留日志供排查）
    if g1:
        for ext in ('.aux', '.log', '.out', '.pdf', '.tex'):
            try:
                os.remove(wrap[:-4] + ext)
            except OSError:
                pass

    applied = False
    if all_ok:
        with io.open(base + '.pre.tex', 'w', encoding='utf-8', newline='\n') as f:
            f.write(api_text)
        applied = True

    return dict(book=book, ch=ch, name=name,
                g1=g1, g2=g2, g3=g3, g4=g4, g5=g5,
                left=left_check, applied=applied,
                msg='; '.join(x for x in [m1 if not g1 else '', m2 if not g2 else '',
                                          m3 if not g3 else '', m4 if not g4 else '',
                                          m5 if not g5 else ''] if x),
                lines=len(out_lines), orig_lines=len(lines))


def main():
    ap = argparse.ArgumentParser(description='批量 API 分段复核与门禁驱动')
    ap.add_argument('--root', default=None, help='项目根目录路径（缺省自动识别）')
    ap.add_argument('--dirs', nargs='+', default=None, help='显式指定待处理的卷目录或章节目录列表')
    ap.add_argument('--book', default=None, help='只跑某卷（例如 I, II, III 或卷名）')
    ap.add_argument('--base-url', default=None, help='LLM API Base URL')
    ap.add_argument('--api-key', default=None, help='LLM API Key')
    ap.add_argument('--model', default=None, help='LLM 模型名')
    ap.add_argument('--config', default=None, help='指定配置文件路径（如 api_config.json）')
    ap.add_argument('--preamble', default=None, help='编译门禁前置宏包路径（默认 ../preamble.tex）')
    ap.add_argument('--workers', type=int, default=10, help='段级并发数（默认 10）')
    ap.add_argument('--final-workers', type=int, default=3, help='汇编门禁并发数（默认 3）')
    args = ap.parse_args()

    project_root = find_project_root(args.root)

    # 加载/覆盖 LLM 配置并同步至 api_refine 模块
    cfg = load_llm_config(args, project_root=project_root)
    if args.config and os.path.exists(args.config):
        try:
            with open(args.config, 'r', encoding='utf-8') as f:
                cdata = json.load(f)
                llm_cdata = cdata.get('llm', cdata)
                for k in ['base_url', 'api_key', 'model', 'temperature', 'max_tokens', 'timeout']:
                    if k in llm_cdata:
                        cfg[k] = llm_cdata[k]
        except Exception as e:
            log('警告：读取指定配置文件 %s 失败：%s' % (args.config, e))

    # 环境变量安全覆盖（支持 OPENAI_API_KEY 与 LLM_API_KEY）
    env_base = os.environ.get('OPENAI_BASE_URL') or os.environ.get('LLM_BASE_URL')
    env_key = os.environ.get('OPENAI_API_KEY') or os.environ.get('LLM_API_KEY')
    env_model = os.environ.get('LLM_MODEL') or os.environ.get('OPENAI_MODEL')
    if env_base:
        cfg['base_url'] = env_base
    if env_key:
        cfg['api_key'] = env_key
    if env_model:
        cfg['model'] = env_model

    # CLI 参数最高优先级（保留兼容）
    if args.base_url:
        cfg['base_url'] = args.base_url
    if args.api_key:
        cfg['api_key'] = args.api_key
    if args.model:
        cfg['model'] = args.model

    api_refine.BASE_URL = cfg.get('base_url', api_refine.BASE_URL)
    api_refine.API_KEY = cfg.get('api_key', api_refine.API_KEY)
    api_refine.MODEL = cfg.get('model', api_refine.MODEL)
    if 'temperature' in cfg:
        api_refine.TEMPERATURE = cfg['temperature']
    if 'max_tokens' in cfg:
        api_refine.MAX_TOKENS = cfg['max_tokens']
    if 'timeout' in cfg:
        api_refine.TIMEOUT = cfg['timeout']

    if not api_refine.API_KEY or api_refine.API_KEY == "YOUR_API_KEY_HERE" or not api_refine.BASE_URL:
        target_cfg = os.path.join(project_root, 'api_config.json')
        template_file = os.path.join(_SCRIPT_DIR, '..', 'api_config.template.json')
        if not os.path.exists(target_cfg) and os.path.exists(template_file):
            import shutil
            try:
                shutil.copy(template_file, target_cfg)
                log('[提示] 已为您在项目根目录下生成配置文件模板：%s' % target_cfg)
            except Exception:
                pass
        log('\n[FAIL] 缺少有效 API Key。请在项目根目录的 api_config.json 中填入真实的 API Key（或配置 OPENAI_API_KEY 环境变量）。')
        sys.exit(2)

    books = resolve_book_volumes(project_root=project_root, custom_dirs=args.dirs)
    secs = collect_sections(book_filter=args.book, books=books)
    log('=== 批量 API 复核 v2：%d 个待处理节，模型 %s，段并发 %d ===' % (
        len(secs), api_refine.MODEL, args.workers))
    if not secs:
        log('没有待处理的节（全部完成）。')
        return

    # 预分段（有 .api.tex 则从上次最佳产物继续）
    sec_data = []
    for book, ch, name, base in secs:
        src_path = base + '.api.tex' if os.path.exists(base + '.api.tex') else base + '.pre.tex'
        lines = read(src_path).split('\n')
        segs = split_segments(lines, SEG_LINES, SEG_LINES * 3)
        sec_data.append(dict(book=book, ch=ch, name=name, base=base,
                             lines=lines, segs=segs,
                             results=[None] * len(segs), remain=len(segs)))

    tasks = []
    for si, sd in enumerate(sec_data):
        for k, (s, e) in enumerate(sd['segs']):
            src = sd['lines'][s:e]
            tail = []
            if k > 0:
                ps, pe = sd['segs'][k - 1]
                prev = [l for l in sd['lines'][ps:pe] if l.strip()]
                tail = prev[-TAIL_LINES:]
            head = []
            if k + 1 < len(sd['segs']):
                hs, he = sd['segs'][k + 1]
                head = [l for l in sd['lines'][hs:he] if l.strip()][:TAIL_LINES]
            tasks.append((si, k, src, tail, head))

    t0 = time.time()
    done_segs = [0]
    total_segs = len(tasks)
    final_futures = []
    fin_pool = ThreadPoolExecutor(max_workers=args.final_workers)
    api_pool = ThreadPoolExecutor(max_workers=args.workers)

    def seg_work(si, k, src, tail, head):
        t1 = time.time()
        out, report, note = process_segment(k + 1, len(sec_data[si]['segs']), src, tail, head)
        return si, k, out, report, note, time.time() - t1

    futures = {api_pool.submit(seg_work, *t): t for t in tasks}
    for fu in as_completed(futures):
        si, k, out, report, note, dt = fu.result()
        sd = sec_data[si]
        sd['results'][k] = (out, report, note, dt)
        sd['remain'] -= 1
        done_segs[0] += 1
        log('[段 %d/%d] %s/%s 段%d %s' % (
            done_segs[0], total_segs, sd['ch'], sd['name'], k + 1, note))
        if sd['remain'] == 0:
            final_futures.append(fin_pool.submit(
                finalize_section, sd['book'], sd['ch'], sd['name'], sd['base'],
                sd['results'], sd['segs'], preamble_path=args.preamble))
    api_pool.shutdown(wait=True)

    results = []
    for fu in as_completed(final_futures):
        r = fu.result()
        results.append(r)
        log('[节完成] %s/%s：G1-%s G2-%s G3-%s G4-%s G5-%s | 残余CHECK %d | %s' % (
            r['ch'], r['name'],
            'P' if r['g1'] else 'F', 'P' if r['g2'] else 'F',
            'P' if r['g3'] else 'F', 'P' if r['g4'] else 'F',
            'P' if r['g5'] else 'F',
            r['left'], '已采纳' if r['applied'] else '未采纳'))
    fin_pool.shutdown(wait=True)

    # 汇总
    n = len(results)
    ok = sum(1 for r in results if all([r['g1'], r['g2'], r['g3'], r['g4'], r['g5']]) and r['left'] == 0)
    applied = sum(1 for r in results if r['applied'])
    log('')
    log('===== 汇总 =====')
    log('处理节数: %d | 全过: %d | 已采纳: %d | 总耗时: %.1f 分钟' % (
        n, ok, applied, (time.time() - t0) / 60))
    bad = [r for r in results if not (all([r['g1'], r['g2'], r['g3'], r['g4'], r['g5']]) and r['left'] == 0)]
    if bad:
        log('---- 需关注（%d 节）----' % len(bad))
        for r in bad:
            log('%s/%s: G1=%s G2=%s G3=%s G4=%s G5=%s 残余CHECK=%d | %s' % (
                r['ch'], r['name'],
                'P' if r['g1'] else 'F', 'P' if r['g2'] else 'F',
                'P' if r['g3'] else 'F', 'P' if r['g4'] else 'F',
                'P' if r['g5'] else 'F', r['left'], r['msg'][:200]))

    # 追加日志
    log_path = 'batch_api_refine.log'
    with io.open(log_path, 'a', encoding='utf-8') as f:
        f.write('\n=== 运行批次 %s ===\n' % time.strftime('%Y-%m-%d %H:%M:%S'))
        f.write('处理 %d 节，采纳 %d 节，耗时 %.1f 分钟\n' % (
            len(results), applied, (time.time() - t0) / 60))
        for r in results:
            f.write('%s/%s/%s: applied=%s left=%d msg=%s\n' % (
                r['book'], r['ch'], r['name'], r['applied'], r['left'], r['msg']))
    log('详细记录已追加至 %s' % log_path)


if __name__ == '__main__':
    main()
