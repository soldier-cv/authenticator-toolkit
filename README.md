# Authenticator Toolkit

> **Note:** This project and I are in no way affiliated with Google.

Google Authenticator 数据解码与 TOTP 动态码生成工具，基于 Flask 的 Web UI。

## 功能特性

| 功能 | 说明 |
|------|------|
| 🖥️ **Web 界面** | 基于 Flask 的现代化 Web UI，浏览器直接访问 |
| 📷 **图片上传** | 直接上传二维码图片（支持 PNG/JPG，最大 16MB） |
| 📋 **URI 粘贴** | 粘贴 `otpauth-migration://offline?data=...` URI |
| ⌨️ **全局 Ctrl+V** | 页面任意位置粘贴，自动识别图片/文本并切换 Tab |
| 🔌 **REST API** | `POST /decode` 和 `POST /generate` 接口，支持程序化调用 |
| 🔑 **TOTP 生成** | 根据 Secret Key 生成 TOTP 动态验证码 |
| 🐳 **Docker 部署** | docker-compose 一键部署，支持挂载目录 |
| 🐍 **纯 Python** | 手动解码 protobuf，无需安装 grpcio-tools |
| 🎨 **莫兰迪色系 UI** | Material Design 3 风格，柔和自然色调 |
| 🌐 **中文界面** | 全中文化 Web 界面 |
| 🛡️ **速率限制** | IP 级限流（每天50次），SQLite 存储 |
| 📊 **用量统计** | 自动记录每个 IP 的请求次数，跨天自动清零 |

## 快速开始

```bash
# Docker 部署
docker compose up -d --build

# 访问 http://localhost:5080
```

### 手动运行

```bash
pip install -r requirements.txt
python app.py
```

## API 使用

### 解码 Google Authenticator 导出数据

```bash
# 通过 URI 解码
curl -X POST http://localhost:5080/decode \
  -F "uri=otpauth-migration://offline?data=CiIKCkhlbGwP..."

# 通过图片解码
curl -X POST http://localhost:5080/decode \
  -F "file=@qrcode.png"
```

### 生成 TOTP 动态码

```bash
# 使用默认参数（SHA1, 6位, 30秒）
curl -X POST http://localhost:5080/generate \
  -H "Content-Type: application/json" \
  -d '{"secret": "JBSWY3DPEHPK3PXP"}'

# 使用自定义参数
curl -X POST http://localhost:5080/generate \
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

## 部署结构

```
/opt/code/authenticator-toolkit/   # 项目代码
/data/authenticator-toolkit/       # 挂载目录（SQLite 数据等）
```

## 配置项

通过环境变量配置（可在 docker-compose.yml 或 .env 文件中设置）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | 5000 | 服务端口 |
| `RATE_LIMIT_DAILY` | 50 | 每日请求上限 |
| `RATE_LIMIT_DB` | /data/usage.db | SQLite 数据库路径 |

## References

- Protobuf 定义来自 [Aegis](https://github.com/beemdevelopment/Aegis/pull/406/files)
- Base32 格式规范: [RFC 3548](https://tools.ietf.org/html/rfc3548)

## License

MIT
