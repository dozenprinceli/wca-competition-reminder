<h1 align="center">WCA 比赛项目提醒</h1>

<p align="center">
  为 WCA 新公示比赛发送个性化邮件提醒。
</p>

<p align="center">
  <a href="README.md">English</a>
</p>

---

WCA 比赛项目提醒会定时查询 WCA 官方 API，并根据每位收件人的项目和地域偏好，为新公示的比赛发送个性化邮件。邮件包含比赛日期和地点；填写收件人坐标时会计算直线距离，未填写时距离显示为 `-`。

## 功能亮点

- 支持全部 17 个 WCA 官方项目。
- 每位收件人可配置最多 10 条关注条件；每条独立设置项目、国家/地区、大洲、位置和可选距离，任一条完整命中即可推送。
- 根据 WCA 坐标在本地计算大圆距离；距离计算本身不需要地图 API，浏览器地图选点为可选增强功能。
- 使用 SQLite 持久化比赛与邮件状态，并自动重试临时失败。
- 首次运行建立静默基线，不会为已有比赛集中补发提醒。
- 支持单次轮询，也可通过 PM2 以每分钟一次的频率常驻运行。
- 邮件通知和注册验证码支持中文、英文和日文，模板保存在本地 `config/email_templates.toml`，可直接修改文案。
- 提供浏览器订阅台，可注册、查询、修改和取消邮件提醒。
- 提供带多管理员验证的只读运维控制台，可查看运行状态和业务数据。
- 将用户及管理员操作写入可查询的结构化审计日志，并滚动保留最近 7 天。

## 环境要求

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- 支持 STARTTLS（通常为 `587` 端口）或隐式 TLS（通常为 `465` 端口）的 SMTP 账户
- 可选：用于地图选点的 Google Maps Platform 与高德地图 Web（JS API）凭据
- 使用下文生产部署方案时，还需要 Node.js 和 [PM2](https://pm2.keymetrics.io/)

## 快速开始

### 1. 安装依赖

```bash
uv sync --frozen --group dev --python 3.12
cp config.example.toml config.toml
```

Windows 请用 `Copy-Item config.example.toml config.toml` 代替 `cp`。Linux 和 macOS 的虚拟环境解释器路径为 `.venv/bin/python`，Windows 为 `.venv\Scripts\python.exe`。

### 2. 配置应用

编辑 `config.toml`，至少完成以下配置：

1. 将 `wca.user_agent` 中的联系邮箱改为 WCA 能够联系到的真实地址。
2. 设置 SMTP 主机、端口、加密方式、用户名和发件地址。
3. 按需添加由 TOML 管理的 `[[recipients]]` 收件人；如果全部通过浏览器订阅台管理，可以省略。
4. 至少添加一个 `[[admins]]` 管理员，并设置唯一的强密码。
5. 如需在订阅台使用地图选点，在 `[web]` 中配置 Google 地图和/或高德地图。

所有可用配置项见 [`config.example.toml`](config.example.toml)。

```toml
[web]
google_maps_api_key = "your-browser-api-key"
amap_api_key = "your-amap-web-key"
amap_service_host = "/_AMapService"
# 本地开发时可改用下列配置（不能与 amap_service_host 同时设置）：
# amap_security_js_code = "your-amap-security-code"

[[admins]]
username = "admin"
password = "replace-with-a-strong-admin-password"

[[recipients]]
name = "Example recipient"
email = "recipient@example.com"
notification_language = "zh" # zh、en 或 ja；省略时为中文

[[recipients.conditions]]
latitude = 31.2304
longitude = 121.4737
max_distance_km = 300
events = "333,minx,pyram"
countries = ["China", "Hong Kong, China"]
continents = ["Asia"]

[[recipients.conditions]]
events = "minx"
continents = ["Europe"]
```

新格式的 TOML 收件人可包含 1 至 10 个 `[[recipients.conditions]]`。当前版本原有的收件人顶层筛选字段仍会作为单条条件读取，但不能与嵌套条件混用。每条条件的经纬度都是可选项：必须同时填写或同时省略。设置正数
`max_distance_km` 后，只接收大圆距离不超过该公里数的比赛，此时经纬度必填；省略坐标时邮件中的距离显示为 `-`。

`email_templates_path` 指向本地邮件模板 TOML，默认为 `config/email_templates.toml`（相对于
`config.toml`）。模板包含通知邮件和注册验证码的中、英、日三种标题、纯文本正文和 HTML 正文，
修改后下次启动/发送时生效。TOML 管理的收件人可以用 `notification_language` 指定 `zh`、`en`
或 `ja`，省略时使用中文。

### 3. 提供 SMTP 密码

在交互式 Shell 中，可以使用 `smtp.password_env` 指定的环境变量（默认为 `WCA_REMINDER_SMTP_PASSWORD`）：

```bash
export WCA_REMINDER_SMTP_PASSWORD='your-app-password'
```

不要把 SMTP 密码写入 `config.toml` 或提交到 Git。应用会按以下优先级读取 SMTP 密码：

1. `--smtp-password-file PATH` 指定的文件
2. 配置的环境变量
3. 名为 `smtp_password` 的 systemd credential

### 4. 验证并测试

```bash
.venv/bin/python -m wca_competition_reminder --config config.toml check-config
.venv/bin/python -m wca_competition_reminder --config config.toml send-test
.venv/bin/python -m wca_competition_reminder --config config.toml poll
```

`check-config` 不会读取 SMTP 密码、访问网络或发送邮件。`send-test` 会向每位收件人各发送一封测试邮件。第一次成功执行 `poll` 时，程序只会把已有的未来比赛记录为静默基线；只有基线建立后新公示的比赛才可能产生提醒。

## 浏览器订阅台

订阅台需要使用现有 SMTP 配置发送注册验证码，请与轮询服务同时启动：

```bash
.venv/bin/python -m wca_competition_reminder \
  --config config.toml \
  --smtp-password-file smtp_password \
  web --host 127.0.0.1 --port 8080
```

打开 `http://127.0.0.1:8080/`。注册时必须填写邮箱、称呼和 6 位邮箱验证码，并勾选同意接收 WCA 比赛通知邮件；同时可以选择通知邮件语言，默认跟随当前界面语言。该选择会保存到订阅，修改时可以重新选择。每个订阅可配置 1 至 10 条关注条件，每条分别包含经纬度、最远距离、项目和地区；条件内的已配置筛选同时满足才算命中，任意一条条件命中即推送。验证码 5 分钟失效，同一邮箱每 50 秒最多发送一次，浏览器按钮会倒计时 60 秒。邮箱是订阅的唯一 ID，查询、修改和取消均不使用令牌。修改时页面会载入完整条件列表；取消时只需邮箱。最远距离必须为正数，设置时该条件的经纬度必填。取消后，该邮箱尚未发送的排队通知也会停止。

经纬度区域会使用已配置的地图服务回填 6 位小数坐标。两套服务均可用时，页面先依据浏览器明确声明的地区和时区给出即时选择，再通过高德 `Geolocation.getCityInfo()` 进行无需定位权限的 IP 城市校验：检测为中国大陆时按钮显示“从高德地图选择”，其他地区显示 Google 地图。IP 检测失败时保留浏览器地区判定；只配置一套服务时直接使用该服务。

Google 地图需要启用 [Maps JavaScript API](https://developers.google.com/maps/documentation/javascript/cloud-setup)，并按部署域名设置 [HTTP referrer 限制和 API 限制](https://developers.google.com/maps/api-security-best-practices)。高德地图需要申请 Web（JS API）key，并参考官方的 [JS API Loader 2.0 加载说明](https://lbs.amap.com/api/javascript-api-v2/guide/abc/load)与[安全密钥说明](https://lbs.amap.com/api/javascript-api-v2/guide/abc/jscode)。生产环境应由同源反向代理保存 `securityJsCode`，并将其固定路径（例如 `/_AMapService`）配置为 `amap_service_host`。`amap_security_js_code` 仅作为本地开发的明文模式，会发送到浏览器；两种安全模式不能同时设置。

高德在中国大陆使用 GCJ-02。页面展示已有 WGS84 表单坐标时调用高德官方 `convertFrom(..., "gps")` 转换，点击所得的 GCJ-02 坐标则在写入前反算回现有坐标约定，以保持距离计算语义一致。

国家、大洲选项由服务端的 `/api/options` 接口从 WCA 目录载入并缓存 6 小时。通过反向代理公开服务时，建议 Web 服务仍只监听本机地址，并在代理层终止 HTTPS。

反向代理必须覆盖客户端转发请求头，行为日志和管理员登录限流才能记录公网客户端地址，而不是 `127.0.0.1`。Nginx 配置中应包含：

```nginx
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-Proto $scheme;
```

Web 服务仅在直接连接来自本机回环地址时接受这些 IP 请求头，并使用最右侧的 `X-Forwarded-For` 地址，以 `X-Real-IP` 作为后备。因此应保持服务仅监听本机地址，并由最近一层代理覆盖或追加这些请求头。

### 管理控制台

打开 `http://127.0.0.1:8080/admin`，使用 `config.toml` 中任意一组
`[[admins]]` 用户名和密码登录。控制台包含运行检查点、订阅用户、比赛、邮件投递和最近 7 天的用户行为日志；日志页支持按主体、行为、结果筛选，搜索邮箱、IP 与详情，并分页读取更早记录。当前页面为只读，不会修改业务状态。登录成功后使用服务端生成的 HttpOnly、SameSite 会话 Cookie，会话 8 小时后过期，服务重启也会使其立即失效。公开部署时必须通过 HTTPS 访问，并将 `config.toml` 权限限制为仅运行账户可读。

可以配置多个管理员，用户名不能重复：

```toml
[[admins]]
username = "operator"
password = "a-unique-strong-password"

[[admins]]
username = "auditor"
password = "another-unique-strong-password"
```

schema v6 会在启动时使用事务自动迁移当前生产版本的 v5 SQLite 状态库，并新增订阅的通知语言字段。旧订阅没有语言选择时统一按中文通知；原有的经纬度、最远距离、项目、国家/地区和大洲保持不变，无需删库或重新建立基线。v4 及更早版本的结构不再自动升级。

## 收件人筛选

### 比赛项目

`events` 是使用逗号分隔的 WCA 项目 ID。留空或省略时表示订阅全部官方项目。

```text
333, 222, 444, 555, 666, 777, 333bf, 333fm, 333oh,
clock, minx, pyram, skewb, sq1, 444bf, 555bf, 333mbf
```

### 地域

`countries` 和 `continents` 都是 TOML 字符串数组：

- 国家/地区必须与 WCA 官方英文显示名完全一致，可通过 [WCA countries API](https://www.worldcubeassociation.org/api/v0/countries) 查询。
- 大洲可选值为 `Africa`、`Asia`、`Europe`、`North America`、`Oceania`、`South America` 和 `Multiple Continents`。
- 两个数组均留空或省略时，匹配全部地区。
- 任意数组包含值时，比赛的国家/地区或大洲命中其中任意一项即可通过地域筛选。

### 距离

`max_distance_km` 是可选的正数。设置后必须同时提供 `latitude` 和 `longitude`，只有本地计算的大圆距离小于或等于该公里数的比赛才会命中。如果比赛坐标在正常重试期限后仍不可用，带距离限制的收件人会被跳过；未设置距离限制的收件人仍按原有降级逻辑收到通知。

### 多条件组合

每位收件人包含 1 至 10 条有序关注条件。单条条件内的项目、地域和距离筛选按 AND 组合；不同条件之间按 OR 组合，只要一条条件完整命中就会发送一封提醒。多条同时命中时仍只发送一封，邮件中的命中项目和距离采用列表中第一条命中的条件。

## CLI 命令

全局参数必须放在子命令之前：

```bash
.venv/bin/python -m wca_competition_reminder \
  --config config.toml \
  --state ./state.sqlite3 \
  --lock ./runner.lock \
  --log-level INFO \
  poll
```

### 子命令

| 命令 | 说明 |
| --- | --- |
| `check-config` | 验证配置，不读取 SMTP 密码，也不发送邮件。 |
| `send-test` | 向每位已配置的收件人发送一封测试邮件。 |
| `poll` | 执行一轮比赛发现、详情补全和邮件发送。 |
| `run` | 立即轮询一次，之后以一分钟为间隔串行轮询。 |
| `status` | 输出 SQLite 中的基线、比赛和邮件状态数量。 |
| `retry-blocked` | 修复底层 SMTP 问题后，将永久阻塞的邮件重新放回待发送队列。 |

### 全局参数

| 参数 | 说明 |
| --- | --- |
| `--config PATH` | TOML 配置路径，默认为 `./config.toml`。 |
| `--state PATH` | 覆盖配置中的 SQLite 状态库路径。 |
| `--lock PATH` | 覆盖配置中的进程锁路径。 |
| `--smtp-password-file PATH` | 从 UTF-8 文本文件读取 SMTP 密码。 |
| `--log-level LEVEL` | 可选 `DEBUG`、`INFO`、`WARNING` 或 `ERROR`，默认为 `INFO`。 |
| `--version` | 输出应用版本。 |
| `-h`、`--help` | 显示程序生成的命令帮助。 |

执行 `python -m wca_competition_reminder --help` 可查看程序生成的完整帮助。

## 日志与审计

`log_dir` 默认为配置文件同目录下的 `logs`。每个命令分别写入
`<命令>.out.log` 和 `<命令>.err.log`：`DEBUG`、`INFO`、`WARNING` 进入 stdout 与
`.out.log`，`ERROR`、`CRITICAL` 进入 stderr 与 `.err.log`，同一条错误不会重复出现在两边。日志每天午夜轮转，当前文件加 6 个日归档，共覆盖最近 7 个自然日。

Web 服务会把页面访问、验证码请求、注册、查询、修改、取消，以及管理员登录、退出和数据查看等事件写入 SQLite 的 `activity_logs` 表。结构化记录包含时间、结果、邮箱、来源 IP、请求路径、User-Agent 和安全筛选后的操作详情，可在管理控制台的“用户日志”页分页查询。写入和读取时都会删除 7 天前的记录；SQLite 会复用释放的页，避免日志表持续扩张。密码和验证码始终不会入库。

同一事件仍会写入文本审计日志，但邮箱会被遮盖。PM2 配置将自己的重复日志副本指向 `/dev/null`，避免绕过 7 天保留周期；生产排查请直接读取 `logs/run.*.log` 和 `logs/web.*.log`。

## 使用 PM2 部署

仓库提供了适用于 Linux 的 [`ecosystem.config.js`](ecosystem.config.js)。它使用项目虚拟环境中的 `.venv/bin/python`，并读取项目目录内的 `config.toml` 和 `smtp_password`，以 `run` 子命令启动常驻进程。

### 安装并启动

使用负责运行服务的专用非 root 账户执行：

```bash
git clone <repository-url> wca-competition-reminder
cd wca-competition-reminder

uv sync --frozen --no-dev --python python3.12
cp config.example.toml config.toml

install -m 600 /dev/null smtp_password
# 编辑 config.toml，并在 smtp_password 中只写入 SMTP 密码。

.venv/bin/python -m wca_competition_reminder \
  --config config.toml \
  --smtp-password-file smtp_password \
  check-config
.venv/bin/python -m wca_competition_reminder \
  --config config.toml \
  --smtp-password-file smtp_password \
  send-test

pm2 start ecosystem.config.js
pm2 save
```

如需重启后自动运行，执行 `pm2 startup`，再执行它输出的命令，最后重新执行 `pm2 save`。PM2 应使用拥有项目文件的同一个账户运行。

### 日常运维

```bash
pm2 status wca-competition-reminder
tail -F logs/run.out.log logs/run.err.log
tail -F logs/web.out.log logs/web.err.log
pm2 restart wca-competition-reminder
pm2 stop wca-competition-reminder
```

更新应用时保留已有状态和秘密文件：

```bash
git pull --ff-only
uv sync --frozen --no-dev --python python3.12
pm2 restart wca-competition-reminder
```

不要把 `config.toml`、`smtp_password`、`state.sqlite3` 和 `runner.lock` 提交到 Git。请备份 `state.sqlite3`，它是业务状态而不是可随时删除的缓存。不要针对同一状态库运行多个 PM2 实例或额外的定时任务；进程锁会有意阻止多个轮询器同时运行。

## 状态与恢复

查看当前状态：

```bash
.venv/bin/python -m wca_competition_reminder --config config.toml status
```

修复永久 SMTP 错误后，重新排队被阻塞的邮件：

```bash
.venv/bin/python -m wca_competition_reminder --config config.toml retry-blocked
```

如需清除所有比赛和邮件状态，请先停止服务，再执行：

```bash
.venv/bin/python clear_database.py --config config.toml
```

只有输入 `CLEAR` 后，脚本才会删除数据。下一次成功轮询会重新建立静默基线。

邮件发送采用至少一次语义。如果 SMTP 服务器已接受邮件，但进程在 SQLite 记录发送成功前崩溃，可能产生重复邮件。稳定的 `Message-ID` 有助于邮件服务器去重，但无法提供绝对保证。

## 开发

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

Windows 请将 `.venv/bin/python` 替换为 `.venv\Scripts\python.exe`，并使用 `.venv\Scripts\ruff.exe` 运行 Ruff。

## 许可证

本项目采用 [MIT 许可证](LICENSE) 发布。
