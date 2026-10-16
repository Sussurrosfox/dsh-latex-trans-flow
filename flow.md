# Amann《Analysis I–III》中译改造：工作流复盘与经验教训（终稿）

> 记录日期：2026-10-08（项目收尾）。由 `todolist.md`（全程工作记录）与早期暂停点复盘合并整理。
> 项目目标：将三卷 OCR + 机翻产物提升为 elegantbook 排版的高质量中文译本 —— **已 100% 达成**。
> 本文档是最终工作流、脚本资产与经验教训的唯一权威复盘，供同类译书/文档结构化项目复用。

---

## 0. 项目终态快照

| 维度 | 终态 |
|---|---|
| 全书规模 | 3 卷 12 章 83 节正文 + 6 个前后置件 |
| 编号体系 | sim 计数器错位 0、漏包 0、裸头 0、伪 section 0、重复 label 0（全书 71 个核心节 Δ≡0） |
| 标签台账 | `label_targets.json`：3,259 个合规标签（thm 1,094 / eq 833 / ex 896 / sec 71 等），三集合等价 100% PASS |
| 交叉引用 | 4,073 处内部引用 100% 规范化为 `\cref`/`\eqref`，跨卷引用经 `xr` 挂载 .aux 后 0 未决 |
| 残余标记 | FIXME-env 0 / FIXME-ex 0 / 边界 CHECK 0 / 悬置脚注 0（74 处全部原位重嵌） |
| 编译验收 | 基础版 18 个装配模块 18/18 PASS；elegantbook 出版版三卷双 pass 100% PASS，共 1,125 页 PDF |
| 索引解耦 | 4,000+ 条双语索引词条归档至 `index_terms_vol1/2/3.md`，死页码正文删除 |

文件链（三条基线证据链，全程未变）：
`<节>.tex`（OCR 基线，只读）→ `<节>.pre.tex`（机械层）→ `<节>.api.tex`（LLM 复核层）→ 门禁全绿后回写采纳至 `.pre.tex` → Phase 5 提升为标准 `.tex`。

---

## 1. 最终工作流

### 1.1 五层处理模型

```
┌─ 规划层 ─────────────────────────────────────────────┐
│  diag.md（诊断+路线图）→ agents.md（任务分配明细）      │
│  → residual_dispatch.md（残余派工+T2 契约+prompt 模板）│
└───────────────────────────────────────────────────────┘
                        ↓
┌─ 机械层（零判断，纯规则，覆盖约 80% 工作量）────────────┐
│  preprocess.py → batch_preprocess.py                  │
│  fix_bare_headers.py（漏包编号头补包）                  │
│  nest_proofs.py（环境折叠归一，AST 平衡防线）           │
│  patch_setcounter.py（装配层计数器，已归档）            │
└───────────────────────────────────────────────────────┘
                        ↓
┌─ LLM 复核层（API 批量，非 agent）───────────────────────┐
│  api_refine.py（分段+双向上下文+段内四重校验）           │
│  batch_api_refine.py（断点续跑，段并发10/门禁并发3）     │
└───────────────────────────────────────────────────────┘
                        ↓
┌─ 子 Agent 收尾层（判断密集，语义级修补）────────────────┐
│  FIXME-env / FIXME-ex / 边界 CHECK / 悬置脚注           │
│  一律对照 chapters_transAndOrigin 双语原件对校          │
└───────────────────────────────────────────────────────┘
                        ↓
┌─ 独立核验层（不信任任何"报告通过"）─────────────────────┐
│  gate_check.py 五门禁 + scan_numbering.py 编号普查      │
│  + collect_residual.py 残余统计 + xelatex 真实编译      │
└───────────────────────────────────────────────────────┘
```

### 1.2 阶段路线图（实际执行顺序）

| 阶段 | 内容 | 关键产物 |
|---|---|---|
| S1 | 机械预处理 + 漏包补包 + 环境折叠归一 | 71 节 `.pre.tex`；`.api.tex` 全量 |
| S2 | 装配层修复（`\setcounter` 节号复位） | 各卷章装配文件 |
| S3 | 编号错位修复（thm 流 / eq 流 / 习题流，135→0） | sim 错位全书归零 |
| S4 | 标签总台账与三集合等价核验 | `label_targets.md/.json`（冻结白名单） |
| S5 | 交叉引用规范化（Python 批量引擎 4,073 处 + 3 处疑难人工闭环） | `cross_refs_report.md` |
| F | 前后置件与版权收官：版权页(Copyright)排版、序言重排、死目录→`\tableofcontents`、参考文献条目化、死索引解耦（各部分分别派发独立 Agent 正交处理） | 三卷 fm/bm + `chapters/frontmatter/` + `index_terms_vol*.md` |
| Phase 5 | elegantbook 出版级迁移：共享 amsthm 计数器复刻原书编号拓扑 + `xr` 跨卷引用 | 三卷 1,125 页出版级 PDF |
| Phase 4 | 74 处悬置脚注双轨重嵌（42 上标指纹批量 + 32 双语语义锚定） | 残余标记 0/0/0/0 |

> 注：原计划中的 P（润色 pass）经评估存在 Token 漂移风险、非核心主干，已从路线图移除。

---

## 2. 脚本资产盘点

### 2.1 核心可复用脚本（`reflect/scripts/`，已完成通用化改造与参数化解耦）

经过通用化改造后，所有脚本均已解耦写死的书名、卷目录、API 密钥与特定豁免，统一通过 `config_utils.py` 进行跨平台编码防护、项目根目录向上自适应探测、多卷发现与环境变量注入，并在保持 Amann 工程 100% 向后兼容的同时支持 CLI/配置驱动复用：

| 脚本 | 职责 | 通用化扩展与 CLI 参数 | 关键设计（复用价值所在） |
|---|---|---|---|
| `config_utils.py` | 统一配置与发现基础设施 | 跨平台 UTF-8 stdio 防护、目录树根探测 `find_project_root()`、多卷发现 `load_project_volumes()`、章节号解析、LLM 凭据加载 | 消除跨项目复用时的硬编码依赖与 Windows 终端乱码陷阱 |
| `gate_check.py` | 五门禁质量与安全校验器 | `--label-regex`, `--preamble`, `--skip-compile`, `--json` | G1 xelatex 编译 / G2 宏洁净 / G3 定理计数 / G4 数学 token 流（剥离脚注+注释+`~` 归一化后严格相等）/ G5 label 格式 |
| `preprocess.py` | 节级 OCR→结构化机械预处理 | `--volume-roman`, `--no-header-strip`, `--extra-types`, `--inplace`, `--out` | 数学区/文本区分离施规则；定理状态机带嵌套深度跟踪；脚注块多锚点切分；转义感知命名定理匹配；平衡花括号标题提取；末尾环境配平自检 |
| `batch_preprocess.py` | 全书批量预处理驱动 | `--root`, `--dirs`, `--pattern`, `--force`, `--dry-run`, `--extra-types`, `--json` | "已有确定性 label 即跳过"幂等保护；逐节静态门禁汇总与结构化报告导出 |
| `scan_numbering.py` | 全量编号普查与计数器模拟 | `--root`, `--out-json`, `--origin-dir`, `--file` | 计数器模拟推进 vs label 后缀比对（Δ）；漏包/裸头/伪 section/重复 label 检测 |
| `canonicalize_numbering.py` | 标签总台账构建工具 | `--root`, `--dirs`, `--out-md`, `--out-json`, `--exemptions`, `--no-exemptions` | 三集合等价核验（模拟显示号 == label 后缀 == 英文原件锚）；可配置豁免清单 |
| `analyze_cross_refs.py` | 工作节枚举 + 引用可行性分析 | `--root`, `--dirs`, `--labels`, `--json` | `get_work_files()` 全书工作节遍历器（多卷自适应发现）；跨章/跨节引用多层拓扑探测 |
| `batch_cross_refs.py` | 交叉引用批量规范化引擎 | `--root`, `--dirs`, `--labels`, `--report-out`, `--apply`, `--dry-run`, `--file` | 多层占位保护（`__PROT_MACRO_N__`/`__PROT_BIB_N__`）；白名单台账零信任校验；`--dry-run`/`--apply` + 审计台账 |
| `nest_proofs.py` | 共享计数器环境折叠归一 | `files`, `--apply`, `--whitelist`, `--whitelist-file`, `--all` | 内嵌 `balance_report`（零未闭合/零错配）+ 标签集等价校验，FAIL 一律拒绝写回；解耦白名单 |
| `fix_bare_headers.py` | 漏包编号头幂等补包 | `--root`, `--dirs`, `--apply`, `--only`, `--compile`, `--preamble`, `--extra-types` | 与 preprocess 同源的嵌套深度跟踪状态机；自动搜索 preamble 宏模板与动态扩展定理词表 |
| `collect_residual.py` | 残余标记统计数据源 | `--root`, `--dirs`, `--ext`, `--out` | FIXME-env/ex/CHECK/悬置脚注计数 + 采纳状态，解耦多卷结构，导出统计 JSON |
| `list_residual_footnotes.py` | 悬置脚注快速普查 | `--root`, `--dirs`, `--ext`, `--json` | 依赖 `analyze_cross_refs.get_work_files`，快速输出全书残余悬置脚注清单 |
| `api_refine.py` | LLM 分段复核修补工具 | `--base-url`, `--api-key`, `--model`, `--config`, `--preamble`, `--apply`, `--seg-lines`, `--jobs` | 环境完整边界切段；双向上下文（上段尾+下段头）；段内四重校验；失败重试→保留原段降级；解耦凭据至环境变量/配置 |
| `batch_api_refine.py` | LLM 批量复核驱动 | `--root`, `--dirs`, `--workers`, `--final-workers`, `--book`, `--base-url`, `--api-key`, `--model`, `--config`, `--preamble` | 断点续跑（只处理"无 .api.tex 或仍有 CHECK"的节）；段并发与汇编门禁并发分离；动态多卷识别与配置注入 |
| `test_api.py` | API 连通性与延迟测试 | `--base-url`, `--api-key`, `--model`, `--config`, `--prompt`, `--timeout` | 最小请求验证配置；支持任意工作目录下直接调用 |
| `compile_all_volumes.py` | 基础装配模块编译回归 | `--root`, `--config`, `--timeout`, `--pattern` | 超时熔断保护；支持 JSON 模块配置与自动模块探查 |
| `compile_all_elegant.py` | elegantbook 双 pass 编译驱动 | `--root`, `--config`, `--main-tex`, `--timeout` | 超时熔断、独立输出目录、PDF 页数/体积验收；PyMuPDF (`fitz`) 优雅降级保护 |
| `frontmatter_manager.py` | 前置件/版权页多Agent骨架管理与核验 | `--root`, `--action scaffold/audit`, `--target`, `--json` | 出版级版权页与序言正交拆分骨架生成；版权要素完整性门禁核验；遵守写域正交红线 |

**通用化设计原则**：
1. **零信任根目录发现**：所有脚本支持 CLI 参数 `--root <PATH>` 显式指定，缺省时通过 `config_utils.find_project_root()` 递归向上探查 `chapters_translate`、`chapters` 或 `.git`，彻底摆脱固定路径约束。
2. **多卷与单卷自适应**：自动发现标准分卷目录，同时支持单卷平面目录或通过 `--dirs` 显式指定工作目录。
3. **敏感凭据环境化**：LLM API 凭据解耦至环境变量 `OPENAI_BASE_URL`、`OPENAI_API_KEY`、`LLM_MODEL` 或 `--config api_config.json`，禁止任何硬编码凭据。
4. **规则与词表外部化**：定理中文类型映射、标签正则、白名单与豁免项全部支持命令行扩展（如 `--extra-types`、`--whitelist`）。
5. **100% 向后兼容**：在 Amann 工程中不带任何参数执行各脚本时，完全保持原有既定行为与输出。

### 2.2 项目专属临时脚本（`archive/`，已归档不再维护）

一次性脚本 63 个 + 各卷拆章拆节脚本 9 个（`archive/vol_split/`），分类索引见 `archive/README.md`。典型类别：

- **悬置脚注专项**（74 处已全部解决）：`audit_all_74_footnotes.py`、`apply_direct_footnotes.py`、`resolve_all_32_footnotes.py` 等 15 个；
- **编号/单节核验**：`verify_*.py`、`check_*.py`、`inspect_*.py`、`scan_labels.py` 等；
- **交叉引用原型**（已被 `batch_cross_refs.py` 取代）：`prototype_ref_converter.py`、`apply_replacements.py`（第 1 章 615 行硬编码替换——反面教材，见 §3.1-2）；
- **调试/对拍**：`_dbg.py`、`dbg_*.py`、`diff_*.py`、`analyze_*.py`；
- **各卷拆章**：`vol_split/`（split + verify，使命已完成）。

---

## 3. 经验教训（合并全程记录，按主题分类）

### 3.1 流程设计：机械 / LLM / Agent 的职责边界

1. **先机械后语言、先结构后引用**：能用规则做的绝不用 LLM/agent。机械层覆盖 817 个公式号、1,074 个定理头、819 道习题、416 个脚注块、1,574 处残留英文——约 80% 工作量且零幻觉风险；LLM 只做规则做不了的"边界判断"20%。
2. **确定性拓扑 vs 概率性 LLM：机械任务必须机械化**。交叉引用是图论上的"符号消歧与边连接"，拓扑唯一（节号唯一、跨章必带罗马数字、公式括号 100% 唯一命中）。Python 脚本 1.8 秒完成 4,073 处替换且数学 Token 流 Exact Match；若派 Agent 通读替换则需数天、Token 成本巨大，且 LLM 极易顺手微调标点/公式，破坏 Gate 4 守恒。**凡规则封闭、拓扑唯一的批量转换，严禁滥用 Agent。**
3. **禁止 agent 手写一次性替换脚本**：agent 曾手写 461 行硬编码字符串替换脚本（`apply_replacements.py` 同类）——效率低下的根因。对策：把逐节 bespoke 脚本泛化为参数化批处理工具。
4. **批处理工具必须断点续跑 + 幂等**：只处理未完成项，中断重跑零浪费（57 分钟/轮的长任务不怕中断）。
5. **采纳（apply）必须有硬门槛**：门禁全过 AND 残余标记清零 AND 计数器 Δ≡0 才允许回写，宁可留下待处理清单也不带病采纳。定稿回写保证 `.pre.tex` 权威性与历史留痕两全。
6. **机械脚本严禁做语义级启发式猜测**：脚本只适用于拓扑封闭、模式明确的无损变换；涉及证明结尾位置推断、断裂条目还原、OCR 乱码引发的环境嵌套破损，必须安全阻断并流转给持双语对照原件的 Agent。

### 3.2 门禁与验证

7. **结构门禁红线的零信任防御价值**：`nest_proofs.py` 面对 13 节 env 栈不平衡坚决拒绝写回，未对破损文件造成二次污染。**机械脚本在 AST/环境栈不平衡时一律严禁静默写回**，是保障大型 LaTeX 资产安全的最坚固底线。
8. **"算法缺陷"与"上游源破损"的精准归因**：批量 FAIL 出现时先做源文件健康度定性（AST 平衡度探测），避免盲目魔改下游脚本——13 节 FAIL 实为上游遗留的未闭合 `\begin{proof}` 与标签交叉嵌套。
9. **三重验证闭环缺一不可**：① `gate_check.py`（宏/label/数学 token）② `scan_numbering.py`（计数器模拟、Δ、裸头）③ xelatex 真实编译。单纯依赖正则或单一门禁必然漏网。
10. **数学 token 流比对是防模型改公式的核心不变量**，但必须剥离"预期变更"：脚注重接会把数学搬进 `\footnote{}`，不剥离会误报（首批 51/61 段误判）。方案：剥离 `\footnote{...}`（平衡括号）+ 注释 + `~` 归一化后严格相等。
11. **模型确实会犯错，不能放松门禁换速度**（偶发插入游离 `$`、丢 `\pi`）：严格门禁 + 失败重试 + 保留原段降级，让坏段永远进不了产物。
12. **"报告通过"不可信，必须独立核验四件套**：自己跑门禁 + 标记计数归零 + 脚注重接点上下文抽查 + 数学 diff 逐块分析（Wave 0 中模型删的 `^3`–`^6` 全是 OCR 假脚注锚点，属正确修复，不逐块看 diff 分不清修复与破坏）。
13. **门禁的覆盖缺口会变成静默丢信息**：`RAW_THM_PATTERN` 不含"示例"导致漏包被 Gate 3 的"13=13"假象掩盖，T2 agent 按红线删 FIXME 差点让问题永久消失。教训：① 定期全书扫描裸编号头，不只信门禁计数；② 共享资产的规则缺口由 Lead 修，不让执行 agent 在红线内"绕开"问题。
14. **自动编号 ≠ label**：amsthm 计数器按 `\begin` 递增显示编号，label 只是锚点。漏包一个定理环境使其后所有定理**显示编号整体偏移一位**，而计数比对完全察觉不到——必须用 scan_numbering 式模拟推进比对。
15. **白名单总台账作为零信任防御网**：任何替换动作的前提是生成的 label 100% 存在于冻结台账（3,259 个标签）中；不在白名单一律拒绝静默替换并注入 `% FIXME-ref:`。
16. **多层占位保护（Placeholder Guard）是零破坏的核心护城河**：正则替换前用唯一占位符封存已有宏（`\label`）与外部文献条目（`[Ada75, 定理 2.35]`），完成后统一还原，确保数学结构与宏语法真空隔离。

### 3.3 OCR 陷阱（实测清单）

17. **脚注锚点形态极不规则**：个位数无花括号（`\({}^2\)` vs `\({}^{10}\)`）；多脚注挤在一个 `\HRule` 块（按锚点切分）；锚点被吸进数学区成假上标（`\sqrt{β-α}^3`）；锚点干脆丢失（全书 74 个悬置脚注需对照原书回填）。
18. **定理陈述内部可以有列表**：`\begin{itemize}` 不能当结构边界，状态机必须跟踪嵌套环境深度，边界关闭延迟到深度归零。
19. **命名定理可选参数里可以有数学**：`9.6 定理( \(\Gamma\) 函数…)`——正则 `[^)）]*` 会误切，需转义感知匹配 `\\.|[^（()）]` 并要求含中文（防把 `(a)` 当定理名）。
20. **OCR 会把定理头吞进 `\section*`**，也会把习题误判为 `\section`（曾致计数器复位与跨节重复 label）；标题提取必须用平衡花括号扫描（标题内可有 `\overline{\mathbb{R}}` 双层嵌套）。
21. **断裂习题修复规范**：严禁仅按文本行匹配；先核查双语原件习题全集定总题数，从后向前逆序确认每题边界，剥离裸题号，把公式/子项/提示完整封装。
22. **断裂块"三步对校定位法"**：① 在 transAndOrigin 检索文本与上标确认语义属性；② 是证明则提升为 `proof` 环境，是真脚注且有锚点则接回 `\footnote{}`；③ 无唯一锚点的悬置脚注严格保留登记，禁止随意插放或静默丢弃。
23. **OCR 分离脚注的"双轨修复"模型**：先用"残存上标指纹"做确定性批量回填（覆盖 56.8% 且零误伤），剩余长尾再与双语源语义对齐锚定——大幅压缩人工判定开销。

### 3.4 LLM API 使用

24. **分段必须带双向上下文**：只给"上一段结尾"时段尾环境结束位置判定必然信息不足（首轮 65 节残留 CHECK 的主因）；补"下一段开头"前瞻后大部分可判。
25. **残余标记用小窗三判定（OK/FIX/KEEP）比开放式编辑可靠**：把"确认边界"变分类任务，模型保守性反而成优点（不确定就 KEEP，不乱改）。
26. **推理模型的 reasoning 算进 max_tokens 且混入 content**：输出用 `===SEG===`/`===REPORT===` 标记包夹提取，容忍前缀推理；超时按段长校准。
27. **批量替换的字符串转义陷阱**：Python `str.format()` 会把数学公式 `{}` 当占位符；LaTeX 源码各阶段存在 `\(` 与 `$`、`{x}_n` 与 `x_n` 等细微变异。应用基于词法切片的精准替换或多重模式容错搜索，避免单一强匹配假性失败。

### 3.5 多 Agent 协作

28. **两级模型与写域正交**：Lead → Subagent 调用深度 ≤2；每个子 Agent 独占其工作节文件，严禁交叉写入共享文件；Lead 独占台账与全局配置（glossary/STYLE/label 表）。
29. **派发工具选型先看是否支持显式模型路由**：`spawn_teammate` 不能选模型且同名 spawn 静默失败；改用 `subagent` + 显式 provider/model 后 6/6 成功。派发后必须验证实际存活数。
30. **前台/后台分流**：结果强依赖链用前台同步等待；大规模批处理用后台异步并发；交付日志与验收汇报自包含、可追溯。
31. **人类作者笔误（Typo）需认知性归因**：脚本拦截的未命中项可能是原书出版物勘误（如"练习 VII.8.13"实为作者差一错误）。绝不能机械"向下取整"猜测，应派双语对校 Agent 从数学命题需求逐题对比候选集，形成完备论证链后人工闭环。
32. **【前置件收官：版权页出版级排版规范】**：最后排版前言与前置件时，严禁仅排版序言而遗漏版权页（Copyright Page）。必须严格包含：原著外文书名/原著者/原出版机构/出版年份/ISBN或LCCN、中文译名/译者/审校者、授权声明与学术教学免责声明、版本号与定稿日期，保证符合正式学术出版物规范。
33. **【前言排版多 Agent 正交派发架构】**：前置件（版权页、原书序言、译者序）逻辑与物理高度正交，**严禁单 Agent 串行吞吐或大包大揽**！必须遵循两级模型写域正交红线，为各部分分别派发独立 Agent（版权专员负责 `copyright.tex`、原书序专员负责 `preface_author.tex`、译者序专员负责 `preface_translator.tex`），各子 Agent 独占其工作文件，由 Lead Agent 统筹主装配文件 `chap00_frontmatter.tex` 并统一验收。
34. **【API-Key 强制首问与引导配置红线】**：在启动或接手 LaTeX 中译流水线任务时，必须第一时间核验 API-Key 配置状态。若未配置或仍为占位符，严禁静默跳过或直接进行后续步骤，必须立刻调用 `ask_user_question` 向用户主动询问并引导配置（提供配置文件路径、模板格式或协助调用 `configure_api`），连通性测试 (`test_api`) 通过后方可推进依赖大模型的复核流程。

### 3.6 工程细节（Windows 平台）

32. **编码规范**：数学文本含大量 Unicode（`∎`、`∈`、中文），Windows 终端默认 GBK 极易 `UnicodeEncodeError`。必须 `python -X utf8` 且脚本内 `sys.stdout.reconfigure(encoding='utf-8')`。
33. **PowerShell 5.1 两大坑**：① 默认按 GBK 读 UTF-8 无 BOM 文件造成"乱码"假象；② 内联 `python -c` 里正则反斜杠转义层数极易错。对策：含正则的调试一律写成临时 .py 文件执行。
34. **Windows 中文/空格/括号路径**：Python 里没问题，PowerShell 里间歇性失败——文件操作统一走 Python 脚本。
35. **并发编译的文件锁定**：上一次 xelatex 未释放句柄会触发 `[WinError 32]`。必须为编译子进程配置超时熔断、独立输出目录及僵尸进程探针。

---

## 4. 同类项目复用指南（起步与全流程驱动）

在新项目或更广泛的 LaTeX 专著/教材中译工程中，可直接借助改造后的 `reflect/scripts/` 资产开展流水线作业：

### 4.1 环境变量与基础配置
可在系统环境变量中配置，或在项目根目录下放置 `api_config.json`：
```bash
# 环境变量（二选一）
export OPENAI_BASE_URL="https://api.example.com/v1"
export OPENAI_API_KEY="sk-your-key-here"
export LLM_MODEL="gemini-2.5-pro"
```
或者放置 `api_config.json`：
```json
{
  "base_url": "https://api.example.com/v1",
  "api_key": "sk-your-key-here",
  "model": "deepseek-chat",
  "timeout": 300
}
```

### 4.2 七步复用标准流水线

1. **第 1 步：拆分与初始化**
   - 将 OCR/机翻初稿按章或按节物理切分至 `chapters_translate/`（或直接存放在各卷目录下），保留原始 `<节>.tex` 作为只读基线；
   - 运行连通性测试验证 LLM 路由：
     ```bash
     python reflect/scripts/test_api.py
     ```

2. **第 2 步：机械清洗与结构化骨架（S1 层）**
   - 单节试运行与规则标定（校准定理词表、眉页行）：
     ```bash
     python reflect/scripts/preprocess.py path/to/01_Section_1.tex --extra-types "性质:property,判据:criterion"
     ```
   - 全书全卷批量驱动（带幂等保护与 JSON 汇总）：
     ```bash
     python reflect/scripts/batch_preprocess.py --root . --json preprocess_summary.json
     ```

3. **第 3 步：漏包头修补与证明折叠（S1.5 层）**
   - 普查是否有漏网裸编号头并自动补包：
     ```bash
     python reflect/scripts/fix_bare_headers.py --root . --apply --compile
     ```
   - 对多子项环境内的悬空证明进行规范折叠：
     ```bash
     python reflect/scripts/nest_proofs.py path/to/*.pre.tex --all --apply
     ```

4. **第 4 步：LLM 分段复核修补（S2 层）**
   - 针对机械层留存的 `% CHECK` 边界标记运行分段 API 复核（断点续跑 + 段级并发）：
     ```bash
     python reflect/scripts/batch_api_refine.py --root . --workers 8 --final-workers 2
     ```
   - 普查残余工作量与采纳状态：
     ```bash
     python reflect/scripts/collect_residual.py --root . --out residual_stats.json
     python reflect/scripts/list_residual_footnotes.py --root .
     ```

5. **第 5 步：编号拓扑普查与标签台账冻结（S4 层）**
   - 运行编号一致性普查与计数器模拟推进：
     ```bash
     python reflect/scripts/scan_numbering.py --root . --out-json numbering_scan.json
     ```
   - 构建并冻结全书引用目标总台账（作为交叉引用的唯一白名单）：
     ```bash
     python reflect/scripts/canonicalize_numbering.py --root . --out-md label_targets.md --out-json label_targets.json
     ```

6. **第 6 步：全书交叉引用批量转换（S5 层）**
   - 预演引用分析与精准命中率审计：
     ```bash
     python reflect/scripts/analyze_cross_refs.py --root . --labels label_targets.json
     python reflect/scripts/batch_cross_refs.py --root . --dry-run --report-out cross_refs_report.md
     ```
   - 确认审计无误后，落盘写回为 `\cref` 与 `\eqref`：
     ```bash
     python reflect/scripts/batch_cross_refs.py --root . --apply
     ```

7. **第 7 步：全书出版级编译与门禁验收（S6 层）**
   - 运行独立模块编译回归或整卷 elegantbook 编译：
     ```bash
     python reflect/scripts/compile_all_volumes.py --root . --timeout 300
     python reflect/scripts/compile_all_elegant.py --root . --timeout 600
     ```
   - 门禁铁律：全流程严守“五门禁（宏洁净/环境平衡/数学Token流/Label规范/XeLaTeX编译）+ 零未决引用 + 计数器模拟 Δ≡0”三重闭环。
