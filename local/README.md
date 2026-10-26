# 引大济岷定制与新版并行部署

上游基线为 `upstream/main` 的 `a5ac16dd`（0.8.0.beta3）。品牌路由、首页、登录页、CLI 授权页、主题和场景代码在 `frontend/src/custom/inupedia/`；单位配置为 `backend/yuxi/modules/system/static/info.inupedia.yaml`，由部署变量 `YUXI_BRAND_FILE_PATH` 指定。Tavily 代理继续使用 `TAVILY_API_BASE`，同时覆盖搜索和正文抓取。

## 生产隔离

旧站位于 `/home/ubuntu/Yuxi`，继续服务 `knowledge.ai.swhisxy.cn`；Spotlight 保持连接旧接口。新版位于 `/home/ubuntu/Yuxi-0.8-preview`，独立 Compose 项目 `yuxi08`、`.env.prod`、端口、凭据、网络和 `.yuxi/state`。预览域名为 `knowledge-next.ai.swhisxy.cn`，验收前不修改旧域名。

0.8 不支持旧数据库、索引、文件和 checkpoint 自动迁移。不要把旧 `.env` 或数据目录直接交给新版。旧 PostgreSQL 和源码配置备份保存在服务器 `/home/ubuntu/yuxi-before-upgrade-20261026/`；旧对象、索引和用户文件仍由原部署持有，该备份不等于全量对象存储快照。

新部署使用 `container` 执行后端。创建独立 `.env.prod` 并填写上游生产 Compose 的必填配置；配置 `COMPOSE_PROJECT_NAME=yuxi08`、独立 `YUXI_STATE_DIR` 和端口（当前 frontend 为 `18180`、API 为 `16050`）。模型/搜索凭据按需配置，禁止继承旧存储连接地址。环境文件仅保存在服务器，不提交到 Git。

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml -f local/compose.preview.yml --profile container config --quiet
docker compose --env-file .env.prod -f docker-compose.prod.yml -f local/compose.preview.yml --profile container build api frontend minio storage-init sandbox-image
```

构建沙箱后，把 `docker image inspect yuxi08-sandbox:0.8.0.beta3 --format '{{.Id}}'` 的结果填写为 `SANDBOX_CONTAINER_IMAGE_DIGEST`。先保持 `YUXI_PREVIEW_PUBLIC=false`，启动完整栈并通过本机 API 初始化管理员，再配置 `YUXI_PREVIEW_PUBLIC=true` 重建 frontend 容器启用预览域名。不要在公网开放尚未初始化的实例。

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml -f local/compose.preview.yml --profile container up -d --no-build
docker compose --env-file .env.prod -f docker-compose.prod.yml -f local/compose.preview.yml --profile container ps -a
curl --fail http://127.0.0.1:16050/api/system/ready
```

本组合使用生产 Nginx frontend，服务端口为 80；旧开发 Vite 的 5173 路由标签不能直接复用。停止新版时使用相同项目配置执行 `down`，不加 `-v`；原部署保持运行。正式切换及旧业务数据迁移需要单独验收。

预览管理员凭据保存在服务器 `.yuxi/preview-admin.private`，仅授权管理员可读；不提交、不写入构建上下文。
