# LaTeX 专著中译与结构化流水线插件 (LaTeX Translation & Restructuring Pipeline)

面向高难度数学教材、学术专著 LaTeX 中译与出版级排版的通用自动化流水线，基于 Amann《Analysis I–III》（3卷12章83节，1,125页）出版级中译改造工程全套实战沉淀构建。

---

## 核心特性

- **五层处理模型**：规划与凭据层（API-Key 强制首问与任务契约）→ 机械层（80%零幻觉规则清洗）→ LLM复核层（分段双向上下文+段内四重校验+原段降级）→ 子Agent收尾层（双语对校）→ 独立核验层（零信任五门禁）→ 前置件出版收官层（版权页+前言多Agent正交排版）。
- **8步标准作业流**：从 API-Key 强制核验与引导配置、OCR 切片初始化、机械结构化、漏包修补与证明折叠、LLM复核，到编号模拟普查、白名单台账冻结、交叉引用批量转换、出版级版权页与前言多 Agent 正交排版，到整卷 ElegantBook 双 pass 编译验收。
- **强制 API-Key 凭据首问与引导配置**：开局主动核验凭据状态，未配置时主动拦截并引导配置，支持工具一键落盘持久化。
- **出版级版权页（Copyright Page）排版规范**：严格涵盖原著出版信息、中文译本信息、授权声明、学术免责声明、编译引擎与版本元数据。
- **前置件多 Agent 正交派发架构**：排版前置件阶段严格遵循写域正交原则，严禁单 Agent 独揽，为版权页（Copyright Agent）、原书序言（Author Preface Agent）、译者序（Translator Preface Agent）分别派发独立 Agent 并行处理，由 Lead 统一装配。
- **零信任五门禁闭环**：
  - G1: XeLaTeX 真实编译无报错
  - G2: 宏洁净（零裸 `\tag`、零不规则 `\HRule`、零伪 `\section*`）
  - G3: 定理环境计数与原文本头精确对齐
  - G4: 数学 Token 流严格守恒（剥离 `\footnote{}`、注释、`~` 归一化后比对）
  - G5: 标签符合确定性命名拓扑（`^(sec|thm|eq|ex):\d|A-`）
- **拓扑计数器模拟推进**：amsthm 共享计数器拓扑仿真，实时计算 Δ 偏移量，拦截因漏包导致的连锁显示编号错位。
- **白名单总台账防护**：三集合等价校验（模拟显示号 == label 后缀 == 英文原件锚），严防虚假引用。
- **多层占位保护**：交叉引用替换前真空封存已有宏与文献条目，保证数学结构零破坏。

---

## 提供的 Agent 工具

### 1. `latex_trans_pipeline`
流水线驱动核心工具，支持以下动作（`action`）：
- `check_api`: 检查当前 LLM API 凭据是否就绪并提供引导；
- `configure_api`: 一键配置并持久化 API 密钥与模型参数至 `api_config.json`；
- `status`: 查询当前工作区的文件状态、API配置、证据链就绪度、台账与编译状态；
- `test_api`: 测试配置的 LLM API 连通性与响应延迟；
- `preprocess`: 运行机械层预处理（支持单节 `--file` 或全书 `--batch`，自动识别罗马卷号、定理类型映射与眉页过滤）；
- `fix_headers`: 扫描漏网裸编号头并幂等补包；
- `nest_proofs`: 对证明环境进行 AST 平衡检查与折叠归一；
- `api_refine`: 批量驱动 LLM 分段复核与 `% CHECK` 消除（支持断点续跑）；
- `scan_numbering`: 全量运行计数器模拟推进普查与 Δ 偏移诊断；
- `canonicalize`: 构建并冻结全书引用白名单总台账 (`label_targets.json` / `label_targets.md`)；
- `cross_refs`: 批量规范化全书内部引用为 `\cref` 与 `\eqref`（支持 `--dry-run` 与 `--apply`）；
- `frontmatter`: 生成出版级版权页与序言的多 Agent 正交拆分骨架 (`mode="scaffold"`) 或核验合规性 (`mode="audit"`)；
- `compile`: 执行基础模块编译回归或整卷 ElegantBook 出版级双 pass 编译；
- `residual_stats`: 普查全书 FIXME、CHECK 及悬置脚注残余数量。

### 2. `latex_trans_gate`
零信任质量门禁独立核验工具：
- `all`: 运行五门禁汇总普查；
- `gate_check`: 运行指定文件或全书的 G1-G5 五门禁校验；
- `numbering`: 校验全书计数器模拟推进 Δ 偏移是否为 0；
- `nesting`: 校验 AST 环境栈配平度与标签等价性；
- `compile`: 校验 XeLaTeX 编译是否通过。

---

## 斜杠指令 (`/textrans`)

- `/textrans help` : 查看指令帮助
- `/textrans check-api` : 检查 LLM API 配置状态并引导
- `/textrans config-api <key> [model] [base_url]` : 快速配置 API 凭据
- `/textrans frontmatter` : 快速生成前言与版权页正交多 Agent 骨架
- `/textrans status` : 查看当前工程流水线状态
- `/textrans gates` : 触发全量质量门禁校验
- `/textrans run <action>` : 快捷触发流水线步骤

---

## 核心红线守则

1. **【强制 API-Key 首问与引导配置】**：流水线启动时必须第一时间核验 API-Key，未配置时严禁盲目执行，必须先向用户主动询问并引导配置。
2. **【前言排版必须包含出版级版权页】**：严禁遗漏版权页，必须规范涵盖原著信息、中文译本团队、版权与授权声明、出版免责声明及元数据。
3. **【前言排版各部分分别派发独立 Agent】**：前置件排版严禁单 Agent 串行处理，必须按版权页、原书序言、译者序分别派发独立 Agent 正交处理，遵守写域正交红线。
4. **机械任务必须机械化**：凡规则封闭、拓扑唯一的批量转换（如交叉引用），严禁派 Agent 通读改写，必须由脚本完成以杜绝数学 Token 漂移。
5. **环境栈不平衡严禁静默写回**：AST 结构破坏时坚决拒绝回写，保障资产底线安全。
6. **计数器模拟推进**：自动编号依赖 `\begin` 推进，单节漏包会导致全节后文显示编号整体偏移 1，不可轻信静态计数。
7. **两级模型写域正交**：Lead 独占共享资产与总台账，子 Agent 独占其工作节文件，互不干扰。
