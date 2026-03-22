---
name: url-to-pdf
description: 将一个或多个网页 URL 转成高质量 PDF，并保存到 `~/Downloads/PDF` 的时间戳目录。用户只要提到导出网页为 PDF、保存公众号/极客时间/知识库页面、批量转网页、登录后继续导出、回复“已登录/登录成功/登录好了/继续”来确认网页登录、或把生成的 PDF 上传到 NotebookLM，就应主动使用这个 skill，而不是只给脚本路径或手工步骤。
---

# URL to PDF

## 作用
这个 skill 负责三件事：

- 把网页渲染成高质量 PDF
- 在需要登录的网站上管理站点级登录态
- 在用户明确要求时把生成的 PDF 上传到 NotebookLM

脚本入口都在 `scripts/`。写 skill 时以这些文件为准，不要以 README 作为真实行为来源。

## 优先入口
默认只使用这些入口：

- 环境诊断：`python3 scripts/doctor.py --json`
- 统一执行入口：`python3 scripts/run.py <script> [args...]`
- 网页转 PDF：`python3 scripts/run.py convert_to_pdf.py <url1> <url2> ...`
- Claude Code / 非交互登录：`python3 scripts/run.py auth_manager.py begin <url>`
- 登录确认：`python3 scripts/run.py auth_manager.py confirm`
- 上传 PDF：`python3 scripts/nlm_upload_cli.py <output_directory> <notebook_id>`

不要默认直接运行 `auth_browser_worker.py`。那是 `auth_manager.py begin` 拉起的内部 worker。

## 先看诊断
先运行：

```bash
python3 scripts/doctor.py --json
```

读取这些字段：

- `playwright_package` / `playwright`
  决定当前 Python 环境能不能执行网页转换
- `interactive_terminal`
  只表示当前 shell 是否适合做交互式网页登录
- `auth_valid` / `nlm_auth_valid`
  只表示 NotebookLM 上传认证，不表示目标网站登录态
- `recommended_install_steps`
  是首次安装 Playwright 的建议路径

注意：

- `auth_valid: false` 不能解释成“公众号/极客时间/知识库没登录”
- `doctor.py` 的 `is_ready` 对 NotebookLM 上传比较严格；即使 `is_ready` 为 false，只要 `playwright` 可用，网页转 PDF 仍可能可以正常执行

## 核心转换流程
默认工作流：

1. 从用户消息里提取 URL
2. 如果 URL 是 `pure.md/...` 这类包装形式，使用原始目标 URL
3. 跑 `python3 scripts/doctor.py --json`
4. 用统一入口执行：

```bash
python3 scripts/run.py convert_to_pdf.py <url1> <url2> ...
```

5. 转换完成后，汇报：
   - 输出目录 `~/Downloads/PDF/<timestamp>/`
   - 关键 PDF 文件名
   - 文件大小（尤其在排查空白页时）

`convert_to_pdf.py` 的真实行为：

- 输出目录固定在 `~/Downloads/PDF/<timestamp>/`
- 同名标题会自动避重命名
- 会触发懒加载、滚动自定义滚动容器、展平滚动父级、隐藏明显 UI
- 会按 URL 复用站点级登录态
- 无法转换单个 URL 时会打印错误，但继续处理后续 URL

## 登录与会话
当前代码不是全局单 session，而是站点级目录：

- `~/.url-to-pdf/profiles/<site>/storage_state.json`
- `~/.url-to-pdf/profiles/<site>/browser_profile/`

`convert_to_pdf.py` 会优先自动复用它们。旧的 `~/.url-to-pdf/session.json` 只作为 legacy fallback。

### 本地交互式终端
如果当前环境适合直接开浏览器，`convert_to_pdf.py` 会在需要时自动 bootstrap 登录：

- 无可复用 session 时
- 页面强烈像登录页时
- 已有 session 但正文像失效页时

手动初始化也可以：

```bash
python3 scripts/run.py bootstrap_login.py <url>
```

### Claude Code / 非交互环境
优先使用显式确认流，不要依赖终端输入：

```bash
python3 scripts/run.py auth_manager.py begin <url>
```

这会：

- 为该站点创建或复用 `browser_profile/`
- 启动后台浏览器 worker
- 持续把最新 `storage_state.json` 刷到站点目录
- 记录最近一次登录尝试到 `~/.url-to-pdf/last_auth_attempt.json`

用户在浏览器里完成登录后，如果他们回复这些话：

- `已登录`
- `登录成功`
- `登录好了`
- `继续`
- `可以了`

就立刻运行：

```bash
python3 scripts/run.py auth_manager.py confirm
```

重点：

- `confirm`、`status`、`cancel` 默认使用“最近一次登录尝试”
- 这时不要要求用户重新贴 URL，除非当前会话里根本没有 begin 过
- `confirm` 的规则是“用户确认优先 + 现有 headless 校验兜底”
- 如果兜底校验失败，告诉用户继续保持浏览器打开，完成登录后再 `confirm`

可用子命令：

```bash
python3 scripts/run.py auth_manager.py begin <url>
python3 scripts/run.py auth_manager.py confirm
python3 scripts/run.py auth_manager.py status
python3 scripts/run.py auth_manager.py cancel
```

## 站点适配
当前 `site_adapters.py` 已内置这些站点：

- `mp.weixin.qq.com`
- `time.geekbang.org`
- `km.netease.com`

这些适配器目前主要提供：

- 正文选择器
- URL / 正文级登录信号

其它站点会落到 generic fallback。

所以在这些站点上，优先相信现有适配器逻辑；在未知站点上，保守解释结果，必要时让用户确认导出效果。

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

标准流程：

1. 先列 notebooks：

```bash
nlm notebook list
```

2. 让用户给 notebook ID；如果用户要新建：
   - 如果只需要默认名称，可以让 `nlm_upload_cli.py` 走 `CREATE_NEW`
   - 如果用户指定自定义名称，先自己运行 `nlm notebook create <title>`，拿到 ID 再上传

3. 上传：

```bash
python3 scripts/nlm_upload_cli.py <output_directory> <notebook_id>
```

上传脚本的真实行为：

- 只会上传目录里的 `*.pdf`
- 找不到 `nlm` 时会直接报错
- 遇到认证失败会提示先 `nlm login`

## 输出要求
结束时至少告诉用户：

- 是否成功生成 PDF
- 输出目录
- 关键文件名
- 文件大小

如果失败，明确说是哪个阶段失败：

- 依赖未就绪
- 网站需要登录
- `confirm` 兜底校验未通过
- 登录后仍停在登录页
- 本地 PDF 成功但 NotebookLM 上传失败

## 相关文件
- `scripts/doctor.py`
  环境诊断和 NotebookLM 上传认证检查
- `scripts/run.py`
  统一入口，自动建 `.venv` 并安装 Playwright / Chromium
- `scripts/convert_to_pdf.py`
  转换、会话复用、自动 bootstrap、登录页校验
- `scripts/auth_manager.py`
  Claude Code 友好的 begin / confirm / status / cancel
- `scripts/auth_browser_worker.py`
  后台有头浏览器 worker
- `scripts/site_adapters.py`
  站点适配和 generic fallback
- `scripts/bootstrap_login.py`
  纯交互式手动 bootstrap
- `scripts/nlm_upload_cli.py`
  NotebookLM 上传
