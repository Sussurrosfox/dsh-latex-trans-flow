---
name: latex-translation-flow
description: LaTeX 专著/教材中译与结构化流水线（Amann 经验复盘通用化版）。集成五层处理模型、8步标准复用流水线（含API前置核验与前言版权页多Agent正交排版）、36项工程经验红线与零信任五门禁闭环。适用于高难度数学教材专著从 OCR/机翻初稿到出版级 ElegantBook 双 pass 排版的全流程处理。
---

# LaTeX 专著/教材中译与结构化流水线 (Amann 经验复盘版)

本插件与技能沉淀自 Amann《Analysis I–III》（3卷12章83节，1,125页）出版级中译改造工程的实战成果与经验教训。工程达成计数器零错配、3,259个白名单标签三集合等价、4,073处交叉引用100%规范化、五门禁全绿通过。

---

## 1. 五层处理架构与证据链

```
┌─ 规划与凭据层（前置核验与任务契约）───────────────────┐
│  API-Key 强制首问与引导配置 → 诊断 → 任务拆分明细       │
└───────────────────────────────────────────────────────┘
                        ↓
┌─ 机械层（零判断，纯规则，覆盖约 80% 工作量）────────────┐
│  preprocess.py (分流施规/状态机/脚注切分/命名定理匹配)   │
│  fix_bare_headers.py (漏包编号头补包)                  │
│  nest_proofs.py (环境折叠归一，AST 平衡防线)            │
└───────────────────────────────────────────────────────┘
                        ↓
┌─ LLM 复核层（API 批量，小窗三判定）─────────────────────┐
│  api_refine.py (分段+双向上下文+段内四重校验+原段降级)   │
│  batch_api_refine.py (断点续跑，段并发/门禁并发解耦)     │
└───────────────────────────────────────────────────────┘
                        ↓
┌─ 子 Agent 收尾层（语义级修补，双语原件对校）────────────┐
│  FIXME-env / FIXME-ex / 边界 CHECK / 悬置脚注          │
│  两级模型写域正交，严格对照英中对照原件人工/Agent闭环    │
└───────────────────────────────────────────────────────┘
                        ↓
┌─ 独立核验层（不信任任何"报告通过"）─────────────────────┐
│  gate_check.py (五门禁) + scan_numbering.py (模拟推进)  │
│  + canonicalize_numbering.py (白名单总台账)            │
│  + batch_cross_refs.py (占位保护批量连接)              │
└───────────────────────────────────────────────────────┘
                        ↓
┌─ 前置件与出版收官层（Front Matter & 多 Agent 正交派发）─┐
│  版权页 (Copyright Page) + 原书序言 + 译者序导读        │
│  各部分分别派发独立 Agent 处理，Lead 负责主装配与编译   │
└───────────────────────────────────────────────────────┘
```

**三条基线证据链（全程不可打乱）**：
`*.tex`（原始 OCR/机翻基线，只读）→ `*.pre.tex`（机械层）→ `*.api.tex`（LLM 复核层）→ 门禁全绿后回写采纳至 `*.pre.tex` → 出版迁移提升为标准 `*.tex`。

---

## 2. 8 步标准作业流水线

### 第 0 步：凭据强制首问与引导配置（必须先确认凭据）
1. **强制前置检查**：
   在接手或启动 LaTeX 中译流水线任务时，**Agent 必须第一时间检查 LLM API-Key 配置状态**（检查环境变量 `OPENAI_API_KEY` 或项目根目录 `api_config.json`）。
2. **主动拦截与引导询问**：
   - 工具调用检查：`latex_trans_pipeline(action="check_api")`
   - 若未配置或仍为占位符：**绝对禁止盲目跳过或继续执行后续步骤！必须调用 `ask_user_question` 向用户主动询问是否已准备好 API Key，并引导配置**。
   - 配置方式支持：
     - ① 工具自动持久化：`latex_trans_pipeline(action="configure_api", api_key="sk-...", model="deepseek-chat")`；
     - ② 编辑自动生成的模板：`api_config.json`；
     - ③ 斜杠指令：`/textrans config-api sk-... deepseek-chat`。
3. 运行连通性测试以确保可用：
   - 工具调用：`latex_trans_pipeline(action="test_api")`

### 第 1 步：拆分与初始化
1. 将 OCR/机翻初稿按章或按节物理切分存入分卷目录，原始文件只读保留作为基线；
2. 运行状态全貌检查：`latex_trans_pipeline(action="status")`。

### 第 2 步：机械清洗与结构化骨架 (S1 层)
1. 单节试运行与规则标定（校准定理词表、眉页行）：
   - 工具调用：`latex_trans_pipeline(action="preprocess", file="chapters/01_Section_1.tex", extra_types="性质:property,判据:criterion")`
2. 全书全卷批量驱动（带确定性 label 跳过与幂等保护）：
   - 工具调用：`latex_trans_pipeline(action="preprocess", batch=true)`

### 第 3 步：漏包头修补与证明折叠 (S1.5 层)
1. 普查漏网裸编号头并自动补包：
   - 工具调用：`latex_trans_pipeline(action="fix_headers", apply=true)`
2. 对多子项环境内的悬挂证明进行折叠归一（带 AST 平衡自检）：
   - 工具调用：`latex_trans_pipeline(action="nest_proofs", apply=true)`

### 第 4 步：LLM 分段复核修补与残余统计 (S2 层)
1. 针对机械层留存的 `% CHECK` 边界标记运行分段 API 复核（断点续跑 + 双向上下文）：
   - 工具调用：`latex_trans_pipeline(action="api_refine", workers=8, final_workers=2)`
2. 普查残余工作量与采纳状态：
   - 工具调用：`latex_trans_pipeline(action="residual_stats")`

### 第 5 步：编号拓扑普查与标签台账冻结 (S4 层)
1. 运行编号一致性普查与计数器模拟推进：
   - 工具调用：`latex_trans_pipeline(action="scan_numbering")`
2. 构建并冻结全书引用目标总台账（作为交叉引用的唯一白名单）：
   - 工具调用：`latex_trans_pipeline(action="canonicalize")`

### 第 6 步：全书交叉引用批量转换 (S5 层)
1. 预演引用分析与精准命中率审计（dry-run 模式）：
   - 工具调用：`latex_trans_pipeline(action="cross_refs", dry_run=true)`
2. 确认审计无误后，落盘写回为 `\cref` 与 `\eqref`（多层占位保护）：
   - 工具调用：`latex_trans_pipeline(action="cross_refs", apply=true)`

### 第 7 步：前言与版权页出版级排版（收官层，多 Agent 正交派发）
在完成正文结构化与引用闭环后，最后排版前言与前置件（Front Matter）。本阶段包含两项强制性规范：

#### 7.1 必须包含出版级版权页（Copyright Page）
严禁仅排版前言而遗漏版权页！前置件必须包含规范的版权页，严格具备以下六大核心要素：
1. **原著外文出版信息**：原书外文名、原著者（Author）、原出版机构（如 Springer, AMS 等）、原版出版年份、原版 ISBN/LCCN/分类号；
2. **中文译本信息**：中文书名、译者团队（Translators）、审校人员；
3. **版权与授权声明**：原书版权声明、经授权合法翻译出版说明、仅供学术交流与教学参考免责声明；
4. **排版引擎与技术声明**：XeLaTeX / ElegantBook 模板引擎；
5. **版本与元数据**：出版定稿版本号（如 v1.0.0）、排版定稿日期（`\today` 或具体日期）；
6. **CIP 数据**（图书在版编目，若有则完整排版）。

#### 7.2 该步骤必须为各部分分别派发独立 Agent 处理
**严禁单个 Agent 独揽串行处理全部前置件！** 前置件物理与逻辑解耦，必须遵循**“两级模型写域正交”**红线原则，按部分分别派发独立的 Subagent 并行处理：
1. **前置件拆分骨架初始化**：
   - 工具调用：`latex_trans_pipeline(action="frontmatter", mode="scaffold")`
   - 生成正交文件结构：`chapters/frontmatter/copyright.tex`、`preface_author.tex`、`preface_translator.tex`。
2. **正交多 Agent 派发职责分工表**：
   - **Agent A（版权专员 Copyright Agent）**：
     - 独占负责：`chapters/frontmatter/copyright.tex`；
     - 职责：对照原书封面、版权页与 CIP 数据，规范排版版权声明，严查 ISBN、原著者与授权条款。
   - **Agent B（原书前言专员 Author Preface Agent）**：
     - 独占负责：`chapters/frontmatter/preface_author.tex`；
     - 职责：对照双语原件对校原书各版次序言，严把数学公式（如历史方程公式）、定理引用、数学家姓名与地名翻译。
   - **Agent C（译者序专员 Translator Preface Agent）**：
     - 独占负责：`chapters/frontmatter/preface_translator.tex`；
     - 职责：编撰中文版译者序，交代翻译背景、符号约定体例与技术致谢。
   - **Lead Agent（总协调与装配）**：
     - 独占负责：主装配文件 `chap00_frontmatter.tex` 与总控文件，统一挂载 `\frontmatter`、`\tableofcontents` 与 `\mainmatter`；
     - 核验前置件合规性：`latex_trans_pipeline(action="frontmatter", mode="audit")`；
     - 执行全书出版级编译与最终验收：`latex_trans_pipeline(action="compile", elegant=true)`；
     - 运行全量零信任门禁：`latex_trans_gate(gate="all")`。

---

## 3. 核心红线与经验教训（38 条实战精粹）

### 3.1 凭据与流程设计红线
1. **【强制首问与引导配置 API-Key 红线】**：在接手或启动 LaTeX 中译流水线任务时，必须第一时间核验 API-Key 配置状态。若未配置或仍为占位符，严禁静默跳过或直接进行后续步骤，必须立刻调用 `ask_user_question` 向用户主动询问并引导配置（提供配置文件路径、模板格式或协助调用 `configure_api`），连通性测试 (`test_api`) 通过后方可进行大模型相关流程！
2. **【前言与前置件排版：必须包含出版级版权页】**：最后排版前言时，严禁仅排版序言而遗漏版权页！必须规范排版版权页（Copyright Page），要素包含：原著外文书名/原著者/原出版机构/出版年份/ISBN或LCCN、中文译名/译者/审校者、授权与学术交流免责声明、版本号与定稿日期。
3. **【前言排版多 Agent 正交派发架构】**：排版前言与前置件时，严禁单 Agent 独揽串行处理全部内容！必须按各部分分别派发独立 Agent（Subagent）并行处理（版权专员负责版权页、原书序专员负责原书序、译者序专员负责译者序，Lead 负责主装配）。各 Agent 严格遵守写域正交红线，严禁交叉篡改！
4. **先机械后语言、先结构后引用**：能用规则做的绝不用 LLM/agent。机械层覆盖约 80% 工作量且零幻觉风险；LLM 只做规则做不了的边界判断。
5. **机械任务必须机械化**：交叉引用是拓扑唯一的符号消歧与边连接（Python 脚本 1.8 秒完成 4,073 处且数学 Token 流精确守恒），**严禁派 Agent 通读逐节改写**，否则极易顺手微调标点/公式导致数学漂移。
6. **禁止 Agent 手写一次性字符串替换脚本**：严禁出现数百行硬编码替换，必须使用参数化批处理引擎。
7. **批处理必须支持断点续跑与幂等性**。
8. **采纳必须有硬门槛**：门禁全过 + 残余标记清零 + 计数器 Δ≡0 才允许回写合并。
9. **机械脚本严禁做语义级启发式猜测**：不确定的边界一律标记流转给双语对校 Agent。

### 3.2 门禁与验证护栏
10. **零信任 AST 防御**：环境栈不平衡坚决拒绝写回，绝不对破损源文件造成二次污染。
11. **精准归因**：批量失败先做 AST 平衡度探测，区分算法缺陷与上游源破损。
12. **三重验证闭环缺一不可**：① `gate_check.py`（五门禁）② `scan_numbering.py`（模拟推进）③ 真实 XeLaTeX 编译。
13. **数学 Token 流比对是防模型篡改公式的核心不变量**：剥离 `\footnote{}` + 注释 + `~` 归一化后比对。
14. **模型会犯错，绝不放松门禁换速度**：失败重试并保留原段降级。
15. **"报告通过"不可信，必须独立四件套核验**。
16. **自动编号 ≠ label**：amsthm 计数器按 `\begin` 递增，漏包一个定理会导致后续所有显示编号偏移 1，只有模拟推进比对才能发现。
17. **白名单总台账零信任**：生成的 label 必须 100% 存在于冻结台账中，不在白名单一律记 `% FIXME-ref:`。
18. **多层占位保护（Placeholder Guard）**：替换前封存已有 `\label` 和文献引用条目，替换后还原。

### 3.3 OCR 陷阱与应对
19. **脚注锚点形态极不规则**：个位数无括号、多脚注挤在一个分割线、锚点被吸入数学区等。
20. **定理内部可以有列表**：`\begin{itemize}` 不是边界，状态机必须跟踪嵌套深度。
21. **命名定理可选参数可含数学**：正则必须转义感知，并要求含中文。
22. **标题提取必须使用平衡花括号扫描**。
23. **悬置脚注双轨修复**：残存上标指纹批量回填（确定性覆盖 >50%）+ 双语源语义对齐。

### 3.4 LLM 与协作细节
24. **分段必须带双向上下文**（前瞻下段头 + 回顾上段尾）。
25. **小窗三判定（OK/FIX/KEEP）比开放式编辑可靠**。
26. **推理模型 reasoning 需包夹提取**：`===SEG===` 与 `===REPORT===`。
27. **两级模型写域正交**：Lead 独占共享资产与总台账，子 Agent 独占其工作节文件。
28. **Windows 平台编码**：全流程锁定 `python -X utf8` 与 UTF-8 stdio。
29. **XeLaTeX 进程锁定防护**：配置超时熔断与独立输出目录。
