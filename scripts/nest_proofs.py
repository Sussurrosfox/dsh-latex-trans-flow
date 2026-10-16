# -*- coding: utf-8 -*-
r"""
nest_proofs.py —— 锚点区间的"单 env + 嵌套 proof"归一（通用化增强版）。

S1 补包 + 首版拆出-重开式 + preprocess 自身缺陷，会在一个编号 item 区间内
留下多余 \begin{E}/\end{E} 开关与悬空 \begin{proof}（计数器每多一对 +1）。

对每个目标 label 锚点：
  1. 区间 = 锚点 → 下一个顶层结构行/带 label 的 thm begin/EOF；
  2. 区间内删除：
     a. 所有**无 label** 的 \begin{E}/\end{E}（E 为锚点同类）；
     b. 顶层（深度 0）悬空 \end{proof}——其配对 begin 在锚点之前，
        属前一条目的尾巴（如 I·4.3 L340 corollary 的证明收尾 L421）。
  3. 区间末统一补一个 \end{E}；
  4. 区间内 \begin{proof}/\end{proof} 正常嵌套保留（depth 自锚点起算）。

校验：env 栈配对 + label 集合不变，任一不过不写回。
"""
import argparse
import glob
import io
import json
import os
import re
import sys

# 动态确保同级脚本路径在 sys.path 中，方便导入 config_utils
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

try:
    from config_utils import ensure_utf8_stdio
except ImportError:
    try:
        from reflect.scripts.config_utils import ensure_utf8_stdio
    except ImportError:
        def ensure_utf8_stdio():
            if hasattr(sys.stdout, 'reconfigure'):
                try:
                    sys.stdout.reconfigure(encoding='utf-8')
                except Exception:
                    pass
            if hasattr(sys.stderr, 'reconfigure'):
                try:
                    sys.stderr.reconfigure(encoding='utf-8')
                except Exception:
                    pass

ensure_utf8_stdio()

MULTI = ('example', 'remark', 'conclusion')

DEFAULT_WHITELIST = {
    'thm:2-3.3', 'thm:3-2.19', 'thm:4-2.10', 'thm:4-2.16', 'thm:4-3.9',
    'thm:6-2.2', 'thm:6-2.4', 'thm:6-6.5', 'thm:6-7.23', 'thm:6-9.7',
    'thm:7-4.4', 'thm:7-5.13', 'thm:7-10.14', 'thm:8-5.15',
    'thm:10-3.10', 'thm:10-7.17', 'thm:11-2.18', 'thm:12-3.10',
}
WHITELIST = set(DEFAULT_WHITELIST)  # 向后兼容外部脚本直接引用

BEGIN_LAB = re.compile(
    r'^\\begin\{(' + '|'.join(MULTI) + r')\}(?:\[[^\]]*\])?\\label\{([^}]+)\}$')
SW = re.compile(r'^\\(begin|end)\{([A-Za-z*]+)\}$')
BAL = re.compile(r'\\(begin|end)\{([A-Za-z*]+)\}')
STRUCT = re.compile(r'^(\\(?:chapter|(?:sub)*section|paragraph)\*?\{|\\HRRule|\\end\{document\})')
PROOF_B = re.compile(r'^\\begin\{proof\}$')
PROOF_E = re.compile(r'^\\end\{proof}$')


def parse_whitelist_str(val):
    """解析命令行逗号或空格分隔的白名单标签字符串"""
    if not val:
        return set()
    parts = re.split(r'[,\s]+', val.strip())
    return {p for p in parts if p}


def load_whitelist_file(filepath):
    """从文件中读取白名单标签，支持 JSON 数组或每行一个标签格式（支持 # 注释）"""
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Whitelist file not found: {filepath}")
    with io.open(filepath, 'r', encoding='utf-8') as f:
        content = f.read().strip()
    if not content:
        return set()
    try:
        data = json.loads(content)
        if isinstance(data, list):
            return {str(item).strip() for item in data if str(item).strip()}
        elif isinstance(data, dict):
            for k in ('whitelist', 'labels', 'targets'):
                if k in data and isinstance(data[k], list):
                    return {str(item).strip() for item in data[k] if str(item).strip()}
    except Exception:
        pass

    res = set()
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '#' in line:
            line = line.split('#', 1)[0].strip()
        for part in re.split(r'[,\s]+', line):
            if part:
                res.add(part)
    return res


def has_proof_issue(lines, ai, hi):
    """
    检查锚点区间 [ai + 1, hi) 内是否存在未闭合或错配的 proof 环境：
    - 错配 (mismatch): proof depth 为 0 时出现 \\end{proof}（悬空闭合），或连续重复 \\end{proof}
    - 未闭合 (unclosed): 区间扫描结束时 proof depth > 0（未闭合证明）
    """
    depth = 0
    prev_end_proof = False
    for k in range(ai + 1, hi):
        s = lines[k].strip()
        if not s:
            continue
        if PROOF_B.match(s):
            depth += 1
            prev_end_proof = False
        elif PROOF_E.match(s):
            if depth == 0:
                return True
            if prev_end_proof:
                return True
            depth -= 1
            prev_end_proof = True
        else:
            prev_end_proof = False
    if depth > 0:
        return True
    return False


def balance_report(text):
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
    return stack, bad


def process(lines, whitelist=None, auto_all=False):
    """
    归一化指定或自动识别的多子项环境内部证明嵌套与裸开关。

    :param lines: 文件行列表
    :param whitelist: 允许处理的锚点标签集合（None 时若 not auto_all 则回退到 DEFAULT_WHITELIST）
    :param auto_all: 是否启用自动模式（自动识别存在未闭合/错配 proof 的锚点）
    :return: (new_text, ops_count)，若无待处理锚点返回 (None, 0)
    """
    if whitelist is None:
        target_whitelist = set(DEFAULT_WHITELIST) if not auto_all else set()
    else:
        target_whitelist = set(whitelist)

    anchors = []
    for i, l in enumerate(lines):
        m = BEGIN_LAB.match(l.strip())
        if not m:
            continue
        env, lab = m.group(1), m.group(2)

        # 1) 计算该锚点的区间终点 hi
        hi = len(lines)
        k = i + 1
        while k < len(lines):
            s = lines[k].strip()
            if STRUCT.match(s) or BEGIN_LAB.match(s):
                hi = k
                break
            k += 1

        # 判定是否属于待处理锚点
        matched = False
        if target_whitelist and lab in target_whitelist:
            matched = True
        elif auto_all and has_proof_issue(lines, i, hi):
            matched = True

        if matched:
            anchors.append((i, env, lab, hi))

    if not anchors:
        return None, 0

    drop = set()
    insert_after = {}   # idx -> env

    for (ai, env, lab, hi) in anchors:
        # 2) 区间内清理（proof depth 自锚点起算）
        k = ai + 1
        depth = 0
        while k < hi:
            s = lines[k].strip()
            if PROOF_B.match(s):
                depth += 1
                k += 1
                continue
            if PROOF_E.match(s):
                if depth > 0:
                    depth -= 1
                else:
                    drop.add(k)      # 悬空 end proof（前一条目尾巴）
                k += 1
                continue
            m = SW.match(s)
            if m and m.group(2) == env and depth == 0:
                drop.add(k)          # 顶层裸开关（嵌套证明体内的保留）
            k += 1

        # 2c) 配对回填与连续悬空 end proof 清理
        k = ai + 1
        while k < hi:
            if k in drop:
                k += 1
                continue
            s = lines[k].strip()
            if PROOF_E.match(s):
                pv = ''
                for x in range(k - 1, ai, -1):
                    if x in drop:
                        continue
                    if lines[x].strip():
                        pv = lines[x].strip()
                        break
                if PROOF_E.match(pv):
                    drop.add(k)
                    continue
            k += 1

        # 2b) 配对保护：凡顶层裸 begin，一律删除（区间末统一补 end）
        k = ai + 1
        depth = 0
        while k < hi:
            s = lines[k].strip()
            if PROOF_B.match(s):
                depth += 1
                k += 1
                continue
            if PROOF_E.match(s):
                depth = max(0, depth - 1)
                k += 1
                continue
            m = SW.match(s)
            if m and m.group(2) == env and depth == 0:
                drop.add(k)
            k += 1

        # 3) 区间末补 end：挂在区间内最后一条未删除行之后
        last = hi - 1
        while last > ai and last in drop:
            last -= 1
        if last > ai:
            insert_after[last] = env

    out = []
    for k, l in enumerate(lines):
        if k in drop:
            continue
        out.append(l)
        if k in insert_after:
            out.append('\\end{%s}' % insert_after[k])
    return '\n'.join(out), len(drop)


def main():
    ap = argparse.ArgumentParser(
        description="规范化 LaTeX 多子项环境 (example, remark, conclusion) 内部证明嵌套与开关归一"
    )
    ap.add_argument('files', nargs='+', help="待处理的 LaTeX 源文件路径列表（支持通配符）")
    ap.add_argument('--apply', action='store_true', help="落盘写回（通过门禁才写回）")
    ap.add_argument('--whitelist', type=str, default=None,
                    help="自定义标签白名单（逗号或空格分隔）")
    ap.add_argument('--whitelist-file', type=str, default=None,
                    help="包含白名单标签列表的文件路径（支持每行一个或 JSON 数组）")
    ap.add_argument('--all', dest='auto_all', action='store_true',
                    help="自动模式：自动针对所有包含 MULTI 且存在未闭合/错配 proof 的锚点进行规范化处理")
    args = ap.parse_args()

    # 构建自定义白名单
    user_whitelist = set()
    has_custom_whitelist = False

    if args.whitelist:
        user_whitelist.update(parse_whitelist_str(args.whitelist))
        has_custom_whitelist = True

    if args.whitelist_file:
        if not os.path.isfile(args.whitelist_file):
            sys.stderr.write(f"错误: 白名单文件 '{args.whitelist_file}' 不存在\n")
            sys.exit(1)
        user_whitelist.update(load_whitelist_file(args.whitelist_file))
        has_custom_whitelist = True

    if has_custom_whitelist:
        active_whitelist = user_whitelist
    elif args.auto_all:
        active_whitelist = None
    else:
        active_whitelist = DEFAULT_WHITELIST

    # 展开文件路径（兼容通配符）
    expanded_files = []
    for f in args.files:
        if any(c in f for c in ('*', '?', '[')):
            matches = glob.glob(f, recursive=True)
            if matches:
                expanded_files.extend(matches)
            else:
                expanded_files.append(f)
        else:
            expanded_files.append(f)

    has_fail = False
    processed_count = 0

    for p in expanded_files:
        if not os.path.isfile(p):
            print('%-46s 文件不存在' % os.path.basename(p))
            has_fail = True
            continue
        txt = io.open(p, encoding='utf-8').read()
        new, ops = process(txt.split('\n'), whitelist=active_whitelist, auto_all=args.auto_all)
        if not new:
            msg = '未发现需处理的错配锚点' if args.auto_all else '白名单锚点不在本文件'
            print('%-46s %s' % (os.path.basename(p), msg))
            continue
        processed_count += 1
        st, bad = balance_report(new)
        b = set(re.findall(r'\\label\{([^}]+)\}', txt))
        a = set(re.findall(r'\\label\{([^}]+)\}', new))
        ok = (not st and not bad) and b == a
        if not ok:
            has_fail = True
        print('%-46s 删 %2d 处 | 未闭 %s | 错配 %s | label %s | %s' % (
            os.path.basename(p), ops, st[:2], bad[:2], '同' if b == a else '变!',
            ('PASS 已写回' if (ok and args.apply) else ('PASS' if ok else 'FAIL 不写回'))))
        if ok and args.apply:
            io.open(p, 'w', encoding='utf-8', newline='\n').write(new + '\n')

    if has_fail:
        print("\n[FAIL] 存在环境未闭合、标签突变或错配文件，门禁阻断！")
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
