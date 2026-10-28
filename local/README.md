# 引大济岷定制与部署

上游基线为 `upstream/main` 的 `4889c339`（0.8.0.beta4）。品牌路由、首页、登录页、CLI 授权页、主题和场景代码位于 `frontend/src/custom/inupedia/`；单位配置为 `backend/yuxi/modules/system/static/info.inupedia.yaml`，由 `YUXI_BRAND_FILE_PATH` 指定。Tavily 代理继续使用 `TAVILY_API_BASE`，覆盖搜索和正文抓取。容器沙盒镜像包含 Node/npm 和固定版本 Skills CLI。

## 环境与入口

| 环境 | 源码目录 | Compose project | 入口 |
|---|---|---|---|
| prod | `/home/ubuntu/Yuxi-0.8-preview` | `yuxi08` | `https://knowledge.ai.swhisxy.cn`；预览域名指向同一实例 |
| local | `/srv/data/ydjm-dev/Yuxi` | `yuxilocal08` | `http://10.20.148.209:5173`；API 端口 5050 |

两套环境分别持有自己的 `.env.prod`、服务密钥、网络和 `.yuxi/state`，不得跨环境复制生产凭据或存储连接。prod 保留已有业务库、对象、索引、用户与自定义 Agent/MCP。local 的 0.7.2 运行数据按用户选择清理，保留原登录账号、密码哈希与模型配置，旧状态仅保留冷备份。

0.8 不支持旧数据库、索引、文件和 checkpoint 自动迁移。不得把旧数据库直接交给新版初始化器；不兼容版本需独立状态目录。升级前停止应用写入并备份整套状态；冷备份位于各服务器部署目录之外，仅授权管理员可读。

## prod 的双域名叠加配置

`local/compose.preview.yml` 的文件名沿用部署历史。设置 `YUXI_PREVIEW_PUBLIC=true` 会同时注册正式域名 `knowledge.ai.swhisxy.cn` 与预览域名 `knowledge-next.ai.swhisxy.cn`，两者服务于同一实例。它不是独立预览环境模板，不能在另一套实例上启用该配置来竞争现有路由。

在部署目录准备独立 `.env.prod`，填写上游生产 Compose 的必填项，使用 `COMPOSE_PROJECT_NAME=yuxi08`、`YUXI_API_PORT=16050`、`YUXI_FRONTEND_PORT=18180`。`YUXI_VERSION` 和 `SANDBOX_CONTAINER_IMAGE` 必须指向已构建的 beta4 定制镜像。在线技能需要 `SANDBOX_CONTAINER_NETWORK=bridge`；镜像 digest 由 daemon 的实际 `.Id` 固定。

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml -f local/compose.preview.yml --profile container config --quiet
docker compose --env-file .env.prod -f docker-compose.prod.yml -f local/compose.preview.yml --profile container build api frontend minio storage-init sandbox-image
docker image inspect yuxi08-sandbox:0.8.0.beta4-inupedia-20261028 --format '{{.Id}}'
```

把上述镜像 ID 填入 `SANDBOX_CONTAINER_IMAGE_DIGEST`。新建环境先保持 `YUXI_PREVIEW_PUBLIC=false`，完成初始化和私网验收后再启用两个域名；现有实例升级前检查活动 Run，保留 `.env.prod` 与部署叠加配置。

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml -f local/compose.preview.yml --profile container up -d --no-build
docker compose --env-file .env.prod -f docker-compose.prod.yml -f local/compose.preview.yml --profile container ps -a
curl --fail http://127.0.0.1:16050/api/system/ready
curl --fail https://knowledge.ai.swhisxy.cn/api/system/ready
```

Nginx 静态 upstream 会缓存 API 容器地址。若 API 换 IP 且 frontend 未重建，在 API 就绪后使用相同 Compose 参数执行 `exec frontend nginx -s reload`，并检查公网 readiness。容器 liveness 和宿主回环就绪不能替代公网入口验收。

local 使用该服务器的 `local/compose.local.yml` 叠加配置，分别开放 5173/5050，不注册生产域名。Spotlight 接入本环境网络，使用仅有 knowledge 权限的 API Key。管理员凭据、API Key 和恢复备份仅保存在对应服务器私有目录，不提交、不放入构建上下文。停止实例使用相同配置执行 `down`，保留数据时不加 `-v`。
