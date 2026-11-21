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

## 文件说明

- `sources.yaml`：信息源和关注词配置
- `briefing.py`：抓取和生成脚本
- `template/index.html`：网页模板
- `data/`：历史数据（每天一个文件，自动保留 60 天）
- `.github/workflows/daily.yml`：定时任务
