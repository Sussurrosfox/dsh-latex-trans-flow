# -*- coding: utf-8 -*-
r"""
fix_bare_headers.py —— 漏包装编号头的幂等机械补包（S1，无 API 依赖，通用增强版）。
处理三类 residue（scan_numbering.py 定价）：
  G1a  裸行头   ^N.N 应用/示例/结论/说明 <正文同句>   （12 项）
  G1b  吞头     ^\subsection*{N.N 应用/示例}$              （II·7.10 的 10.14）
  G1d  新词表   结论/说明 裸行                            （III·10.3 / III·11.2 等）
命名无类型头（II·6.4 "4.13 微积分第二基本定理"）不在本脚本范围，留交 agent。

打包规则与 preprocess.rule_b5 同源：
  * 嵌套 TRACKED 环境深度跟踪；结构性边界（新定理 env / \section / \subsection* /
    下一个裸头 / \HRRule / EOF）才关闭；
  * 定理体内 "证明 … ∎" 拆成 \begin{proof}，∎ 后重开原 env，保持 (a)(b)(c)(d) 结构；
  * label 一律 thm:章-节.原书序号（OCR 头编号派生，事后零顺延）。

每文件自动门禁：
  1. math token 流与修前完全相等（剥离脚注/注释，gate_check 归一化）；
  2. 本类型裸头清零；env 增量 == 补包数；新 label 形态合规；
  3. scan_numbering.scan_file 复核 missing/bare/Δ；
  4. xelatex 独立编译（自动生成 compile_ 包装，--compile 开启）。
"""
import argparse
import io
import os
import re
import shutil
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

try:
    from config_utils import ensure_utf8_stdio, find_project_root, load_project_volumes
    ensure_utf8_stdio()
except ImportError:
    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass
    def ensure_utf8_stdio():
        pass
    def find_project_root(start_path=None):
        return os.path.abspath(start_path) if start_path else os.getcwd()
    def load_project_volumes(project_root=None, config_file=None, custom_dirs=None):
        return [("Root", project_root or os.getcwd())]

ROOT = find_project_root()

import gate_check
import scan_numbering

DEFAULT_TYPE_MAP = {
    '应用': 'example', '示例': 'example', '例与注': 'example', '例': 'example',
    '结论': 'conclusion', '说明': 'remark',
}
DEFAULT_TYPES_ALT_KEYS = ['应用', '示例', '结论', '说明']

TYPE_MAP = dict(DEFAULT_TYPE_MAP)
TYPES_ALT = r'(?:' + '|'.join(DEFAULT_TYPES_ALT_KEYS) + r')'

BASE_THM_ENVS = [
    'theorem', 'proposition', 'lemma', 'corollary', 'definition',
    'example', 'remark', 'axiom', 'conclusion', 'proof'
]

BARE_RE = re.compile(r'^(\d+)\.(\d+)\s*(' + TYPES_ALT + r')\b\s*(.*)$')
SUBHEAD_RE = re.compile(r'^\s*\\subsection\*\{(\d+)\.(\d+)\s*(' + TYPES_ALT + r')\s*\}\s*$')
SECRE = re.compile(r'\\section\{[^}]*\}\\label\{(sec:\d+-\d+)\}')
BEGIN_ANY = re.compile(r'\\begin\{(' + '|'.join(BASE_THM_ENVS) + r')\}')
TRACKED_OPEN = re.compile(r'\\begin\{(' + '|'.join(
    ('itemize', 'enumerate', 'center', 'figure', 'table', 'tabular',
     'tcolorbox', 'mdframed', 'minipage', 'align', 'align*', 'gather',
     'gather*', 'multline', 'flalign', 'eqnarray')) + r')\}')
TRACKED_CLOSE = re.compile(r'\\end\{(' + '|'.join(
    ('itemize', 'enumerate', 'center', 'figure', 'table', 'tabular',
     'tcolorbox', 'mdframed', 'minipage', 'align', 'align*', 'gather',
     'gather*', 'multline', 'flalign', 'eqnarray')) + r')\}')
STRUCT = re.compile(r'^(\\(?:sub)?section\*?\{|\\HRRule|\\end\{document\})')
PROOF_START = re.compile(r'^\s*证明[.:：]?\s*')
QED = re.compile(r'\s*[∎■Ⅰ]\s*$')
BAL = re.compile(r'\\(begin|end)\{([A-Za-z*]+)\}')


def update_type_mappings(extra_types=None):
    """根据 extra_types 扩充 TYPE_MAP 和 TYPES_ALT，并同步更新相关正则。"""
    global TYPE_MAP, TYPES_ALT, BARE_RE, SUBHEAD_RE, BEGIN_ANY
    if not extra_types:
        return

    items = []
    if isinstance(extra_types, str):
        items = [extra_types]
    elif isinstance(extra_types, (list, tuple, set)):
        items = list(extra_types)
    elif isinstance(extra_types, dict):
        for k, v in extra_types.items():
            items.append(f"{k}:{v}")

    alt_keys = set(DEFAULT_TYPES_ALT_KEYS)
    thm_envs = set(BASE_THM_ENVS)

    for raw in items:
        for pair in re.split(r'[,;]+', str(raw).strip()):
            pair = pair.strip()
            if not pair:
                continue
            if ':' in pair:
                k, v = pair.split(':', 1)
            elif '=' in pair:
                k, v = pair.split('=', 1)
            else:
                continue
            k = k.strip()
            v = v.strip()
            if k and v:
                TYPE_MAP[k] = v
                alt_keys.add(k)
                thm_envs.add(v)

    sorted_keys = sorted(alt_keys, key=len, reverse=True)
    TYPES_ALT = r'(?:' + '|'.join(re.escape(k) for k in sorted_keys) + r')'
    BARE_RE = re.compile(r'^(\d+)\.(\d+)\s*(' + TYPES_ALT + r')\b\s*(.*)$')
    SUBHEAD_RE = re.compile(r'^\s*\\subsection\*\{(\d+)\.(\d+)\s*(' + TYPES_ALT + r')\s*\}\s*$')

    sorted_envs = sorted(thm_envs, key=len, reverse=True)
    BEGIN_ANY = re.compile(r'\\begin\{(' + '|'.join(re.escape(e) for e in sorted_envs) + r')\}')


def build_type_matchers(extra_types=None):
    """向后兼容辅助函数：更新并返回当前 (TYPE_MAP, BARE_RE, SUBHEAD_RE)。"""
    if extra_types:
        update_type_mappings(extra_types)
    return TYPE_MAP, BARE_RE, SUBHEAD_RE


def pick_work(d):
    api = d + '.api.tex'
    pre = d + '.pre.tex'
    return api if os.path.exists(api) else pre


def wrap_file(path, type_map=None, bare_re=None, subhead_re=None):
    """返回 (new_text, fixes, errors)。fixes=[(line, class, label)]。"""
    tmap = type_map if type_map is not None else TYPE_MAP
    b_re = bare_re if bare_re is not None else BARE_RE
    sh_re = subhead_re if subhead_re is not None else SUBHEAD_RE

    wt = gate_check.read_file_safely(path)
    lines = wt.split('\n')
    out = []
    errs = []
    state = None            # None | 'thm' | 'proof'
    env_of = None           # 当前 env 名（thm 态）
    env_saved = None        # proof 态期间记住的 env 名
    in_proof = False        # thm 态下是否处于嵌套 proof 中
    depth = 0
    pending = False
    fixes = []

    m0 = SECRE.search(wt)
    if not m0:
        return None, [], ['无 sec: 标签，跳过']
    ch, sec = m0.group(1)[4:].split('-')

    def close_env():
        nonlocal state, env_of, env_saved, pending, in_proof
        if state == 'proof':
            out.append('\\end{proof}')
            out.append('\\begin{%s}' % env_saved)
            state, env_of = 'thm', env_saved
        elif state == 'thm':
            if in_proof:
                out.append('\\end{proof}')
                in_proof = False
            out.append('\\end{%s}' % env_of)
            state, env_of = None, None
        pending = False

    for i, line in enumerate(lines, 1):
        st = line.strip()

        # 跟踪非定理环境深度
        o_cnt = len(TRACKED_OPEN.findall(st))
        c_cnt = len(TRACKED_CLOSE.findall(st))
        depth += o_cnt - c_cnt

        mb = b_re.match(st) if not st.startswith('%') else None
        ms = sh_re.match(st) if not st.startswith('%') else None
        is_struct = bool(STRUCT.match(st) or BEGIN_ANY.search(st))

        if (mb or ms or is_struct) and state:
            if depth <= 0:
                close_env()
            else:
                pending = True

        if pending and depth <= 0:
            close_env()

        if ms:
            ch_item, num_item, k = ms.group(1), ms.group(2), ms.group(3)
            env = tmap.get(k, 'example')
            lab = 'thm:%s-%s.%s' % (ch, sec, num_item)
            out.append('\\begin{%s}\\label{%s}' % (env, lab))
            state, env_of = 'thm', env
            fixes.append((i, 'G1b-吞头 ' + k, lab))
            continue

        if mb:
            ch_item, num_item, k, rest = mb.group(1), mb.group(2), mb.group(3), mb.group(4)
            env = tmap.get(k, 'example')
            lab = 'thm:%s-%s.%s' % (ch, sec, num_item)
            out.append('\\begin{%s}\\label{%s}' % (env, lab))
            state, env_of = 'thm', env
            fixes.append((i, 'G1a-裸行 ' + k, lab))
            if rest:
                m_pf = PROOF_START.match(rest)
                if m_pf:
                    out.append('\\begin{proof}')
                    in_proof = True
                    tail = rest[m_pf.end():]
                    if tail:
                        out.append(tail)
                else:
                    out.append(rest)
            continue

        if state == 'thm' and not in_proof:
            m_pf = PROOF_START.match(st)
            if m_pf:
                out.append('\\begin{proof}')
                in_proof = True
                tail = st[m_pf.end():]
                if tail:
                    out.append(tail)
                continue

        if in_proof and QED.search(st):
            st_clean = QED.sub('', st)
            if st_clean.strip():
                out.append(st_clean)
            out.append('\\end{proof}')
            in_proof = False
            continue

        out.append(line)

    if state:
        if in_proof:
            out.append('\\end{proof}')
        out.append('\\end{%s}' % env_of)

    return '\n'.join(out), fixes, errs


def balance_check(text):
    r"""env 配对校验（含行号）。"""
    stack = []
    bad = []
    for m in BAL.finditer(text):
        kind, env = m.group(1), m.group(2)
        if env == 'document':
            continue
        ln = text[:m.start()].count('\n') + 1
        if kind == 'begin':
            stack.append((env, ln))
        else:
            if stack and stack[-1][0] == env:
                stack.pop()
            else:
                bad.append((env, ln))
    if not stack and not bad:
        return True, '平衡'
    return False, ('未闭%s 错配%s' % (stack[:4], bad[:4]))


def resolve_preamble(target_dir, preamble=None, project_root=None):
    """
    解析编译所需的 preamble 相对引用路径（统一转换为适用于 TeX 的正斜杠路径）。
    1. 若指定 preamble，优先查找该文件；
    2. 缺省时自动搜索 ../preamble.tex 或项目根目录下的 preamble.tex；
    3. 若均未命中，兜底返回 '../preamble.tex'。
    """
    if preamble:
        cand = preamble
        if not os.path.isabs(cand):
            for base in [os.getcwd(), project_root, target_dir]:
                if base:
                    p = os.path.abspath(os.path.join(base, cand))
                    if os.path.exists(p):
                        cand = p
                        break
        if os.path.isabs(cand):
            try:
                return os.path.relpath(cand, target_dir).replace('\\', '/')
            except Exception:
                return cand.replace('\\', '/')
        return cand.replace('\\', '/')

    # 缺省候选 1: target_dir 上级目录下的 ../preamble.tex
    p1 = os.path.join(target_dir, '..', 'preamble.tex')
    if os.path.exists(p1):
        return '../preamble.tex'

    # 缺省候选 2: project_root 下的 preamble.tex
    if project_root:
        p2 = os.path.join(project_root, 'preamble.tex')
        if os.path.exists(p2):
            try:
                return os.path.relpath(p2, target_dir).replace('\\', '/')
            except Exception:
                return p2.replace('\\', '/')

    # 缺省候选 3: target_dir 同级目录下的 preamble.tex
    p3 = os.path.join(target_dir, 'preamble.tex')
    if os.path.exists(p3):
        return 'preamble.tex'

    return '../preamble.tex'


def compile_check(path, preamble=None, project_root=None, preamble_path=None):
    """独立编译检查，解耦前置宏包模板路径。"""
    d = os.path.dirname(os.path.abspath(path))
    f = os.path.basename(path)
    tag = 'compile_fix_%s' % f
    wrap = os.path.join(d, tag)
    effective_preamble = preamble or preamble_path
    pre_tex = resolve_preamble(d, preamble=effective_preamble, project_root=project_root)

    io.open(wrap, 'w', encoding='utf-8', newline='\n').write(
        '\\input{%s}\n\\begin{document}\n\\input{%s}\n\\end{document}\n' % (pre_tex, f))
    try:
        r = subprocess.run(['xelatex', '-interaction=nonstopmode', tag],
                           cwd=d, capture_output=True, text=True, timeout=600,
                           encoding='utf-8', errors='replace')
        errs = [l for l in r.stdout.splitlines() if l.startswith('!')]
        for j in ('log', 'aux', 'out', 'xdv', 'pdf'):
            q = os.path.join(d, tag.replace('.tex', '.' + j))
            if os.path.exists(q):
                try:
                    os.remove(q)
                except OSError:
                    pass
        return r.returncode == 0 and not errs, errs[:5]
    except Exception as e:
        return False, [str(e)]


def iter_targets(root_dir=None, custom_dirs=None):
    project_root = os.path.abspath(root_dir) if root_dir else ROOT
    volumes = load_project_volumes(project_root=project_root, custom_dirs=custom_dirs)
    seen = set()
    for vname, vdir in volumes:
        if not os.path.exists(vdir):
            continue
        cand_roots = [
            os.path.join(vdir, 'chapters_translate'),
            os.path.join(vdir, 'chapters'),
            vdir
        ]
        target_root = next((cr for cr in cand_roots if os.path.isdir(cr)), None)
        if not target_root:
            continue

        for root, dirs, files in os.walk(target_root):
            dirs.sort()
            for f in sorted(files):
                if f.startswith('compile') or f.startswith('tmp'):
                    continue
                m = re.match(r'(\d+_Section_\d+)\.(?:pre|api)\.tex$', f)
                if not m:
                    m = re.match(r'([a-zA-Z0-9_-]+)\.(?:pre|api)\.tex$', f)
                if m:
                    stem = m.group(1)
                    stem_path = os.path.join(root, stem)
                    if stem_path not in seen:
                        seen.add(stem_path)
                        yield stem_path


def main():
    ap = argparse.ArgumentParser(description="漏包装编号头的幂等机械补包与门禁校验工具")
    ap.add_argument('--root', default=None, help='项目根目录路径（缺省自动探测）')
    ap.add_argument('--dirs', nargs='*', default=None, help='自定义卷/章目录列表')
    ap.add_argument('--preamble', default=None, help='宏包模板路径（缺省自动搜索 ../preamble.tex 或项目根目录下的 preamble.tex）')
    ap.add_argument('--extra-types', default=None, help='扩充定理类型映射（如 "性质:property"，支持多次指定或逗号分隔）')
    ap.add_argument('--apply', action='store_true', help='执行落盘写回（仅在门禁通过时）')
    ap.add_argument('--only', default=None, help='节名前缀，如 03_Section_3')
    ap.add_argument('--compile', action='store_true', help='开启 xelatex 独立编译验证')
    args = ap.parse_args()

    if args.extra_types:
        update_type_mappings(args.extra_types)

    project_root = os.path.abspath(args.root) if args.root else ROOT
    custom_dirs = None
    if args.dirs:
        custom_dirs = []
        for d in args.dirs:
            for sub in d.split(','):
                sub = sub.strip()
                if sub:
                    custom_dirs.append(sub)

    total_fix = 0
    total_files = 0
    for d in iter_targets(root_dir=project_root, custom_dirs=custom_dirs):
        stem = os.path.basename(d)
        if args.only and not stem.startswith(args.only):
            continue
        work = pick_work(d)
        if not os.path.exists(work):
            continue
        new, fixes, errs = wrap_file(work, type_map=TYPE_MAP, bare_re=BARE_RE, subhead_re=SUBHEAD_RE)
        if not new:
            for e in errs:
                print('\n### %s / %s' % (os.path.basename(os.path.dirname(d)),
                                         os.path.basename(work)))
                print('   错', e)
            continue
        if not fixes and not errs:
            continue
        total_files += 1
        total_fix += len(fixes)
        print('\n### %s / %s' % (os.path.basename(os.path.dirname(d)),
                                 os.path.basename(work)))
        for ln, k, lab in fixes:
            print('   L%-5d %s  %s' % (ln, k, lab))
        for e in errs:
            print('   错', e)
        if not args.apply:
            continue
        # ---- 门禁 1：math token 比对（修前 vs 修后） ----
        before = gate_check.read_file_safely(work)
        ok4, msg4 = gate_check.check_math_tokens(before, new)
        # ---- 门禁 2：形式（修后零残留）----
        bare_left = len([l for l in new.split('\n')
                         if not l.strip().startswith('%') and BARE_RE.match(l.strip())])
        sub_left = len([l for l in new.split('\n') if SUBHEAD_RE.match(l.strip())])
        ok2 = (bare_left == 0 and sub_left == 0)
        # ---- 门禁 1.5：env 平衡 ----
        okb, msgb = balance_check(new)
        if not okb:
            print('   门禁1.5 env平衡: FAIL %s（不写回）' % msgb)
            continue
        # ---- 写回 + 门禁 3：scan 复核 ----
        io.open(work, 'w', encoding='utf-8', newline='\n').write(new + '\n'
                                                                  if not new.endswith('\n') else new)
        r = scan_numbering.scan_file(os.path.dirname(work), stem)
        print('   门禁1 数学token: %s | %s' % ('PASS' if ok4 else 'FAIL', msg4))
        print('   门禁1.5 env平衡: %s' % ('PASS' if okb else 'FAIL'))
        print('   门禁2 裸头残留: %s (bare=%d sub=%d)' % ('PASS' if ok2 else 'FAIL', bare_left, sub_left))
        if r:
            print('   门禁3 scan: missing=%s bare=%d Δ=%s' % (
                r['missing'], len(r['bare_headers']), r['shift_onset']))
        if args.compile:
            ok1, e1 = compile_check(work, preamble=args.preamble, project_root=project_root)
            print('   门禁4 编译: %s %s' % ('PASS' if ok1 else 'FAIL', e1))
    print('\n=== 合计：%d 节 / %d 处补包%s ===' % (
        total_files, total_fix, '（已写回）' if args.apply else '（dry-run）'))


if __name__ == '__main__':
    main()
