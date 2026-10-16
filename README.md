# Authenticator Toolkit

> **Note:** This project and I are in no way affiliated with Google.

Google Authenticator 数据解码与 TOTP 动态码生成工具，基于 Flask 的 Web UI。

## 功能特性

| 功能 | 说明 |
|------|------|
| 🖥️ **Web 界面** | 基于 Flask 的现代化 Web UI，浏览器直接访问 |
| 🔒 **访问鉴权** | HTTP Basic Auth 应用层鉴权，未配置口令拒绝启动（fail-closed） |
| 📷 **图片上传** | 直接上传二维码图片（支持 PNG/JPG，最大 16MB） |
| 📋 **URI 粘贴** | 粘贴 `otpauth-migration://offline?data=...` URI |
| ⌨️ **全局 Ctrl+V** | 页面任意位置粘贴，自动识别图片/文本并切换 Tab |
| 🔌 **REST API** | `POST /decode`、`POST /generate`、`POST /generate/batch` 接口 |
| 🔑 **TOTP 生成** | 根据 Secret Key 生成 TOTP 动态验证码，支持倒计时和自动刷新 |
| 📦 **批量生成** | 批量生成多个 Secret 的动态码，一次性验证多个账户 |
| 📱 **二维码生成** | 前端生成 otpauth 二维码，可下载导入其他验证器 |
| 🐳 **Docker 部署** | docker-compose 一键部署，支持挂载目录 |
| 🐍 **纯 Python** | 手动解码 protobuf，无需安装 grpcio-tools |
| 🎨 **莫兰迪色系 UI** | Material Design 3 风格，柔和自然色调 |
| 🌐 **中文界面** | 全中文化 Web 界面 |
| 🛡️ **速率限制** | IP 级限流（每天50次），SQLite 存储 |
| 📊 **用量统计** | 自动记录每个 IP 的请求次数，跨天自动清零 |

## 安全原则

- **不在后端存储用户的 Secret** — Secret 仅在请求时用于计算，不写入任何数据库或文件
- **Secret 不记录日志** — 所有计算在服务端完成后立即丢弃 Secret
- **二维码在前端生成** — 生成二维码时 Secret 不发送到后端
- **强制访问鉴权（Fail-Closed）** — 未配置口令时容器进程直接拒绝启动，不接受静默放行

## 访问鉴权与安全机制

### 1. 鉴权机制与路由保护
- 系统采用成熟的 HTTP Basic Auth（RFC 7617）标准协议，使用 `Flask-HTTPAuth` 与 `werkzeug.security` 实现常量时间口令哈希校验。
- 受保护路由：`/`（Web 界面）、`/decode`（解码）、`/generate`（生成动态码）、`/generate/batch`（批量生成）。
- 免鉴权路由：`/health`（健康检查），响应体仅包含运行状态与限流器统计，不包含任何密钥与敏感字段。
- 错误响应：未提供凭证或凭证错误均返回 HTTP 401 及标准 `WWW-Authenticate: Basic realm="Authenticator Toolkit"` 响应头，且两者返回的 JSON 响应体完全一致，无法通过响应推断用户名是否存在。

### 2. Fail-Closed 启动拦截
若环境变量中既未配置 `TOTP_ACCESS_PASSWORD` 也未配置 `TOTP_ACCESS_PASSWORD_HASH`，应用在导入启动阶段将立即输出明确错误信息至 stderr 并抛出 `RuntimeError` 拒绝启动。容器将无法正常启动且健康检查持续失败，防止因配置疏漏导致服务无鉴权暴露。

### 3. 网络层收口与端口映射
- 容器端口仅绑定宿主机本地回环地址 **`127.0.0.1:5081:5000`**，阻断来自外部网络的直连绕过风险。
- 宿主机 5080 端口保留给反向代理服务监听，用户对外统一访问入口为 **`http://100.64.0.88:5080`**。

### 4. 手机浏览器访问说明
使用手机浏览器（Safari / Chrome / Edge 等）访问 `http://100.64.0.88:5080` 时，浏览器会自动弹出系统原生 HTTP Basic 认证对话框。输入配置的用户名（默认 `admin`）与访问口令确认后，即可无缝进入 Web 界面使用所有功能。

### 5. 口令轮换步骤
当需要修改或轮换访问口令时，操作步骤如下：
1. 编辑宿主机密钥配置文件（如 `/home/xl/.hermes/.secrets/authenticator-toolkit.env`），修改 `TOTP_ACCESS_PASSWORD` 或更新为新的哈希值；
2. 在项目目录下执行以下命令重新加载环境变量并重启容器：
   ```bash
   docker compose up -d
   ```
3. 容器重启后新口令立即生效，无需重新构建镜像。

### 6. Basic Auth 在非 HTTPS 下的风险与缓解
- **潜在风险**：HTTP Basic Auth 凭证在传输过程中以 Base64 编码存放于 `Authorization` 请求头中，Base64 为可逆编码而非加密。若直接暴露在明文公网环境中，存在被中间人（MITM）嗅探与凭证劫持的风险。
- **缓解与防护设计**：
  1. **本地回环收口**：业务容器仅绑定 `127.0.0.1:5081`，外部任何未授权流量无法直接探测或连接后端容器；
  2. **ZeroTier 底层全链路加密**：对外入口 `http://100.64.0.88:5080` 属于 ZeroTier 虚拟专用网络，节点间所有物理网络流量均经过 256 位端到端强加密（Salsa20/Poly1305），公网运营商及链路路由节点无法嗅探解密；
  3. **反代与隧道承担 TLS**：若后续需通过公网域名提供服务，应由宿主机反向代理（Nginx / OpenResty）或隧道服务（如 Cloudflare Tunnel）负责 TLS 卸载与证书管理，应用层与反代层职责分离，避免单点脆弱。

## 快速开始

```bash
# Docker 部署（端口绑定 127.0.0.1:5081:5000，密钥来自 env_file）
docker compose up -d --build

# 对外统一入口（通过反向代理）
# http://100.64.0.88:5080
```

### 手动运行

```bash
pip install -r requirements.txt
export TOTP_ACCESS_USER=admin
export TOTP_ACCESS_PASSWORD="your_password_here"
python app.py
```

## API 使用

> **提示**：所有 API 请求均需携带 Basic Auth 凭证（使用 `-u "username:password"` 或添加 `Authorization: Basic <base64>` 请求头）。

### 解码 Google Authenticator 导出数据

```bash
# 通过 URI 解码
curl -u "admin:your_password_here" -X POST http://100.64.0.88:5080/decode \
  -F "uri=otpauth-migration://offline?data=CiIKCkhlbGwP..."

# 通过图片解码
curl -u "admin:your_password_here" -X POST http://100.64.0.88:5080/decode \
  -F "file=@qrcode.png"
```

#### 响应示例

```json
{
  "accounts": [
    {
      "name": "alice@example.com",
      "issuer": "Google",
      "secret_base32": "JBSWY3DPEHPK3PXP",
      "algorithm": "SHA1",
      "digits": 6,
      "type": "TOTP"
    }
  ]
}
```

### 生成单个 TOTP 动态码

```bash
# 使用默认参数（SHA1, 6位, 30秒）
curl -u "admin:your_password_here" -X POST http://100.64.0.88:5080/generate \
  -H "Content-Type: application/json" \
  -d '{"secret": "JBSWY3DPEHPK3PXP"}'

# 使用自定义参数
curl -u "admin:your_password_here" -X POST http://100.64.0.88:5080/generate \
  -H "Content-Type: application/json" \
  -d '{
    "secret": "JBSWY3DPEHPK3PXP",
    "algorithm": "SHA256",
    "digits": 8,
    "period": 60
  }'
```

#### 请求参数

| 参数 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| `secret` | string | 是 | - | Base32 编码的 Secret Key |
| `algorithm` | string | 否 | SHA1 | 算法：SHA1, SHA256, SHA512, MD5 |
| `digits` | integer | 否 | 6 | 验证码位数：6, 7, 8 |
| `period` | integer | 否 | 30 | 有效期（秒）：1-300 |

#### 响应示例

```json
{
  "code": "123456",
  "algorithm": "SHA1",
  "digits": 6,
  "period": 30,
  "remaining_seconds": 25,
  "remaining_percent": 83.3
}
```

### 批量生成 TOTP 动态码

一次请求生成多个 Secret 的动态码，批量请求只计一次速率限制。

```bash
curl -u "admin:your_password_here" -X POST http://100.64.0.88:5080/generate/batch \
  -H "Content-Type: application/json" \
  -d '{
    "items": [
      {"secret": "JBSWY3DPEHPK3PXP"},
      {"secret": "GEZDGNBVGY3TQOJQ", "algorithm": "SHA256", "digits": 8},
      {"secret": "INVALID_KEY"}
    ]
  }'
```

#### 请求参数

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `items` | array | 是 | Secret 列表，最多 20 个 |
| `items[].secret` | string | 是 | Base32 编码的 Secret Key |
| `items[].algorithm` | string | 否 | 算法，默认 SHA1 |
| `items[].digits` | integer | 否 | 位数，默认 6 |
| `items[].period` | integer | 否 | 周期（秒），默认 30 |

#### 响应示例

```json
{
  "results": [
    {
      "index": 0,
      "code": "123456",
      "algorithm": "SHA1",
      "digits": 6,
      "period": 30,
      "remaining_seconds": 25,
      "remaining_percent": 83.3
    },
    {
      "index": 1,
      "code": "12345678",
      "algorithm": "SHA256",
      "digits": 8,
      "period": 30,
      "remaining_seconds": 18,
      "remaining_percent": 60.0
    },
    {
      "index": 2,
      "error": "Invalid secret key format (must be base32 encoded)"
    }
  ]
}
```

### 错误码说明

| HTTP 状态码 | 说明 |
|------------|------|
| `200` | 成功 |
| `400` | 请求参数错误（缺少参数、格式无效等） |
| `401` | 未提供鉴权凭证或凭证错误（WWW-Authenticate: Basic） |
| `429` | 超出速率限制，响应中包含 `retry_after` 字段 |
| `500` | 服务器内部错误 |

#### 错误响应格式

```json
{
  "error": "错误描述信息"
}
```

速率限制错误：

```json
{
  "error": "Daily limit reached (50/day)",
  "limits": {"daily": "50/50"},
  "retry_after": "tomorrow"
}
```

## 部署结构

```
/opt/code/authenticator-toolkit/   # 项目代码
/data/authenticator-toolkit/       # 挂载目录（SQLite 数据等）
```

## 配置项

通过环境变量配置（可在 docker-compose.yml、env_file 或宿主环境中设置）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | 5000 | 服务端口 |
| `TOTP_ACCESS_USER` | `admin` | HTTP Basic Auth 用户名（strip 为空则回退 admin） |
| `TOTP_ACCESS_PASSWORD` | - | HTTP Basic Auth 访问口令（无默认值，未配置则拒绝启动） |
| `TOTP_ACCESS_PASSWORD_HASH` | - | HTTP Basic Auth 访问口令哈希（可选，werkzeug 格式） |
| `RATE_LIMIT_DAILY` | 50 | 每日请求上限 |
| `RATE_LIMIT_DB` | /data/usage.db | SQLite 数据库路径 |

## References

- Protobuf 定义来自 [Aegis](https://github.com/beemdevelopment/Aegis/pull/406/files)
- Base32 格式规范: [RFC 3548](https://tools.ietf.org/html/rfc3548)
- HTTP 基础认证规范: [RFC 7617](https://tools.ietf.org/html/rfc7617)

## License

MIT
