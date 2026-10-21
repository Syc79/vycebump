<!-- markdownlint-disable-file MD033 -->
# Vycebump — Vyce.cloud 免费 VPS 自动续期保活

<p align="center">
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/license-MIT-green.svg"></a>
  <img alt="Python" src="https://img.shields.io/badge/Python-3.8%2B-3776AB?logo=python&logoColor=white">
  <img alt="Zero Dependencies" src="https://img.shields.io/badge/dependencies-0-brightgreen.svg">
  <img alt="Tests" src="https://img.shields.io/badge/tests-passing-brightgreen.svg">
  <img alt="GitHub Actions" src="https://img.shields.io/badge/GitHub%20Actions-ready-2088FF?logo=githubactions&logoColor=white">
</p>

<p align="center">
  <b>把「每 24 小时手动点一次续期」这件事彻底交给机器。</b><br>
  自动推算 24h 冷却窗口，进入可续期区间后调用官方接口续期，Telegram 实时播报剩余存活时间。<br>
  零第三方依赖，可跑在 GitHub Actions（完全免费）或本机 Chrome（免手抄 Cookie）。
</p>

<p align="center">
  <img src="assets/demo.svg" alt="Vycebump 本地运行输出示例" width="820">
</p>

<p align="center">
  <a href="#为什么需要自动续期">为什么需要</a> •
  <a href="#核心特性">核心特性</a> •
  <a href="#快速开始">快速开始</a> •
  <a href="#环境变量">环境变量</a> •
  <a href="#安全与执行策略">安全策略</a> •
  <a href="#常见问题">常见问题</a> •
  <a href="#致谢">致谢</a>
</p>

---

专为 [Vyce.cloud](https://vyce.cloud/#/servers) 免费 VPS 设计的自动续期与保活工具，架构与理念灵感源自 [dengyie/katabump](https://github.com/dengyie/katabump)。

## 为什么需要自动续期？

Vyce.cloud 为免费 VPS（如 `Vps-Mini`，1 vCore / 2 GB RAM / 6 GB NVMe / 纯 IPv6）提供长期免费使用资格，但附带一套保活机制：

| 机制 | 说明 |
| :--- | :--- |
| **48 小时生命周期** | 每台免费 VPS 创建或续期后，存活上限为 48 小时 |
| **24 小时冷却保护** | 存活时间 > 24h 时面板显示 `Cooldown`，续期接口返回 `429 renewal_cooldown` |
| **续期重置** | 在最后 24 小时窗口内（或机器已停止时）续期，存活时间立即重置回 48 小时 |
| **逾期关机与销毁** | 48 小时未续期则关机（文件保留）；关机超过 3 天未续期则彻底销毁 |

也就是说，**只要错过一次 24h 窗口，机器就进入倒计时**。Vycebump 负责推算冷却倒计时，在窗口打开时自动续期，实现无感保活。

## 核心特性

- **零依赖原生 Python** — 仅用标准库（`urllib`、`ssl`、`json`、`ipaddress`），无需 `pip install` 任何东西，开箱即用。
- **双模驱动**：
  - **模式 A · 本地 CDP 无感捕获** — 本机 Chrome 开启 `--remote-debugging-port=9222` 后，自动从已登录标签页提取最新 `__Host-vyce_sid`，免手动复制粘贴。
  - **模式 B · GitHub Actions 云端调度** — 配置 Secret 后每 4 小时自动巡检续期，零成本、零维护。
- **冷却期智能跳过** — 内置倒计时推算，冷却期内直接跳过续期请求，减少无效调用与被平台频控的风险。
- **全协议代理支持** — 内置 `proxy_handler.py`，支持 VLESS、VMess、Hysteria2、TUIC、Trojan、AnyTLS、SOCKS5、HTTP(S)，以及双跳链式代理；Actions 中自动拉起 sing-box 并做健康探测。
- **Telegram 实时推送** — 账号脱敏、服务器状态、剩余存活时间、下次续期窗口与错误告警。
- **43 个单元测试** — 覆盖核心算法、状态边界、CDP 与代理安全策略，CI 每次运行前自动执行。

## 快速开始

### 方式一：GitHub Actions 云端自动调度（推荐）

配置一次，永久生效，不需要任何常开设备。

1. **Fork 本仓库**到你的 GitHub 账号。
   > ⚠️ **安全提示**：Fork 后**无需、也严禁**在源码里硬编码任何凭据或节点链接。所有敏感信息一律通过 Actions Secrets 注入。本项目**不读取任何明文凭据文件**，请勿把凭据以文件形式提交到公开仓库。
2. 进入你 Fork 的仓库 **Settings → Secrets and variables → Actions**，新增以下 Repository Secret：

   | Secret | 必填 | 说明 |
   | :--- | :---: | :--- |
   | `VYCE_COOKIE` | ✅ | Vyce.cloud 登录 Cookie，格式 `__Host-vyce_sid=xxxx...` |
   | `TG_BOT_TOKEN` | | Telegram Bot Token（[@BotFather](https://t.me/BotFather) 获取） |
   | `TG_CHAT_ID` | | Telegram 接收通知的 Chat ID |
   | `PROXY_URL` | | 代理节点链接（`vless://`、`hy2://`、`socks5://` 等） |
   | `USERS_JSON` | | 多账号配置，见下方 |

   Cookie 获取方式：浏览器 F12 → Application → Cookies → `https://vyce.cloud`，复制 `__Host-vyce_sid` 的值；也可直接从请求头 `Cookie` 中复制。

3. **（可选）多账号**，配置 `USERS_JSON`：

   ```json
   [
     {"name": "user1", "cookie": "__Host-vyce_sid=cookie1..."},
     {"name": "user2", "cookie": "__Host-vyce_sid=cookie2..."}
   ]
   ```

4. 进入仓库 **Actions** 页面，点击 **Enable workflow** 启用定时调度，然后选择 **Vyce.cloud Auto Renew → Run workflow** 做一次手动验证。

工作流默认每 4 小时运行一次（`0 */4 * * *`），并支持手动指定 `force` 强制续期（忽略冷却保护，用于调试）。

续期和库存创建工作流都受 Repository Variable `VYCE_AUTOMATION_OWNER` 控制：只有值为 `github` 时才会启动 runner；值为 `local` 或未设置时跳过任务。不要在本机 Edge 自动监控或续期仍启用时切换到 `github`，以免云端与本机同时执行。切换前先停止本机任务，并确认没有待核验的创建或续期请求。

### 方式二：本地运行（搭配 Chrome 9222 端口）

本机 Chrome 已登录 `https://vyce.cloud/#/servers` 且开启远程调试端口（需本机具备 `node` 供 CDP WebSocket 提取 Cookie）时：

```bash
# macOS 示例：启动带调试端口的 Chrome
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 &

# 运行续期脚本（自动探测 9222 端口并提取活跃 Cookie）
python3 app.py
```

终端输出示例：

```text
[2026-10-19 12:15:11] vycebump 保活脚本启动
🔍 尝试从本地 Chrome 9222 CDP 探测活跃登录态...
✅ 成功从本地 Chrome 提取到最新 Session Cookie！

==================================================
🔑 正在处理账户: ex****le
==================================================
✅ 登录成功！用户: example_user

🖥️ 检查服务器: vps-mini
   类型: free (mini) | 状态: running
   ⏳ 剩余存活时间: 1d 12h (到期: 2026-10-21 00:27:23)
   ❄️ 当前处于冷却期中 (Cooldown)，无需续期。
   ⏰ 预计下次可续期时间: 2026-10-20 00:27:23 (约 12h 12m 后)

✅ 任务处理完毕，状态已保存至 renew_state.json。
```

## 环境变量

| 变量名 | 说明 | 示例 | 默认值 |
| :--- | :--- | :--- | :--- |
| `VYCE_COOKIE` | 单账号登录 Cookie，可只填 token（会自动补 `__Host-vyce_sid=` 前缀） | `__Host-vyce_sid=ICYUl...` | 空 |
| `VYCE_USER` | 单账号显示名（通知与日志脱敏用） | `myname` | `VyceUser` |
| `USERS_JSON` | 多账号 JSON 数组，元素支持 `name`/`login` 与 `cookie`/`token` | `[{"name":"..","cookie":".."}]` | 空 |
| `CDP_URL` | 本地 Chrome 调试地址（仅允许回环） | `http://127.0.0.1:9222` | `http://127.0.0.1:9222` |
| `FORCE_RENEW` | 强制续期，无视冷却保护 | `true` / `false` | `false` |
| `STATE_FILE` | 状态与冷却倒计时缓存路径 | `./renew_state.json` | `./renew_state.json` |
| `TG_BOT_TOKEN` | Telegram Bot Token | `123456:ABC-DEF...` | 空 |
| `TG_CHAT_ID` | Telegram 接收通知 Chat ID | `987654321` | 空 |
| `PROXY_SERVER` | HTTP/SOCKS 代理地址（未设置时自动读取 `https_proxy` / `http_proxy`） | `http://127.0.0.1:8080` | 空 |
| `PROXY_URL` | 全协议节点分享链接（Actions 中拉起 sing-box 并健康探测） | `hy2://pwd@host:port?sni=...` | 空 |
| `PROXY_CHAIN_URL` | 二级链式代理节点，与 `PROXY_URL` 组成双跳（代码支持，默认工作流未注入，需自行加 env） | `socks5://127.0.0.1:1080` | 空 |
| `ALLOW_INSECURE_PROXY` | 允许节点携带 `insecure=1`（跳过 TLS 证书校验；默认工作流未注入，需自行加 env） | `1` / `true` | 关闭 |

> 冷却期内的 `429 renewal_cooldown` 属于**预期状态**：脚本记录下次可续期窗口、正常退出（状态码 0），不会告警。

## 安全与执行策略

1. **零源码硬编码凭据（Fork 友好）** — 任何人 Fork 后无需修改源码，凭据、代理链接与 Telegram 配置全部走 Actions Secrets。项目**不支持也不读取 `login.json` 等明文凭据文件**，从根上避免凭据落盘被误提交。
2. **HTTP 429 冷却契约** — 存活时间 > 24h 时平台返回 `429 {"error":"renewal_cooldown"}`：
   - **预期冷却**：判定为健康状态，记录下次续期窗口，不告警，工作流以状态码 0 正常退出；
   - **非预期 429 或其它错误**（限流、网络阻断、Cookie 失效等）：触发 Telegram 告警，并以非零退出码让 CI 亮红提醒排查。
3. **CDP 本地边界** — 只允许连接 `127.0.0.1` / `::1` 回环地址，拒绝带凭据或非回环的调试端点；仅从 URL 精确为 `https://vyce.cloud` 的标签页提取 Cookie，并校验 WebSocket 目标与端口一致，杜绝恶意重定向与第三方页面抓取。
4. **代理 Fail-Closed** — Actions 中配置 `PROXY_URL` 后会拉起 sing-box 并做连通性探测；节点异常则**立即失败退出**，绝不静默降级为直连，避免真实出口 IP 泄露。sing-box 二进制下载带 SHA256 校验。
5. **状态缓存边界** — `renew_state.json` 仅用于本地减少无意义请求（已加入 `.gitignore`，不会入库）；Actions 每次都是干净环境，以服务端返回的冷却状态为准。

## 常见问题

**Q：会不会被判定为异常流量 / 封号？**
A：脚本只在冷却结束、进入可续期窗口后调用一次官方续期接口，其余时间仅做少量状态查询，请求频率远低于人工点面板；不注入页面脚本、不模拟点击，Actions 模式下也不依赖浏览器。

**Q：Cookie 会过期吗？**
A：会。Vyce 的会话 Cookie 有有效期，失效后续期会返回鉴权错误并触发 Telegram 告警，此时重新获取 `__Host-vyce_sid` 更新 Secret 即可。本地 CDP 模式无需手动维护 Cookie，只要 Chrome 保持登录状态，每次运行都会自动抓取最新会话。

**Q：Actions 免费额度够用吗？**
A：公开仓库的 Actions 完全免费；私有仓库每月 2000 分钟额度，本工作流单次运行通常不到 1 分钟、每天 6 次，开销可忽略。

**Q：定时任务突然不跑了？**
A：三个常见原因：① Fork 后没有在 Actions 页面点击 **Enable workflow**；② GitHub 会在公开仓库**连续 60 天无仓库活动**后自动停用定时工作流，点一下 **Enable workflow** 即可恢复；③ 运行失败时可在该次运行的 Artifacts 中下载 `diagnostic-logs`（内含 `singbox.log`）排查。

**Q：支持多账号吗？**
A：支持，通过 `USERS_JSON` 配置，脚本会逐个账号串行处理并分别推送通知。

**Q：机器已经被关机/销毁了还能救回来吗？**
A：关机状态（48h 内未续期）仍可通过续期重置存活时间；**关机超过 3 天被彻底销毁**后无法恢复，只能重新创建。

**Q：需要 `pip install` 吗？**
A：不需要。项目零第三方依赖，仅本地 CDP 模式额外需要系统里有 `node`。

**Q：本地同时设置了 `VYCE_COOKIE`，为什么没走 CDP 自动抓取？**
A：账号来源有优先级：只要 `USERS_JSON` 或 `VYCE_COOKIE` 能解析出账号，脚本就不会再去连 Chrome；只有两者都为空时才启用 CDP 探测。想让本地运行始终使用浏览器里的最新会话，就不要设置这两个变量。

## 开发与测试

```bash
# 运行全部单元测试（43 个，无需额外依赖）
python3 -m unittest discover -s tests -v
```

仓库结构：

```text
vycebump/
├── app.py              # 主程序：CDP 取 Cookie、续期、状态与通知
├── proxy_handler.py    # 代理分享链接 → sing-box 配置生成
├── tests/              # 单元测试：核心算法 / CDP 安全 / 代理安全 / 工作流策略
└── .github/workflows/  # Actions 定时续期工作流
```

## 致谢

[![LINUX DO](https://img.shields.io/badge/Community-LINUX%20DO-2563eb.svg?logo=linux&logoColor=white)](https://linux.do/)

> 🐧 **本项目致谢 [LINUX DO](https://linux.do/) 社区。** 从架构选型、保活思路到代理与排障经验，都受益于社区佬友们的无私分享与深入讨论。致敬开源精神与纯粹的技术探索！

## 许可证

本项目依据 [MIT License](LICENSE) 开源，仅供个人自动化管理与技术交流学习使用。

---

如果这个项目帮你省下了每天手动续期的时间，欢迎点个 **Star** ⭐ 支持一下。
