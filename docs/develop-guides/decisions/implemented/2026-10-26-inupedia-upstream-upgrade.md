# 引大济岷定制同步上游 0.8

状态：implemented
类型：architecture
Owner：frontend/src/custom/inupedia/index.js

## 问题

定制分支基于 0.7.2，上游 0.8 更换目录、认证装配、Schema 和索引，不提供旧数据原地升级。用户要求保留二次开发，并明确选择独立部署新版、旧站和数据保持运行，验收后再决定切换。

## 决策

### 实现方案

合并固定的 upstream/main a5ac16dd（0.8.0.beta3）。定制页面迁入 frontend/src/custom/inupedia，按新版公开模块入口接入身份、配置和 Agent；登录脚本跟随新版认证流程，单位全名由品牌配置提供。主题保留品牌配置和新版 CSS 色板的明暗切换。后端单位配置迁入 system/static，助手身份保留；Tavily 代理迁入 extensions/web/providers.py，同时覆盖搜索与正文抓取。

新版使用独立 Compose 项目 yuxi08、凭据、网络、端口和空数据目录 /home/ubuntu/Yuxi-0.8-preview/.yuxi/state。local/compose.preview.yml 组合生产 Nginx frontend 和 container 沙箱构建；前端本机端口为 18180，API 为 16050。预览域名 knowledge-next.ai.swhisxy.cn 在管理员初始化与登录核验后开放，并使用有效 HTTPS 证书。生产品牌路径由 YUXI_BRAND_FILE_PATH 指向 /app/yuxi/modules/system/static/info.inupedia.yaml。

旧 /home/ubuntu/Yuxi、knowledge.ai.swhisxy.cn 和 Spotlight 旧接口保持运行。源代码、未提交改动、旧生产 PostgreSQL 与源码配置分别保留恢复副本；原对象、索引和用户文件仍由旧部署持有。部署细节和回退操作由 local/README.md 维护。

## 替代方案

直接覆盖旧部署会破坏数据兼容；停留旧版无法满足更新目标。手工修改 Schema 版本不能产生合法迁移。共享旧存储会让新旧进程同时写入不兼容数据，因此新环境从空状态目录初始化。

## 后果

0.8 是 beta 候选。旧账号、知识库和会话不会自动进入新版；预览使用独立管理员。用户验收后再单独处理正式入口切换和旧业务数据迁移。container 使用独立 runner 与每 Run 临时环境，沿用上游默认禁止联网，不复用旧 provisioner。

## 验证

- 工程信任检查和 verifier 的 66 项单元测试通过；文档构建通过。
- frontend lint、typecheck、生产 build 通过。852 项前端单测在无空格路径的源码副本通过；上游部分测试直接使用 URL.pathname，原含空格路径会产生 %20 路径错误。
- 43 项网页供应商单测通过，覆盖 Tavily 代理路径、默认官方地址、其他供应商不受影响，以及真实 search_web 用例的代理请求、鉴权和查询正文。去掉代理分支会使代理 URL 和请求断言失败。
- Linux 后端完整单测在独立 API 镜像通过：3389 passed、10 skipped。跳过项不计入通过；macOS 的 Linux renameat2 与系统依赖差异不用于生产验收结论。
- 旧生产 905 个 tracked 文件逐一校验，唯一差异为 Compose 的本机端口绑定；新版保留本机绑定策略。新版 2132 个 tracked 文件与服务器一致，镜像内 443 个后端源文件与候选提交一致。
- Compose 与挂载回读确认新环境不写入旧目录；API、worker 与 app-init 的品牌路径、Tavily 代理和独立存储地址正确。新旧站 HTTPS 均返回 200，新版 readiness 为 ready、degraded=false；管理员登录、Agent 列表和品牌接口通过。
- 实际模型请求经过 API、worker 完成；同一 Turn 回读包含预期 UPGRADE_SMOKE_OK。另一个 Run 实际调用 execute，在 container 沙箱计算 17×19 并写入 upgrade-check.txt，经 Viewer API 回读文件确认 323；知识库管理接口读取通过。浏览器实际首页展示公司 Logo、单位全名与工程协同首页。

本次不宣称旧数据迁移或已有业务知识库检索已完成。旧数据库备份通过 pg_restore 列表读取校验；它不替代全量对象存储备份或恢复演练。
