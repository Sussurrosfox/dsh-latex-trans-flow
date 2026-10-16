# -*- coding: utf-8 -*-
"""
config_utils.py - 竞赛/教材中译与结构化流水线通用配置与文件发现工具模块

职责：
1. 抹平 Windows / Linux 终端编码差异（自动启用 UTF-8 stdio）；
2. 自动化识别项目根目录（自底向上探查标记文件或目录）；
3. 灵活解析多卷、单卷、章节目录结构（支持罗马数字与阿拉伯数字命名）；
4. 提供规范的 LLM API 配置加载链（CLI 参数 -> 环境变量 -> 配置文件 -> 兜底默认值）；
5. 保持与现有 Amann《Analysis I-III》工程 100% 向后兼容。
"""

import os
import re
import sys
import json
from pathlib import Path

# 1. 终端与输出流编码保护
def ensure_utf8_stdio():
    """确保 stdout 与 stderr 使用 UTF-8 编码，防止 Windows 平台 Unicode 打印崩溃"""
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

# 2. 罗马数字双向映射表
ROMAN_MAP = {
    'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6,
    'VII': 7, 'VIII': 8, 'IX': 9, 'X': 10, 'XI': 11, 'XII': 12,
    'XIII': 13, 'XIV': 14, 'XV': 15, 'XVI': 16, 'XVII': 17, 'XVIII': 18,
    'XIX': 19, 'XX': 20
}
INT_TO_ROMAN = {v: k for k, v in ROMAN_MAP.items()}

def parse_roman_or_int(val):
    """将输入的字符串（'I', 'VI', '1', '06' 等）解析为整数，失败返回 None"""
    if val is None:
        return None
    val_str = str(val).strip()
    if val_str.isdigit():
        return int(val_str)
    val_upper = val_str.upper()
    return ROMAN_MAP.get(val_upper, None)

# 3. 根目录与路径解析
def find_project_root(start_path=None):
    """
    寻找项目根目录：
    从 start_path 开始逐级向上，寻找含有 reflect 目录、.git、或 label_targets.json 的目录。
    若找不到则返回当前工作目录。
    """
    if start_path is None:
        start_path = os.getcwd()
    
    current = os.path.abspath(start_path)
    if os.path.isfile(current):
        current = os.path.dirname(current)

    while True:
        # 标志性指示文件或文件夹
        if (os.path.isdir(os.path.join(current, 'reflect')) or
            os.path.exists(os.path.join(current, 'label_targets.json')) or
            os.path.exists(os.path.join(current, 'project_config.json')) or
            os.path.isdir(os.path.join(current, '.git'))):
            return current
        
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    return os.path.abspath(os.getcwd())

# Amann 项目默认卷目录（向后兼容基线）
DEFAULT_AMANN_VOLUMES = [
    ("Vol I", r"Analysis I Herbert Amann_ Joachim Escher - Analysis I 1 (2004, Birkhäuser) - libgen.li.pdf_ot_db2be1c91nqc73d37ek0"),
    ("Vol II", r"Analysis II (Herbert Amann, Joachim Escher) (Z-Library).pdf_ot_db2ba4c91nqc73d37dc0"),
    ("Vol III", r"Analysis III (Herbert Amann , Joachim Escher) (Z-Library).pdf_ot_db2b5dc91nqc73d37bm0")
]

def load_project_volumes(project_root=None, config_file=None, custom_dirs=None):
    """
    加载项目卷列表 [(vol_name, vol_dir), ...]
    优先级：
    1. custom_dirs（命令行显式指定的一组目录）
    2. config_file 或 project_root/project_config.json 中配置的 "volumes"
    3. 若 project_root 下存在 Amann 默认三卷目录，则自动匹配
    4. 自动扫描包含 chapters_translate 或 chapters 的子目录
    5. 若当前目录本身就包含 chapters/ 或 chapters_translate/，则视为单卷项目 ("Main", project_root)
    """
    if project_root is None:
        project_root = find_project_root()
    
    # 1. custom_dirs
    if custom_dirs:
        vols = []
        for i, d in enumerate(custom_dirs, 1):
            abs_d = os.path.abspath(d)
            name = os.path.basename(abs_d.rstrip(r'\/')) or f"Vol {i}"
            vols.append((name, abs_d))
        return vols

    # 2. 检查配置文件
    cfg_path = config_file or os.path.join(project_root, 'project_config.json')
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                if 'volumes' in cfg and isinstance(cfg['volumes'], list):
                    vols = []
                    for item in cfg['volumes']:
                        if isinstance(item, (list, tuple)) and len(item) == 2:
                            vname, vdir = item
                            abs_vdir = os.path.join(project_root, vdir) if not os.path.isabs(vdir) else vdir
                            vols.append((vname, abs_vdir))
                        elif isinstance(item, dict):
                            vname = item.get('name', 'Vol')
                            vdir = item.get('path', '')
                            abs_vdir = os.path.join(project_root, vdir) if not os.path.isabs(vdir) else vdir
                            vols.append((vname, abs_vdir))
                    if vols:
                        return vols
        except Exception:
            pass

    # 3. 检查 Amann 默认三卷目录
    amann_matched = []
    for vname, vrel in DEFAULT_AMANN_VOLUMES:
        full_dir = os.path.join(project_root, vrel)
        if os.path.exists(full_dir):
            amann_matched.append((vname, full_dir))
    if len(amann_matched) > 0:
        return amann_matched

    # 4. 自动扫描子目录
    discovered = []
    if os.path.exists(project_root):
        for entry in sorted(os.listdir(project_root)):
            entry_path = os.path.join(project_root, entry)
            if not os.path.isdir(entry_path):
                continue
            # 若含有 chapters 或 chapters_translate 则视为卷
            if (os.path.isdir(os.path.join(entry_path, 'chapters_translate')) or
                os.path.isdir(os.path.join(entry_path, 'chapters'))):
                discovered.append((entry, entry_path))
    if discovered:
        return discovered

    # 5. 单卷项目兜底
    if (os.path.isdir(os.path.join(project_root, 'chapters_translate')) or
        os.path.isdir(os.path.join(project_root, 'chapters'))):
        return [("Main", project_root)]

    return [("Root", project_root)]

def infer_chapter_section(file_or_dir_path):
    """
    通用章号、节号推断器。
    支持多种命名风格：
    - 01_Chapter_I, Chapter_VI, ch01, Chapter_1, Chap_3
    - 02_Section_2.tex, Section_10.pre.tex, sec03.tex, 01_Section_1
    返回: (chapter_num, section_num)，未能推断的字段返回 None
    """
    norm_path = os.path.normpath(file_or_dir_path)
    base_name = os.path.basename(norm_path)
    parent_name = os.path.basename(os.path.dirname(norm_path))

    chapter_num = None
    section_num = None

    # 1. 尝试从路径或父目录推断章号
    for candidate in [base_name, parent_name, norm_path]:
        # 形式 1: Chapter_([IVXLCDM]+)
        m = re.search(r'Chapter_([IVXLCDM]+)\b', candidate, re.IGNORECASE)
        if m:
            chapter_num = parse_roman_or_int(m.group(1))
            if chapter_num:
                break
        # 形式 2: Chapter_(\d+) 或 Chapter-(\d+) 或 Chapter\s*(\d+)
        m = re.search(r'Chapter[_-](\d+)\b', candidate, re.IGNORECASE)
        if m:
            chapter_num = int(m.group(1))
            break
        # 形式 3: ch(\d+) 或 chap(\d+)
        m = re.search(r'(?:^|[\\/_\.-]|(?<=\b))(?:ch|chap)[_-]?(\d+)', candidate, re.IGNORECASE)
        if m:
            chapter_num = int(m.group(1))
            break
        # 形式 3b: 第(\d+)章
        m = re.search(r'第\s*(\d+)\s*章', candidate)
        if m:
            chapter_num = int(m.group(1))
            break
        # 形式 4: 前导序号 如 01_Chapter_I 中的 01
        m = re.search(r'(\d+)_Chapter', candidate, re.IGNORECASE)
        if m:
            chapter_num = int(m.group(1))
            break
        # 形式 5: 简单前导序号 如 01_convex_functions 或 01_Section
        m = re.search(r'(?:^|[\\/])(\d+)_', candidate)
        if m:
            chapter_num = int(m.group(1))
            break

    # 2. 尝试推断节号
    for candidate in [base_name, norm_path]:
        # 形式 1: Section_(\d+)
        m = re.search(r'Section_(\d+)\b', candidate, re.IGNORECASE)
        if m:
            section_num = int(m.group(1))
            break
        # 形式 2: sec(\d+) 或 sec_(\d+)
        m = re.search(r'\bsec[_-]?(\d+)\b', candidate, re.IGNORECASE)
        if m:
            section_num = int(m.group(1))
            break
        # 形式 3: 前导序号如 08_Section_8
        m = re.search(r'(\d+)_Section', candidate, re.IGNORECASE)
        if m:
            section_num = int(m.group(1))
            break

    return chapter_num, section_num

def discover_work_files(volumes, priority_exts=('.api.tex', '.pre.tex', '.tex'), target_chapters_dir='chapters_translate'):
    """
    通用全书工作节文件发现器。
    根据 priority_exts 优先级，对每节文件进行去重拾取。
    返回: [(vol_name, chapter_num, section_num, abs_filepath), ...] 按 (chap, sec) 排序
    """
    collected = []
    for vname, vdir in volumes:
        # 探测章节目录存放位置
        possible_dirs = [
            os.path.join(vdir, target_chapters_dir),
            os.path.join(vdir, 'chapters'),
            vdir
        ]
        chosen_dir = None
        for pd in possible_dirs:
            if os.path.isdir(pd):
                chosen_dir = pd
                break
        if not chosen_dir:
            continue

        for root, dirs, fnames in os.walk(chosen_dir):
            for fn in fnames:
                if fn.startswith('compile') or fn.startswith('tmp'):
                    continue
                # 判断是否匹配支持的扩展名
                matched_ext = None
                for ext in priority_exts:
                    if fn.endswith(ext):
                        matched_ext = ext
                        break
                if not matched_ext:
                    continue

                full_path = os.path.join(root, fn)
                c_num, s_num = infer_chapter_section(full_path)
                if c_num is not None:
                    s_num = s_num if s_num is not None else 0
                    collected.append((vname, c_num, s_num, full_path, matched_ext))

    # 按优先级去重：每个 (vname, c_num, s_num) 保留 priority_exts 中排在最前面的
    grouped = {}
    for vname, c, s, path, ext in collected:
        key = (c, s)
        pri = priority_exts.index(ext) if ext in priority_exts else 999
        if key not in grouped or pri < grouped[key][0]:
            grouped[key] = (pri, (vname, c, s, path))

    results = [item[1] for item in grouped.values()]
    return sorted(results, key=lambda x: (x[1], x[2]))

# 4. LLM API 配置加载
def load_llm_config(args=None, project_root=None):
    """
    加载 LLM API 配置：
    优先级：CLI 参数 -> 环境变量 -> api_config.json -> 默认回退值
    """
    if project_root is None:
        project_root = find_project_root()
    
    cfg = {
        'base_url': os.environ.get('OPENAI_BASE_URL') or os.environ.get('LLM_BASE_URL') or "",
        'api_key': os.environ.get('OPENAI_API_KEY') or os.environ.get('LLM_API_KEY') or "",
        'model': os.environ.get('LLM_MODEL') or os.environ.get('OPENAI_MODEL') or "gpt-4o",
        'temperature': 0.1,
        'max_tokens': 8192,
        'timeout': 300
    }

    # 读取配置文件
    for fname in ['api_config.json', 'llm_config.json', 'project_config.json']:
        cfg_file = os.path.join(project_root, fname)
        if os.path.exists(cfg_file):
            try:
                with open(cfg_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    llm_data = data.get('llm', data)
                    for k in cfg:
                        if k in llm_data:
                            cfg[k] = llm_data[k]
                break
            except Exception:
                pass

    # 环境变量覆盖
    env_base = os.environ.get('OPENAI_BASE_URL') or os.environ.get('LLM_BASE_URL')
    env_key = os.environ.get('OPENAI_API_KEY') or os.environ.get('LLM_API_KEY')
    env_model = os.environ.get('LLM_MODEL') or os.environ.get('OPENAI_MODEL')
    if env_base:
        cfg['base_url'] = env_base
    if env_key:
        cfg['api_key'] = env_key
    if env_model:
        cfg['model'] = env_model

    # CLI 覆盖
    if args:
        if getattr(args, 'base_url', None):
            cfg['base_url'] = args.base_url
        if getattr(args, 'api_key', None):
            cfg['api_key'] = args.api_key
        if getattr(args, 'model', None):
            cfg['model'] = args.model

    return cfg
