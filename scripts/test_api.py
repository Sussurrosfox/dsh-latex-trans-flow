# -*- coding: utf-8 -*-
"""
test_api.py - LLM API 连通性与响应质量验证脚本
支持命令行参数、环境变量、配置文件或 api_refine 默认值。
"""

import os
import sys
import json
import time
import argparse
import urllib.request
import urllib.error

# 确保脚本所在目录在 sys.path 中，无论在何目录下运行都能准确定位与导入
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

try:
    from config_utils import ensure_utf8_stdio, load_llm_config
    ensure_utf8_stdio()
except ImportError:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    load_llm_config = None

try:
    import api_refine
except ImportError:
    api_refine = None


def main():
    parser = argparse.ArgumentParser(description="LLM API 连通性测试工具")
    parser.add_argument('--base-url', help='LLM API Base URL（缺省读取环境变量或默认值）', default=None)
    parser.add_argument('--api-key', help='LLM API Key', default=None)
    parser.add_argument('--model', help='模型 ID', default=None)
    parser.add_argument('--config', help='JSON 配置文件路径', default=None)
    parser.add_argument('--prompt', help='测试提问内容', default='用中文回答：1+1=？')
    parser.add_argument('--timeout', type=int, help='超时时间（秒）', default=120)
    args = parser.parse_args()

    # 1. 基础配置加载（config_utils -> api_refine -> 默认回退）
    if load_llm_config:
        cfg = load_llm_config(args)
    elif api_refine:
        cfg = {
            'base_url': getattr(api_refine, 'BASE_URL', "") or os.environ.get('OPENAI_BASE_URL', ""),
            'api_key': getattr(api_refine, 'API_KEY', "") or os.environ.get('OPENAI_API_KEY', ""),
            'model': getattr(api_refine, 'MODEL', "gpt-4o") or os.environ.get('LLM_MODEL', "gpt-4o"),
            'timeout': getattr(api_refine, 'TIMEOUT', 120),
        }
    else:
        cfg = {
            'base_url': os.environ.get('OPENAI_BASE_URL', ""),
            'api_key': os.environ.get('OPENAI_API_KEY', ""),
            'model': os.environ.get('LLM_MODEL', "gpt-4o"),
            'timeout': 120,
        }

    # 2. 如果指定了 --config，解析并覆盖
    if args.config and os.path.exists(args.config):
        try:
            with open(args.config, 'r', encoding='utf-8') as f:
                cdata = json.load(f)
                llm_cdata = cdata.get('llm', cdata)
                for k in ['base_url', 'api_key', 'model', 'timeout']:
                    if k in llm_cdata:
                        cfg[k] = llm_cdata[k]
        except Exception as e:
            print(f"警告：读取指定配置文件 {args.config} 失败：{e}")

    # 3. 环境变量覆盖
    env_base = os.environ.get('OPENAI_BASE_URL') or os.environ.get('LLM_BASE_URL')
    env_key = os.environ.get('OPENAI_API_KEY') or os.environ.get('LLM_API_KEY')
    env_model = os.environ.get('LLM_MODEL') or os.environ.get('OPENAI_MODEL')
    if env_base:
        cfg['base_url'] = env_base
    if env_key:
        cfg['api_key'] = env_key
    if env_model:
        cfg['model'] = env_model

    # 4. CLI 参数最高优先级
    base_url = args.base_url or cfg.get('base_url', "")
    api_key = args.api_key or cfg.get('api_key', "")
    model = args.model or cfg.get('model', "gpt-4o")
    timeout = args.timeout or cfg.get('timeout', 120)

    def mask_key(k):
        if not k or k == "YOUR_API_KEY_HERE":
            return '(未配置/占位符)'
        k = k.strip()
        if len(k) <= 8:
            return '****'
        return f"{k[:3]}****{k[-4:]}"

    print("=== 测试 LLM API 连通性 ===")
    print(f"Base URL: {base_url}")
    print(f"Model:    {model}")
    print(f"API Key:  {mask_key(api_key)}")

    if not base_url or not api_key or api_key == "YOUR_API_KEY_HERE":
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

    url = base_url.rstrip('/') + '/chat/completions'
    payload = {
        'model': model,
        'messages': [{'role': 'user', 'content': args.prompt}],
        'max_tokens': 64,
        'stream': False,
    }
    body = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=body, method='POST', headers={
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + api_key,
    })

    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        dt = time.time() - t0
        print(f"[SUCCESS] 响应成功 (耗时: {dt:.2f}s)")
        reply = data.get('choices', [{}])[0].get('message', {}).get('content', '').strip()
        print(f"Reply: {reply}")
        print(f"Usage: {data.get('usage')}")
    except urllib.error.HTTPError as e:
        dt = time.time() - t0
        print(f"[FAIL] HTTP 错误 {e.code} (耗时: {dt:.2f}s)")
        print(e.read().decode('utf-8', 'replace')[:500])
        sys.exit(1)
    except Exception as e:
        dt = time.time() - t0
        print(f"[FAIL] 请求失败 (耗时: {dt:.2f}s): {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
