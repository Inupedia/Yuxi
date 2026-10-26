# 引大济岷定制同步上游 0.8

状态：proposed
类型：architecture
Owner：frontend/src/custom/inupedia/index.js

## 问题

定制分支基于 0.7.2，上游 0.8 更换目录、认证装配、Schema 和索引，不提供旧数据原地升级。用户要求保留二次开发，并授权独立部署新版、旧站和数据保持运行，验收后再切换。

## 提案

### 实现方案

合并固定的 upstream/main a5ac16dd。定制页面迁入 frontend/src/custom/inupedia，按新版公开模块入口接入身份、配置和 Agent；认证处理使用新版流程。后端单位配置迁入 system/static，助手身份随新 prompt 保留；Tavily 代理迁入网页供应商端点 Owner。

新版生产使用独立 Compose 项目、端口、凭据、网络和空数据目录。旧 /home/ubuntu/Yuxi 保留。使用 container 沙箱适配现有 Docker 服务器，不复用旧 provisioner。验收前不切换原域名或 Spotlight 的旧 API。

## 替代方案

直接覆盖旧部署会破坏旧数据兼容；停留旧版无法满足更新目标。手工伪造 Schema 版本违反上游约束。

## 验收标准

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 品牌页可构建与访问 | 旧 import 和认证接口失配 | frontend/src/custom/inupedia | lint、build、浏览器 | 未迁移路径导致 build 失败 | Not run |
| Tavily 代理保留 | 请求绕过代理 | extensions/web/providers.py | test_web_search_provider.py | 移除代理分支时断言失败 | Not run |
| 新旧生产数据隔离 | 新版写入旧库 | docker-compose.prod.yml 和部署配置 | Compose 配置与运行挂载回读 | 复用旧路径视为不通过 | Not run |

## 风险

0.8 是 beta 候选；旧账号、知识库、会话不会自动进入新版。并行站验证后由用户决定正式切换，不能以 readiness 代替业务验收。
