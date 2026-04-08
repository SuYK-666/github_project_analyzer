# GitHub Project Analyzer

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB)
![Flask](https://img.shields.io/badge/Web-Flask-000000)
![DeepSeek](https://img.shields.io/badge/LLM-DeepSeek-0EA5E9)
![Status](https://img.shields.io/badge/Status-Active-22C55E)

一个面向课程项目、技术复盘与工程方法演示的多智能体分析系统。输入 GitHub 仓库链接并选择分析方向，即可自动生成一致性的 Markdown、HTML、DOCX 三份报告。

支持分析方向：

- 工程经济与项目管理
- 伦理法规与工程安全

## 快速导航

- [核心亮点](#核心亮点)
- [系统架构](#系统架构)
- [代码级洞察能力](#代码级洞察能力)
- [快速开始](#快速开始)
- [运行方式](#运行方式)
- [配置项说明](#配置项说明)
- [质量保障机制](#质量保障机制)
- [报告格式规范](#报告格式规范)
- [常见问题](#常见问题)
- [贡献指南](#贡献指南)

---

## 核心亮点

- 多智能体流水线：Crawler -> Context Profiler -> Code Insight -> Domain Agent -> Critic -> Renderer
- 双方向专精：单次任务只输出一个方向，避免内容混杂
- 三格式一致交付：MD、HTML、DOCX 基于同一语义源渲染
- 代码级洞察增强：目录树 + 依赖清单 + 核心源码采样 + 轻量静态指标（复杂度/疑似密钥）
- One-Page Web 交互：输入配置、过程反馈、报告预览、文件下载在一页完成
- 实时监控更稳：SSE 实时流 + 轮询兜底，避免前端误判任务状态
- 质量门禁：Critic 最多 3 轮评审，达标提前结束，满轮选优
- 安全门禁：残缺检测、提示词泄露检测、输出净化三重保障
- GitHub 限流韧性：API 受限时自动启用无 API 兜底抓取模式
- 全链路可追踪：每次运行独立日志，完整记录 Agent 状态与缓存路径

---

## 适用场景

- 软件工程课程报告自动化
- 开源项目阶段性复盘
- 工程经济与伦理法规教学案例生成
- 多智能体系统工程化演示

---

## 系统架构

```text
Browser (One-Page UI)
      |
      | REST + SSE (+ Polling Fallback)
      v
Flask WebApp
      |
      v
Orchestrator
  |- CrawlerAgent           GitHub 数据抓取 / 限流兜底
  |- ContextProfilerAgent   项目技术名片与事实锚点
      |- CodeInsightAgent       目录树/依赖/源码采样与代码级洞察
  |- Econ/Ethics Agent      方向化初稿生成
  |- CriticAgent            评分、残缺检测、泄露检测、重写
  |- ReportRenderer         MD / HTML / DOCX 渲染
      |
      v
Artifacts + Cache + Logs
```

---

## 功能矩阵

| 模块 | 能力 | 工程特性 |
| --- | --- | --- |
| Crawler | 仓库元数据、README、语言、Issue、贡献者抓取 | Tree API、Manifest 抓取、核心源码采样、Rate Limit 降级 |
| Context Profiler | 生成项目技术名片与分析锚点 | 事实驱动提示词、输出净化 |
| Code Insight | 生成代码级洞察摘要 | 轻量静态指标、Map-Reduce 摘要、结构化证据输出 |
| Domain Agent | 生成 2000 字级方向化报告 | 总分总结构、阶段化分析、代码级事实锚定 |
| Critic | 自动审稿与重写驱动 | 分数阈值、最多 3 轮、残缺与泄露硬失败 |
| Renderer | 输出 MD/HTML/DOCX | 三格式一致性、Word 规范化样式控制 |
| Web UI | 任务下发与过程可视化 | SSE + Polling、实时步骤条、在线预览与下载 |

---

## 项目结构

```text
github_project_analyzer/
├── main.py
├── webapp.py
├── requirements.txt
├── .env.example
├── README.md
├── config/
│   ├── settings.py
│   └── prompts.py
├── agents/
│   ├── orchestrator.py
│   ├── crawler_agent.py
│   ├── context_profiler.py
│   ├── code_insight_agent.py
│   ├── econ_agent.py
│   ├── ethics_agent.py
│   └── critic_agent.py
├── utils/
│   ├── deepseek_client.py
│   ├── github_parser.py
│   ├── output_sanitizer.py
│   └── run_logger.py
├── renderers/
│   ├── report_renderer.py
│   └── templates/
│       ├── report_template.html
│       └── report_template.md
├── web/
│   ├── templates/index.html
│   └── static/
│       ├── app.css
│       └── app.js
├── logs/
└── data_workspace/
    ├── raw_data/
    ├── processed_cache/
    └── final_reports/reports/
```

---

## 快速开始

### 1. 环境要求

- Python 3.10+
- 可访问 DeepSeek API
- 可访问 GitHub（建议配置 Token）

### 2. 安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. 配置环境变量

```powershell
Copy-Item .env.example .env
```

至少填写：

- DEEPSEEK_API_KEY

建议填写：

- GITHUB_TOKEN（减少 API 限流风险）

### 一分钟体验

```powershell
python main.py
```

浏览器打开后只需要三步：

1. 填写 DeepSeek API Key（可选填 GitHub Token）
2. 输入仓库链接并选择分析方向
3. 点击“开始智能分析”，等待生成并下载三格式报告

---

## 运行方式

### Web 模式（默认）

```powershell
python main.py
```

默认地址：[http://127.0.0.1:8765](http://127.0.0.1:8765)

可选参数：

- --host：监听地址
- --port：端口
- --no-open-browser：启动后不自动打开浏览器

### CLI 模式

```powershell
python main.py --cli
python main.py --cli --repo-url https://github.com/fastapi/fastapi --analysis econ
python main.py --cli --repo-url https://github.com/pallets/flask --analysis ethics
```

CLI 可选参数：

- --quiet：隐藏流水线进度输出
- --debug：异常时输出完整堆栈

---

## Web 页面能力

- API Key / GitHub Token 输入与显示切换
- 本地记忆密钥（localStorage）
- 分析方向卡片选择
- 实时阶段反馈（抓取、画像、代码洞察、初稿、质检、渲染）
- 运行日志实时显示（SSE）
- 流中断自动降级轮询同步，避免误报失败
- HTML 报告内嵌预览
- 一键下载 DOCX / HTML / MD

---

## 配置项说明

| 变量名 | 默认值 | 说明 |
| --- | --- | --- |
| DEEPSEEK_API_KEY | 空 | DeepSeek API Key |
| DEEPSEEK_BASE_URL | [https://api.deepseek.com](https://api.deepseek.com) | DeepSeek API Base URL |
| DEEPSEEK_MODEL | deepseek-chat | 模型名 |
| GITHUB_TOKEN | 空 | GitHub Token，建议填写 |
| GITHUB_API_BASE_URL | [https://api.github.com](https://api.github.com) | GitHub API Base URL |
| OUTPUT_LANGUAGE | zh-CN | 输出语言 |
| REQUEST_TIMEOUT | 60 | 请求超时（秒） |
| MAX_RETRY | 3 | 网络请求重试次数 |
| TEMPERATURE | 0.4 | 生成温度 |
| MAX_TOKENS | 2800 | 单次生成 token 上限 |
| MAX_RETRY_ROUNDS | 3 | Critic 最大轮次（系统封顶 3） |
| REPORT_TARGET_CHARS | 2000 | 报告目标字数 |
| REPORT_MIN_CHARS | 1700 | 参考下限 |
| REPORT_MAX_CHARS | 2600 | 参考上限 |
| CRITIC_SCORE_THRESHOLD | 8.0 | Critic 通过阈值 |

---

## 输出产物与可追踪性

### 最终产物

- data_workspace/final_reports/reports/*.md
- data_workspace/final_reports/reports/*.html
- data_workspace/final_reports/reports/*.docx

### 中间缓存

- data_workspace/raw_data：抓取原始数据（含目录树、manifest、核心源码采样）
- data_workspace/processed_cache：
      - 01_crawler_payload
      - 02_context_profile
      - 03_code_insight
      - 04_draft_report
      - 05_critic_round_*
      - 06_final_state

### 运行日志

- logs/log_YYYYMMDD_HHMMSS.log

日志记录项包括：

- 时间戳
- 状态流转（START/RUNNING/DONE/WARN/FAILED）
- 执行 Agent
- 重试、评分、选稿、缓存路径等关键信息

---

## 质量保障机制

### Critic 门禁

- 评分门禁：score >= CRITIC_SCORE_THRESHOLD 才通过
- 轮次策略：最多 3 轮，达标提前结束
- 满轮选稿：优先选择完整、无泄露、得分最高版本

### 硬失败规则

- 残缺文本：章节缺失、结尾未收束、符号未闭合
- 提示词泄露：检测到元提示语或模板指令残留

### 生成后净化

- 自动清理模型元话术
- 移除不应进入正文的提示词内容

---

## GitHub 限流策略

当 GitHub API 命中限流时，系统不会立即中断：

1. 优先尝试 API 路径（可读取完整仓库统计信息）
2. 若触发 403 rate limit，自动切换到无 API 兜底模式
3. 兜底模式通过公开页面 + README raw 地址继续分析

说明：兜底模式可保持任务完成，但统计信息细节会少于 API 模式。

---

## 代码级洞察能力

为解决“仅依赖 README 导致分析偏浅”的问题，当前版本已引入代码级证据链，并保持原有流水线稳定性。

### 数据获取层（Crawler 扩展）

- 目录树抓取：通过 Git Tree API 递归获取仓库结构
- Manifest 抓取：自动识别并拉取 requirements.txt、package.json、pom.xml、go.mod、pyproject.toml
- 核心源码采样：启发式抽取 3-5 个高价值文件（入口、核心模块、服务层等）

### 洞察生成层（CodeInsightAgent）

- 依赖分析：解析依赖数量、清单分布和关键依赖样本
- 架构信号：结合目录树判断模块化与工程化程度（tests/docs/src/CI）
- 轻量静态指标：估计复杂度并扫描疑似硬编码敏感信息
- Map-Reduce 摘要：先按文件局部摘要，再汇总为可复用的代码级洞察

### 报告赋能层（Econ/Ethics）

- 工程经济方向可引用可维护性与技术债客观锚点
- 伦理法规方向可引用依赖风险与代码安全治理锚点
- 领域报告必须显式引用代码级证据，避免泛化空谈

---

## 报告格式规范

### DOCX

- 标题：方正小标宋简体，二号，居中
- 副标题区块：楷体_GB2312，三号，居中
- 副标题区块前后各一空行，区块内部逐行连续排版
- 一级标题：黑体，三号，段前段后各 0.5 行
- 二级标题：楷体_GB2312，三号
- 正文：仿宋_GB2312，三号，首行缩进 2 字符，固定行距 28 磅
- 西文字体统一 Times New Roman
- Markdown 粗体语法会转换为 Word 粗体
- Markdown 反引号语法不会原样保留到 Word 文本

### HTML

- 报告采用单列阅读结构
- 技术名片位于正文上方
- 响应式排版，避免横向撑宽

### Markdown

- 作为可编辑中间格式，便于审阅与复用

---

## Web API

| 方法 | 路径                         | 说明                         |
| ---- | ---------------------------- | ---------------------------- |
| POST | /api/start-analysis          | 创建分析任务                 |
| GET  | /api/stream/{job_id}         | SSE 实时事件流               |
| GET  | /api/result/{job_id}         | 查询任务状态与结果           |
| GET  | /api/download/{job_id}/{fmt} | 下载报告文件（docx/html/md） |

### 创建任务请求示例

```json
{
  "apiKey": "your-deepseek-key",
  "githubToken": "optional-github-token",
  "repoUrl": "https://github.com/owner/repo",
  "analysisType": "econ"
}
```

---

## 常见问题

### 1) 页面提示 apiKey 不能为空

- 检查 Web 页面 API Key 输入是否为空
- CLI 模式下检查 .env 中 DEEPSEEK_API_KEY

### 2) GitHub API 触发限流

- 优先在页面填写 GitHub Token
- 或在 .env 设置 GITHUB_TOKEN
- 即使未配置，也会尝试无 API 兜底模式

### 3) 前端显示“流连接中断”

- 这是网络抖动时的降级提示
- 前端会自动切换轮询继续同步，不会直接判失败

### 4) DOCX 字体显示不一致

- 目标机器未安装对应中文字体时会自动回退
- 可在本机安装方正小标宋简体、楷体_GB2312、仿宋_GB2312

---

## 开发指南

### 本地静态检查

```powershell
python -m compileall main.py webapp.py agents config utils renderers
```

### 开发建议

- 修改输出链路时同步更新 Critic 规则与净化逻辑
- 增加新 Agent 时同步补充 prompts 与日志状态
- 保留 data_workspace 缓存，便于问题复盘与回归比对

---

## 贡献指南

欢迎提交 Issue 与 PR。

建议流程：

1. Fork 并创建分支
2. 提交功能或修复
3. 通过静态编译检查
4. 在 PR 中附上改动说明与影响范围

---

## Roadmap

- 批量任务队列与多仓库并行分析
- 更严格的事实引用链路与可解释性增强
- 多模型交叉评审与报告一致性对照
- 自动化回归样本集与评分基线

---

## 安全与合规声明

本项目仅用于教学研究、课程作业与授权场景下的工程分析。
请勿将其用于任何未授权的安全测试或违规用途。

---

## 许可证

本项目采用 MIT License。

详见 [LICENSE](LICENSE)。
