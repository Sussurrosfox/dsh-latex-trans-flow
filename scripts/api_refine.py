# -*- coding: utf-8 -*-
r"""
Amann《Analysis I-III》中译改造：预处理后处理脚本 (api_refine.py) —— 分段模式 v2

定位：preprocess.py（机械层）之后、agent 之前的"复核修补层"的 API 化实现。
      将 .pre.tex 按【环境完整边界】切成若干段（不在定理/证明/习题/数学环境内部切开），
      逐段调用 OpenAI 兼容 chat/completions 接口完成复核修补。

每段四重校验（v2 已排除脚注重接导致的误报）：
  1. ===SEG===/===REPORT=== 结构完整；
  2. 数学 token 流零变异（剥离脚注与注释后比较，~ 归一化）；
  3. 环境计数不变（剥离脚注与注释后比较；模型只许移动不许增删环境）；
  4. 行数偏差 ≤45%。
校验不过自动重试一次；仍不过则保留原段并记入报告（绝不带病组装）。

用法（试运行：先只处理一节看效果）：
    python api_refine.py <节文件>                     # 分段处理一节，写 .api.tex + 门禁
    python api_refine.py <节文件> --verbose           # 附每段 diff 预览与逐段报告
    python api_refine.py <节文件> --apply             # 门禁全过且 CHECK 清零才采纳为 .pre.tex
    python api_refine.py <节文件> --no-gate           # 跳过门禁
    python api_refine.py <节文件> --seg-lines 120     # 每段目标行数（默认 180）
    python api_refine.py <节文件> --jobs 4            # 并发段数（默认 1，试运行建议 1）
    python api_refine.py <节文件> --skip-clean        # 无 % CHECK 的节直接跳过

参数填写：BASE_URL / API_KEY / MODEL 在下方配置区填写（留空则报错退出）。
  兼容 OpenAI 格式：POST {BASE_URL}/chat/completions
"""

import os
import re
import sys
import json
import time
import difflib
import argparse
import threading
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor

# 确保脚本所在目录加入 sys.path 以便导入工具模块
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

try:
    from config_utils import ensure_utf8_stdio, load_llm_config
    ensure_utf8_stdio()
except ImportError:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    def load_llm_config(args=None, project_root=None):
        return {
            'base_url': os.environ.get('OPENAI_BASE_URL') or os.environ.get('LLM_BASE_URL') or "",
            'api_key': os.environ.get('OPENAI_API_KEY') or os.environ.get('LLM_API_KEY') or "",
            'model': os.environ.get('LLM_MODEL') or os.environ.get('OPENAI_MODEL') or "gpt-4o",
            'temperature': 0.1,
            'max_tokens': 8192,
            'timeout': 300
        }

# ============================ 配置区 ============================
# 优先从环境变量 (OPENAI_BASE_URL, OPENAI_API_KEY, LLM_MODEL)、配置文件 (api_config.json) 或 CLI 读取。
_DEFAULT_CFG = load_llm_config()
BASE_URL = _DEFAULT_CFG.get('base_url', "")
API_KEY = _DEFAULT_CFG.get('api_key', "")
MODEL = _DEFAULT_CFG.get('model', "gpt-4o")
TEMPERATURE = _DEFAULT_CFG.get('temperature', 0.1)
MAX_TOKENS = _DEFAULT_CFG.get('max_tokens', 8192)        # 单段输出上限（段约 180 行，8192 足够；截断可调大）
SEG_LINES = 180          # 每段目标行数
TAIL_LINES = 12          # 传递给下一段的上下文尾行数
TIMEOUT = _DEFAULT_CFG.get('timeout', 300)            # 单段调用超时（秒）
RETRIES = 2
# ============================================================================

SYSTEM_PROMPT = r"""你是数学教材中译改造的"结构化复核"助手。输入是一份已被 Python 脚本
机械预处理的 LaTeX 节文件的一个【分段】，另附上一段结尾与下一段开头的少量"上下文行"
（仅供理解语境，严禁重复输出）。公式编号、定理/证明/习题环境、脚注重接、标点全角化已由
脚本完成，但环境结束边界是启发式推断的，段内可能留有 % CHECK 标记。

本段任务（只复核修补段内内容）：
1. 处理段内每一个 % CHECK 标记：
   - "环境结束位置为启发式推断"：对照段内后续内容（含"下一段开头"上下文）核对 \end 位置；
     若下一段开头已显示该环境确已结束，直接确认并删除标记；仍不足以下结论时原样保留。
   - "悬置脚注 n" / "待人工重接的断裂脚注块"：在段内寻找锚点 \({}^n\) 或 ${}^n$
     （形态不定，可能在数学区内），改写为行内 \footnote{...} 并删除标记；找不到则保留。
   - "已删除OCR书眉行"：无需处理，可删除该注释行。
2. 环境配对修复【只能通过移动 \begin/\end 的位置完成】，不得新增、不得删除任何环境。
   定理/证明/习题环境不得跨越 itemize/enumerate/center 等边界。
   - 若发现脚本漏包的裸编号习题（如习题小节后裸写的 "3 …"），不要自行补环境，
     在该行行首加标记 "% FIXME-ex:习题N"。
   - 若发现必须删除/新增才能修复的环境错误（疑似脚本误生成），不要删改，
     在该处加标记 "% FIXME-env:说明"。
3. 命名定理（如"定理(柯西-施瓦茨不等式)"）把名称移入环境可选参数
   \begin{theorem}[柯西-施瓦茨不等式]，环境正文只留陈述本身。
4. % FIXME-ref 跨节引用标记保持原样，严禁猜测或编造 \label / \cref。
5. 红线：不得改动任何数学公式内容与记号；不得增删数学论断；不得修改既有 \label；
   不得改变中文正文实质内容（除明显 OCR 错字，如误识的"我"、孤立标点）。

输出格式（严格遵守，两个标记各出现一次）：
===SEG===
<修正后的本段完整内容：只含本段行，不含任何上下文行，不加任何解释>
===REPORT===
<本段修改说明；无修改写"无">"""

SWEEP_PROMPT = r"""你是 LaTeX 复核助手。下面是从一份预处理后的节文件中截取的【窗口】，
其中标注行号的一行是 % CHECK 标记（脚本对紧邻其上的 \end{...} 环境结束位置不确定）。

任务：判断该 \end{...} 的位置是否正确。
- 若正确：回答 ===VERDICT=== OK（我会直接删除该标记行）。
- 若不正确：回答 ===VERDICT=== FIX，并在 ===WINDOW=== 中给出修正后的完整窗口
  （只可移动 \end{...} 的位置并删除该 % CHECK 标记行；不得改动数学公式、
  不得增删环境、不得改动其他任何文字）。
- 若窗口信息不足以下结论：回答 ===VERDICT=== KEEP（保留标记待人工处理）。

输出格式：
===VERDICT===
OK 或 FIX 或 KEEP
===WINDOW===
（FIX 时给出修正后的窗口全文；否则留空）
===REPORT===
一句说明"""

_print_lock = threading.Lock()


def log(*a):
    with _print_lock:
        print(*a)
        sys.stdout.flush()


def estimate_tokens(text):
    cjk = len(re.findall(r'[一-鿿　-〿＀-￯]', text))
    return int(cjk + (len(text) - cjk) / 4)


def call_llm(messages):
    """调用 OpenAI 兼容接口，返回 (content, usage)。"""
    if not BASE_URL or not API_KEY:
        print('错误：缺少 BASE_URL 或 API_KEY。请通过环境变量、配置文件或 CLI 参数提供。')
        sys.exit(2)
    url = BASE_URL.rstrip('/') + '/chat/completions'
    payload = {'model': MODEL, 'messages': messages,
               'temperature': TEMPERATURE, 'max_tokens': MAX_TOKENS,
               'stream': False}
    body = json.dumps(payload).encode('utf-8')
    last_err = None
    for attempt in range(RETRIES + 1):
        try:
            req = urllib.request.Request(url, data=body, method='POST', headers={
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + API_KEY,
            })
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            return data['choices'][0]['message']['content'], data.get('usage', {})
        except urllib.error.HTTPError as e:
            last_err = 'HTTP %s: %s' % (e.code, e.read().decode('utf-8', 'replace')[:400])
        except Exception as e:
            last_err = str(e)
        if attempt < RETRIES:
            wait = 5 * (attempt + 1)
            log('  调用失败（%s），%d 秒后重试 [%d/%d]...' % (last_err, wait, attempt + 1, RETRIES))
            time.sleep(wait)
    raise RuntimeError('API 调用最终失败：%s' % last_err)


def read(path):
    for enc in ('utf-8', 'utf-8-sig'):
        try:
            with open(path, 'r', encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    raise ValueError('无法解码 %s' % path)


# ---------------------------------------------------------------- 分段

ENV_RE = re.compile(r'\\(begin|end)\s*\{([^}]*)\}')


def line_depth_delta(line):
    r"""单行对环境深度的净增量（\begin/\end 配对，独立成行的显示数学计入）。"""
    delta = 0
    for kind, name in ENV_RE.findall(line):
        name = re.sub(r'\s+', '', name)
        if name == 'document':
            continue
        delta += 1 if kind == 'begin' else -1
    if re.search(r'\\\[', line):
        delta += 1
    if re.search(r'\\\]', line):
        delta -= 1
    return delta


def split_segments(lines, target, hard_cap):
    r"""在【深度 0 的空行】处切分；返回 [(start, end)]（end exclusive，空行归属前段末尾）。
    保证每段内部环境配对完整（除单个环境超过 hard_cap 的极端情况）。"""
    candidates = set()
    depth = 0
    for i, ln in enumerate(lines):
        before = depth
        depth += line_depth_delta(ln)
        if ln.strip() == '' and before == 0 and depth == 0:
            candidates.add(i + 1)  # 切在该空行之后（空行归前段）
    segs = []
    start = 0
    acc = 0
    for i in range(len(lines)):
        acc += 1
        if acc >= target and (i + 1) in candidates and i + 1 < len(lines):
            segs.append((start, i + 1))
            start = i + 1
            acc = 0
        elif acc >= hard_cap:
            nxt = next((c for c in sorted(candidates) if c > i + 1), None)
            if nxt is not None:
                segs.append((start, nxt))
                start = nxt
                acc = 0
    if start < len(lines):
        segs.append((start, len(lines)))
    return segs


# ---------------------------------------------------------------- 单段校验

def strip_noise(text):
    r"""剥离 \footnote{...}（平衡括号）与注释——脚注重接是预期变更，不参与校验。"""
    text = re.sub(r'(?m)%.*$', '', text)
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


def env_counts(text):
    c = {}
    for kind, name in ENV_RE.findall(text):
        name = re.sub(r'\s+', '', name)
        if name == 'document':
            continue
        key = (kind, name)
        c[key] = c.get(key, 0) + 1
    return c


def first_diff(a, b):
    """返回首个差异处的上下文描述（用于校验失败的原因定位）。"""
    sm = difflib.SequenceMatcher(None, a, b)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != 'equal':
            ca = a[max(0, i1 - 25):min(len(a), i2 + 25)]
            cb = b[max(0, j1 - 25):min(len(b), j2 + 25)]
            return '…%r / …%r' % (ca, cb)
    return '（无可见差异）'


def validate_segment(src_lines, out_lines):
    r"""返回 (ok, reason)。剥离脚注/注释后：数学 token 流零变异 + 环境计数不变 + 长度合理。"""
    from gate_check import extract_math
    src_text = strip_noise('\n'.join(src_lines))
    out_text = strip_noise('\n'.join(out_lines))
    if abs(len(out_lines) - len(src_lines)) > max(30, int(len(src_lines) * 0.45)):
        return False, '行数偏差过大（%d → %d）' % (len(src_lines), len(out_lines))
    ci, co = env_counts(src_text), env_counts(out_text)
    for key in set(ci) | set(co):
        if ci.get(key, 0) != co.get(key, 0):
            return False, '环境计数变化：%s %s→%s（环境只许移动位置）' % (
                key, ci.get(key, 0), co.get(key, 0))
    mi = extract_math(src_text)
    mo = extract_math(out_text)
    if mi != mo:
        return False, '数学 token 流变异（%d → %d）：%s' % (
            len(mi), len(mo), first_diff(mi, mo))
    return True, 'ok'


def sweep_residual_checks(text, progress=None):
    """对残余 % CHECK 标记逐一开小窗确认/修正（自下而上）。返回 (新文本, 已解决数, 说明列表)。"""
    lines = text.split('\n')
    notes = []
    resolved = 0
    i = len(lines) - 1
    while i >= 0:
        if '% CHECK' not in lines[i]:
            i -= 1
            continue
        lo = max(0, i - 30)
        hi = min(len(lines), i + 30)
        window = lines[lo:hi]
        marker_off = i - lo
        user = ('【窗口内容：第 %d 行为 %% CHECK 标记（窗口共 %d 行）】\n%s'
                % (marker_off + 1, len(window), '\n'.join(window)))
        messages = [{'role': 'system', 'content': SWEEP_PROMPT},
                    {'role': 'user', 'content': user}]
        try:
            content, _ = call_llm(messages)
        except RuntimeError as e:
            notes.append('行 %d：API 失败（%s），保留标记' % (i + 1, e))
            i -= 1
            continue
        vm = re.search(r'===VERDICT===\s*\n\s*(OK|FIX|KEEP)', content)
        verdict = vm.group(1) if vm else None
        rep = re.search(r'===REPORT===\s*\n(.*)$', content, re.DOTALL)
        rep_text = (rep.group(1).strip()[:120] if rep else '')
        if verdict == 'OK':
            lines.pop(i)
            resolved += 1
            notes.append('行 %d：确认边界正确，删除标记（%s）' % (i + 1, rep_text))
            i -= 1
        elif verdict == 'FIX':
            wm = re.search(r'===WINDOW===\s*\n(.*?)\n===REPORT===', content, re.DOTALL)
            if not wm:
                notes.append('行 %d：FIX 但缺少窗口内容，保留标记' % (i + 1))
                i -= 1
                continue
            new_win = wm.group(1).split('\n')
            while new_win and new_win[0].strip() == '':
                new_win.pop(0)
            while new_win and new_win[-1].strip() == '':
                new_win.pop()
            from gate_check import extract_math
            if ('% CHECK' in '\n'.join(new_win)
                    or extract_math(strip_noise('\n'.join(window)))
                       != extract_math(strip_noise('\n'.join(new_win)))
                    or abs(len(new_win) - len(window)) > 10):
                notes.append('行 %d：FIX 未过校验，保留标记' % (i + 1))
                i -= 1
                continue
            lines[lo:hi] = new_win
            resolved += 1
            notes.append('行 %d：修正边界并删除标记（%s）' % (i + 1, rep_text))
            i = lo - 1
        else:
            notes.append('行 %d：模型判断信息不足（KEEP），保留标记（%s）' % (i + 1, rep_text))
            i -= 1
        if progress:
            progress(resolved)
    return '\n'.join(lines), resolved, notes


def process_segment(idx, total, src_lines, tail_lines, head_lines=None):
    """处理一个分段，返回 (out_lines, report, note)。
    tail_lines = 上一段结尾（上文），head_lines = 下一段开头（下文，供判断段尾环境边界）。"""
    seg_text = '\n'.join(src_lines)
    user = ['下面是节文件的一个分段。']
    if tail_lines:
        user.append('【上下文A：上一段结尾 %d 行，仅供理解，严禁重复输出】\n%s'
                    % (len(tail_lines), '\n'.join(tail_lines)))
    if head_lines:
        user.append('【上下文B：下一段开头 %d 行，仅供判断段尾环境边界，严禁重复输出】\n%s'
                    % (len(head_lines), '\n'.join(head_lines)))
    user.append('【本段内容（共 %d 行）】\n%s' % (len(src_lines), seg_text))
    messages = [{'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': '\n\n'.join(user)}]

    note = '未知错误'
    for attempt in range(2):
        try:
            content, usage = call_llm(messages)
        except RuntimeError as e:
            return src_lines, '（API 失败：%s）' % e, 'API 失败，保留原段'
        m = re.search(r'===SEG===\s*\n(.*?)\n===REPORT===\s*\n(.*)$', content, re.DOTALL)
        if not m:
            note = '输出缺少 ===SEG===/===REPORT=== 结构'
        else:
            out_lines = m.group(1).split('\n')
            while out_lines and out_lines[0].strip() == '':
                out_lines.pop(0)
            while out_lines and out_lines[-1].strip() == '':
                out_lines.pop()
            ok, reason = validate_segment(src_lines, out_lines)
            if ok:
                left = len(re.findall(r'% CHECK', '\n'.join(out_lines)))
                note = 'ok（%d→%d 行，残余 CHECK %d）' % (len(src_lines), len(out_lines), left)
                log('  段 %d/%d：%s' % (idx, total, note))
                return out_lines, m.group(2).strip('\n'), note
            note = reason
        log('  段 %d/%d：校验未过（%s），重试一次...' % (idx, total, note))
        messages.append({'role': 'user', 'content':
                         '上一次输出未通过自动校验：%s。请重新输出，严格遵守：只输出本段修正内容，'
                         '不得改动任何数学公式，不得增删 \\begin/\\end 环境（只可移动位置），'
                         '并保持 ===SEG===/===REPORT=== 结构。' % note})
    return src_lines, '（自动校验未通过：%s；已保留原段，待人工处理）' % note, note


def main():
    ap = argparse.ArgumentParser(description='LaTeX 节文件分段复核修补工具 (api_refine)')
    ap.add_argument('target', help='节文件（NN_Section_N.tex 或其 .pre.tex）')
    ap.add_argument('--base-url', default=None, help='LLM API Base URL（优先级高于配置文件与环境变量）')
    ap.add_argument('--api-key', default=None, help='LLM API Key（优先级高于配置文件与环境变量）')
    ap.add_argument('--model', default=None, help='覆盖 MODEL 配置')
    ap.add_argument('--config', default=None, help='指定配置文件路径（如 api_config.json）')
    ap.add_argument('--preamble', default=None, help='编译门禁前置宏包路径（解耦写死的 ../preamble.tex）')
    ap.add_argument('--apply', action='store_true',
                    help='门禁全过且 CHECK 清零时，将 .api.tex 采纳为新的 .pre.tex')
    ap.add_argument('--no-gate', action='store_true', help='跳过门禁')
    ap.add_argument('--verbose', action='store_true', help='打印每段 diff 预览与逐段报告')
    ap.add_argument('--seg-lines', type=int, default=SEG_LINES, help='每段目标行数')
    ap.add_argument('--tail', type=int, default=TAIL_LINES, help='上下文尾行数')
    ap.add_argument('--jobs', type=int, default=1, help='并发段数（默认 1）')
    ap.add_argument('--skip-clean', action='store_true', help='无 %% CHECK 的节直接跳过')
    args = ap.parse_args()

    global BASE_URL, API_KEY, MODEL, TEMPERATURE, MAX_TOKENS, TIMEOUT
    # 动态加载并覆盖 LLM 配置
    cfg = load_llm_config(args)
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

    BASE_URL = cfg.get('base_url', BASE_URL)
    API_KEY = cfg.get('api_key', API_KEY)
    MODEL = cfg.get('model', MODEL)
    TEMPERATURE = cfg.get('temperature', TEMPERATURE)
    MAX_TOKENS = cfg.get('max_tokens', MAX_TOKENS)
    TIMEOUT = cfg.get('timeout', TIMEOUT)

    if not API_KEY or API_KEY == "YOUR_API_KEY_HERE" or not BASE_URL:
        if 'find_project_root' in globals():
            proj_root = find_project_root()
        else:
            try:
                from config_utils import find_project_root
                proj_root = find_project_root()
            except Exception:
                proj_root = os.getcwd()
        target_cfg = os.path.join(proj_root or os.getcwd(), 'api_config.json')
        template_file = os.path.join(_SCRIPT_DIR, '..', 'api_config.template.json')
        if not os.path.exists(target_cfg) and os.path.exists(template_file):
            import shutil
            try:
                shutil.copy(template_file, target_cfg)
                print(f"[提示] 已为您在项目根目录下生成配置文件模板：{target_cfg}")
            except Exception:
                pass
        print(f"\n[FAIL] 缺少有效 API Key。请在项目根目录的 api_config.json 中填入真实的 API Key（或配置 OPENAI_API_KEY 环境变量）。")
        sys.exit(2)

    # ---- 定位 .pre.tex ----
    target = args.target
    if target.endswith('.pre.tex'):
        base = target[:-len('.pre.tex')]
    elif target.endswith('.tex'):
        base = target[:-len('.tex')]
    else:
        print('错误：目标必须是 .tex 或 .pre.tex 文件')
        sys.exit(2)
    pre_path = base + '.pre.tex'
    if not os.path.exists(pre_path):
        print('错误：未找到 %s' % pre_path)
        print('请先运行：python preprocess.py %s' % (base + '.tex'))
        sys.exit(2)
    orig_path = base + '.tex'
    pre_text = read(pre_path)
    orig_text = read(orig_path)

    n_check = len(re.findall(r'% CHECK', pre_text))
    print('=== api_refine（分段模式 v2）: %s ===' % os.path.basename(pre_path))
    print('模型: %s | 输入 %d 字符（约 %d tokens）| %% CHECK 标记 %d 个' % (
        MODEL, len(pre_text), estimate_tokens(pre_text), n_check))
    if n_check == 0 and args.skip_clean:
        print('无 %% CHECK 标记，--skip-clean 生效，跳过。')
        return

    # ---- 分段 ----
    lines = pre_text.split('\n')
    segs = split_segments(lines, args.seg_lines, args.seg_lines * 3)
    print('分为 %d 段（目标 %d 行/段，上下文尾 %d 行，并发 %d）' % (
        len(segs), args.seg_lines, args.tail, args.jobs))

    # ---- 逐段处理 ----
    results = [None] * len(segs)

    def work(k):
        s, e = segs[k]
        src = lines[s:e]
        tail = []
        if k > 0:
            ps, pe = segs[k - 1]
            prev = [l for l in lines[ps:pe] if l.strip()]
            tail = prev[-args.tail:]
        head = []
        if k + 1 < len(segs):
            hs, he = segs[k + 1]
            head = [l for l in lines[hs:he] if l.strip()][:args.tail]
        t0 = time.time()
        out, report, note = process_segment(k + 1, len(segs), src, tail, head)
        results[k] = (out, report, note, time.time() - t0)

    if args.jobs > 1:
        with ThreadPoolExecutor(max_workers=args.jobs) as ex:
            list(ex.map(work, range(len(segs))))
    else:
        for k in range(len(segs)):
            work(k)

    out_lines = []
    reports = []
    for k, (out, report, note, dt) in enumerate(results):
        s, e = segs[k]
        out_lines.extend(out)
        reports.append('## 段 %d/%d（原 %d–%d 行，%.1fs，%s）\n\n%s'
                       % (k + 1, len(segs), s + 1, e, dt, note, report))
    api_text = '\n'.join(out_lines)
    if not api_text.endswith('\n'):
        api_text += '\n'

    left_check = len(re.findall(r'% CHECK', api_text))
    print('组装完成：%d 行（原 %d 行），残余 %% CHECK：%d（原 %d）' % (
        len(out_lines), len(lines), left_check, n_check))

    # ---- 残余 CHECK 清扫（小窗二选一确认） ----
    sweep_notes = []
    if left_check > 0:
        print('启动清扫 pass：%d 个残余标记...' % left_check)
        api_text, resolved, sweep_notes = sweep_residual_checks(api_text)
        left_check = len(re.findall(r'% CHECK', api_text))
        print('清扫完成：解决 %d 个，残余 %d 个' % (resolved, left_check))

    # ---- 写出 ----
    api_path = base + '.api.tex'
    with open(api_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(api_text)
    report_path = base + '.api.report.md'
    with open(report_path, 'w', encoding='utf-8', newline='\n') as f:
        sweep_md = ('\n\n## 清扫 pass（残余 CHECK 处理）\n\n' + '\n'.join('- ' + n for n in sweep_notes)) if sweep_notes else ''
        f.write('# 复核报告（分段模式 v2）：%s\n\n%s%s\n' % (
            os.path.basename(base), '\n\n'.join(reports), sweep_md))
    print('已写出 %s / %s' % (os.path.basename(api_path), os.path.basename(report_path)))

    if args.verbose:
        sm = difflib.SequenceMatcher(None, lines, out_lines)
        shown = 0
        print('---- diff 预览（前 50 处变更）----')
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == 'equal':
                continue
            print('@@ -%d,%d +%d,%d @@' % (i1 + 1, i2 - i1, j1 + 1, j2 - j1))
            for l in lines[i1:i2][:3]:
                print('  - ' + l[:110])
            for l in out_lines[j1:j2][:3]:
                print('  + ' + l[:110])
            shown += 1
            if shown >= 50:
                print('……（其余从略，详见 .api.report.md）')
                break

    # ---- 门禁 ----
    if args.no_gate:
        print('（--no-gate：跳过门禁）')
        return
    from gate_check import (check_clean_macros, check_label_format,
                            check_theorem_count, check_math_tokens,
                            check_compilation)
    wrap = os.path.join(os.path.dirname(api_path), 'compile_' + os.path.basename(api_path))
    if args.preamble:
        try:
            preamble_ref = os.path.relpath(os.path.abspath(args.preamble), os.path.dirname(os.path.abspath(api_path))).replace('\\', '/')
        except Exception:
            preamble_ref = os.path.abspath(args.preamble).replace('\\', '/')
    else:
        preamble_ref = '../preamble.tex'

    with open(wrap, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\\input{%s}\n\\begin{document}\n\\input{%s.tex}\n\\end{document}\n'
                % (preamble_ref, os.path.basename(api_path)[:-4]))
    g1, m1 = check_compilation(api_path, preamble_path=args.preamble)
    g2, m2 = check_clean_macros(api_text)
    g3, m3 = check_theorem_count(orig_text, api_text)
    g4, m4 = check_math_tokens(orig_text, api_text)
    g5, m5 = check_label_format(api_text)
    print('---- 门禁（基线 = 原始 %s）----' % os.path.basename(orig_path))
    print('G1 编译        : %s - %s' % ('PASS' if g1 else 'FAIL', m1))
    print('G2 宏洁净      : %s %s' % ('PASS' if g2 else 'FAIL', '' if g2 else m2))
    print('G3 定理计数    : %s - %s' % ('PASS' if g3 else 'FAIL', m3))
    print('G4 数学 token  : %s - %s' % ('PASS' if g4 else 'FAIL', m4))
    print('G5 label 格式  : %s - %s' % ('PASS' if g5 else 'FAIL', m5))
    all_ok = g1 and g2 and g3 and g4 and g5
    print('总计: %s' % ('ALL PASSED' if all_ok else 'REJECTED'))
    if left_check:
        print('注意：仍有 %d 个 %% CHECK 标记未处理（段内信息不足或校验未过），详见报告。' % left_check)

    if args.apply and all_ok and left_check == 0:
        with open(pre_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(api_text)
        print('已采纳：%s 已更新为复核后版本' % os.path.basename(pre_path))
    elif args.apply:
        print('门禁未全过或尚有 CHECK 残留，拒绝 --apply。')
    if not all_ok:
        sys.exit(1)


if __name__ == '__main__':
    main()
