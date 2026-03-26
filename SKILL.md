---
name: url-to-pdf
description: 将一个或多个网页 URL 导出成 PDF，并在需要时上传到 NotebookLM。只要用户提到网页转 PDF、保存公众号/极客时间/知识库/内部文档页面、批量导出、登录后继续、回复“已登录/登录成功/登录好了/继续”表示网页登录完成，或要把刚生成的 PDF 上传到 NotebookLM，就直接使用这个 skill；不要只给脚本路径或手工步骤。
---

# URL to PDF

## 这个 skill 负责什么

- 把网页按真实浏览器渲染结果导出成 PDF
- 管理按站点保存的登录态
- 在用户明确要求时，把导出的 PDF 上传到 NotebookLM

脚本入口都在 `scripts/`。判断真实行为时，以这些脚本为准，不要以 README 为准。

## 先记住这几个规则

- 诊断先用 `python3 scripts/doctor.py --json`
- 真正执行转换或登录时，优先用 `python3 scripts/run.py <script> ...`
- 不要默认直接运行 `auth_browser_worker.py`
- 用户说“已登录 / 登录成功 / 登录好了 / 继续 / 可以了”时，如果当前会话里已经跑过 `auth_manager.py begin`，就立刻跑 `auth_manager.py confirm`
- `auth_valid` / `nlm_auth_valid` 只表示 NotebookLM 上传认证状态，不表示目标网站登录态

## 优先入口

默认只用这些入口：

- 环境诊断：`python3 scripts/doctor.py --json`
- 统一执行入口：`python3 scripts/run.py <script> [args...]`
- 网页转 PDF：`python3 scripts/run.py convert_to_pdf.py <url1> <url2> ...`
- 交互式登录初始化：`python3 scripts/run.py bootstrap_login.py <url>`
- 非交互登录开始：`python3 scripts/run.py auth_manager.py begin <url>`
- 非交互登录确认：`python3 scripts/run.py auth_manager.py confirm`
- NotebookLM 上传：`python3 scripts/nlm_upload_cli.py <output_directory> <notebook_id_or_url>`

## 默认工作流

### 1. 用户只是回复“已登录”之类的确认词

先判断当前会话里是否已经跑过 `auth_manager.py begin`。

如果有，直接运行：

```bash
python3 scripts/run.py auth_manager.py confirm
```

这时不要要求用户重新贴 URL，除非根本没有最近一次登录尝试。

### 2. 用户要导出网页

默认这样做：

1. 从用户消息里提取 URL
2. 如果 URL 是 `pure.md/...` 这类包装地址，使用原始目标 URL
3. 先跑：

```bash
python3 scripts/doctor.py --json
```

4. 再用统一入口执行：

```bash
python3 scripts/run.py convert_to_pdf.py <url1> <url2> ...
```

5. 完成后至少汇报：
   - 输出目录 `~/Downloads/PDF/<timestamp>/`
   - 关键 PDF 文件名
   - 文件大小

## 怎么读 `doctor.py`

重点看这些字段：

- `playwright_package` / `playwright`
  决定当前 Python 环境能不能执行网页渲染
- `interactive_terminal`
  只表示当前进程是不是连着 TTY
- `auth_valid` / `nlm_auth_valid`
  只表示 NotebookLM 上传认证，不表示目标网站是否已登录
- `recommended_install_steps`
  是 Playwright 的推荐安装路径

注意：

- `doctor.py` 不会替你安装依赖
- `run.py` 会在真正执行脚本前自动创建 `.venv` 并安装 Playwright / Chromium
- `is_ready` 对 NotebookLM 上传比较严格；即使它是 `false`，只要 Playwright 正常，网页转 PDF 仍然可能可以执行

## 登录与会话

当前代码按站点保存登录态，不是全局单 session：

- `~/.url-to-pdf/profiles/<site>/storage_state.json`
- `~/.url-to-pdf/profiles/<site>/browser_profile/`

旧的 `~/.url-to-pdf/session.json` 只作为 legacy fallback；如果域名匹配，会迁移到站点目录。

### 当前代码里的三种处理方式

#### 1. 已有 session，而且当前页面不像登录页

`convert_to_pdf.py` 会直接复用已有 `storage_state.json` 继续转换，不进入登录流程。

#### 2. 页面需要登录，当前是交互式终端

`convert_to_pdf.py` 会走自动 bootstrap：

- 打开可见浏览器
- 等待页面内容和 cookie 变化
- 保存新的 session
- 回到无头上下文继续转换

如果用户只是想先把登录态准备好，也可以手动跑：

```bash
python3 scripts/run.py bootstrap_login.py <url>
```

#### 3. 页面需要登录，当前不是交互式终端

不要让 `convert_to_pdf.py` 自己继续等。当前代码里，这种情况应该直接切到显式确认流：

```bash
python3 scripts/run.py auth_manager.py begin <url>
```

浏览器里完成登录后，再执行：

```bash
python3 scripts/run.py auth_manager.py confirm
```

这条规则同时适用于：

- 第一次登录
- 旧 session 已失效

### `auth_manager.py` 这条流要注意什么

`begin` 会：

- 为该站点创建或复用 `browser_profile/`
- 启动后台浏览器 worker
- 持续把最新 `storage_state.json` 刷到站点目录
- 记录最近一次登录尝试到 `~/.url-to-pdf/last_auth_attempt.json`

`confirm` / `status` / `cancel` 默认使用最近一次登录尝试。

`confirm` 的逻辑是：

- 用户确认优先
- 再用 headless 校验做兜底

如果兜底校验失败，告诉用户保持浏览器打开，继续完成登录后再执行一次 `confirm`。

## `interactive_terminal` 的真实含义

当前代码里，“交互式终端”的判断就是：

- `stdin` 是 TTY
- `stdout` 是 TTY

不要把它理解成“用户一定能操作电脑”或“浏览器一定能打开”。它只是当前脚本选择登录策略时使用的环境信号。

## 站点适配

当前 `site_adapters.py` 已内置这些站点：

- `mp.weixin.qq.com`
- `time.geekbang.org`
- `km.netease.com`

这些适配器主要提供：

- 正文选择器
- URL / 正文级登录信号

其它站点会落到 generic fallback。

## PDF 质量判断

导出成功不等于内容正确。至少检查这些信号：

- 文件是否存在
- 文件大小是否明显大于空白壳 PDF
- 文件名是否像正文标题，而不是“登录”

如果用户是在排查质量问题，优先从这些方向解释：

- 懒加载内容没触发
- 自定义滚动容器没完全展开
- 登录页被导成了 PDF
- UI 隐藏规则误伤正文

## NotebookLM 上传

只有在用户明确说要上传时才继续。

推荐流程：

1. 先列出 notebooks：

```bash
nlm notebook list
```

2. 让用户给出 notebook ID
3. 如果用户要新建 notebook：
   - 默认名称：可以让 `nlm_upload_cli.py` 走 `CREATE_NEW`
   - 自定义名称：先运行 `nlm notebook create <title>`，拿到 ID 再上传
4. 上传：

```bash
python3 scripts/nlm_upload_cli.py <output_directory> <notebook_id_or_url>
```

上传脚本的真实行为：

- 只上传目录里的 `*.pdf`
- 找不到 `nlm` 时直接报错
- 认证失败时提示先 `nlm login`

## 失败时怎么说

不要只说“失败了”。明确说卡在哪一层：

- Python / Playwright / Chromium 未就绪
- 网站需要登录
- 非交互环境应改走 `begin -> confirm`
- `confirm` 兜底校验未通过
- 登录后仍停在登录页
- 本地 PDF 已成功，但 NotebookLM 上传失败

## 输出要求

结束时至少告诉用户：

- 是否成功生成 PDF
- 输出目录
- 关键文件名
- 文件大小

如果还做了上传，再补充：

- 上传到哪个 notebook
- 哪些文件上传成功

## 相关文件

- `scripts/doctor.py`
  环境诊断和 NotebookLM 上传认证检查
- `scripts/run.py`
  统一入口，自动建 `.venv` 并安装 Playwright / Chromium
- `scripts/convert_to_pdf.py`
  转换、会话复用、登录检测、登录策略分流
- `scripts/auth_manager.py`
  非交互环境下的 begin / confirm / status / cancel
- `scripts/auth_browser_worker.py`
  `begin` 拉起的后台有头浏览器 worker
- `scripts/bootstrap_login.py`
  纯交互式手动 bootstrap
- `scripts/site_adapters.py`
  站点适配和 generic fallback
- `scripts/nlm_upload_cli.py`
  NotebookLM 上传
