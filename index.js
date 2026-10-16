import { execFile } from 'node:child_process';
import * as path from 'node:path';
import * as fs from 'node:fs';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const scriptsDir = path.join(__dirname, 'scripts');

/**
 * 动态探测当前活跃的项目工作目录
 */
function resolveProjectRoot(customRoot, ctx) {
  if (customRoot && fs.existsSync(customRoot)) {
    return path.resolve(customRoot);
  }
  try {
    const registry = ctx?.get?.('workspaceRegistry') || ctx?.workspaceRegistry;
    if (registry && typeof registry.list === 'function') {
      const list = registry.list();
      if (list && list.length > 0 && list[0]?.path) {
        return path.resolve(list[0].path);
      }
    }
  } catch (_) {}
  return process.cwd();
}

/**
 * 辅助函数：对 API Key 进行脱敏保护（如 sk-****1234）
 */
function maskApiKey(key) {
  if (!key || typeof key !== 'string') return '';
  const trimmed = key.trim();
  if (trimmed.length <= 8) return '****';
  return `${trimmed.slice(0, 3)}****${trimmed.slice(-4)}`;
}

/**
 * 执行 Python 脚本辅助函数，锁定 UTF-8 编码与长超时
 * 支持 extraEnv 环境变量注入，避免凭据在命令行参数中明文泄露
 */
function runPython(scriptRelOrName, args = [], cwd = process.cwd(), timeoutMs = 180000, pythonBin = 'python', extraEnv = {}) {
  return new Promise((resolve) => {
    let scriptPath;
    if (path.isAbsolute(scriptRelOrName)) {
      scriptPath = scriptRelOrName;
    } else {
      scriptPath = path.join(scriptsDir, scriptRelOrName);
    }

    const env = {
      ...process.env,
      PYTHONIOENCODING: 'utf-8',
      PYTHONUTF8: '1',
      ...extraEnv,
    };

    execFile(
      pythonBin,
      [scriptPath, ...args],
      { cwd, env, timeout: timeoutMs, maxBuffer: 25 * 1024 * 1024, encoding: 'utf-8' },
      (err, stdout, stderr) => {
        resolve({
          success: !err,
          code: err ? (err.code ?? 1) : 0,
          stdout: stdout ? stdout.trim() : '',
          stderr: stderr ? stderr.trim() : '',
          error: err ? err.message : null,
        });
      }
    );
  });
}

/**
 * 检查或初始化项目的 LLM API 配置文件
 * 优先顺序：显式参数 -> 环境变量 -> 项目 api_config.json
 * 若全部缺失或仍为占位符，则自动从模板生成 api_config.json 并返回强引导提示
 */
function ensureOrPromptApiConfig(proj, args = {}) {
  // 1. 如果调用时显式传入了有效 key
  if (args.api_key && args.api_key !== 'YOUR_API_KEY_HERE' && args.api_key.trim().length > 5) {
    return {
      ready: true,
      source: 'args',
      api_key: args.api_key.trim(),
      base_url: args.base_url || 'https://api.openai.com/v1',
      model: args.model || 'deepseek-chat',
    };
  }

  // 2. 如果系统环境变量中已配置有效 key
  const envKey = process.env.OPENAI_API_KEY || process.env.LLM_API_KEY;
  if (envKey && envKey !== 'YOUR_API_KEY_HERE' && envKey.trim().length > 5) {
    return {
      ready: true,
      source: 'environment',
      api_key: envKey.trim(),
      base_url: process.env.OPENAI_BASE_URL || process.env.LLM_BASE_URL || 'https://api.openai.com/v1',
      model: process.env.LLM_MODEL || process.env.OPENAI_MODEL || 'deepseek-chat',
    };
  }

  // 3. 检查项目根目录下是否存在 api_config.json 或 llm_config.json
  const targetCfg = path.join(proj, 'api_config.json');
  const templatePath = path.join(__dirname, 'api_config.template.json');

  if (fs.existsSync(targetCfg)) {
    try {
      const data = JSON.parse(fs.readFileSync(targetCfg, 'utf-8'));
      const key = (data.api_key || data.llm?.api_key || '').trim();
      if (key && key !== 'YOUR_API_KEY_HERE' && key.length > 5) {
        return {
          ready: true,
          source: 'file',
          configPath: targetCfg,
          api_key: key,
          base_url: data.base_url || data.llm?.base_url || 'https://api.openai.com/v1',
          model: data.model || data.llm?.model || 'deepseek-chat',
        };
      }
    } catch (_) {}
  } else {
    // 自动将插件中的模板复制到项目根目录
    if (fs.existsSync(templatePath)) {
      try {
        fs.copyFileSync(templatePath, targetCfg);
      } catch (_) {}
    }
  }

  // 4. 未就绪：返回强引导与自动创建的模版路径
  return {
    ready: false,
    configPath: targetCfg,
    message: [
      '### 🔑 【必须配置大模型 API 凭据】',
      '',
      '> **流水线提示**：当前未检测到有效的大模型 API-Key（未配置或仍为占位符）。大模型分段复核层 (S2) 与连通性测试需要有效的 API 凭据方可执行。',
      '',
      `📁 **配置模板文件已自动就绪**：\`${targetCfg}\``,
      '',
      '---',
      '#### 🚀 三种立即可用的配置方法（任选其一）：',
      '',
      '**① 本地文件方式（推荐 · 持久生效）**',
      `直接使用文本编辑器打开项目根目录下的 \`${targetCfg}\`（已自动为您生成标准模板），填入您的真实 API Key 即可：`,
      '```json',
      '{',
      '  "base_url": "https://api.deepseek.com/v1",',
      '  "api_key": "sk-your-actual-api-key",',
      '  "model": "deepseek-chat"',
      '}',
      '```',
      '> 💡 *支持 DeepSeek (`deepseek-chat`)、OpenAI (`gpt-4o`)、Kimi、GLM 等所有兼容 OpenAI 格式的服务商。*',
      '',
      '**② 快捷命令方式（交互便捷 · 免开文件）**',
      '- **方式 A (斜杠指令)**：在输入框直接发送指令：',
      '  `/textrans config-api sk-your-actual-api-key deepseek-chat`',
      '- **方式 B (工具调用)**：在对话中直接唤起 `configure_api`：',
      '  `latex_trans_pipeline(action="configure_api", api_key="sk-...", model="deepseek-chat")`',
      '',
      '**③ 系统环境方式（跨项目通用 · 全局生效）**',
      '在操作系统或终端中配置环境变量：',
      '- **Windows PowerShell**：`$env:OPENAI_API_KEY="sk-..."`（或在系统属性中添加环境变量）',
      '- **Linux / macOS**：`export OPENAI_API_KEY="sk-..."`',
      '',
      '---',
      '🔍 **连通性校验**：完成上述任一配置后，运行 `/textrans run test_api` 或调用 `latex_trans_pipeline(action="test_api")` 即可完成一键网络与响应测试。',
    ].join('\n'),
  };
}

/**
 * 辅助函数：将 API 配置写入 api_config.json
 */
function writeApiConfigFile(proj, config) {
  try {
    const targetCfg = path.join(proj, 'api_config.json');
    let existing = {};
    if (fs.existsSync(targetCfg)) {
      try {
        existing = JSON.parse(fs.readFileSync(targetCfg, 'utf-8'));
      } catch (_) {}
    }

    const updated = {
      base_url: (config.base_url || existing.base_url || 'https://api.openai.com/v1').trim(),
      api_key: (config.api_key || existing.api_key || '').trim(),
      model: (config.model || existing.model || 'deepseek-chat').trim(),
      temperature: config.temperature ?? existing.temperature ?? 0.1,
      max_tokens: config.max_tokens ?? existing.max_tokens ?? 8192,
      timeout: config.timeout ?? existing.timeout ?? 300,
    };

    fs.writeFileSync(targetCfg, JSON.stringify(updated, null, 2), 'utf-8');
    return { success: true, path: targetCfg, config: updated };
  } catch (err) {
    return { success: false, error: err.message };
  }
}

export const inject = ['tools'];

export function apply(ctx, config = {}) {
  const pythonBin = config.pythonPath || 'python';

  // =========================================================================
  // 1. 注册核心驱动工具: latex_trans_pipeline
  // =========================================================================
  ctx.tools.register({
    name: 'latex_trans_pipeline',
    description: 'LaTeX 专著/教材中译与结构化流水线核心驱动工具（基于 Amann 五层架构与 7 步标准流水线）。支持API核验与引导(check_api)、一键配置API(configure_api)、状态普查(status)、连通性测试(test_api)、机械预处理(preprocess)、漏包补包(fix_headers)、环境折叠(nest_proofs)、LLM批量复核(api_refine)、编号拓扑普查(scan_numbering)、标签台账冻结(canonicalize)、交叉引用批量规范化(cross_refs)、前言与版权页多Agent骨架管理(frontmatter)、编译回归(compile)与残余标记普查(residual_stats)。',
    parameters: {
      type: 'object',
      properties: {
        action: {
          type: 'string',
          enum: [
            'check_api',
            'configure_api',
            'status',
            'test_api',
            'preprocess',
            'fix_headers',
            'nest_proofs',
            'api_refine',
            'scan_numbering',
            'canonicalize',
            'cross_refs',
            'frontmatter',
            'compile',
            'residual_stats',
          ],
          description: '流水线操作阶段：check_api(检查API配置) | configure_api(一键持久化API配置) | status(查询状态) | test_api(测试API) | preprocess(机械预处理) | fix_headers(漏包编号头补包) | nest_proofs(证明折叠与AST自检) | api_refine(LLM分段复核) | scan_numbering(计数器模拟普查) | canonicalize(冻结标签台账) | cross_refs(交叉引用批量替换) | frontmatter(前置件与版权页骨架生成及核验) | compile(编译回归) | residual_stats(残余统计)',
        },
        project_root: {
          type: 'string',
          description: '项目根目录路径（缺省时自动自适应探测）',
        },
        file: {
          type: 'string',
          description: '单个目标 TeX 文件路径（单节预处理/单节复核/单节交叉引用/前置件核验时使用）',
        },
        batch: {
          type: 'boolean',
          description: '是否批量执行（默认 true，用于 preprocess）',
        },
        apply: {
          type: 'boolean',
          description: '是否落盘写入生效（默认 false 保持只读/审计，设为 true 时正式回写，用于 fix_headers, nest_proofs, cross_refs）',
        },
        dry_run: {
          type: 'boolean',
          description: '是否预演审计（不落盘回写，用于 cross_refs 或 batch_preprocess）',
        },
        extra_types: {
          type: 'string',
          description: '扩展定理中文映射词表，例如 "性质:property,判据:criterion,法则:rule"',
        },
        workers: {
          type: 'number',
          description: 'LLM 分段并发数（默认 8，用于 api_refine/batch_api_refine）',
        },
        final_workers: {
          type: 'number',
          description: 'LLM 汇编与门禁并发数（默认 2，用于 batch_api_refine）',
        },
        elegant: {
          type: 'boolean',
          description: '是否执行出版级 ElegantBook 双 pass 编译（默认 false 为基础模块编译，设为 true 为整卷 ElegantBook 编译）',
        },
        timeout: {
          type: 'number',
          description: '命令超时时间（秒，默认 180）',
        },
        base_url: {
          type: 'string',
          description: 'LLM API 基础地址（例如 https://api.openai.com/v1 或本地代理，可选）',
        },
        api_key: {
          type: 'string',
          description: 'LLM API 认证密钥（配置或调用时传入）',
        },
        model: {
          type: 'string',
          description: 'LLM 模型名称（例如 gpt-4o, deepseek-chat, gemini-2.5-pro 等）',
        },
        config_file: {
          type: 'string',
          description: '显式指定 API 配置文件路径（例如 api_config.json）',
        },
        mode: {
          type: 'string',
          enum: ['scaffold', 'audit'],
          description: 'frontmatter 操作模式：scaffold(生成版权页与多Agent正交拆分骨架) | audit(核验前置件版权页与前言合规性)',
        },
      },
      required: ['action'],
    },
    output: {
      schema: {
        type: 'object',
        properties: {
          action: { type: 'string' },
          success: { type: 'boolean' },
          report: { type: 'string' },
          data: { type: 'object' },
        },
      },
      render: (_args, val) => [{
        type: 'text',
        text: val.report || (val.success ? '✔ 执行成功' : '✖ 执行失败'),
      }],
    },
    async execute(args) {
      const proj = resolveProjectRoot(args.project_root, ctx);
      const action = args.action;
      const timeoutMs = (args.timeout || 180) * 1000;

      // 0.1 check_api: 检查 API 配置状态并引导
      if (action === 'check_api') {
        const apiCheck = ensureOrPromptApiConfig(proj, args);
        if (apiCheck.ready) {
          return {
            action,
            success: true,
            report: [
              '✔ **LLM API 凭据已就绪**',
              `- 来源: ${apiCheck.source === 'file' ? `配置文件 (${apiCheck.configPath})` : apiCheck.source === 'environment' ? '环境变量' : '显式参数'}`,
              `- 模型: \`${apiCheck.model}\``,
              `- Base URL: \`${apiCheck.base_url}\``,
              `- API Key: \`${maskApiKey(apiCheck.api_key)}\` (安全脱敏保护)`,
              '',
              '您可直接使用 `api_refine` 进行大模型段级复核，或调用 `test_api` 进行连通性与延迟测试。',
            ].join('\n'),
            data: {
              ...apiCheck,
              api_key: maskApiKey(apiCheck.api_key),
            },
          };
        }
        return {
          action,
          success: false,
          report: apiCheck.message,
          data: { configPath: apiCheck.configPath, needsConfig: true },
        };
      }

      // 0.2 configure_api: 一键配置并持久化 API
      if (action === 'configure_api') {
        if (!args.api_key || args.api_key.trim().length === 0) {
          return {
            action,
            success: false,
            report: '✖ 配置失败：必须提供有效的 `api_key` 参数！\n例如: `latex_trans_pipeline(action="configure_api", api_key="sk-...", model="deepseek-chat")`',
          };
        }
        const writeRes = writeApiConfigFile(proj, {
          api_key: args.api_key,
          base_url: args.base_url,
          model: args.model,
        });
        if (!writeRes.success) {
          return {
            action,
            success: false,
            report: `✖ 写入配置文件失败: ${writeRes.error}`,
          };
        }
        return {
          action,
          success: true,
          report: [
            '✔ **LLM API 凭据已成功持久化写入！**',
            `- 配置文件: \`${writeRes.path}\``,
            `- 配置模型: \`${writeRes.config.model}\``,
            `- 基础地址: \`${writeRes.config.base_url}\``,
            `- API Key: \`${maskApiKey(writeRes.config.api_key)}\` (已安全持久化脱敏)`,
            '',
            '建议下一步调用 `test_api` 检验连通性：',
            '`latex_trans_pipeline(action="test_api")`',
          ].join('\n'),
          data: {
            ...writeRes.config,
            api_key: maskApiKey(writeRes.config.api_key),
          },
        };
      }

      // 1. status: 状态全景普查
      if (action === 'status') {
        const stats = {
          projectRoot: proj,
          totalTex: 0,
          preTex: 0,
          apiTex: 0,
          hasLabelTargets: false,
          labelCount: 0,
        };

        const scanDir = (dir) => {
          if (!fs.existsSync(dir)) return;
          for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
            const full = path.join(dir, ent.name);
            if (ent.isDirectory() && ent.name !== 'node_modules' && ent.name !== '.git') {
              scanDir(full);
            } else if (ent.isFile()) {
              if (ent.name.endsWith('.api.tex')) stats.apiTex++;
              else if (ent.name.endsWith('.pre.tex')) stats.preTex++;
              else if (ent.name.endsWith('.tex')) stats.totalTex++;
            }
          }
        };
        scanDir(proj);

        const labelPath = path.join(proj, 'label_targets.json');
        if (fs.existsSync(labelPath)) {
          stats.hasLabelTargets = true;
          try {
            const data = JSON.parse(fs.readFileSync(labelPath, 'utf-8'));
            stats.labelCount = Object.keys(data).length;
          } catch (_) {}
        }

        const resResidual = await runPython('collect_residual.py', ['--root', proj], proj, 60000, pythonBin);
        const apiCheck = ensureOrPromptApiConfig(proj, args);

        const lines = [
          '=== LaTeX 专著中译与结构化流水线状态 ===',
          `工程根目录: ${proj}`,
          `LLM API 凭据: ${apiCheck.ready ? `✔ 已就绪 (${apiCheck.model || '可用'})` : '⚠️ 未配置 (请先运行 check_api / configure_api 引导配置)'}`,
          `基线 TeX 文件数: ${stats.totalTex}`,
          `机械预处理层 (.pre.tex): ${stats.preTex}`,
          `LLM 复核产物 (.api.tex): ${stats.apiTex}`,
          `引用白名单台账: ${stats.hasLabelTargets ? `✔ 已冻结 (${stats.labelCount} 个标签)` : '⚪ 未就绪 (需运行 canonicalize)'}`,
          '',
          '残余标记与采纳统计:',
          resResidual.stdout || '暂无统计数据',
        ];

        return {
          action,
          success: true,
          report: lines.join('\n'),
          data: { ...stats, apiReady: apiCheck.ready },
        };
      }

      // 2. test_api: API 连通性测试
      if (action === 'test_api') {
        const apiCheck = ensureOrPromptApiConfig(proj, args);
        if (!apiCheck.ready) {
          return {
            action,
            success: false,
            report: apiCheck.message,
            data: { configPath: apiCheck.configPath, needsConfig: true },
          };
        }
        const cliArgs = [];
        if (args.base_url) cliArgs.push('--base-url', args.base_url);
        // 安全加固：严禁通过命令行暴露 api_key，必须统一通过子进程环境变量注入！
        if (args.model) cliArgs.push('--model', args.model);
        if (args.config_file) cliArgs.push('--config', args.config_file);

        const llmEnv = {};
        if (apiCheck.api_key) {
          llmEnv.OPENAI_API_KEY = apiCheck.api_key;
          llmEnv.LLM_API_KEY = apiCheck.api_key;
        }
        if (apiCheck.base_url) {
          llmEnv.OPENAI_BASE_URL = apiCheck.base_url;
          llmEnv.LLM_BASE_URL = apiCheck.base_url;
        }
        if (apiCheck.model) {
          llmEnv.OPENAI_MODEL = apiCheck.model;
          llmEnv.LLM_MODEL = apiCheck.model;
        }

        const res = await runPython('test_api.py', cliArgs, proj, 45000, pythonBin, llmEnv);
        return {
          action,
          success: res.success,
          report: `[LLM API 连通性与延迟测试]\n${res.stdout || res.stderr || (res.success ? '连通性正常' : '测试失败')}`,
        };
      }

      // 3. preprocess: 机械预处理 (单节或全书批量)
      if (action === 'preprocess') {
        if (args.file) {
          const cliArgs = [args.file];
          if (args.extra_types) cliArgs.push('--extra-types', args.extra_types);
          const res = await runPython('preprocess.py', cliArgs, proj, timeoutMs, pythonBin);
          return {
            action,
            success: res.success,
            report: `[单节机械预处理: ${args.file}]\n${res.stdout || res.stderr}`,
          };
        } else {
          const cliArgs = ['--root', proj];
          if (args.dry_run) cliArgs.push('--dry-run');
          if (args.extra_types) cliArgs.push('--extra-types', args.extra_types);
          cliArgs.push('--json', path.join(proj, 'preprocess_summary.json'));
          const res = await runPython('batch_preprocess.py', cliArgs, proj, timeoutMs * 2, pythonBin);
          return {
            action,
            success: res.success,
            report: `[全书批量预处理]\n${res.stdout || res.stderr}`,
          };
        }
      }

      // 4. fix_headers: 漏包编号头补包
      if (action === 'fix_headers') {
        const cliArgs = ['--root', proj];
        if (args.apply) cliArgs.push('--apply');
        if (args.extra_types) cliArgs.push('--extra-types', args.extra_types);
        const res = await runPython('fix_bare_headers.py', cliArgs, proj, timeoutMs, pythonBin);
        return {
          action,
          success: res.success,
          report: `[漏包编号头补包 ${args.apply ? '(已写回)' : '(预演模式，使用 --apply 落盘)'}]\n${res.stdout || res.stderr}`,
        };
      }

      // 5. nest_proofs: 证明环境折叠归一与 AST 自检
      if (action === 'nest_proofs') {
        const targetPattern = args.file || path.join(proj, '**', '*.pre.tex');
        const cliArgs = [targetPattern, '--all'];
        if (args.apply) cliArgs.push('--apply');
        const res = await runPython('nest_proofs.py', cliArgs, proj, timeoutMs, pythonBin);
        return {
          action,
          success: res.success,
          report: `[环境折叠归一与 AST 防卫 ${args.apply ? '(已写回)' : '(校验模式，使用 --apply 落盘)'}]\n${res.stdout || res.stderr}`,
        };
      }

      // 6. api_refine: LLM 分段复核
      if (action === 'api_refine') {
        const apiCheck = ensureOrPromptApiConfig(proj, args);
        if (!apiCheck.ready) {
          return {
            action,
            success: false,
            report: apiCheck.message,
            data: { configPath: apiCheck.configPath, needsConfig: true },
          };
        }

        const llmEnv = {};
        if (apiCheck.api_key) {
          llmEnv.OPENAI_API_KEY = apiCheck.api_key;
          llmEnv.LLM_API_KEY = apiCheck.api_key;
        }
        if (apiCheck.base_url) {
          llmEnv.OPENAI_BASE_URL = apiCheck.base_url;
          llmEnv.LLM_BASE_URL = apiCheck.base_url;
        }
        if (apiCheck.model) {
          llmEnv.OPENAI_MODEL = apiCheck.model;
          llmEnv.LLM_MODEL = apiCheck.model;
        }

        if (args.file) {
          const cliArgs = [args.file];
          if (args.apply) cliArgs.push('--apply');
          if (args.base_url) cliArgs.push('--base-url', args.base_url);
          // 安全加固：严禁通过命令行暴露 api_key，必须统一通过子进程环境变量注入！
          if (args.model) cliArgs.push('--model', args.model);
          if (args.config_file) cliArgs.push('--config', args.config_file);
          const res = await runPython('api_refine.py', cliArgs, proj, timeoutMs * 2, pythonBin, llmEnv);
          return {
            action,
            success: res.success,
            report: `[单节 LLM 分段复核: ${args.file}]\n${res.stdout || res.stderr}`,
          };
        } else {
          const workers = args.workers || 8;
          const finalWorkers = args.final_workers || 2;
          const cliArgs = ['--root', proj, '--workers', String(workers), '--final-workers', String(finalWorkers)];
          if (args.base_url) cliArgs.push('--base-url', args.base_url);
          // 安全加固：严禁通过命令行暴露 api_key，必须统一通过子进程环境变量注入！
          if (args.model) cliArgs.push('--model', args.model);
          if (args.config_file) cliArgs.push('--config', args.config_file);
          const res = await runPython('batch_api_refine.py', cliArgs, proj, timeoutMs * 3, pythonBin, llmEnv);
          return {
            action,
            success: res.success,
            report: `[批量 LLM 分段复核 (并发 ${workers}/${finalWorkers})]\n${res.stdout || res.stderr}`,
          };
        }
      }

      // 7. scan_numbering: 全量计数器模拟普查
      if (action === 'scan_numbering') {
        const outJson = path.join(proj, 'numbering_scan.json');
        const cliArgs = ['--root', proj, '--out-json', outJson];
        if (args.file) cliArgs.push('--file', args.file);
        const res = await runPython('scan_numbering.py', cliArgs, proj, timeoutMs, pythonBin);
        return {
          action,
          success: res.success,
          report: `[计数器模拟推进普查与 Δ 偏移诊断]\n${res.stdout || res.stderr}\n报告已输出至: ${outJson}`,
        };
      }

      // 8. canonicalize: 冻结标签总台账
      if (action === 'canonicalize') {
        const outMd = path.join(proj, 'label_targets.md');
        const outJson = path.join(proj, 'label_targets.json');
        const cliArgs = ['--root', proj, '--out-md', outMd, '--out-json', outJson];
        const res = await runPython('canonicalize_numbering.py', cliArgs, proj, timeoutMs, pythonBin);
        return {
          action,
          success: res.success,
          report: `[引用总台账构建与三集合等价校验]\n${res.stdout || res.stderr}\n台账已冻结:\n- ${outJson}\n- ${outMd}`,
        };
      }

      // 9. cross_refs: 全书交叉引用批量规范化
      if (action === 'cross_refs') {
        const labelJson = path.join(proj, 'label_targets.json');
        const reportMd = path.join(proj, 'cross_refs_report.md');
        const cliArgs = ['--root', proj, '--labels', labelJson, '--report-out', reportMd];
        if (args.apply) {
          cliArgs.push('--apply');
        } else {
          cliArgs.push('--dry-run');
        }
        if (args.file) cliArgs.push('--file', args.file);
        const res = await runPython('batch_cross_refs.py', cliArgs, proj, timeoutMs, pythonBin);
        return {
          action,
          success: res.success,
          report: `[交叉引用批量规范化 (${args.apply ? '已写回应用' : 'dry-run 审计预演'})]\n${res.stdout || res.stderr}\n审计报告: ${reportMd}`,
        };
      }

      // 10. frontmatter: 前置件与版权页多 Agent 正交骨架管理与合规核验
      if (action === 'frontmatter') {
        const mode = args.mode || 'scaffold';
        const cliArgs = ['--root', proj, '--action', mode];
        if (args.file) {
          cliArgs.push('--target', args.file);
        }
        const res = await runPython('frontmatter_manager.py', cliArgs, proj, timeoutMs, pythonBin);
        return {
          action,
          success: res.success,
          report: `[前置件与版权页排版 (${mode === 'scaffold' ? '多 Agent 正交骨架生成' : '合规核验'})]\n${res.stdout || res.stderr}`,
        };
      }

      // 11. compile: 基础模块或出版级编译
      if (action === 'compile') {
        if (args.elegant) {
          const cliArgs = ['--root', proj, '--timeout', String(args.timeout || 600)];
          const res = await runPython('compile_all_elegant.py', cliArgs, proj, (args.timeout || 600) * 1000, pythonBin);
          const textOut = `${res.stdout || ''}\n${res.stderr || ''}`;
          const ok = res.success && !/\[FAIL\]|\bFAIL\b|\bREJECTED\b/i.test(textOut);
          return {
            action,
            success: ok,
            report: `[ElegantBook 出版级双 pass 编译回归]\n${res.stdout || res.stderr}`,
          };
        } else {
          const cliArgs = ['--root', proj, '--timeout', String(args.timeout || 300)];
          const res = await runPython('compile_all_volumes.py', cliArgs, proj, (args.timeout || 300) * 1000, pythonBin);
          const textOut = `${res.stdout || ''}\n${res.stderr || ''}`;
          const ok = res.success && !/\[FAIL\]|\bFAIL\b|\bREJECTED\b/i.test(textOut);
          return {
            action,
            success: ok,
            report: `[基础装配模块编译回归]\n${res.stdout || res.stderr}`,
          };
        }
      }

      // 12. residual_stats: 残余标记普查
      if (action === 'residual_stats') {
        const outJson = path.join(proj, 'residual_stats.json');
        const res1 = await runPython('collect_residual.py', ['--root', proj, '--out', outJson], proj, 60000, pythonBin);
        const res2 = await runPython('list_residual_footnotes.py', ['--root', proj], proj, 60000, pythonBin);
        return {
          action,
          success: res1.success && res2.success,
          report: `=== 残余工作量与标记普查 ===\n${res1.stdout}\n\n悬置脚注普查:\n${res2.stdout}`,
        };
      }

      return {
        action,
        success: false,
        report: `未知操作: ${action}`,
      };
    },
  });

  // =========================================================================
  // 2. 注册零信任质量门禁工具: latex_trans_gate
  // =========================================================================
  ctx.tools.register({
    name: 'latex_trans_gate',
    description: 'LaTeX 专著中译零信任质量门禁核验工具。支持全量门禁汇总(all)、G1-G5五门禁校验器(gate_check)、计数器模拟一致性门禁(numbering)、AST环境平衡门禁(nesting)与XeLaTeX编译门禁(compile)。',
    parameters: {
      type: 'object',
      properties: {
        gate: {
          type: 'string',
          enum: ['all', 'gate_check', 'numbering', 'nesting', 'compile'],
          description: '门禁项：all(全量汇总) | gate_check(G1-G5五门禁单节或全量校验) | numbering(计数器拓扑Δ≡0门禁) | nesting(AST环境折叠与配平门禁) | compile(编译通过门禁)',
        },
        target: {
          type: 'string',
          description: '待检查文件或目录路径（默认当前工作区）',
        },
        preamble: {
          type: 'string',
          description: '可选 preamble 宏文件路径（用于 gate_check）',
        },
        skip_compile: {
          type: 'boolean',
          description: '是否跳过 G1 XeLaTeX 编译门禁（只跑 G2-G5 纯文本静态门禁）',
        },
      },
      required: ['gate'],
    },
    output: {
      schema: {
        type: 'object',
        properties: {
          gate: { type: 'string' },
          passed: { type: 'boolean' },
          report: { type: 'string' },
        },
      },
      render: (_args, val) => [{
        type: 'text',
        text: val.report || (val.passed ? '✔ 门禁通过' : '✖ 门禁未通过'),
      }],
    },
    async execute(args) {
      const proj = resolveProjectRoot(args.target, ctx);
      const gate = args.gate;
      const reports = [];
      let allPassed = true;

      // 零信任失败标记审查（不仅检查 exit code === 0，还严格排查 stdout/stderr 失败关键字，杜绝假绿灯）
      const hasFailureMarker = (text) => {
        if (!text) return false;
        return /\[FAIL\]|\bFAIL\b|\bREJECTED\b/i.test(text);
      };

      // 1. numbering 门禁：模拟推进比对，Δ 必须全书全节归零
      if (gate === 'all' || gate === 'numbering') {
        const outJson = path.join(proj, 'numbering_gate.json');
        const res = await runPython('scan_numbering.py', ['--root', proj, '--out-json', outJson], proj, 120000, pythonBin);
        const textOut = (res.stdout || '') + '\n' + (res.stderr || '');
        const hasFail = hasFailureMarker(textOut) || textOut.includes('Δ != 0') || (textOut.includes('异常') && !textOut.includes('异常 0 节'));
        let pass = res.code === 0;
        if (fs.existsSync(outJson)) {
          try {
            const data = JSON.parse(fs.readFileSync(outJson, 'utf-8'));
            if (Array.isArray(data) && data.length > 0) {
              pass = pass && data.every(item => item.OK);
            }
          } catch (e) {
            pass = false;
          }
        } else {
          pass = pass && !hasFail;
        }
        if (!pass) allPassed = false;
        reports.push(`[${pass ? '✔ PASS' : '✖ FAIL'}] 计数器拓扑门禁 (Numbering Δ≡0 & Bare Headers):\n${res.stdout || res.stderr}`);
      }

      // 2. nesting 门禁：AST 环境配平，零错配零未闭合
      if (gate === 'all' || gate === 'nesting') {
        const targetPat = path.join(proj, '**', '*.pre.tex');
        const res = await runPython('nest_proofs.py', [targetPat, '--all'], proj, 120000, pythonBin);
        const textOut = (res.stdout || '') + '\n' + (res.stderr || '');
        const hasFail = hasFailureMarker(textOut) || /发现\s*\d+\s*处错配|未闭合环境|未闭合证明/.test(textOut);
        const pass = res.code === 0 && !hasFail;
        if (!pass) allPassed = false;
        reports.push(`[${pass ? '✔ PASS' : '✖ FAIL'}] AST 与环境栈平衡门禁 (Nesting & Balance):\n${res.stdout || res.stderr}`);
      }

      // 3. gate_check: G1-G5 五门禁校验器
      if (gate === 'all' || gate === 'gate_check') {
        const targetFile = args.target && fs.existsSync(args.target) && fs.statSync(args.target).isFile()
          ? args.target
          : null;

        if (targetFile) {
          const cliArgs = [targetFile];
          if (args.preamble) cliArgs.push('--preamble', args.preamble);
          if (args.skip_compile) cliArgs.push('--skip-compile');
          const res = await runPython('gate_check.py', cliArgs, proj, 120000, pythonBin);
          const textOut = (res.stdout || '') + '\n' + (res.stderr || '');
          const hasFail = hasFailureMarker(textOut);
          const pass = res.code === 0 && !hasFail;
          if (!pass) allPassed = false;
          reports.push(`[${pass ? '✔ PASS' : '✖ FAIL'}] 五门禁校验器 (${path.basename(targetFile)}):\n${res.stdout || res.stderr}`);
        } else {
          reports.push('[ℹ INFO] 全书五门禁抽查：建议传入具体的节文件进行 G1-G5 精确核验。');
        }
      }

      // 4. compile 门禁：XeLaTeX 编译
      if (gate === 'all' || gate === 'compile') {
        const res = await runPython('compile_all_volumes.py', ['--root', proj, '--timeout', '180'], proj, 180000, pythonBin);
        const textOut = (res.stdout || '') + '\n' + (res.stderr || '');
        const hasFail = hasFailureMarker(textOut) || textOut.includes('TIMEOUT') || textOut.includes('NOT FOUND');
        const pass = res.code === 0 && !hasFail;
        if (!pass) allPassed = false;
        reports.push(`[${pass ? '✔ PASS' : '✖ FAIL'}] LaTeX 编译回归门禁 (Compile Regression):\n${res.stdout || res.stderr}`);
      }

      const summary = `=== 零信任质量门禁检查报告 (${gate}) ===\n总体结论: ${allPassed ? '全部通过 (ALL PASS)' : '存在未通过项 (FAIL)'}\n\n` + reports.join('\n\n');
      return {
        gate,
        passed: allPassed,
        report: summary,
      };
    },
  });

  // =========================================================================
  // 3. 注册斜杠指令: /textrans
  // =========================================================================
  const commandsService = ctx.get('commands');
  if (commandsService && typeof commandsService.register === 'function') {
    commandsService.register({
      name: 'textrans',
      description: 'LaTeX 专著中译与结构化流水线指令 (/textrans status | gates | check-api | config-api | frontmatter | run | help)',
      input: {
        hint: 'status | check-api | config-api <key> [model] | frontmatter | gates | run <step> | help',
      },
      async handler(inv) {
        const raw = (inv.rawInput || '').trim();
        const parts = raw.split(/\s+/).filter(Boolean);
        const sub = parts[0] || 'help';
        const proj = resolveProjectRoot(null, ctx);

        if (sub === 'help') {
          return {
            kind: 'success',
            text: [
              '📖 **LaTeX 专著中译与结构化流水线指令指南**',
              '- `/textrans check-api` : 检查 LLM API 凭据是否就绪并引导配置',
              '- `/textrans config-api <key> [model] [base_url]` : 一键快速持久化配置 API',
              '- `/textrans status` : 查看当前工程文件、API状态、证据链与台账就绪状态',
              '- `/textrans frontmatter` : 生成前言与版权页多 Agent 正交拆分骨架',
              '- `/textrans gates` : 运行全量零信任质量门禁核验',
              '- `/textrans run test_api` : 测试 LLM API 连通性与延迟',
              '- `/textrans run preprocess` : 运行机械预处理 (S1 层)',
              '- `/textrans run fix_headers` : 运行漏包编号头补包',
              '- `/textrans run nest_proofs` : 运行证明折叠与 AST 配平',
              '- `/textrans run scan_numbering` : 运行计数器模拟推进普查 (S4 层)',
              '- `/textrans run canonicalize` : 冻结全书引用白名单总台账',
              '- `/textrans run cross_refs` : 批量规范化全书内部引用 (S5 层)',
              '- `/textrans run compile` : 运行 LaTeX 模块编译回归 (S6 层)',
            ].join('\n'),
          };
        }

        if (sub === 'check-api') {
          const apiCheck = ensureOrPromptApiConfig(proj, {});
          if (apiCheck.ready) {
            return {
              kind: 'success',
              text: `✔ **LLM API 已就绪**\n模型: \`${apiCheck.model}\`\nKey: \`${maskApiKey(apiCheck.api_key)}\`\n基础地址: \`${apiCheck.base_url}\`\n配置来源: ${apiCheck.configPath || '环境变量'}`,
            };
          }
          return { kind: 'error', text: apiCheck.message };
        }

        if (sub === 'config-api') {
          const key = parts[1];
          const model = parts[2] || 'deepseek-chat';
          const baseUrl = parts[3] || 'https://api.openai.com/v1';
          if (!key) {
            return {
              kind: 'error',
              text: '用法: `/textrans config-api <API_KEY> [model] [base_url]`',
            };
          }
          const writeRes = writeApiConfigFile(proj, { api_key: key, model, base_url: baseUrl });
          return {
            kind: writeRes.success ? 'success' : 'error',
            text: writeRes.success
              ? `✔ API 凭据已保存至 ${writeRes.path} (模型: ${model}, Key: ${maskApiKey(key)})`
              : `✖ 保存失败: ${writeRes.error}`,
          };
        }

        if (sub === 'frontmatter') {
          const res = await runPython('frontmatter_manager.py', ['--root', proj, '--action', 'scaffold'], proj, 60000, pythonBin);
          return {
            kind: res.success ? 'success' : 'error',
            text: res.stdout || res.stderr,
          };
        }

        if (sub === 'status') {
          const res = await runPython('collect_residual.py', ['--root', proj], proj, 60000, pythonBin);
          const apiCheck = ensureOrPromptApiConfig(proj, {});
          return {
            kind: 'success',
            text: `[API 状态]: ${apiCheck.ready ? `✔ 就绪 (${apiCheck.model}, Key: ${maskApiKey(apiCheck.api_key)})` : '⚠️ 未配置 (请先执行 /textrans check-api)'}\n\n[流水线状态与残余标记]:\n${res.stdout || res.stderr}`,
          };
        }

        if (sub === 'gates') {
          const res = await runPython('scan_numbering.py', ['--root', proj], proj, 60000, pythonBin);
          return {
            kind: res.success ? 'success' : 'error',
            text: `[编号与拓扑门禁]\n${res.stdout || res.stderr}`,
          };
        }

        if (sub === 'run') {
          const step = parts[1];
          if (!step) {
            return {
              kind: 'error',
              text: '请指定要运行的步骤，例如: `/textrans run test_api` 或 `/textrans run canonicalize`',
            };
          }
          if (step === 'test_api') {
            const apiCheck = ensureOrPromptApiConfig(proj, {});
            if (!apiCheck.ready) {
              return { kind: 'error', text: apiCheck.message };
            }
            const llmEnv = {};
            if (apiCheck.api_key) {
              llmEnv.OPENAI_API_KEY = apiCheck.api_key;
              llmEnv.LLM_API_KEY = apiCheck.api_key;
            }
            if (apiCheck.base_url) {
              llmEnv.OPENAI_BASE_URL = apiCheck.base_url;
              llmEnv.LLM_BASE_URL = apiCheck.base_url;
            }
            if (apiCheck.model) {
              llmEnv.OPENAI_MODEL = apiCheck.model;
              llmEnv.LLM_MODEL = apiCheck.model;
            }
            const res = await runPython('test_api.py', [], proj, 45000, pythonBin, llmEnv);
            return { kind: res.success ? 'success' : 'error', text: res.stdout || res.stderr };
          }
          if (step === 'canonicalize') {
            const res = await runPython('canonicalize_numbering.py', ['--root', proj], proj, 120000, pythonBin);
            return { kind: res.success ? 'success' : 'error', text: res.stdout || res.stderr };
          }
          if (step === 'compile') {
            const res = await runPython('compile_all_volumes.py', ['--root', proj], proj, 180000, pythonBin);
            return { kind: res.success ? 'success' : 'error', text: res.stdout || res.stderr };
          }
          return {
            kind: 'error',
            text: `未知运行步骤: ${step}。支持: test_api, preprocess, fix_headers, nest_proofs, scan_numbering, canonicalize, cross_refs, compile。`,
          };
        }

        return {
          kind: 'error',
          text: `未知指令: ${sub}。请使用 /textrans help 查看支持的指令。`,
        };
      },
    });
  }

  // =========================================================================
  // 4. 注入系统 Prompt 上下文（五层架构 + 强制 API 首问 + 版权页与多 Agent 正交派发红线）
  // =========================================================================
  const systemPromptService = ctx.get('systemPrompt');
  if (systemPromptService && typeof systemPromptService.context === 'function') {
    systemPromptService.context({
      name: 'latex-trans-flow-context',
      order: 125,
      text: [
        '【LaTeX 专著/教材中译与结构化流水线协作者规则 (Amann 经验复盘通用化版)】',
        '1. 五层处理架构与证据链：',
        '   - 机械层 (S1, 80%工作量)：preprocess / fix_bare_headers / nest_proofs 纯规则清洗，覆盖定理头、公式号、习题、脚注切分，零幻觉。',
        '   - LLM复核层 (S2, 20%工作量)：api_refine 带双向上下文（前瞻下段头+回顾上段尾）与段内四重校验，小窗三判定（OK/FIX/KEEP），失败降级回退原段。',
        '   - 子Agent收尾层：仅处理复杂语义疑难（FIXME-env/ex、长尾悬置脚注），必须严格对照 chapters_transAndOrigin 双语原件对校。',
        '   - 独立核验层 (S3-S6)：gate_check 五门禁 + scan_numbering 编号模拟 + canonicalize_numbering 台账冻结 + batch_cross_refs 交叉引用 + compile 编译。',
        '   - 前置件收官层 (Front Matter)：出版级版权页排版 + 序言重排 + 目录装配，多 Agent 正交并行派发。',
        '   - 严格证据链：*.tex(只读基线) → *.pre.tex(机械层) → *.api.tex(复核层) → 门禁全绿回写采纳至 *.pre.tex → 出版迁移提升为 *.tex。',
        '',
        '2. 核心红线守则与执行规范（不可逾越的底线）：',
        '   - 【强制首问与引导配置 API-Key 红线】：在接手或启动 LaTeX 中译流水线任务时，必须第一时间核验 API-Key 配置状态（环境变量或 api_config.json）。若未配置或仍为占位符，严禁静默跳过或直接进行后续步骤，必须立刻调用 ask_user_question 向用户主动询问并引导配置（提供配置文件路径、模板格式或协助调用 configure_api），连通性测试 (test_api) 通过后方可进行大模型相关流程！',
        '   - 【前言与前置件排版：必须包含出版级版权页】：最后排版前言时，严禁仅排版序言而遗漏版权页！必须规范排版版权页（Copyright Page），要素包含：原著外文书名/原著者/原出版机构/出版年份/ISBN或LCCN、中文译名/译者/审校者、授权与学术交流免责声明、版本号与定稿日期。',
        '   - 【前言排版多 Agent 正交派发架构】：排版前言与前置件时，严禁单 Agent 独揽串行处理全部内容！必须按各部分分别派发独立 Agent（Subagent）并行处理：',
        '     ① 版权专员（Copyright Agent）：独占负责 chapters/frontmatter/copyright.tex；',
        '     ② 原书前言专员（Author Preface Agent）：独占负责 chapters/frontmatter/preface_author.tex（对照双语原件对校数学公式与人名）；',
        '     ③ 译者序专员（Translator Preface Agent）：独占负责 chapters/frontmatter/preface_translator.tex；',
        '     ④ Lead Agent：统筹主装配文件并统一执行 XeLaTeX 出版级编译与门禁验收。各 Agent 严格遵守写域正交红线，严禁交叉篡改！',
        '   - 机械任务必须机械化：交叉引用是图论拓扑消歧，严禁派 Agent 通读改写文本！Python 批量引擎 1.8s 精确守恒完成数千处替换，杜绝 Agent 改写公式或微调标点导致的 Token 漂移。',
        '   - 零信任 AST 防御：环境栈不平衡时机械脚本严禁静默写回，坚决守住源文件安全底线。',
        '   - 数学 Token 流守恒不变量：剥离 \\footnote{}、注释并对 ~ 归一化后比对，任何公式变异一律阻断。',
        '   - 自动编号 ≠ label：amsthm 计数器按 \\begin 递增，漏包一个环境将导致后续所有显示编号偏移 1！必须使用 scan_numbering 模拟推进核对。',
        '   - 白名单总台账零信任：所有替换目标必须 100% 存在于已冻结的 label_targets.json 中，不在白名单一律记 % FIXME-ref:。',
        '   - 多层占位保护 (Placeholder Guard)：替换前封存已有 \\label 与文献条目，确保数学结构真空隔离。',
        '   - 悬置脚注双轨修复：残存上标指纹批量回填（覆盖>50%）+ 双语源语义锚定长尾。',
        '   - 平台工程规范：Windows 终端全流程锁定 UTF-8，XeLaTeX 编译配置超时熔断与进程锁规避。',
      ].join('\n'),
    });
  }
}
