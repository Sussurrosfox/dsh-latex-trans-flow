# -*- coding: utf-8 -*-
"""
compile_all_volumes.py - 全书多模块 XeLaTeX 联合编译回归验证工具

通用增强版特性：
1. 抹平 Windows / Linux 终端编码差异（引入 config_utils.ensure_utf8_stdio）；
2. 支持自动化识别项目根目录（引入 config_utils.find_project_root）；
3. 提供命令行参数支持（--root, --config, --timeout, --pattern）；
4. 保留 Amann 18 个模块作为向后兼容基线（DEFAULT_MODULES）；
5. 支持通过 JSON 配置文件自定义模块列表；若非默认工程且未提供配置则基于正则自动探测模块；
6. 完善的单模块编译超时保护（默认 300 秒）。
"""

import os
import sys
import time
import re
import json
import argparse
import subprocess
from pathlib import Path

# 引入 config_utils 通用配置工具
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

try:
    from config_utils import ensure_utf8_stdio, find_project_root
    ensure_utf8_stdio()
except ImportError:
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
    def find_project_root(start_path=None):
        return os.path.abspath(start_path or os.getcwd())

# Amann 默认 18 个模块基线（保持向后兼容）
DEFAULT_MODULES = [
    # 卷 I (7 个)
    ("Vol I", r"Analysis I Herbert Amann_ Joachim Escher - Analysis I 1 (2004, Birkhäuser) - libgen.li.pdf_ot_db2be1c91nqc73d37ek0\chapters_translate", "compile_00_Frontmatter.tex"),
    ("Vol I", r"Analysis I Herbert Amann_ Joachim Escher - Analysis I 1 (2004, Birkhäuser) - libgen.li.pdf_ot_db2be1c91nqc73d37ek0\chapters_translate", "compile_01_Chapter_I.tex"),
    ("Vol I", r"Analysis I Herbert Amann_ Joachim Escher - Analysis I 1 (2004, Birkhäuser) - libgen.li.pdf_ot_db2be1c91nqc73d37ek0\chapters_translate", "compile_02_Chapter_II.tex"),
    ("Vol I", r"Analysis I Herbert Amann_ Joachim Escher - Analysis I 1 (2004, Birkhäuser) - libgen.li.pdf_ot_db2be1c91nqc73d37ek0\chapters_translate", "compile_03_Chapter_III.tex"),
    ("Vol I", r"Analysis I Herbert Amann_ Joachim Escher - Analysis I 1 (2004, Birkhäuser) - libgen.li.pdf_ot_db2be1c91nqc73d37ek0\chapters_translate", "compile_04_Chapter_IV.tex"),
    ("Vol I", r"Analysis I Herbert Amann_ Joachim Escher - Analysis I 1 (2004, Birkhäuser) - libgen.li.pdf_ot_db2be1c91nqc73d37ek0\chapters_translate", "compile_05_Chapter_V.tex"),
    ("Vol I", r"Analysis I Herbert Amann_ Joachim Escher - Analysis I 1 (2004, Birkhäuser) - libgen.li.pdf_ot_db2be1c91nqc73d37ek0\chapters_translate", "compile_06_Backmatter.tex"),

    # 卷 II (5 个)
    ("Vol II", r"Analysis II (Herbert Amann, Joachim Escher) (Z-Library).pdf_ot_db2ba4c91nqc73d37dc0\chapters_translate", "compile_00_Frontmatter.tex"),
    ("Vol II", r"Analysis II (Herbert Amann, Joachim Escher) (Z-Library).pdf_ot_db2ba4c91nqc73d37dc0\chapters_translate", "compile_01_Chapter_VI.tex"),
    ("Vol II", r"Analysis II (Herbert Amann, Joachim Escher) (Z-Library).pdf_ot_db2ba4c91nqc73d37dc0\chapters_translate", "compile_02_Chapter_VII.tex"),
    ("Vol II", r"Analysis II (Herbert Amann, Joachim Escher) (Z-Library).pdf_ot_db2ba4c91nqc73d37dc0\chapters_translate", "compile_03_Chapter_VIII.tex"),
    ("Vol II", r"Analysis II (Herbert Amann, Joachim Escher) (Z-Library).pdf_ot_db2ba4c91nqc73d37dc0\chapters_translate", "compile_04_Backmatter.tex"),

    # 卷 III (6 个)
    ("Vol III", r"Analysis III (Herbert Amann , Joachim Escher) (Z-Library).pdf_ot_db2b5dc91nqc73d37bm0\chapters_translate", "compile_00_Frontmatter.tex"),
    ("Vol III", r"Analysis III (Herbert Amann , Joachim Escher) (Z-Library).pdf_ot_db2b5dc91nqc73d37bm0\chapters_translate", "compile_01_Chapter_IX.tex"),
    ("Vol III", r"Analysis III (Herbert Amann , Joachim Escher) (Z-Library).pdf_ot_db2b5dc91nqc73d37bm0\chapters_translate", "compile_02_Chapter_X.tex"),
    ("Vol III", r"Analysis III (Herbert Amann , Joachim Escher) (Z-Library).pdf_ot_db2b5dc91nqc73d37bm0\chapters_translate", "compile_03_Chapter_XI.tex"),
    ("Vol III", r"Analysis III (Herbert Amann , Joachim Escher) (Z-Library).pdf_ot_db2b5dc91nqc73d37bm0\chapters_translate", "compile_04_Chapter_XII.tex"),
    ("Vol III", r"Analysis III (Herbert Amann , Joachim Escher) (Z-Library).pdf_ot_db2b5dc91nqc73d37bm0\chapters_translate", "compile_05_Backmatter.tex"),
]

# 向后兼容接口别名
MODULES = DEFAULT_MODULES


def load_modules_from_config(config_path, project_root):
    """
    从 JSON 配置文件中解析待编译模块列表。
    支持格式：
    1. {"modules": [["Vol I", "path/to/dir", "compile_xx.tex"], ...]}
    2. {"modules": [{"volume": "Vol I", "dir": "...", "tex": "..."}, ...]}
    3. 直接为顶层列表: [["Vol I", ...], ...]
    """
    with open(config_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    raw_items = data.get('modules', data) if isinstance(data, dict) else data
    if not isinstance(raw_items, list):
        raise ValueError(f"配置文件 {config_path} 格式无效，未找到列表形式的模块定义")

    modules = []
    for item in raw_items:
        if isinstance(item, (list, tuple)) and len(item) >= 3:
            vname, vdir, tex_name = item[0], item[1], item[2]
        elif isinstance(item, dict):
            vname = item.get('volume', item.get('name', 'Module'))
            vdir = item.get('dir', item.get('path', ''))
            tex_name = item.get('tex', item.get('file', ''))
        else:
            continue

        if not os.path.isabs(vdir):
            vdir = os.path.normpath(os.path.join(project_root, vdir))
        modules.append((vname, vdir, tex_name))

    return modules


def discover_modules(project_root, pattern=r'^compile_.*\.tex$'):
    """
    在 project_root 下递归自动搜索匹配 pattern 的编译模块文件。
    自动推断所属卷名及目录。
    """
    regex = re.compile(pattern, re.IGNORECASE)
    discovered = []
    ignored_dirs = {'.git', '.langgraph', '__pycache__', '.pytest_cache', 'build', '.idea', '.vscode'}

    for root_dir, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in ignored_dirs and not d.startswith('.')]

        for fn in sorted(files):
            if regex.search(fn):
                vdir = os.path.abspath(root_dir)
                rel = os.path.relpath(vdir, project_root)
                parts = Path(rel).parts

                # 启发式推断卷名称
                vname = "Main"
                if parts and parts[0] != '.':
                    top_name = parts[0]
                    m_vol = re.search(r'(?:Vol(?:ume)?|Analysis)[_\s-]*([IVXLCDM\d]+)', top_name, re.IGNORECASE)
                    if m_vol:
                        vname = f"Vol {m_vol.group(1).upper()}"
                    else:
                        vname = top_name

                discovered.append((vname, vdir, fn))

    discovered.sort(key=lambda x: (x[0], x[2]))
    return discovered


def is_default_amann_project(project_root):
    """检测当前 project_root 是否为 Amann 原工程目录结构"""
    matched = 0
    for _, vdir, tex_name in DEFAULT_MODULES:
        full_path = os.path.join(project_root, vdir, tex_name)
        if os.path.exists(full_path):
            matched += 1
    return matched >= 3


def resolve_modules(project_root, config_path=None, pattern=r'^compile_.*\.tex$'):
    """解析待编译模块列表，具有自适应优先级：CLI 配置 > 默认 Amann 工程 > 正则自动探测"""
    # 1. 若显式提供 config
    if config_path:
        cfg_full = os.path.abspath(config_path) if os.path.isabs(config_path) else os.path.join(project_root, config_path)
        if not os.path.exists(cfg_full):
            raise FileNotFoundError(f"指定的配置文件不存在: {cfg_full}")
        return load_modules_from_config(cfg_full, project_root)

    # 2. 检查是否为 Amann 默认工程且 pattern 未被自定义修改
    default_pattern = r'^compile_.*\.tex$'
    if pattern == default_pattern and is_default_amann_project(project_root):
        modules = []
        for vname, vdir, tex_name in DEFAULT_MODULES:
            full_vdir = os.path.normpath(os.path.join(project_root, vdir)) if not os.path.isabs(vdir) else vdir
            modules.append((vname, full_vdir, tex_name))
        return modules

    # 3. 自动探测匹配 pattern 的模块
    print(f"[提示] 自动探测匹配正则 '{pattern}' 的编译模块...")
    discovered = discover_modules(project_root, pattern=pattern)
    if not discovered and is_default_amann_project(project_root):
        # 兜底回退到 DEFAULT_MODULES
        modules = []
        for vname, vdir, tex_name in DEFAULT_MODULES:
            full_vdir = os.path.normpath(os.path.join(project_root, vdir)) if not os.path.isabs(vdir) else vdir
            modules.append((vname, full_vdir, tex_name))
        return modules

    # 4. 单卷专著兜底探测（如 main.tex, book.tex, 项目根目录主文件等）
    if not discovered:
        cands = ['main.tex', 'book.tex', 'document.tex']
        for f in sorted(os.listdir(project_root)):
            if f.endswith('.tex') and not f.startswith('.') and f not in cands:
                cands.append(f)
        for cand in cands:
            cand_p = os.path.join(project_root, cand)
            if os.path.isfile(cand_p):
                try:
                    with open(cand_p, 'r', encoding='utf-8', errors='ignore') as f_cand:
                        content = f_cand.read(4096)
                        if r'\documentclass' in content and (r'\begin{document}' in content or r'\subfile' in content):
                            print(f"[提示] 探测到单卷专著主文档: {cand}")
                            discovered.append(("Main", project_root, cand))
                            break
                except Exception:
                    pass

    return discovered


def main():
    parser = argparse.ArgumentParser(description="全书多模块 XeLaTeX 联合编译回归验证工具")
    parser.add_argument("--root", type=str, default=None, help="项目根目录（默认自动查找）")
    parser.add_argument("--config", type=str, default=None, help="模块配置文件（JSON 格式，指定待编译的模块列表）")
    parser.add_argument("--timeout", type=int, default=300, help="单模块编译超时时间（秒，默认 300）")
    parser.add_argument("--pattern", type=str, default=r"^compile_.*\.tex$",
                        help="自动搜索 compile_*.tex 模块的正则模式（若未提供 config 且非默认工程时自动探测）")
    args = parser.parse_args()

    project_root = find_project_root(args.root)
    modules = resolve_modules(project_root, config_path=args.config, pattern=args.pattern)

    print(f"==================================================================")
    print(f"  XeLaTeX 联合编译回归验收 (项目根目录: {project_root})")
    print(f"  待编译模块总数: {len(modules)} 个 | 超时上限: {args.timeout}s")
    print(f"==================================================================")

    if not modules:
        print("[警告] 未发现可编译的模块，请检查项目路径或 --pattern/--config 设置。")
        sys.exit(1)

    results = []
    for vname, vdir, tex_name in modules:
        tex_path = os.path.join(vdir, tex_name)
        pdf_name = tex_name.rsplit('.', 1)[0] + ".pdf"
        pdf_path = os.path.join(vdir, pdf_name)

        if not os.path.exists(tex_path):
            print(f"[{vname}] {tex_name:28s} -> NOT FOUND (文件缺失: {tex_path})")
            results.append({
                'volume': vname,
                'module': tex_name,
                'success': False,
                'returncode': -2,
                'elapsed': 0.0,
                'pdf_size': 0
            })
            continue

        # 记录初始时间并运行 xelatex (使用临时文件重定向避免 Windows 管道死锁，确保超时时树状强制终结)
        t0 = time.time()
        cmd = ["xelatex", "-interaction=nonstopmode", tex_name]
        run_log_path = os.path.join(vdir, f".{tex_name}.compile.log")
        try:
            with open(run_log_path, 'w', encoding='utf-8', errors='ignore') as log_f:
                proc = subprocess.Popen(
                    cmd,
                    cwd=vdir,
                    stdout=log_f,
                    stderr=subprocess.STDOUT
                )
                proc.wait(timeout=args.timeout)
            elapsed = time.time() - t0
            retcode = proc.returncode
            timed_out = False
        except subprocess.TimeoutExpired:
            elapsed = time.time() - t0
            retcode = -1
            timed_out = True
            # Windows 平台下树状终结 xelatex 及其派生的 xdvipdfmx 僵尸进程，彻底释放文件锁
            if os.name == 'nt':
                try:
                    subprocess.run(['taskkill', '/F', '/T', '/PID', str(proc.pid)], capture_output=True)
                except Exception:
                    pass
            try:
                proc.kill()
                proc.wait()
            except Exception:
                pass

        pdf_exists = os.path.exists(pdf_path)
        pdf_size = os.path.getsize(pdf_path) if pdf_exists else 0
        success = (not timed_out) and (retcode == 0) and pdf_exists and (pdf_size > 1000)

        if timed_out:
            status_str = "TIMEOUT"
        elif success:
            status_str = "PASS"
        else:
            status_str = "FAIL"

        print(f"[{vname}] {tex_name:28s} -> {status_str} (exitcode: {retcode}, time: {elapsed:.1f}s, size: {pdf_size/1024:.1f}KB)")

        results.append({
            'volume': vname,
            'module': tex_name,
            'success': success,
            'returncode': retcode,
            'elapsed': elapsed,
            'pdf_size': pdf_size
        })

    total_count = len(results)
    total_pass = sum(1 for r in results if r['success'])
    pass_rate = (total_pass / total_count * 100) if total_count > 0 else 0.0

    print(f"\n==================================================================")
    print(f"                      编译验收结论汇总")
    print(f"==================================================================")
    print(f"总计编译模块: {total_count} 个")
    print(f"成功编译通过: {total_pass} 个")
    print(f"综合通过率  : {pass_rate:.2f}%")
    print(f"==================================================================")

    # 零信任门禁判定：存在编译失败模块时必须返回非零 exit code，阻断假绿灯
    if total_pass < total_count:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
