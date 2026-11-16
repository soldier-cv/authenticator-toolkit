# Authenticator Toolkit — Agent 工作规约

## 0. 项目定位

Google Authenticator 导出数据解码与 TOTP 动态码生成 Web 工具，基于 Flask + 原生 JavaScript 实现。
- 仓库远程地址: `https://github.com/soldier-cv/authenticator-toolkit.git`
- 默认主分支: `main`
- 本地开发/体检仓库路径: `/opt/code/authenticator-toolkit-repo`
- 宿主机运行态目录: `/opt/code/authenticator-toolkit`

## 1. 运行环境事实

- 生产对外统一入口: `http://100.64.0.88:5080`（由 OpenResty 反向代理监听 5080 端口，配置归档在 `deploy/openresty/authenticator-toolkit.conf`，权威路径为 `/opt/1panel/www/conf.d/authenticator-toolkit.conf`；仅限 ZeroTier 网段 `100.64.0.0/10` 与本地回环访问）。
- 容器网络与端口: Docker 容器 `authenticator-toolkit` 内部监听 `5000` 端口，宿主机端口严格回环绑定至 `127.0.0.1:5081:5000`，不对任何外部网络接口裸奔。
- 凭据真源路径: 生产环境变量文件位于宿主机 `/home/xl/.hermes/.secrets/authenticator-toolkit.env`，由 `docker-compose.yml` 的 `env_file` 指令引入；禁止将明文凭据提交到代码仓库。
- 数据持久化路径: SQLite 数据库位于宿主机 `/data/authenticator-toolkit/usage.db`（容器内挂载至 `/data/usage.db`），仅用于记录 IP 每日访问限额计数，不持久化任何用户密钥。
- 生产探针验证: `curl -sI http://127.0.0.1:5081/health` 应返回 HTTP 200，响应体包含 `uptime_seconds` 与 `rate_limiter` 状态。

## 2. 硬规则

1. **访问鉴权强制 Fail-Closed（严禁无口令启动）**
   - 理由: 本工具涉及 2FA 核心密钥与迁移码解码，若无口令裸奔将造成灾难性凭证泄露。
   - 约束: 当 `TOTP_ACCESS_PASSWORD` 与 `TOTP_ACCESS_PASSWORD_HASH` 均未配置时，应用在加载期必须向 stderr 输出明确报错并抛出 `RuntimeError` 拒绝启动。
   - 验证方式: 运行 `TOTP_ACCESS_PASSWORD= TOTP_ACCESS_PASSWORD_HASH= uv run --with-requirements requirements.txt python3 -c 'import app'`，退出码必须非 0 且 stderr 必须包含 `fail-closed`。

2. **Secret 绝不落盘与日志化**
   - 理由: 用户提供的 Base32 Secret Key 与迁移码仅在内存中即时参与 HMAC 计算，离开会话必须立即丢弃。
   - 约束: 严禁在数据库写入 Secret，严禁在 application log / print / gunicorn 日志中打印 Secret。前端二维码直接在浏览器端基于 Canvas/SVG 生成，不将 Secret 发送至后端。
   - 验证方式: 运行 `git grep -in "secret" app.py`，确认所有命中仅限于内存解码与 `pyotp.TOTP` 计算，无任何文件写或日志调用。

3. **界面文案纪律（严禁堆砌需求说明）**
   - 理由: 遵循 §0.2 规范，需求背景与实现设计只写在代码注释与文档中，不上用户界面。
   - 约束: 页面 UI 仅展示功能名称、操作引导、输入表单与简明错误提示（发生了什么 + 怎么办）。
   - 验证方式: 运行 `grep -rnE '本功能实现|为了满足需求|根据.*要求' templates/`，输出必须为 0 命中。

4. **绝对禁止生产干扰与破坏操作**
   - 理由: 保护生产运行环境稳定，避免容器中断或状态漂移。
   - 约束: 本地开发与标准检查仅在 `/opt/code/authenticator-toolkit-repo` 中执行。严禁重启容器、严禁修改 `/opt/1panel` 与 `/data` 目录、严禁触发未授权 CI 构建、严禁直接创建或推送 git tag。
   - 验证方式: 运行 `docker ps --filter name=authenticator-toolkit` 确认容器未被重启，`git status` 确认当前处于仓库目录且无越权修改。

5. **凭据与私密文件零入库**
   - 理由: 防范密钥泄露到公开 GitHub 仓库。
   - 约束: `.gitignore` 必须阻断 `.env`、`*.pem`、`*.key`、`*.token` 与 `credentials.json`；`.env.example` 仅保留键名与中文注释。
   - 验证方式: 运行 `git ls-files | grep -E '\.env$|\.pem$|\.key$|\.token$|credentials\.json$'`，输出必须完全为空。

## 3. 开发与验证流程

1. **开工同步**: 每次工作前必须先拉取远端对齐基线：
   ```bash
   git fetch && git pull --ff-only origin main
   ```
2. **依赖要求**:
   - Python 3.11+ 运行环境；
   - 依赖清单以 `requirements.txt` 为准，特别注意 `pyotp` 必须约束为 `pyotp>=2.9.0,<2.11.0`。
3. **改动验证必跑命令**:
   - 自动化测试回归:
     ```bash
     TOTP_ACCESS_PASSWORD=test_auth_pwd_998 RATE_LIMIT_DB=/tmp/test_usage.db uv run --with pytest --with-requirements requirements.txt pytest
     ```
   - 凭据入库检查:
     ```bash
     git ls-files | grep -E '\.env$|\.pem$|\.key$|\.token$'
     ```
   - 规范检查脚本:
     ```bash
     bash /home/xl/.hermes/profiles/coding/skills/devops/project-repo-standards/scripts/audit_repo.sh /opt/code/authenticator-toolkit-repo
     ```

## 4. 已知坑

1. **PyOTP >= 2.11.0 破坏性升级**:
   - 现象: PyOTP 2.11+ 强制校验 NIST SP 800-63B 最小密钥长度（`< 112 bits / 14 bytes` 抛出 `ValueError`），而 Google Authenticator 大量主流服务导出 16 字符 Base32 密钥（仅 10 字节 / 80 bits），升级会导致 `/generate` 产生 500 异常。
   - 规避: `requirements.txt` 必须显式限制 `pyotp>=2.9.0,<2.11.0`。
2. **反向代理图片上传 413 错误**:
   - 现象: OpenResty 默认 `client_max_body_size` 为 1MB，用户上传较高分辨率的二维码截图时反代直接拦截返回 413 Request Entity Too Large。
   - 规避: 反向代理配置 `deploy/openresty/authenticator-toolkit.conf` 必须保持 `client_max_body_size 20m;` 与 Flask 容器 `MAX_CONTENT_LENGTH (16MB)` 对齐并留有余量。
3. **反向代理双重 Basic Auth 弹框**:
   - 现象: 若反向代理层配置了 `auth_basic`，会与 Flask 应用层的 Basic Auth 叠加导致用户需输入两次密码。
   - 规避: 反代层仅做 IP ACL 白名单控制（ZeroTier 与回环放行），鉴权统一收口在应用层（`Flask-HTTPAuth`）。
4. **测试环境 SQLite 路径权限**:
   - 现象: 默认 `RATE_LIMIT_DB=/data/usage.db`，非 root 用户在本地运行测试时对宿主 `/data` 目录无写入权限导致测试失败。
   - 规避: 本地执行 pytest 时必须显式指定 `RATE_LIMIT_DB=/tmp/test_usage.db`。

## 5. 需求台账 / 决策日志

- **2026-10-10**: 初始版本定型。支持 Google Authenticator migration payload protobuf 手工纯 Python 解码、图片识别与 Base32 / TOTP 生成。
- **2026-10-16**: 架构安全加固。引入 HTTP Basic Auth 访问鉴权与 fail-closed 拦截；端口收口至 `127.0.0.1:5081`；完善 `/health` 健康诊断端点。
- **2026-10-16**: 鉴权范围收敛。还原与鉴权无关的等价重构代码，保持 TOTP 算法层逐字节一致。
- **2026-11-16**: 反代配置归档。将生产 OpenResty 反向代理配置归档于 `deploy/openresty/authenticator-toolkit.conf`。
- **2026-11-16**: 仓库规范化改造。补齐 `.woodpecker.yml`、`AGENTS.md`、`.env.example`、`CHANGELOG.md`、`.editorconfig`、`.gitattributes` 与 `favicon.ico` 图标链；约束 pyotp 依赖版本防上游破坏性变更。
