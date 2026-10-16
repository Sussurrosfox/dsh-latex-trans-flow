# -*- coding: utf-8 -*-
r"""
Amann《Analysis I-III》中译改造：节级批量预处理器 (preprocess.py)

用途：在 T-agent（结构化）介入之前，先把"规则确定、无需语言判断"的改造批量完成，
     使 agent 只需处理边界存疑处（% CHECK 标记）、跨节引用（% FIXME-ref）与语言润色。

处理规则：
  A. 全局机械清洗（零风险）
     A1. \mathrel{\text{ := }}            -> \coloneqq
     A2. \mathop{\sum }\limits 等大算子    -> \sum\limits 等
     A3. \left( {x}\right) 分隔符内多余空白 -> \left({x}\right)
     A4. OCR 书眉残留行（如 "I. 2 集合"）   -> 删除并标记
     A5. 文本区裸 ∎ / ■ / Ⅰ              -> 删除并计数
     A6. LATEX / TEX                     -> \LaTeX{} / \TeX{}（仅文本区）
  B. 结构骨架（启发式，边界处打 % CHECK 供 agent 复核）
     B1. \section*{N 标题}                -> \section{标题}\label{sec:CH-N}
     B2. 其余 \section*{主题}             -> \subsection*{主题}（习题/练习统一为 习题）
     B3. \[ ... \tag{x.y} \]             -> \begin{equation}\label{eq:CH-x.y} ... \end{equation}
     B4. \HRule 夹注块 + \({}^n\) 锚点    -> \footnote{...} 重接
     B5. x.y 定理/命题/... 裸文本头        -> theorem 类环境 + \label{thm:CH-x.y}（含证明包裹）
     B6. 习题小节内顺序编号行              -> exercise 环境 + \label{ex:CH-N}
  C. 文本区标点（仅文本区，需 CJK 邻接）
     C1. 半角 ( ) : , ;                   -> 全角（）：，；
     C2. \text{ and/or/for all/... }      -> \text{且/或/对所有/...}（精确匹配词表）

用法：
  python preprocess.py <tex文件> [--chapter N] [--section M] [--inplace] [--out 输出路径]
  章/节号缺省时从路径自动推断（01_Chapter_VI -> 6，08_Section_8 -> 8）。
  默认输出到 <文件名>.pre.tex，并打印各规则命中统计。
"""

import os
import re
import sys
import argparse

try:
    from config_utils import ensure_utf8_stdio, infer_chapter_section, ROMAN_MAP
    ensure_utf8_stdio()
except ImportError:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    ROMAN_MAP = {}
    infer_chapter_section = lambda p: (None, None)

# ---------------------------------------------------------------- 工具：数学区掩码

MATH_SPAN_PATTERNS = [
    r'\\begin\{(?:equation|align|gather|multline|eqnarray)\*?\}.*?\\end\{(?:equation|align|gather|multline|eqnarray)\*?\}',
    r'\\\[.*?\\\]',
    r'\\\(.*?\\\)',
    r'(?<!\$)\$\$(.*?)\$\$',
    r'(?<!\\)(?<!\$)\$(?!\$).*?(?<!\\)(?<!\$)\$(?!\$)',
]

def split_math_spans(text):
    """把文本切成 (is_math, segment) 列表。数学区规则与文本区规则分别施加。"""
    spans = []
    for pat in MATH_SPAN_PATTERNS:
        for m in re.finditer(pat, text, re.DOTALL):
            spans.append((m.start(), m.end()))
    spans.sort()
    merged = []
    for s, e in spans:
        if merged and s < merged[-1][1]:
            continue  # 嵌套/重叠跳过内层
        merged.append((s, e))
    out, pos = [], 0
    for s, e in merged:
        if s > pos:
            out.append((False, text[pos:s]))
        out.append((True, text[s:e]))
        pos = e
    if pos < len(text):
        out.append((False, text[pos:]))
    return out

def apply_on_regions(text, text_func=None, math_func=None):
    parts = []
    for is_math, seg in split_math_spans(text):
        if is_math and math_func:
            parts.append(math_func(seg))
        elif not is_math and text_func:
            parts.append(text_func(seg))
        else:
            parts.append(seg)
    return ''.join(parts)

# ---------------------------------------------------------------- 规则 A：全局机械清洗

def rule_a1_defeq(seg):
    return seg.replace(r'\mathrel{\text{ := }}', r'\coloneqq')

BIGOPS = ['sum', 'prod', 'bigcap', 'bigcup', 'bigoplus', 'bigotimes',
          'bigodot', 'bigvee', 'bigwedge', 'int', 'iint', 'iiint',
          'biguplus', 'bigsqcup']

def rule_a2_bigops(seg):
    for op in BIGOPS:
        seg = re.sub(r'\\mathop\{\\' + op + r'\s*\}\s*\\limits', r'\\' + op + r'\\limits', seg)
    return seg

def rule_a3_lrspace(seg):
    # \left( x\right) -> \left(x\right)：仅去掉 \leftX 后紧跟的空白与 \rightY 前的空白
    seg = re.sub(r'(\\left[()\[\]|{}\\|.])\s+', r'\1', seg)
    seg = re.sub(r'\s+(\\right[()\[\]|{}\\|.])', r'\1', seg)
    return seg

def make_rule_a4_headers(book_roman=None):
    # OCR 书眉行：可选页码 + 卷号罗马数字/阿拉伯数字.节号 + 标题，如 "I. 2 集合" / "22 I. 2 集合"
    if book_roman:
        prefix = re.escape(str(book_roman))
    else:
        prefix = r'(?:[IVXLCDM]+|\d+)'
    pat = re.compile(
        r'^\d{0,3}\s*' + prefix + r'\.\s*\d+\s+[^\\\s%].{0,50}$', re.MULTILINE)
    def _f(seg):
        return pat.sub('% CHECK: 已删除OCR书眉行', seg)
    return _f

def rule_a5_qed(seg):
    # 文本区孤立的 ∎ ■ Ⅰ（证明结束符 OCR 残留），前后为空白/行界
    seg = re.sub(r'(?<=[\s\n])[∎■Ⅰ](?=[\s\n])', '', seg)
    return seg

def rule_a6_latex(seg):
    seg = re.sub(r'\bLATEX\b', r'\\LaTeX{}', seg)
    seg = re.sub(r'\bTEX\b', r'\\TeX{}', seg)
    return seg

def rule_a7_unicode_math(seg):
    # 修复文本区裸数学根号 √2 -> $\sqrt{2}$
    seg = re.sub(r'√(\d+)', r'$\\sqrt{\1}$', seg)
    seg = re.sub(r'√([a-zA-Z])', r'$\\sqrt{\1}$', seg)
    seg = seg.replace('√', r'$\sqrt{\quad}$')
    # 修复常见 OCR 错乱符号（如音乐符号 𝄞 还原为脚注9锚点）
    seg = seg.replace(r'${}^{\text{ 𝄞 }}$', r'${}^9$')
    seg = seg.replace('𝄞', r'${}^9$')
    return seg

# ---------------------------------------------------------------- 规则 B：结构骨架

THM_TYPE_MAP = {
    '定理': 'theorem', '命题': 'proposition', '引理': 'lemma',
    '推论': 'corollary', '定义': 'definition', '公理': 'axiom',
    '判据': 'criterion', '法则': 'rule',
    '例与注': 'example', '例': 'example', '例子': 'example', '示例': 'example', '应用': 'example',
    '注记': 'remark', '备注': 'remark', '注': 'remark', '说明': 'remark',
    '结论': 'conclusion',
}

THM_HEADER_RE = re.compile(
    r'^(?:\\section\*\{)?(\d+)\.(\d+)\s*'
    r'(定理|命题|引理|推论|定义|公理|判据|法则|示例|例与注|例|例子|注记|备注|注|应用|结论|说明)\s*'
    r'(?:[（(]((?:\\.|[^（()）]){0,120})[）)])?\s*\}?\s*')

def _is_real_name(named):
    """命名定理参数必须含中文，防止把 (a)、(i) 之类误当定理名。"""
    return bool(named) and re.search(r'[一-鿿]', named) is not None

PROOF_START_RE = re.compile(r'^\s*(证明|反证法证明|为证此结论|为证明此定理|为证明该定理)[.．、:：]?\s*')

def _match_braced(text, start):
    """从 text[start]=='{' 处做花括号平衡扫描，返回 (内容, 右花括号后位置)；失败返回 (None, start)。"""
    assert text[start] == '{'
    depth = 0
    i = start
    while i < len(text):
        c = text[i]
        if c == '\\':
            i += 2
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
        i += 1
    return None, start

def rule_b1_b2_sections(text, chapter, counters):
    """节标题与小节标题（平衡括号扫描，支持任意深度嵌套的数学式标题）。"""
    out = []
    pos = 0
    cn_types_str = '定理|命题|引理|推论|定义|公理|判据|法则|示例|例与注|例|例子|注记|备注|注|应用|结论|说明'
    THM_IN_TITLE = re.compile(
        r'^(?:\d+\.\d+\s*(?:' + cn_types_str + r')|(?:' + cn_types_str + r')\s*[\d一二三四五六七八九十\.]+)')
    while True:
        m = re.compile(r'\\section\*\{').search(text, pos)
        if not m:
            out.append(text[pos:])
            break
        out.append(text[pos:m.start()])
        title, after = _match_braced(text, m.end() - 1)
        if title is None:
            out.append(m.group(0))
            pos = m.end()
            continue
        title = title.strip()
        sm = re.match(r'^(\d+)\s+(.+)$', title, re.DOTALL)
        cm = re.match(r'^第\s*(\d+)\s*章\s*(.+)$', title, re.DOTALL)
        bracket_m = re.match(r'^\[(\d+)\]\s*(.+)$', title, re.DOTALL)
        # 被 OCR 误判为标题的定理头留给 B5
        if THM_IN_TITLE.match(title):
            out.append(m.group(0) + title + '}')
        elif cm:
            counters['B1'] += 1
            out.append('\\chapter{%s}\\label{chap:%s}' % (cm.group(2).strip(), cm.group(1)))
        elif bracket_m:
            counters['B1'] += 1
            out.append('\\section{%s}\\label{sec:%s}' % (bracket_m.group(2).strip(), bracket_m.group(1)))
        elif sm:
            counters['B1'] += 1
            out.append('\\section{%s}\\label{sec:%s-%s}' % (sm.group(2).strip(), chapter, sm.group(1)))
        else:
            counters['B2'] += 1
            if title in ('习题', '练习'):
                title = '习题'
            out.append('\\subsection*{%s}' % title)
        pos = after
    return ''.join(out)

def rule_b3_tags(text, chapter, counters, flags):
    # 1. 将 $$ ... $$ 规范化为 \[ ... \] 或包含 \tag 的 equation
    def repl_double_dollar(m):
        body = m.group(1).strip()
        tag_m = re.search(r'\\tag\*?\{([^}]+)\}', body)
        if tag_m:
            tag = tag_m.group(1).strip()
            clean_body = re.sub(r'\\tag\*?\{[^}]+\}', '', body).strip()
            if re.fullmatch(r'[A-Za-z0-9\.]+', tag):
                counters['B3'] += 1
                return '\\begin{equation}\\label{eq:%s-%s}\n%s\n\\end{equation}' % (
                    chapter, tag.replace('.', '-'), clean_body)
            counters['B3-flag'] += 1
            return '\\begin{equation}\n%s\n\\tag*{%s}\\end{equation}' % (clean_body, tag)
        return '\\[\n%s\n\\]' % body

    text = re.sub(r'(?<!\\)\$\$(.*?)\$\$', repl_double_dollar, text, flags=re.DOTALL)

    def repl(m):
        body, tag = m.group(1), m.group(2).strip()
        if re.fullmatch(r'[A-Za-z0-9\.]+', tag):
            counters['B3'] += 1
            return '\\begin{equation}\\label{eq:%s-%s}%s\\end{equation}' % (
                chapter, tag.replace('.', '-'), body)
        flags.append('非数字 tag（保留待人工）: \\tag{%s}' % tag)
        counters['B3-flag'] += 1
        return '\\begin{equation}%s\\tag*{%s}\\end{equation}' % (body, tag)
    # \[ ... \tag{x.y} \]——正文不得跨越 \] 或另一个 \[（防止吞并无 tag 的相邻 display）
    text = re.sub(
        r'\\\[((?:(?!\\\]|\\\[).)*?)\\tag\{([^{}]*)\}\s*\\\]', repl, text, flags=re.DOTALL)
    return text

HRULE_REGION_RE = re.compile(r'\\HRule\s*(.*?)\\HRule', re.DOTALL)
ANCHOR_ANY_RE = re.compile(
    r'(?:'
    r'\$\{\}\^\{?(\\?\d+)\}?(?:\\mathrm\{[^}]*\})?\$'
    r'|\$\^\{?(\\?\d+)\}?(?:\\mathrm\{[^}]*\})?\$'
    r'|\\\(\s*(?:\{\})?\^\{?(\\?\d+)\}?\s*\\\)'
    r'|\$\{\}\^\{?(\\?\d+)\}?'
    r'|\$\^\{?(\\?\d+)\}?'
    r')\s*'
)

def _fn_like(body):
    r"""判定 \HRule 块是否为脚注块：不含结构内容（环境/标题/公式号/标签/条目/图片）。
    长度不设限——注文可能含多个显示公式（长注）；结构标记才是错位吞正文的可靠信号。"""
    if re.search(r'\\(begin|end)\{|\\section|\\subsection|\\chapter|\\tag\{|\\label\{'
                 r'|\\footnote\{|\\item|\\includegraphics', body):
        return False
    return True

def rule_b4_footnotes(text, counters, flags):
    r"""\HRule 夹注块 → 行内 \footnote。双轨高可靠：精准锚点回填 + 位置物理吸附回填。"""
    blocks = []
    def repl_block(m):
        body = m.group(1)
        if not _fn_like(body):
            counters['B4-skip'] += 1
            flags.append('疑似错位的 \\HRule 块（含结构内容，未删除，需人工处理）: %s'
                         % ' '.join(body.split())[:40])
            return m.group(0)
        blocks.append(body)
        return f'\n%%__HRULE_BLOCK_{len(blocks)-1}__%%\n'

    text = HRULE_REGION_RE.sub(repl_block, text)

    notes = []  # (block_idx, num, note_text)
    for b_idx, b in enumerate(blocks):
        anchors = list(ANCHOR_ANY_RE.finditer(b))
        if not anchors:
            counters['B4-loose'] += 1
            raw_c = ' '.join(b.split())
            raw_c = re.sub(r'^\$\s*', '', raw_c)
            if raw_c:
                notes.append((b_idx, '1', raw_c))
            continue
        for k, a in enumerate(anchors):
            num = next((g for g in a.groups() if g is not None), '1')
            num = num.lstrip('\\')
            start = a.end()
            end = anchors[k + 1].start() if k + 1 < len(anchors) else len(b)
            note = ' '.join(b[start:end].split())
            note = re.sub(r'^(?:\\mathrm\{[^}]*\}|[A-Za-z]+)?\$\s*', '', note)
            note = re.sub(r'^\$\s*', '', note)
            # 注文内的显示数学转内联（\footnote 内不能容纳 \[...\]）
            note = note.replace(r'\[', '\\(').replace(r'\]', '\\)').replace('$$', '$')
            if note:
                notes.append((b_idx, num, note))
                counters['B4-block'] += 1

    for b_idx, num, note in notes:
        anchor = re.compile(
            rf'\$\{{\}}\^\{{\\text\{{\s*(?:\\circled\{{{num}\}}|{num})\s*\}}\}}\$'
            rf'|\$\{{\}}\^\{{?{num}\}}?\$'
            rf'|\$\^\{{?{num}\}}?\$'
            rf'|\\\((\{{\}})?\^\{{?{num}\}}?\\\) '
            rf'|(?<=[一-鿿\w\)）])\$\^\{{{num}\}}\$'
        )
        hits = list(anchor.finditer(text))
        if hits:
            text = anchor.sub(lambda m: '\\footnote{%s}' % note, text, count=1)
            counters['B4'] += 1
        else:
            placeholder = f'%%__HRULE_BLOCK_{b_idx}__%%'
            text = text.replace(placeholder, f'\\footnote{{{note}}}%' + f' CHECK: 脚注{num}缺失锚点，已吸附回填\n' + placeholder, 1)
            counters['B4'] += 1
            flags.append('脚注 %s 缺失显式锚点，已吸附回填至所属页段尾' % num)

    text = re.sub(r'%%__HRULE_BLOCK_\d+__%%\n?', '', text)
    text = re.sub(r'\\HRule\n?', '', text)
    return text

def rule_b7_figures(text):
    r"""将伪图片排版转换为标准 LaTeX figure 浮动体环境与 \\caption、\\label"""
    pat = re.compile(
        r'\\begin\{center\}\s*\n\s*\\includegraphics\[(.*?)\]\{(.*?)\}\s*\n\s*\\end\{center\}\s*(?:\\hspace\*\{[^\}]*\}\s*)?\n+\s*图\s*([A-Za-z0-9\.]+)[.．、:：\s]+([^\n]+)',
        re.MULTILINE
    )
    def repl_fig(m):
        opt = m.group(1).strip()
        img_path = m.group(2).strip()
        fig_num = m.group(3).strip()
        caption_text = m.group(4).strip()
        label_name = f"fig:{fig_num.replace('.', '-')}"
        return (
            f"\\begin{{figure}}[htbp]\n"
            f"  \\centering\n"
            f"  \\includegraphics[{opt}]{{{img_path}}}\n"
            f"  \\caption{{{caption_text}}}\n"
            f"  \\label{{{label_name}}}\n"
            f"\\end{{figure}}"
        )
    return pat.sub(repl_fig, text)

def rule_b5_theorems(lines, chapter, counters, flags, thm_type_map=None, thm_header_re=None):
    r"""行级状态机：定理类环境 + 证明包裹。
    支持 Amann 风格（6.1 定理）与中文专著通用风格（定理6.1．/定理 10.1./定理 E.1.）。
    嵌套环境（itemize/center 等）计入深度；结构边界触发关闭时若深度>0则延迟到归零，
    避免把 \end{thm} 插进定理陈述自带的列表/图形块内部。"""
    type_map = thm_type_map or THM_TYPE_MAP
    if isinstance(thm_header_re, (list, tuple)):
        header_re_amann, header_re_cn = thm_header_re
    else:
        header_re_amann, header_re_cn = thm_header_re or THM_HEADER_RE, None

    out = []
    state = None          # None | 'thm' | 'proof'
    env_of_thm = None
    depth = 0             # 嵌套的非定理环境深度
    pending = False       # 已请求关闭，等待 depth 归零
    TRACKED = ('itemize', 'enumerate', 'center', 'figure', 'table', 'tabular',
               'tcolorbox', 'mdframed', 'minipage', 'align', 'align*',
               'gather', 'gather*', 'multline', 'flalign', 'eqnarray')

    def emit_close():
        nonlocal state, env_of_thm, pending
        if state == 'proof':
            out.append('\\end{proof}')
            out.append('% CHECK: 证明结束位置为启发式推断')
        elif state == 'thm':
            out.append('\\end{%s}' % env_of_thm)
            out.append('% CHECK: 环境结束位置为启发式推断')
        state, env_of_thm, pending = None, None, False

    for line in lines:
        stripped = line.strip()
        opens = re.findall(r'\\begin\{(' + '|'.join(TRACKED) + r')\}', stripped)
        closes = re.findall(r'\\end\{(' + '|'.join(TRACKED) + r')\}', stripped)
        pre_depth = depth
        depth += len(opens) - len(closes)

        # 尝试匹配定理头（Amann 风格或中文专著风格）
        matched_thm = None
        if header_re_amann:
            m_a = header_re_amann.match(stripped)
            if m_a:
                env = type_map.get(m_a.group(3), 'theorem')
                lab_idx = '%s-%s.%s' % (chapter, m_a.group(1), m_a.group(2))
                named = m_a.group(4)
                matched_thm = (env, lab_idx, named, m_a.end(), m_a.group(0))
        if not matched_thm and header_re_cn:
            m_c = header_re_cn.match(stripped)
            if m_c:
                env = type_map.get(m_c.group(1), 'theorem')
                raw_idx = m_c.group(2).rstrip('.．、:：')
                CN_NUM_MAP = {'一': '1', '二': '2', '三': '3', '四': '4', '五': '5', '六': '6', '七': '7', '八': '8', '九': '9', '十': '10'}
                if raw_idx in CN_NUM_MAP:
                    raw_idx = CN_NUM_MAP[raw_idx]
                if '.' in raw_idx:
                    parts = raw_idx.split('.')
                    lab_idx = '%s-%s' % (parts[0], parts[1])
                else:
                    lab_idx = '%s-%s' % (chapter, raw_idx)
                named = m_c.group(3)
                matched_thm = (env, lab_idx, named, m_c.end(), m_c.group(0))

        is_struct = bool(re.match(
            r'^(\\section|\\subsection|\\chapter|\\HRule|\\end\{document\}'
            r'|\\begin\{(center|figure|table|tcolorbox)\})', stripped))

        # 1. 待关闭且嵌套已归零：在输出本行之前先关闭
        if pending and depth <= 0:
            emit_close()

        if matched_thm:
            if state and depth <= 0:
                emit_close()
            env, lab_idx, raw_named, end_pos, match_str = matched_thm
            counters['B5'] += 1
            named = raw_named if _is_real_name(raw_named) else None
            # 命名参数中混入的 \footnote 移出可选参数（amsthm 标题内脚注不安全）
            fn_in_name = None
            if named:
                fm = re.search(r'\\footnote\{.*\}\s*$', named)
                if fm:
                    fn_in_name = fm.group(0)
                    named = named[:fm.start()].rstrip()
            opt = '[%s]' % named if named else ''
            if str(chapter) == '10' and lab_idx == '10-11':
                out.append('\\stepcounter{theorem}% 顺延对齐：原书 10.10 位于脚注，主线顺延跳号')
            out.append('\\begin{%s}%s\\label{thm:%s}' % (env, opt, lab_idx))
            if fn_in_name:
                out.append(fn_in_name)
                flags.append('定理 %s 命名参数中的脚注已移至环境体首' % lab_idx)
            rest = stripped[end_pos:]
            # 定理头被 OCR 吞进 \section*{...} 或 \subsection*{...} 时，剥掉标题的右括号
            if (match_str.startswith('\\section*') or match_str.startswith('\\subsection*')) and rest.rstrip().endswith('}'):
                rest = rest.rstrip()[:-1].rstrip()
                flags.append('定理 %s 的头/首句曾被误判为标题，已还原' % lab_idx)
            if rest:
                out.append(rest)
            state, env_of_thm = 'thm', env
            continue

        if state == 'thm' and PROOF_START_RE.match(stripped) and depth <= 0:
            out.append('\\end{%s}' % env_of_thm)
            out.append('\\begin{proof}')
            rest = PROOF_START_RE.sub('', stripped)
            if rest:
                out.append(rest)
            state = 'proof'
            continue

        # 2. 结构边界（用进入本行前的深度判断）：关闭打开的环境
        if state in ('thm', 'proof') and not pending and pre_depth <= 0:
            if is_struct:
                emit_close()
            elif state == 'proof' and re.search(r'(?:证毕[。.]?|[∎■Ⅰ\u25a0\u25a1])\s*$', stripped) and stripped:
                out.append(re.sub(r'\s*(?:证毕[。.]?|[∎■Ⅰ\u25a0\u25a1])\s*$', '', stripped))
                emit_close()
                continue

        out.append(line)

    if state in ('thm', 'proof'):
        emit_close()
    return out

def rule_b6_exercises(lines, chapter, section, counters, flags):
    """习题小节内，把顺序编号行包成 exercise 环境。"""
    out = []
    in_exsec = False
    in_ex = False
    expect = 1
    for line in lines:
        stripped = line.strip()
        if re.match(r'^\\subsection\*\{习题\}', stripped):
            if in_ex:
                out.append('\\end{exercise}')
                in_ex = False
            in_exsec = True
            expect = 1
            out.append(line)
            continue
        if in_exsec and re.match(r'^\\(sub)?section', stripped):
            if in_ex:
                out.append('\\end{exercise}')
                in_ex = False
            in_exsec = False
            out.append(line)
            continue
        if in_exsec:
            m = re.match(r'^(\d{1,2})\s+(?=[一-鿿\\(（A-Za-z])', stripped)
            if m and int(m.group(1)) == expect:
                if in_ex:
                    out.append('\\end{exercise}')
                out.append('\\begin{exercise}\\label{ex:%s-%s.%d}' % (chapter, section, expect))
                counters['B6'] += 1
                rest = stripped[m.end():]
                if rest:
                    out.append(rest)
                in_ex = True
                expect += 1
                continue
        out.append(line)
    if in_ex:
        out.append('\\end{exercise}')
        out.append('% CHECK: 最后一道习题的结束位置为启发式推断')
    return out

# ---------------------------------------------------------------- 规则 C：文本区标点

def rule_c1_punct(seg):
    seg = re.sub(r'(?<=[一-鿿])\(', '（', seg)
    seg = re.sub(r'\)(?=[一-鿿，。；：、])', '）', seg)
    seg = re.sub(r'(?<=[一-鿿]):', '：', seg)
    seg = re.sub(r'(?<=[一-鿿]),', '，', seg)
    seg = re.sub(r'(?<=[一-鿿]);', '；', seg)
    return seg

TEXT_WORD_MAP = {
    'and': '且', 'or': '或', 'for all': '对所有', 'with': '满足',
    'otherwise': '否则', 'if': '若', 'then': '则', 'for': '对',
    'to': '到', 'for some': '对某个',
}

def rule_c2_textwords(seg, counters):
    def repl(m):
        w = m.group(1).strip()
        if w in TEXT_WORD_MAP:
            counters['C2'] += 1
            return '\\text{%s}' % TEXT_WORD_MAP[w]
        return m.group(0)
    return re.sub(r'\\text\{\s*([A-Za-z][A-Za-z ]{1,20}?)\s*\}', repl, seg)

# ---------------------------------------------------------------- 主流程

ROMANS = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6,
          'VII': 7, 'VIII': 8, 'IX': 9, 'X': 10, 'XI': 11, 'XII': 12}

def infer_numbers(path):
    c, s = infer_chapter_section(path)
    if c is not None or s is not None:
        return c, s
    # 兼容原正则表达式
    chapter = section = None
    m = re.search(r'_Chapter_([IVX]+)', path)
    if m:
        chapter = ROMANS.get(m.group(1))
    m = re.search(r'_Section_(\d+)', os.path.basename(path))
    if m:
        section = int(m.group(1))
    return chapter, section

def book_roman_of(chapter, volume_roman=None):
    if volume_roman:
        return str(volume_roman)
    if chapter is None:
        return None
    if chapter <= 5:
        return 'I'
    if chapter <= 8:
        return 'II'
    if chapter <= 12:
        return 'III'
    return None

def build_thm_matcher(extra_thm_types=None):
    """根据扩展定理类型表动态生成环境映射与正则，兼容 Amann 风格与中文专著标准风格"""
    type_map = dict(THM_TYPE_MAP)
    if extra_thm_types:
        if isinstance(extra_thm_types, str):
            for pair in extra_thm_types.split(','):
                if ':' in pair:
                    k, v = pair.split(':', 1)
                    type_map[k.strip()] = v.strip()
        elif isinstance(extra_thm_types, dict):
            type_map.update(extra_thm_types)
    keys_sorted = sorted(type_map.keys(), key=lambda x: len(x), reverse=True)
    cn_types = '|'.join(re.escape(k) for k in keys_sorted)
    # 模式1: Amann 风格: 6.1 定理
    header_re_amann = re.compile(
        r'^(?:\\(?:sub)*section\*\{)?(\d+)\.(\d+)\s*'
        r'(' + cn_types + r')\s*'
        r'(?:[（(]((?:\\.|[^（()）]){0,120})[）)])?\s*\}?\s*')
    # 模式2: 中文专著标准风格: 定理6.1. / 定理 10.1. / 定理一 / 定理 E.1.
    header_re_cn = re.compile(
        r'^(?:\\(?:sub)*section\*\{)?(' + cn_types + r')\s*'
        r'([A-Za-z0-9一二三四五六七八九十\.]+)[.．、:：]?\s*'
        r'(?:[（(]((?:\\.|[^（()）]){0,120})[）)])?\s*\}?\s*')
    return type_map, (header_re_amann, header_re_cn)

def preprocess(text, chapter, section, volume_roman=None, strip_headers=True, extra_thm_types=None):
    counters = {k: 0 for k in
                ['B1', 'B2', 'B3', 'B3-flag', 'B4', 'B4-block', 'B4-flag',
                 'B4-loose', 'B4-skip', 'B5', 'B6', 'C2']}
    flags = []

    type_map, header_re = build_thm_matcher(extra_thm_types)

    # --- A 级：按区域施加
    a4 = make_rule_a4_headers(book_roman_of(chapter, volume_roman))
    def math_side(seg):
        seg = rule_a1_defeq(seg)
        seg = rule_a2_bigops(seg)
        seg = rule_a3_lrspace(seg)
        return seg
    def text_side(seg):
        seg = rule_a1_defeq(seg)
        if strip_headers:
            seg = a4(seg)
        seg = rule_a5_qed(seg)
        seg = rule_a6_latex(seg)
        seg = rule_a7_unicode_math(seg)
        return seg
    text = apply_on_regions(text, text_side, math_side)

    # --- B1/B2 标题
    text = rule_b1_b2_sections(text, chapter, counters)

    # --- B4 脚注重接（先于 B5，避免状态机被 \HRule 干扰）
    text = rule_b4_footnotes(text, counters, flags)

    # --- B3 公式 tag -> equation+label
    text = rule_b3_tags(text, chapter, counters, flags)

    # --- B7 图片规范化为标准 figure 环境
    text = rule_b7_figures(text)

    # --- B5 定理环境（行级状态机）
    lines = text.split('\n')
    lines = rule_b5_theorems(lines, chapter, counters, flags, thm_type_map=type_map, thm_header_re=header_re)

    # --- B6 习题环境
    lines = rule_b6_exercises(lines, chapter, section, counters, flags)
    text = '\n'.join(lines)

    # --- C 级：文本区标点与残留英文词表（\text{...} 位于数学区内，故 C2 两侧都施加）
    def text_side2(seg):
        seg = rule_c1_punct(seg)
        seg = rule_c2_textwords(seg, counters)
        return seg
    def math_side2(seg):
        return rule_c2_textwords(seg, counters)
    text = apply_on_regions(text, text_side2, math_side2)

    # --- 自检：定理类环境必须配平（防 \HRule 错位吞噬等意外）
    THM_ENVS = set(type_map.values()) | {'proof', 'exercise'}
    for env in sorted(THM_ENVS):
        b = len(re.findall(r'\\begin\{%s\}' % env, text))
        e = len(re.findall(r'\\end\{%s\}' % env, text))
        if b != e:
            flags.append('自检失败：环境 %s 不配平（begin=%d, end=%d），该节需人工检查' % (env, b, e))

    return text, counters, flags

def main():
    ap = argparse.ArgumentParser(description="LaTeX 节级批量预处理与结构化脚本")
    ap.add_argument('target', help='待处理的 .tex 文件')
    ap.add_argument('--chapter', type=int, default=None, help='指定章号（缺省时从路径自动推断）')
    ap.add_argument('--section', type=int, default=None, help='指定节号（缺省时从路径自动推断）')
    ap.add_argument('--volume-roman', '--book-roman', dest='volume_roman', default=None, help='指定卷罗马数字（如 I, II, III）')
    ap.add_argument('--no-header-strip', action='store_true', help='跳过 OCR 眉页行过滤规则')
    ap.add_argument('--extra-types', default=None, help='扩展定理类型映射，如 "性质:property,判据:criterion"')
    ap.add_argument('--inplace', action='store_true', help='直接写回原文件')
    ap.add_argument('--out', default=None, help='指定输出文件路径')
    args = ap.parse_args()

    chapter, section = infer_numbers(args.target)
    chapter = args.chapter or chapter
    section = args.section or section
    if not chapter:
        print('ERROR: 无法推断章号，请用 --chapter 指定')
        sys.exit(2)
    if not section:
        section = 0

    with open(args.target, 'r', encoding='utf-8') as f:
        text = f.read()

    new_text, counters, flags = preprocess(
        text, chapter, section,
        volume_roman=args.volume_roman,
        strip_headers=not args.no_header_strip,
        extra_thm_types=args.extra_types
    )

    out_path = args.target if args.inplace else (
        args.out or re.sub(r'\.tex$', '.pre.tex', args.target))
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(new_text)

    print('=== preprocess: %s -> %s ===' % (os.path.basename(args.target), out_path))
    print('章 %s / 节 %s' % (chapter, section))
    for k in ['B1', 'B2', 'B3', 'B3-flag', 'B4', 'B4-block', 'B4-flag',
              'B4-loose', 'B4-skip', 'B5', 'B6', 'C2']:
        print('  %-8s : %d' % (k, counters[k]))
    checks = len(re.findall(r'% CHECK', new_text))
    print('  %% CHECK 标记（需 agent 复核）: %d' % checks)
    if flags:
        print('  --- 警告 ---')
        for fl in flags:
            print('  ! ' + fl)

if __name__ == '__main__':
    main()
