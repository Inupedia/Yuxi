# Container 后端的请求级技能下载

状态：implemented
类型：bug-fix
Owner：backend/yuxi/sandbox_runner/skill_installer.py

## 问题

设置页远程技能安装没有活动 Run，无法调用只接受 Run 身份的 container executor；基础镜像也缺少 Node.js。禁网配置另外阻止图片生成等在线技能访问外部服务。

## 决策

### 实现方案

技能服务保留来源策略校验与安装草稿发布边界。container 后端通过认证 runner 的固定技能 CLI 接口获取文件，runner 独占容器创建、资源限制和删除；请求容器不挂载用户文件、不注入模型凭据，不进入 Agent Run 的 orphan 集合。CLI 参数限制为查询、列出与指定技能复制；文件导出拒绝链接、特殊文件、越界路径，并限制总大小和条目。正常请求 finally 删除容器；超时、崩溃由独立标签和期限兜底回收。

镜像预置固定版本 skills CLI 与 Node/npm。联网继续由部署配置显式选择 bridge，仓库默认 none 保留。

## 替代方案

- 将技能请求伪装成 Agent Run：污染 Run、租约与用户消息语义，不采用。
- 在 API 内执行 CLI 或挂 Docker socket：扩大业务进程权限，不采用。
- 改用 Cube：要求额外的 KVM 执行节点，不能作为现有 container 部署的局部修复。

## 验证

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 无 Run 可准备技能草稿 | 请求与容器执行 | remote.py / skill_installer.py | 真实 HTTP 准备与回读 SKILL.md | 不存在的技能、来源失败 | Passed |
| 下载不能写用户目录 | 文件与挂载边界 | skill_installer.py / remote.py | Docker inspect 与路径测试 | 路径穿越、链接、命令参数注入 | Passed |
| 容器必回收 | 失败、取消与崩溃 | skill_installer.py | 请求后 Docker 标签查询 | 超时后无残留 | Passed |
| 在线图片接口可达 | DNS/TLS | 部署 network 设置 | 真实沙盒请求及产物读取 | 禁网复现失败 | Passed |

## 后果

bridge 增加沙盒外网访问面；业务数据库凭据不注入沙盒。下载容器有独立四请求上限及内存、CPU、PID、临时磁盘和执行期限。技能安装成功不等于技能所要求的所有文档工具链已预装，具体依赖仍按技能说明验证。

相关后端测试 105 项通过。Linux 镜像内全量非 slow unit 为 3301 passed、122 skipped；跳过项由各测试自身依赖条件控制。真实 HTTP 从推荐来源准备 4 项草稿、确认个人安装后逐项回读 SKILL.md，随后删除测试安装；不存在的技能返回逐项失败，下载容器无残留。Docker inspect 证明下载容器 UID 1000、无挂载、只读根、cap-drop ALL、bridge 和 1 GiB 内存限制。真实 Agent 会话调用 Qwen-Image 并登记 PNG，直接回读产物验证为 1328 × 1328，PNG 解码成功。
