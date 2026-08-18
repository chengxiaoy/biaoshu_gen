# biaoshu_gen —— 软件标书智能体 POC

上传招标文件（docx）与企业知识库，自动解析招标要求并生成投标文件草稿。
设计文档：`docs/superpowers/specs/2026-08-18-biaoshu-agent-poc-design.md`

## 技术栈

Python 3.11+ · poetry · LangGraph（单一状态图 + SqliteSaver 断点续跑）·
PydanticAI + DeepSeek（结构化输出节点）· Claude Code SDK（harness 文件操作节点，
继承本机 ANTHROPIC_BASE_URL/ANTHROPIC_AUTH_TOKEN 智谱网关环境）

## 安装

```bash
poetry install
cp .env.example .env   # 或手动在 .env 写入 DEEPSEEK_API_KEY=sk-xxx
```

## 数据准备

```bash
# 招标文件放入 data/tender/（可同时放响应文件模板 *模板*.docx，init 会自动发现）
cp docs/软件招标文件.docx docs/标书模板.docx data/tender/
# 企业知识库放入 data/company/（docx/md/txt/jpg 等）
cp docs/营业执照测试.jpg data/company/
```

## 分阶段使用（人工控制点：03_facts.yaml / 04_outline.yaml 可编辑后续跑）

```bash
poetry run biaoshu init --tender data/tender/软件招标文件.docx --kb data/company
poetry run biaoshu parse      # 招标解析（按目录分节阅读）→ 01_parse/
poetry run biaoshu template   # 响应模板抽取（harness）→ 02_template/
poetry run biaoshu facts      # 全局事实 → 03_facts.yaml（可人工编辑）
poetry run biaoshu outline    # 技术方案目录 → 04_outline.yaml（可人工编辑）
poetry run biaoshu body       # 正文生成+审核检验（≤2 轮回环）→ 05_body/
poetry run biaoshu fill       # 三表并行填写（harness）→ 06_fill/
poetry run biaoshu assemble   # 拼装草稿 → 07_draft/标书草稿_v1.docx
poetry run biaoshu review     # 全面审核（harness）→ 08_review/
poetry run biaoshu revise     # 按意见修改并跑完循环（≤2 轮）
poetry run biaoshu status     # 查看进度
```

全自动（冒烟）：`poetry run biaoshu run`

## 测试

```bash
poetry run pytest        # 无 LLM 成本（假模型 + mock harness）
```
