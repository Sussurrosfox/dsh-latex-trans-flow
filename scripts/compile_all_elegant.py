# -*- coding: utf-8 -*-
"""
compile_all_elegant.py - 全书多卷 elegantbook 出版级整本 XeLaTeX 联合编译验证工具

通用增强版特性：
1. 抹平 Windows / Linux 终端编码差异（引入 config_utils.ensure_utf8_stdio）；
2. 自动化识别项目根目录与多卷结构（引入 config_utils.find_project_root, load_project_volumes）；
3. 提供命令行参数支持（--root, --config, --main-tex, --timeout）；
4. 保留 Amann 三卷基线（DEFAULT_VOLUMES），保持 100% 向后兼容；
5. PyMuPDF (fitz) 优雅降级保护：未安装 fitz 时自动基于文件大小和 PDF 魔数头进行基础验证，不抛出异常；
6. 完善的双 Pass 编译超时中断保护机制（默认 600 秒）。
"""

import os
import sys
import time
import argparse
import subprocess

# 引入 config_utils 通用配置工具
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

try:
    from config_utils import ensure_utf8_stdio, find_project_root, load_project_volumes
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
    def load_project_volumes(project_root=None, config_file=None, custom_dirs=None):
        return [("Root", project_root or os.getcwd())]

# Amann 默认三卷基线（保持向后兼容）
DEFAULT_VOLUMES = [
    ("Vol I", r"Analysis I Herbert Amann_ Joachim Escher - Analysis I 1 (2004, Birkhäuser) - libgen.li.pdf_ot_db2be1c91nqc73d37ek0\chapters_translate", "elegant_main.tex", "elegant_main.pdf"),
    ("Vol II", r"Analysis II (Herbert Amann, Joachim Escher) (Z-Library).pdf_ot_db2ba4c91nqc73d37dc0\chapters_translate", "elegant_main.tex", "elegant_main.pdf"),
    ("Vol III", r"Analysis III (Herbert Amann , Joachim Escher) (Z-Library).pdf_ot_db2b5dc91nqc73d37bm0\chapters_translate", "elegant_main.tex", "elegant_main.pdf"),
]

# 向后兼容接口别名
VOLUMES = DEFAULT_VOLUMES


def is_default_amann_project(project_root):
    """检测当前 project_root 是否为 Amann 原工程默认卷结构"""
    matched = 0
    for _, vdir, tex_name, _ in DEFAULT_VOLUMES:
        full_path = os.path.join(project_root, vdir, tex_name)
        if os.path.exists(full_path):
            matched += 1
    return matched >= 2


def resolve_volumes(project_root, config_path=None, main_tex="elegant_main.tex"):
    """
    解析待编译各卷配置：
    - 若未指定 config 且 main_tex 为默认值且为 Amann 工程，直接使用 DEFAULT_VOLUMES；
    - 否则通过 load_project_volumes 动态加载并定位 main_tex 路径。
    """
    pdf_name = main_tex.rsplit('.', 1)[0] + ".pdf" if main_tex.endswith('.tex') else main_tex + ".pdf"

    if config_path is None and main_tex == "elegant_main.tex" and is_default_amann_project(project_root):
        volumes = []
        for vname, vdir, tname, pname in DEFAULT_VOLUMES:
            full_vdir = os.path.normpath(os.path.join(project_root, vdir)) if not os.path.isabs(vdir) else vdir
            volumes.append((vname, full_vdir, tname, pname))
        return volumes

    # 通用多卷加载逻辑
    raw_vols = load_project_volumes(project_root=project_root, config_file=config_path)
    volumes = []
    for vname, vdir in raw_vols:
        # 定位 main_tex 所在子目录（chapters_translate -> chapters -> vdir）
        candidate_dirs = [
            os.path.join(vdir, 'chapters_translate'),
            os.path.join(vdir, 'chapters'),
            vdir
        ]
        target_dir = vdir
        for cd in candidate_dirs:
            if os.path.isfile(os.path.join(cd, main_tex)):
                target_dir = cd
                break
        else:
            if os.path.isdir(os.path.join(vdir, 'chapters_translate')):
                target_dir = os.path.join(vdir, 'chapters_translate')

        volumes.append((vname, target_dir, main_tex, pdf_name))

    return volumes


def _run_single_pass(cmd, timeout, cwd=None):
    """运行单次 xelatex pass，支持 Windows 进程树超时强制终结"""
    t0 = time.time()
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='ignore'
        )
        stdout, stderr = proc.communicate(timeout=timeout)
        elapsed = time.time() - t0
        return proc.returncode, elapsed, False, proc
    except subprocess.TimeoutExpired:
        elapsed = time.time() - t0
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
        return -1, elapsed, True, proc


def compile_volume(vname, vdir, tex_name, pdf_name, timeout=600):
    """编译单卷 elegantbook 文档，具备双 Pass 编译与 PyMuPDF 优雅降级保护"""
    print(f"\n>>> 开始编译 [{vname}] elegantbook ({tex_name}) ...")
    tex_path = os.path.join(vdir, tex_name)
    pdf_path = os.path.join(vdir, pdf_name)

    if not os.path.exists(tex_path):
        print(f"  [错误] 未找到编译主文件: {tex_path}")
        return False, 0, 0, 0.0

    cmd = ["xelatex", "-interaction=nonstopmode", tex_name]

    # Pass 1
    code1, t1, timed1, _ = _run_single_pass(cmd, timeout, cwd=vdir)
    if timed1:
        print(f"  [Pass 1 超时] 编译超时 (超过设定阈值 {timeout}s)")
        return False, 0, 0, t1
    print(f"  [Pass 1] returncode: {code1}, 耗时: {t1:.1f}s")

    if code1 != 0:
        log_path = os.path.join(vdir, tex_name.replace('.tex', '.log'))
        print(f"  [Pass 1 失败] 检查 log: {log_path}")
        if os.path.exists(log_path):
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    if line.startswith('! '):
                        print('   ', line.strip())
        return False, 0, 0, t1

    # Pass 2 for cross-references & TOC
    code2, t2, timed2, _ = _run_single_pass(cmd, timeout, cwd=vdir)
    if timed2:
        print(f"  [Pass 2 超时] 编译超时 (超过设定阈值 {timeout}s)")
        return False, 0, 0, t1 + t2
    print(f"  [Pass 2] returncode: {code2}, 耗时: {t2:.1f}s")

    if os.path.exists(pdf_path):
        size_kb = os.path.getsize(pdf_path) / 1024
        pages = None
        has_fitz = False

        # 尝试使用 PyMuPDF 进行精准页数统计
        try:
            import fitz
            doc = fitz.open(pdf_path)
            pages = len(doc)
            doc.close()
            has_fitz = True
        except ImportError:
            # 优雅降级：PyMuPDF 未安装
            has_fitz = False
        except Exception:
            # 打开异常降级
            has_fitz = False

        # 基础验证：检查文件大小 (>1KB) 且校验 PDF 魔数头 (%PDF-)
        is_valid_pdf = False
        if size_kb > 1.0:
            try:
                with open(pdf_path, 'rb') as fp:
                    header = fp.read(5)
                    if header.startswith(b'%PDF-'):
                        is_valid_pdf = True
            except Exception:
                pass

        if is_valid_pdf:
            if has_fitz and pages is not None:
                print(f"  [编译成功] 产出: {pdf_name} | 页数: {pages} 页 | 体积: {size_kb:.1f} KB")
            else:
                print(f"  [编译成功] 产出: {pdf_name} | 体积: {size_kb:.1f} KB (PyMuPDF 未安装/不可用，已通过大小与魔数基础验证)")
            return True, pages, size_kb, t1 + t2
        else:
            print(f"  [验证失败] 生成的 PDF 文件损坏或体积异常 (体积: {size_kb:.1f} KB)")
            return False, 0, size_kb, t1 + t2

    return False, 0, 0, t1 + t2


def main():
    parser = argparse.ArgumentParser(description="全书多卷 elegantbook 出版级整本 XeLaTeX 联合编译验证工具")
    parser.add_argument("--root", type=str, default=None, help="项目根目录（默认自动查找）")
    parser.add_argument("--config", type=str, default=None, help="卷配置文件（JSON 格式，指定待编译卷列表或配置）")
    parser.add_argument("--main-tex", type=str, default="elegant_main.tex", help="目标编译主文件名（默认 elegant_main.tex）")
    parser.add_argument("--timeout", type=int, default=600, help="单 Pass 编译超时时间（秒，默认 600）")
    args = parser.parse_args()

    project_root = find_project_root(args.root)
    volumes_to_compile = resolve_volumes(project_root, config_path=args.config, main_tex=args.main_tex)

    print("==================================================================")
    print(f"  出版级 elegantbook 全卷联合编译验证 (项目根目录: {project_root})")
    print(f"  待编译卷数: {len(volumes_to_compile)} 卷 | 目标文件: {args.main_tex} | 超时上限: {args.timeout}s")
    print("==================================================================")

    if not volumes_to_compile:
        print("[警告] 未找到待编译的卷结构，请检查项目目录或 --config 参数。")
        sys.exit(1)

    results = []
    for vname, vdir, tex_name, pdf_name in volumes_to_compile:
        success, pages, size_kb, total_time = compile_volume(vname, vdir, tex_name, pdf_name, timeout=args.timeout)
        results.append({
            'volume': vname,
            'success': success,
            'pages': pages,
            'size_kb': size_kb,
            'time': total_time
        })

    print("\n==================================================================")
    print("                      全卷 elegantbook 编译验收结论")
    print("==================================================================")
    for r in results:
        status = "PASS" if r['success'] else "FAIL"
        page_str = f"{r['pages']:4d} 页" if (r['pages'] is not None and r['pages'] > 0) else " -- 页"
        print(f"  [{r['volume']:7s}] -> {status:4s} | 页数: {page_str} | 体积: {r['size_kb']:7.1f} KB | 耗时: {r['time']:5.1f}s")

    pass_count = sum(1 for r in results if r['success'])
    total_count = len(results)
    pass_rate = (pass_count / total_count * 100) if total_count > 0 else 0.0

    counted_pages = [r['pages'] for r in results if r['pages'] is not None and r['pages'] > 0]
    if len(counted_pages) == total_count and total_count > 0:
        pages_summary = f"{sum(counted_pages)} 页"
    elif counted_pages:
        pages_summary = f"{sum(counted_pages)} 页 (部分卷因未安装 PyMuPDF 未计入)"
    else:
        pages_summary = "未统计 (PyMuPDF 未安装)"

    print("------------------------------------------------------------------")
    print(f"  全书总卷数: {total_count} 卷 | 成功率: {pass_count}/{total_count} ({pass_rate:.2f}%)")
    print(f"  全书出版级 PDF 总页数: {pages_summary}")
    print("==================================================================")

    # 零信任门禁判定：存在编译失败卷时必须返回非零 exit code，阻断假通过
    if pass_count < total_count:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
