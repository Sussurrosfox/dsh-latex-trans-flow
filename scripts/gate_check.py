# -*- coding: utf-8 -*-
"""
gate_check.py - 单节质量与合规门禁脚本（通用增强版）
用于校验结构化 (Phase 2) 与润线/复核 (Phase 4) 产物是否符合标准。

五大门禁项：
1. compile: XeLaTeX 真实编译检查（无致命报错）
2. clean_macros: 无 \\tag、无 \\HRule 边界、无裸 \\section* 标题残留
3. theorem_count: 定理类环境计数与原文裸文本头计数核对
4. math_tokens: 数学公式 token 流零变异（允许 \\coloneqq 规范化、空白、波浪号~ 与中文 \\text 替换）
5. label_format: label 命名规范（默认符合 ^(sec|thm|eq|ex|def|lem|prop|cor|rem|fig|tab):(\\d+|[A-Z])- 规则）
"""

import os
import sys
import re
import json
import subprocess
import argparse

# 确保 UTF-8 输出
try:
    from config_utils import ensure_utf8_stdio
    ensure_utf8_stdio()
except ImportError:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')

# 默认标签正则：支持常见的章/节/定理/式/习题/图表前缀，支持阿拉伯数字章及任意大写字母附录 (A-Z)
DEFAULT_LABEL_REGEX = r'^(?:chap|sec|subsec|thm|eq|ex|def|lem|prop|cor|rem|fig|tab):(?:(?:\d+|[A-Z])-[\w\.\-]+|(?:\d+|[A-Z])|[\w\.\-]+)$'
LABEL_PATTERN = re.compile(DEFAULT_LABEL_REGEX)

THEOREMS = ['theorem', 'proposition', 'lemma', 'corollary', 'definition', 'example', 'remark', 'axiom', 'criterion', 'rule', 'conclusion']

# 裸头与环境正则（涵盖常用中文数学环境，兼容 Amann 风格与中文专著标准风格）
RAW_THM_PATTERN = re.compile(
    r'(?:^|\n|(?<=[。！？\.\s])|\\(?:sub)*section\*\{)\s*(?:'
    r'(\d+\.\d+)\s*(定理|命题|引理|推论|定义|示例|例与注|例|例子|注记|备注|注|评注|公理|判据|法则|应用(?!于)|结论|说明)'
    r'|'
    r'(定理|命题|引理|推论|定义|示例|例与注|例|例子|注记|备注|注|评注|公理|判据|法则|应用(?!于)|结论|说明)\s*([A-Za-z0-9一二三四五六七八九十\.]+)[.．、:：]?'
    r')',
    re.MULTILINE
)
ENV_THM_PATTERN = re.compile(
    r'\\begin\{(theorem|proposition|lemma|corollary|definition|example|remark|axiom|criterion|rule|conclusion)\}',
    re.MULTILINE
)

def check_compilation(tex_path, preamble_path=None, timeout=120):
    """
    Gate 1: Compile checking with xelatex.
    若文件自带 \documentclass（如 subfiles 或独立主文件），直接编译；
    否则优先使用同目录下的 compile_{base_name} 包装；
    若不存在但提供了 preamble_path，则自动生成轻量级测试编译包装并清理。
    """
    dir_name = os.path.dirname(os.path.abspath(tex_path))
    base_name = os.path.basename(tex_path)
    compile_tex = os.path.join(dir_name, f"compile_{base_name}")
    created_temp_wrapper = False
    
    file_content = read_file_safely(tex_path)
    if r'\documentclass' in file_content:
        target_compile_file = os.path.abspath(tex_path)
    elif os.path.exists(compile_tex):
        target_compile_file = compile_tex
    elif preamble_path and os.path.exists(preamble_path):
        created_temp_wrapper = True
        target_compile_file = os.path.join(dir_name, f"_tmp_gate_compile_{base_name}")
        rel_preamble = os.path.relpath(preamble_path, dir_name).replace('\\', '/')
        with open(target_compile_file, 'w', encoding='utf-8') as f:
            f.write(f"\\input{{{rel_preamble}}}\n\\begin{{document}}\n\\input{{{base_name}}}\n\\end{{document}}\n")
    else:
        return True, "No standalone compile wrapper found; skipped standalone compilation."

    try:
        cmd = ["xelatex", "-interaction=nonstopmode", os.path.basename(target_compile_file)]
        proc = subprocess.Popen(
            cmd,
            cwd=dir_name,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace'
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            passed = (proc.returncode == 0)
            lines = (stdout or '').splitlines()
            err_lines = [l for l in lines if l.startswith('!') or 'Error' in l][:10]
            msg = f"Compilation succeeded ({proc.returncode})" if passed else f"Compilation failed with exit code {proc.returncode}:\n" + "\n".join(err_lines)
        except subprocess.TimeoutExpired:
            passed = False
            msg = f"Compilation timed out ({timeout}s)"
            if os.name == 'nt':
                try:
                    subprocess.run(['taskkill', '/F', '/T', '/PID', str(proc.pid)], capture_output=True)
                except Exception:
                    pass
            try:
                proc.kill()
                proc.communicate()
            except Exception:
                pass
    except Exception as e:
        passed = False
        msg = f"Compilation exception: {e}"
    finally:
        if created_temp_wrapper:
            # 清理临时文件
            stem = os.path.splitext(target_compile_file)[0]
            for ext in ['.tex', '.aux', '.log', '.out', '.pdf', '.xdv']:
                p = stem + ext
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass

    return passed, msg

def check_clean_macros(content):
    """Gate 2: Ensure no forbidden tags or markers."""
    errors = []
    
    # 1. tag
    tags = re.findall(r'\\tag\{.*?\}', content)
    if tags:
        errors.append(f"Found {len(tags)} \\tag macros: {tags[:5]}")
        
    # 2. HRule
    hrules = re.findall(r'\\HRule', content)
    if hrules:
        errors.append(f"Found {len(hrules)} \\HRule footnotes boundaries")
        
    # 3. section* should not be used as main section title
    sec_stars = re.findall(r'\\section\*\{.*?\}', content)
    if sec_stars:
        errors.append(f"Found {len(sec_stars)} \\section* headings: {sec_stars[:5]}")
        
    return len(errors) == 0, errors

def _strip_footnotes_and_comments(text):
    r"""剥离 \footnote{...}（平衡括号）、\HRule 夹注块与注释——脚注重接属预期变更，不参与数学与正文定理比对。"""
    text = re.sub(r'(?m)%.*$', '', text)
    text = re.sub(r'\\HRule\s*\n.*?\n\s*\\HRule', '', text, flags=re.DOTALL)
    out = []
    i = 0
    for m in re.finditer(r'\\footnote\{', text):
        depth = 1
        j = m.end()
        while j < len(text) and depth:
            c = text[j]
            if c == '\\':
                j += 2
                continue
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
            j += 1
        out.append(text[i:m.start()])
        i = j
    out.append(text[i:])
    return ''.join(out)

def check_theorem_count(original_content, new_content):
    """Gate 3: Check count of theorem environments vs original raw headers."""
    orig_clean = _strip_footnotes_and_comments(original_content)
    raw_matches = RAW_THM_PATTERN.findall(orig_clean)
    raw_count = len(raw_matches)
    
    new_clean = _strip_footnotes_and_comments(new_content)
    env_matches = ENV_THM_PATTERN.findall(new_clean)
    env_count = len(env_matches)
    
    if raw_count == env_count:
        return True, f"Theorem count matched: {env_count} environments (raw headers: {raw_count})"
    else:
        raw_descs = [f"{m[0] or m[2]} {m[1] or m[3]}".strip() for m in raw_matches]
        return False, (
            f"Theorem count mismatch: expected {raw_count} (raw: {raw_descs}), "
            f"got {env_count} environments (envs: {env_matches})"
        )

def normalize_math_tokens(formula):
    """Normalize mathematical formula string into comparable token stream."""
    f = formula
    # Remove comments
    f = re.sub(r'%.*?\n', '', f)
    # Normalize definition equality
    f = f.replace(r'\mathrel{\text{ := }}', r'\coloneqq')
    f = f.replace(r':=', r'\coloneqq')
    # Normalize \mathop{\sum}\limits to \sum
    f = re.sub(r'\\mathop\{\\sum\s*\}\s*\\limits', r'\\sum', f)
    f = re.sub(r'\\mathop\{\\prod\s*\}\s*\\limits', r'\\prod', f)
    f = re.sub(r'\\mathop\{\\bigcap\s*\}\s*\\limits', r'\\bigcap', f)
    f = re.sub(r'\\mathop\{\\bigcup\s*\}\s*\\limits', r'\\bigcup', f)
    # Normalize sizing modifiers (\left, \right)
    f = re.sub(r'\\left(?=[()\[\]|.\\])', '', f)
    f = re.sub(r'\\right(?=[()\[\]|.\\])', '', f)
    # Remove all \text{...} contents (text translations are allowed)
    f = re.sub(r'\\text\{.*?\}', '', f)
    # Remove \label{...} and \tag{...}
    f = re.sub(r'\\label\{.*?\}', '', f)
    f = re.sub(r'\\tag\{.*?\}', '', f)
    # Normalize \limits modifier
    f = re.sub(r'\\(?:no)?limits(?=[^a-zA-Z]|$)', '', f)
    # Normalize redundant braces repeatedly
    for _ in range(3):
        f = re.sub(r'\{([^{}\\]*)\}', r'\1', f)
    # Remove spacing commands
    f = re.sub(r'\\[;,! ]', '', f)
    f = re.sub(r'\\quad', '', f)
    f = re.sub(r'\\qquad', '', f)
    # Ties（~）与不可断行空格在数学中等价于空白
    f = f.replace('~', '')
    # Remove whitespace
    f = re.sub(r'\s+', '', f)
    return f

# 统一合并数学环境与公式正则：按文本物理位置一次性顺序提取，防止乱序与跨正则冲突
MATH_UNIFIED_PATTERN = re.compile(
    r'\$\$(?P<disp_dollar>.*?)\$\$'
    r'|\\\[(?P<disp_bracket>.*?)\\\]'
    r'|\\begin\{(?P<env_name>(?:equation|align|gather|multline|eqnarray|flalign|alignat)\*?)\}(?P<disp_env>.*?)\\end\{(?P=env_name)\}'
    r'|\\\((?P<inline_paren>.*?)\\\)'
    r'|(?<!\\)(?<!\$)\$(?!\$)(?P<inline_dollar>[^\$\n\r]+?(?:\r?\n(?![ \t]*(?:\r?\n|%))[^\$\n\r]*){0,2}?)(?<!\\)(?<!\$)\$',
    re.DOTALL
)

def extract_math(content):
    """
    采用统一合并正则一次性按文本物理出现位置顺序提取所有数学公式字符串。
    严格避免跨越连续注释行、段落空行或未配对文本时的过度抓取。
    """
    math_tokens = []
    for m in MATH_UNIFIED_PATTERN.finditer(content):
        for name in ('disp_dollar', 'disp_bracket', 'disp_env', 'inline_paren', 'inline_dollar'):
            val = m.group(name)
            if val is not None:
                token = normalize_math_tokens(val)
                if token:
                    math_tokens.append(token)
                break
    return "".join(math_tokens)

def check_math_tokens(original_content, new_content):
    """
    Gate 4: 零信任严格比对数学 Token 流守恒不变量。
    彻底废除 95% 假守恒放行机制！
    在剥离注释、脚注，规范化空白和波浪号~及 coloneqq 后，orig_clean 与 new_clean 必须 100% 精确相等。
    如果存在差异，必须返回 (False, diff 报告)，打印出差异长度、前 100 字符的差异片段与统一 diff 摘要，严禁模糊放行！
    """
    import difflib

    orig_clean = _strip_footnotes_and_comments(original_content)
    new_clean = _strip_footnotes_and_comments(new_content)

    orig_math = extract_math(orig_clean)
    new_math = extract_math(new_clean)

    if orig_math == new_math:
        return True, f"Math tokens exact match (100% strict invariant, len={len(orig_math)})"

    diff_len = abs(len(new_math) - len(orig_math))

    # 寻找首个不一致的字符位置
    first_diff = 0
    min_len = min(len(orig_math), len(new_math))
    while first_diff < min_len and orig_math[first_diff] == new_math[first_diff]:
        first_diff += 1

    # 提取差异位置起前 100 字符的差异片段
    orig_snippet = orig_math[first_diff:first_diff + 100]
    new_snippet = new_math[first_diff:first_diff + 100]

    # 生成统一 diff 摘要
    chunk_size = 60
    orig_chunks = [orig_math[i:i + chunk_size] + '\n' for i in range(0, len(orig_math), chunk_size)]
    new_chunks = [new_math[i:i + chunk_size] + '\n' for i in range(0, len(new_math), chunk_size)]
    diff_lines = list(difflib.unified_diff(
        orig_chunks,
        new_chunks,
        fromfile='orig_math_tokens',
        tofile='new_math_tokens',
        n=2
    ))[:15]
    diff_summary = "".join(diff_lines).strip()

    diff_report = (
        f"Math tokens divergence detected (ZERO TRUST VIOLATION):\n"
        f"  - Length: original={len(orig_math)}, new={len(new_math)}, diff_len={diff_len}\n"
        f"  - First mismatch at position {first_diff}:\n"
        f"    [Orig (first 100 chars)]: {orig_snippet!r}\n"
        f"    [New  (first 100 chars)]: {new_snippet!r}"
    )
    if diff_summary:
        diff_report += f"\n  - Unified diff summary:\n{diff_summary}"

    return False, diff_report

def check_label_format(content, label_regex=None):
    """Gate 5: Check labels format against allowed regex."""
    pat = re.compile(label_regex) if label_regex else LABEL_PATTERN
    labels = re.findall(r'\\label\{([^\{\}]+)\}', content)
    invalid = []
    for l in labels:
        if not pat.match(l):
            invalid.append(l)
    if not invalid:
        return True, f"All {len(labels)} labels adhere to naming rules."
    else:
        return False, f"Found {len(invalid)} invalid labels: {invalid}"

def read_file_safely(path):
    """Read text file safely with multiple encoding fallbacks."""
    for enc in ['utf-8', 'utf-8-sig', 'utf-16', 'utf-16-le', 'latin-1']:
        try:
            with open(path, 'r', encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Cannot decode file {path}")

def run_gate(target_tex, original_tex=None, label_regex=None, preamble_path=None, skip_compile=False):
    """Run all gates on target_tex and return (all_passed, results_dict)."""
    new_content = read_file_safely(target_tex)
        
    orig_content = None
    if original_tex and os.path.exists(original_tex):
        orig_content = read_file_safely(original_tex)
            
    print(f"=== Running Gates on: {os.path.basename(target_tex)} ===")
    
    # 1. Clean macros
    g2_ok, g2_msg = check_clean_macros(new_content)
    print(f"Gate 2 [Clean Macros]: {'PASS' if g2_ok else 'FAIL'} - {g2_msg}")
    
    # 2. Labels
    g5_ok, g5_msg = check_label_format(new_content, label_regex=label_regex)
    print(f"Gate 5 [Label Format]: {'PASS' if g5_ok else 'FAIL'} - {g5_msg}")
    
    # 3. Theorems (if orig available)
    if orig_content:
        g3_ok, g3_msg = check_theorem_count(orig_content, new_content)
        print(f"Gate 3 [Theorem Count]: {'PASS' if g3_ok else 'FAIL'} - {g3_msg}")
        
        g4_ok, g4_msg = check_math_tokens(orig_content, new_content)
        print(f"Gate 4 [Math Tokens]: {'PASS' if g4_ok else 'FAIL'} - {g4_msg}")
    else:
        g3_ok, g4_ok = True, True
        g3_msg, g4_msg = "SKIPPED (no baseline provided)", "SKIPPED (no baseline provided)"
        print("Gate 3 & 4 [Baseline compare]: SKIPPED (no baseline provided)")
        
    # 4. Compilation
    if skip_compile:
        g1_ok, g1_msg = True, "SKIPPED (--skip-compile requested)"
        print(f"Gate 1 [Compilation]: SKIPPED - {g1_msg}")
    else:
        g1_ok, g1_msg = check_compilation(target_tex, preamble_path=preamble_path)
        print(f"Gate 1 [Compilation]: {'PASS' if g1_ok else 'FAIL'} - {g1_msg}")
    
    all_ok = g1_ok and g2_ok and g3_ok and g4_ok and g5_ok
    print(f"=== OVERALL RESULT: {'ALL PASSED' if all_ok else 'REJECTED'} ===")
    
    details = {
        'target': target_tex,
        'all_passed': all_ok,
        'g1_compile': {'pass': g1_ok, 'msg': g1_msg},
        'g2_clean': {'pass': g2_ok, 'msg': g2_msg},
        'g3_theorem': {'pass': g3_ok, 'msg': g3_msg},
        'g4_math': {'pass': g4_ok, 'msg': g4_msg},
        'g5_label': {'pass': g5_ok, 'msg': g5_msg}
    }
    return all_ok, details

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="LaTeX 规范化与迁移单节门禁校验器")
    parser.add_argument('target', help='待校验的目标 .tex 文件')
    parser.add_argument('--origin', help='原始 OCR/基线 .tex 文件（用于 Gate 3 和 Gate 4 守恒对比）', default=None)
    parser.add_argument('--label-regex', help=f'自定义合规标签正则（默认: {DEFAULT_LABEL_REGEX}）', default=None)
    parser.add_argument('--preamble', help='编译前置宏包文件路径（如缺失 compile_ 包装时使用）', default=None)
    parser.add_argument('--skip-compile', action='store_true', help='跳过 XeLaTeX 实际编译门禁')
    parser.add_argument('--json', action='store_true', help='输出机器可读 JSON 格式结果')
    args = parser.parse_args()
    
    success, details = run_gate(
        args.target,
        original_tex=args.origin,
        label_regex=args.label_regex,
        preamble_path=args.preamble,
        skip_compile=args.skip_compile
    )
    if args.json:
        print("\n=== JSON RESULT ===")
        print(json.dumps(details, ensure_ascii=False, indent=2))
        
    sys.exit(0 if success else 1)
