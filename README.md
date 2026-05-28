# GXIC Auto Checkin

广西工业职业技术学院课堂自动签到系统。自动扫描签到、回复学习资料、AI 答题，支持 Web 监控面板。

## 功能

- **自动签到** — 实时扫描课堂签到，随机延迟后自动提交
- **资料回复** — 自动回复学习资料（"收到"）
- **AI 答题** — 调用 DeepSeek API 自动完成测验/作业
- **手动补签** — 通过 Web 面板手动触发补签/补做
- **批量处理** — 一键处理所有待办项
- **自动续期** — Cookie 过期时自动重新登录
- **健康监控** — 连续失败自动恢复，错误日志去重

## 快速开始

### Docker 部署（推荐）

```bash
# 克隆仓库
git clone https://github.com/sssshj114/GXIC-auto-checkin.git
cd GXIC-auto-checkin

# 复制配置文件并填入真实值
cp data/.env.example data/.env
vim data/.env

# 启动
docker compose up -d
```

访问 `http://localhost:23891` 打开监控面板。

### 本地运行

```bash
pip install -r requirements.txt

# 复制配置文件
cp data/.env.example data/.env
# 编辑 data/.env 填入配置

# 设置 PYTHONPATH 并启动
set PYTHONPATH=src
python app.py
```

## 配置说明

在 `data/.env` 中配置（复制 `data/.env.example`）：

| 变量 | 必需 | 说明 |
|---|---|---|
| `COOKIE` | 是 | 浏览器 Cookie |
| `DEEPSEEK_API_KEY` | 是 | DeepSeek API 密钥（用于 AI 答题） |
| `UI_TOKEN` | 否 | Web 面板访问令牌，不设则仅允许本机访问 |
| `WEIXIN_ID` | 否 | 微信 OpenID（自动登录用） |
| `STUDENT_CODE` | 否 | 学号（自动登录用） |
| `LOGIN_PASSWORD` | 否 | 密码（自动登录用） |
| `BASE_URL` | 否 | 平台地址，默认 `https://gxic.itolearn.com` |
| `COOKIE_PERSIST_ENABLED` | 否 | 是否将刷新的 Cookie 回写 .env，默认 `false` |

### 可选调参

| 变量 | 默认值 | 说明 |
|---|---|---|
| `HIGH_ALERT_BEFORE` | 5 | 课前几分钟进入高频扫描 |
| `HIGH_ALERT_AFTER` | 20 | 课后几分钟保持高频扫描 |
| `FAST_SCAN_INTERVAL_MIN/MAX` | 12/20 | 高频扫描间隔（秒） |
| `SLOW_SCAN_INTERVAL_MIN/MAX` | 180/300 | 低频扫描间隔（秒） |
| `CHECKIN_DELAY_MIN/MAX` | 5/18 | 签到随机延迟（秒） |
| `MATERIAL_REPLY_DELAY_MIN/MAX` | 10/35 | 资料回复随机延迟（秒） |
| `EXAM_THINK_TIME_MIN/MAX` | 3/12 | 答题模拟思考时间（秒） |

## 项目结构

```
├── app.py                  # 入口文件
├── src/auto_checkin/       # 主包
│   ├── config.py           # 配置加载
│   ├── logger.py           # 日志（轮转 + 错误抑制）
│   ├── network.py          # HTTP 请求、重试、限流、DeepSeek API
│   ├── web.py              # Web 服务器和 REST API
│   ├── static/index.html   # 前端面板
│   └── core/
│       ├── scheduler.py    # 主循环调度
│       ├── checkin.py      # 签到扫描与提交
│       ├── material.py     # 资料扫描与回复
│       ├── exam.py         # AI 答题
│       ├── course.py       # 课表获取与解析
│       ├── session.py      # Cookie 管理与自动登录
│       ├── state.py        # 线程安全状态管理
│       ├── statistics.py   # 运行统计（持久化）
│       ├── health_check.py # 健康监控与自动恢复
│       └── scan_mode.py    # 扫描频率策略
├── tests/                  # 单元测试
├── data/                   # 运行时数据（gitignore）
└── docker-compose.yml
```

## Web API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 监控面板 |
| GET | `/health` | 健康检查 |
| GET | `/api/data` | 运行数据（课表、日志、课程状态） |
| GET | `/api/statistics` | 统计信息 |
| GET | `/api/checkin/history` | 补签历史 |
| GET | `/api/homework/scan?icid=xxx` | 扫描指定课程待办项 |
| GET | `/api/scan-all` | 扫描全部课程待办项 |
| POST | `/api/refresh` | 刷新课表 |
| POST | `/api/checkin/retro` | 手动补签 |
| POST | `/api/homework/submit` | 手动补做作业 |
| POST | `/api/material/reply` | 手动回复资料 |
| POST | `/api/process-all` | 批量处理待办项 |
| POST | `/api/statistics/reset` | 重置统计 |

API 需要 `Authorization: Bearer <UI_TOKEN>` 认证（未设置 `UI_TOKEN` 时仅允许本机访问）。

## 许可

仅供学习交流使用。
