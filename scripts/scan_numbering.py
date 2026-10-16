# -*- coding: utf-8 -*-
r"""
scan_numbering.py - 全书编号一致性普查与计数器模拟分析工具（通用增强版）

位置：机械预处理(preprocess.py) + API 复核(api_refine.py) 之后、R-agent 交叉引用之前。
目的：把"自动编号偏移"这类系统性隐患一次定价，为"先修结构、后统一顺延"方案提供数据。

对每节（.api.tex 优先，否则 .pre.tex；对照 .tex OCR 基线）检查：
  G 漏包   基线有的编号项，成品中无对应 env（裸文本头仍留在文件里）
  E 多包   成品出现了基线没有的编号项
  S 错位   \label 后缀 != 模拟计数器值（OCR 头编号抄错 / 文件中途 \section 复位）
  X 习题断档 exercise 标签序号不连续或数量与基线不符
  L 形态   label 不合规则 / 文件内重复 / 节内多个 \section{} / \section*{ 吞定理头

计数器模拟规则（与 preamble 一致）：定理族共用一个 [section] 计数器，
每遇 \section{...}\label{sec:...} 复位；equation 同为 [section] 计数器；
exercise 独立 [section] 计数器。
"""
import io
import json
import os
import re
import sys
import argparse

try:
    from config_utils import ensure_utf8_stdio, find_project_root, load_project_volumes
    ensure_utf8_stdio()
except ImportError:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    find_project_root = lambda: os.getcwd()
    load_project_volumes = lambda r: [("Root", r or os.getcwd())]

THM_ENVS = ('theorem', 'proposition', 'lemma', 'corollary', 'definition',
            'example', 'remark', 'axiom', 'criterion', 'rule', 'conclusion')
CN_TYPES = r'(?:定理|命题|引理|推论|定义|公理|判据|法则|示例|例与注|例|例子|注记|备注|注|评注|应用|结论|说明)'
RAW_THM = re.compile(
    r'(?:^|\n|(?<=[。！？\.\s])|\\(?:sub)*section\*\{)\s*(?:'
    r'(\d+)\.(\d+)\s*' + CN_TYPES +
    r'|' +
    CN_TYPES + r'\s*([A-Za-z0-9一二三四五六七八九十]+)[\.．、:：]?(\d*)'
    r')'
)
BARE = re.compile(
    r'^\s*(?:(\d+)\.(\d+)\s*' + CN_TYPES + r'\b|' +
    CN_TYPES + r'\s*([A-Za-z0-9一二三四五六七八九十]+)[\.．、:：]?(\d*)\b)'
)
BEGIN = re.compile(r'\\begin\{(' + '|'.join(THM_ENVS) + r')\}(\[[^\]]*\])?')
SECRE = re.compile(r'\\(?:chapter|section)\{[^}]*\}\\label\{(?:chap|sec):([^}]+)\}')
SECANY = re.compile(r'\\(?:chapter|section)\{')
SECSTAR = re.compile(r'\\(?:chapter|section)\*\{([^}]*)\}')
SUBHEAD = re.compile(r'\\(?:sub)*section\*\{(\d+)\.(\d+)\s*' + CN_TYPES)
THM_IN_STAR = re.compile(r'^\d+\.\d+\s*' + CN_TYPES)
EXB = re.compile(r'\\begin\{exercise\}(\[[^\]]*\])?(\\label\{ex:([^}]+)\})?')
EQB = re.compile(r'\\begin\{equation\}[^\n]*\\label\{eq:([^}]+)\}')
LABEL = re.compile(r'\\label\{([^}]+)\}')
GOODLAB = re.compile(r'^(chap|sec|subsec|thm|eq|ex|fig):(?:\d+|[A-Z])(?:-[\w\.\-]+)?$')
XNUM = re.compile(r'^\s*(\d{1,2})\s+\S')
EN_TYPED = re.compile(
    r'^\s*(?:\\(?:sub)*section\*\{)?\s*(\d+)\.(\d+)\s+'
    r'(Theorem|Proposition|Lemma|Corollary|Definition|Axiom|'
    r'Examples?|Remarks?|Applications?|Conclusion|Fact|Observation|Convention|'
    r'Notation|Rule|Criterion)\b', re.IGNORECASE)
EN_NAMED = re.compile(
    r'^\s*(?:\\(?:sub)*section\*\{)?\s*(\d+)\.(\d+)\s+[A-Z][a-z]')


def scan_file(dirpath, stem, origin_dir_name='chapters_transAndOrigin'):
    # 若存在原始备份目录，优先使用原始基线
    orig_cand = os.path.join(os.path.dirname(dirpath), 'chapters_orig_backup', stem + '.tex')
    if os.path.exists(orig_cand):
        base = orig_cand
    else:
        base = os.path.join(dirpath, stem + '.tex')
    api = os.path.join(dirpath, stem + '.api.tex')
    pre = os.path.join(dirpath, stem + '.pre.tex')
    if not os.path.exists(base):
        return None
    work = api if os.path.exists(api) else pre
    if not os.path.exists(work):
        return None
    bt = io.open(base, encoding='utf-8').read()
    wt = io.open(work, encoding='utf-8').read()
    blines = bt.split('\n')
    wlines = wt.split('\n')

    out = {'file': os.path.basename(dirpath) + '/' + stem,
           'work': os.path.basename(work)}

    bt_clean = re.sub(r'\\HRule\s*\n.*?\n\s*\\HRule', '', bt, flags=re.DOTALL)
    expected = []
    for m in RAW_THM.finditer(bt_clean):
        g = m.groups()
        if g[0] and g[1]:
            expected.append(f"{g[0]}.{g[1]}")
        elif g[2]:
            sub = f".{g[3]}" if g[3] else ""
            expected.append(f"{g[2]}{sub}")
    CN_MAP = {'一': '1', '二': '2', '三': '3', '四': '4', '五': '5', '六': '6', '七': '7', '八': '8', '九': '9', '十': '10'}
    exp_items = []
    for e in expected:
        if '.' in e:
            part = e.split('.')[-1]
            part = CN_MAP.get(part, part)
            if part.isdigit():
                exp_items.append(int(part))
        else:
            e_norm = CN_MAP.get(e, e)
            if e_norm.isdigit():
                exp_items.append(int(e_norm))
    exp_items = sorted(set(exp_items))

    thm_ctr = eq_ctr = ex_ctr = 0
    thm_labs, eq_labs, ex_labs = [], [], []
    mism, sec_lines, secstar_lines = [], [], []
    bare_hits, dup, badlab = [], [], []
    seen = {}
    shifts = []          # (line, label_suffix - counter) 供定位偏移起点
    for i, line in enumerate(wlines, 1):
        st = line.strip()
        ms = SECRE.search(st)
        if ms:
            sec_lines.append(i)
            thm_ctr = eq_ctr = ex_ctr = 0
            continue
        m_step = re.search(r'\\(?:stepcounter\{theorem\}|addtocounter\{theorem\}\{(\d+)\})', st)
        if m_step:
            delta = int(m_step.group(1)) if m_step.group(1) else 1
            thm_ctr += delta
            continue
        for m in SECSTAR.finditer(st):
            if THM_IN_STAR.match(m.group(1).strip()):
                secstar_lines.append(i)
        mb = BARE.match(st)
        if mb and not st.startswith('%'):
            g = mb.groups()
            num_desc = f"{g[0]}.{g[1]}" if (g[0] and g[1]) else (f"{g[2]}.{g[3]}" if g[3] else str(g[2]))
            bare_hits.append((i, num_desc))
        for mh in SUBHEAD.finditer(st):
            bare_hits.append((i, mh.group(1) + '.' + mh.group(2) + '(§*)'))
        # ---- 定理族 env ----
        for m in BEGIN.finditer(st):
            thm_ctr += 1
            lab = re.search(r'\\label\{(thm:[^}]+)\}', st[m.end():m.end() + 40])
            if not lab:
                for j in range(1, 4):
                    k = i - 1 + j
                    nxt = wlines[k].strip() if k < len(wlines) else ''
                    if nxt.startswith('\\label{thm:'):
                        lab = re.match(r'\\label\{(thm:[^}]+)\}', nxt)
                        break
                    if nxt and not nxt.startswith('%'):
                        break
            if lab:
                full = lab.group(1)
                thm_labs.append(full)
                mm = re.match(r'thm:(?:(\d+|[A-Z])-)?([A-Za-z0-9\.\-]+)$', full)
                if not mm:
                    mism.append(('thm形态', full, i))
                else:
                    last_num = mm.group(2).split('.')[-1].split('-')[-1]
                    if last_num.isdigit():
                        idx = int(last_num)
                        shifts.append((i, idx - thm_ctr))
                        if idx != thm_ctr:
                            mism.append(('thm', full, thm_ctr, i))
        # ---- 习题 env ----
        me = EXB.search(st)
        if me:
            ex_ctr += 1
            if me.group(3):
                v = me.group(3)
                ex_labs.append(v)
                mm = re.match(r'(?:(\d+|[A-Z])-)?([A-Za-z0-9\.\-]+)$', v)
                if not mm:
                    mism.append(('ex形态', v, i))
                else:
                    last_num = mm.group(2).split('.')[-1].split('-')[-1]
                    if last_num.isdigit() and int(last_num) != ex_ctr:
                        mism.append(('ex', v, ex_ctr, i))
        # ---- 公式 env ----
        mq = EQB.search(st)
        if mq:
            eq_ctr += 1
            v = mq.group(1)
            eq_labs.append(v)
            mm = re.match(r'(?:(\d+|[A-Z])-)?([A-Za-z0-9\.\-]+)$', v)
            if not mm:
                mism.append(('eq形态', v, i))
            else:
                last_num = mm.group(2).split('.')[-1].split('-')[-1]
                if last_num.isdigit() and int(last_num) != eq_ctr:
                    mism.append(('eq', v, eq_ctr, i))
        # ---- label 形态 / 重复 ----
        for lm in LABEL.finditer(line):
            lb = lm.group(1)
            if not GOODLAB.match(lb):
                badlab.append((i, lb))
            if lb in seen:
                dup.append((lb, seen[lb], i))
            seen[lb] = i

    got_items = []
    for lb in thm_labs:
        mm = re.match(r'thm:(?:(\d+|[A-Z])-)?([A-Za-z0-9\.\-]+)$', lb)
        if mm:
            last_part = mm.group(2).split('.')[-1].split('-')[-1]
            if last_part.isdigit():
                got_items.append(int(last_part))
    got_items = sorted(set(got_items))

    # ---------- 中英对照原件的编号锚（英文头，line-start） ----------
    en_items = []
    if 'chapters_translate' in dirpath:
        en_path = dirpath.replace('chapters_translate', origin_dir_name)
    else:
        en_path = None
    en_file = os.path.join(en_path, stem + '.tex') if en_path else None
    if en_file and os.path.exists(en_file):
        et = io.open(en_file, encoding='utf-8').read()
        for l in et.split('\n'):
            s = l.strip()
            if s.startswith('%'):
                continue
            m = EN_TYPED.match(s) or (EN_NAMED.match(s) if not EN_TYPED.match(s) else None)
            if m:
                en_items.append(int(m.group(2)))
        en_items = sorted(list(dict.fromkeys(en_items)))
        en_missing = [x for x in en_items if x not in got_items]
        en_extra = [x for x in got_items if x not in en_items]
        en_seq_ok = en_items == got_items
    else:
        en_items = []
        en_missing = []
        en_extra = []
        en_seq_ok = True
    missing = [x for x in exp_items if x not in got_items]
    extra = [x for x in got_items if x not in exp_items]

    ex_base = 0
    start = None
    for i, l in enumerate(blines):
        s = l.strip()
        if s.startswith('习题') or s.startswith('练习'):
            start = i
    if start is not None:
        for l in blines[start + 1:]:
            if XNUM.match(l) and not BARE.match(l):
                ex_base += 1

    # 偏移起点：delta 首次偏离 0 的行
    onset = None
    for i, d in shifts:
        if d != 0:
            onset = (i, d)
            break
    cent = {}
    for i, d in shifts:
        cent[d] = cent.get(d, 0) + 1

    is_amann_slice = 'chapters_translate' in dirpath
    sec_mult_err = (len(sec_lines) > 1) if is_amann_slice else False

    out.update({
        'dirpath': dirpath,
        'expected_n': len(exp_items), 'thm_envs': len(thm_labs),
        'missing': missing, 'extra': extra, 'bare_headers': bare_hits,
        'en_items': en_items, 'en_missing': en_missing, 'en_extra': en_extra,
        'en_seq_ok': en_seq_ok,
        'sim_mismatch': mism, 'dup_labels': dup, 'bad_labels': badlab,
        'sec_lines': sec_lines, 'secstar_thm': secstar_lines,
        'ex_envs': len(ex_labs), 'ex_base': ex_base,
        'eq_envs': len(eq_labs), 'shift_onset': onset,
        'shift_centers': cent,
    })
    out['OK'] = not (missing or extra or bare_hits or mism or dup or badlab
                     or sec_mult_err or secstar_lines
                     or len(ex_labs) != ex_base or en_missing or en_extra)
    return out


def main():
    parser = argparse.ArgumentParser(description="全书编号一致性普查与计数器模拟分析")
    parser.add_argument('--root', help='项目根目录路径（缺省自动探测）', default=None)
    parser.add_argument('--out-json', help='普查结果 JSON 存储路径（默认 numbering_scan.json）', default=None)
    parser.add_argument('--origin-dir', help='双语对照基准目录名称（默认 chapters_transAndOrigin）', default='chapters_transAndOrigin')
    parser.add_argument('--file', help='仅普查指定的单个文件路径', default=None)
    args = parser.parse_args()

    project_root = find_project_root(args.root)
    out_json_path = args.out_json or os.path.join(project_root, 'numbering_scan.json')

    if args.file:
        dirpath = os.path.dirname(os.path.abspath(args.file))
        stem = re.sub(r'\.(?:tex|pre\.tex|api\.tex)$', '', os.path.basename(args.file))
        res = scan_file(dirpath, stem, origin_dir_name=args.origin_dir)
        results = [res] if res else []
    else:
        volumes = load_project_volumes(project_root=project_root)
        files = {}
        for vname, vdir in volumes:
            # 兼容 chapters_translate 与 chapters
            cand_dirs = [os.path.join(vdir, 'chapters_translate'), os.path.join(vdir, 'chapters'), vdir]
            ct = None
            for cd in cand_dirs:
                if os.path.isdir(cd):
                    ct = cd
                    break
            if not ct:
                continue

            for root, dirs, fnames in os.walk(ct):
                for fn in sorted(fnames):
                    if not (fn.endswith('.tex') or fn.endswith('.pre.tex') or fn.endswith('.api.tex')):
                        continue
                    if fn.startswith('compile') or fn.startswith('tmp') or fn.startswith('_tmp'):
                        continue
                    stem = re.sub(r'\.(?:api|pre)?\.tex$', '', fn)
                    files[(root, stem)] = 1
        keys = sorted(files)
        results = [scan_file(d, s, origin_dir_name=args.origin_dir) for d, s in keys]
        results = [r for r in results if r]

    with io.open(out_json_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=1)

    bad = [r for r in results if not r['OK']]
    print('=== 普查 %d 节，异常 %d 节 ===\n' % (len(results), len(bad)))
    agg = {'missing': 0, 'extra': 0, 'bare': 0, 'sim': 0,
           'ex': 0, 'sec': 0, 'star': 0, 'dup': 0, 'en': 0}
    for r in bad:
        f = []
        if r['missing']:
            f.append('漏包%s' % r['missing'])
            agg['missing'] += len(r['missing'])
        if r['extra']:
            f.append('多包%s' % r['extra'])
            agg['extra'] += len(r['extra'])
        if r['bare_headers']:
            f.append('裸头%d' % len(r['bare_headers']))
            agg['bare'] += len(r['bare_headers'])
        if r['sim_mismatch']:
            f.append('错位%d(起L%sΔ%s)' % (len(r['sim_mismatch']),
                                          r['shift_onset'][0] if r['shift_onset'] else '?',
                                          r['shift_onset'][1] if r['shift_onset'] else '?'))
            agg['sim'] += len(r['sim_mismatch'])
        if r['ex_envs'] != r['ex_base']:
            f.append('习题 %d!=%d' % (r['ex_envs'], r['ex_base']))
            agg['ex'] += 1
        if ('chapters_translate' in r.get('dirpath', '')) and len(r['sec_lines']) > 1:
            f.append('多section%s' % r['sec_lines'])
            agg['sec'] += 1
        if r['secstar_thm']:
            f.append('吞头L%s' % r['secstar_thm'])
            agg['star'] += 1
        if r['dup_labels'] or r['bad_labels']:
            f.append('label问题%d' % (len(r['dup_labels']) + len(r['bad_labels'])))
            agg['dup'] += 1
        if r['en_missing'] or r['en_extra']:
            f.append('锚缺%s多%s' % (r['en_missing'], r['en_extra']))
            agg['en'] += len(r['en_missing']) + len(r['en_extra'])
        print('%-40s %s' % (r['file'], '  '.join(f)))
    print()
    print('=== 汇总 ===')
    for k, v in agg.items():
        print('  %-8s %d' % (k, v))
    print()
    if agg['bare'] > 0:
        print('=== 裸编号头（漏包直证）===')
        for r in bad:
            for ln, num in r['bare_headers']:
                print('  %-40s L%-5d %s' % (r['file'], ln, num))
        print()
    print('=== 英文原件锚：成品 label 缺失 / 多余 的编号 ===')
    for r in bad:
        if r['en_missing'] or r['en_extra']:
            print('  %-40s 缺%s 多%s 顺序一致=%s' % (
                r['file'], r['en_missing'], r['en_extra'], r['en_seq_ok']))
    print()
    print('=== 计数器错位明细 ===')
    for r in bad:
        for row in r['sim_mismatch']:
            if row[0] == 'thm':
                print('  %-40s L%-5d %s 显示应为%s' % (r['file'], row[3], row[1], row[2]))
            else:
                print('  %-40s L%-5d [%s] %s' % (r['file'], row[-1], row[0], row[1]))
    print()
    print('=== 错位分布（label后缀-计数器 的取值:次数）===')
    for r in bad:
        if r['shift_centers']:
            print('  %-40s %s' % (r['file'], r['shift_centers']))

    print(f"\n[OK] 普查结果已导出至: {out_json_path}")
    if bad:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
