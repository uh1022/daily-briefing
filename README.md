# 每日信息汇总

每天北京时间早上自动抓取 AI、技术博客、矿业、民爆等公开信息源，生成一个网页。不依赖大模型，不需要服务器。

- **网页地址**：https://uh1022.github.io/daily-briefing/
- **更新时间**：每天北京时间 08:17 开始，9 点前完成（GitHub 高峰期偶有延迟）
- **手动更新**：仓库的 Actions → 每日汇总 → Run workflow

## 常用操作

| 想做什么 | 怎么做 |
|---|---|
| 增删信息源 | 编辑 `sources.yaml`，在对应分类下加一段或删一段，提交即可（提交后会自动重新生成一次） |
| 改关注词 | 编辑 `sources.yaml` 顶部的 `keywords` |
| 看哪个源坏了 | 网页底部"信息源 x/y 正常"，点开看失败原因 |
| 改页面样式 | `template/index.html` |

## 页面结构

- **总览**：每个分类的今日综述 + 前 3 条重点
- **分类页**：今日综述、今日重点（最多 5 条）、其他动态（同一事件的多篇报道合并成一条，可展开看全部来源）

"重点"的判断：
- 默认按规则：报道这件事的媒体越多、命中的关注词权重越高，排得越前
- 设置了大模型后：大模型从规则排出的前 15 条里挑重点，写中文标题、一句话要点和每类综述；只根据标题和摘要整理，出错时自动退回规则排序

## 接入大模型（可选）

支持任何 OpenAI 兼容接口（DeepSeek、通义千问、Kimi、智谱、OpenRouter、各类中转等）。在仓库 **Settings → Secrets and variables → Actions** 里设置三项：

| 位置 | 名称 | 填什么 | 示例 |
|---|---|---|---|
| Secrets | `LLM_API_KEY` | 服务商给的密钥 | `sk-...` |
| Variables | `LLM_BASE_URL` | 接口地址（到 /v1 为止） | `https://api.deepseek.com/v1` |
| Variables | `LLM_MODEL` | 模型名 | `deepseek-chat` |

设置好后到 Actions → 每日汇总 → Run workflow 手动跑一次即可生效。换服务商只改这三项。

## 文件说明

- `sources.yaml`：信息源和关注词配置
- `briefing.py`：抓取和生成脚本
- `aggregate.py`：同一事件合并、重点打分（规则）
- `llm.py`：大模型整理（可选）
- `translate.py`：英文标题和摘要机器翻译成中文（微软翻译为主、谷歌翻译备用，都是免费接口；失败时显示原文）
- `template/index.html`：网页模板
- `data/`：历史数据（每天一个文件，自动保留 60 天）
- `.github/workflows/daily.yml`：定时任务
