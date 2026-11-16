# 变更日志 (CHANGELOG)

本项目遵循 [Semantic Versioning (SemVer 2.0.0)](https://semver.org/lang/zh-CN/) 语义化版本规范。

## [Unreleased]

### Added
- 补齐站点图标 `static/favicon.ico`、`static/favicon.svg` 与根路径 `favicon.ico`，并在 `templates/index.html` 与 `app.py` 中接入免鉴权路由。
- 补齐标准化仓库工程配置：`.editorconfig`、`.gitattributes`、`.gitignore` 强化。
- 补齐 `.env.example` 环境变量配置模板（无敏感信息，纯中文注释说明）。
- 补齐写实工作规约 `AGENTS.md`（环境事实、硬规则及可执行验证方式）。
- 补齐内网 CI 流水线 `.woodpecker.yml`（自动化测试与 Docker 镜像构建推送）。

### Changed
- 约束 `requirements.txt` 中 `pyotp>=2.9.0,<2.11.0`，规避上游 2.11+ 对 10 字节（80-bit）常用 Base32 密钥强行抛出 112-bit 截断异常的问题。
- 补充 `tests/test_basic_auth.py` 中对 `/favicon.ico` 免鉴权访问的状态码断言。

## [1.1.0] - 2026-10-16

### Added
- 引入 HTTP Basic Auth 应用层访问鉴权（基于 `Flask-HTTPAuth` 与 `werkzeug.security`）。
- 引入未配置口令时强制拒绝启动机制（Fail-Closed Enforcement）。
- 增强 `/health` 健康检查诊断端点，提供运行时间与限流器状态且不暴露敏感字段。
- 容器网络端口回环收口至 `127.0.0.1:5081:5000`，由宿主反向代理（OpenResty）统一对外提供 ZeroTier 内网访问。

### Changed
- 归档反向代理配置至 `deploy/openresty/authenticator-toolkit.conf`。

## [1.0.0] - 2026-10-10

### Added
- 基于 Flask 的 Material Design 3 风格 Web 交互界面。
- Google Authenticator 导出数据解码（支持二维码图片识别与 `otpauth-migration://` URI 解析）。
- 纯 Python Protobuf 手工解码实现，无需额外编译依赖。
- 基于 Secret Key 生成 TOTP 动态码，支持 SHA1/SHA256/SHA512/MD5 算法与 6/7/8 位数定制。
- 批量 TOTP 验证码生成接口与前端交互。
- 前端纯客户端生成 otpauth 二维码，保障密钥不二次上传。
- 基于 SQLite 的 IP 级每日速率限制器（RateLimiter）。
- Dockerfile 与 docker-compose.yml 容器化部署支持。
