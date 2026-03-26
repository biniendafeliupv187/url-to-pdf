# @url-to-pdf Skill

这个 skill 主要做两件事：

- 把网页按真实浏览器渲染结果导出成 PDF
- 在你明确需要时，把导出的 PDF 上传到 Google NotebookLM

![流程图](./workflow.png)

## 它现在会做什么

- 用 Playwright + Chromium 打开页面，再导出 PDF
- 输出目录固定在 `~/Downloads/PDF/<timestamp>/`
- 同名文件会自动避重命名
- 会触发懒加载、滚动自定义滚动容器、展开常见的 `flex` / `overflow` 限制
- 会隐藏导航、侧边栏、悬浮 footer 一类明显干扰阅读的 UI
- 登录态按站点保存，不再共用一个全局 session
- 单个 URL 失败时会打印错误，然后继续处理后面的 URL

登录相关的文件默认放在这里：

- `~/.url-to-pdf/profiles/<site>/storage_state.json`
- `~/.url-to-pdf/profiles/<site>/browser_profile/`

旧的 `~/.url-to-pdf/session.json` 还会作为兼容兜底读取；如果域名匹配，会迁移到站点目录。

## 先跑什么

如果你只是想先看看环境状态，先跑这个：

```bash
python3 scripts/run.py doctor.py --json
```

如果你是第一次在这台机器上用，直接从统一入口开始最省事：

```bash
python3 scripts/run.py convert_to_pdf.py https://example.com
```

`run.py` 会负责这些事：

- 创建技能目录下的 `.venv`
- 安装 Playwright Python 包
- 安装 Chromium 浏览器
- 再执行你指定的脚本

它不会帮你安装 `uv`、`nlm`，也不会替你完成 `nlm login`。

## 登录怎么分流

当前代码里，登录分流看的是页面状态和运行环境，不是单纯看“是不是第一次登录”。

### 1. 站点 session 还有效

脚本会直接复用已有的 `storage_state.json`，继续无头转换，不进入登录流程。

### 2. 页面需要登录，当前是交互式终端

`convert_to_pdf.py` 会自动拉起一个可见浏览器，等待你完成登录，然后把新的 session 写回站点目录，接着继续导出。

这里的“交互式终端”按当前代码的定义，就是 `stdin` 和 `stdout` 都是 TTY。

如果你只是想手动把某个站点的登录态先准备好，也可以直接跑：

```bash
python3 scripts/run.py bootstrap_login.py <url>
```

### 3. 页面需要登录，当前不是交互式终端

这时不要指望 `convert_to_pdf.py` 自己继续走完登录。现在的脚本逻辑是直接切到显式确认流：

```bash
python3 scripts/run.py auth_manager.py begin <url>
```

浏览器里完成登录后，再执行：

```bash
python3 scripts/run.py auth_manager.py confirm
```

`confirm` 会读取最近一次登录尝试，不需要你再次传 URL，除非这次会话里根本没跑过 `begin`。

如果 `confirm` 的兜底校验没有通过，浏览器先别关，继续完成登录，再执行一次 `confirm`。

可用的登录命令有这些：

```bash
python3 scripts/run.py auth_manager.py begin <url>
python3 scripts/run.py auth_manager.py confirm
python3 scripts/run.py auth_manager.py status
python3 scripts/run.py auth_manager.py cancel
```

## 常用命令

```bash
python3 scripts/run.py doctor.py --json
python3 scripts/run.py convert_to_pdf.py <url1> <url2> ...
python3 scripts/run.py bootstrap_login.py <url>
python3 scripts/run.py auth_manager.py begin <url>
python3 scripts/run.py auth_manager.py confirm
python3 scripts/nlm_upload_cli.py <output_directory> <notebook_id_or_url>
```

## NotebookLM 上传

上传是单独一条流程，不影响网页转 PDF 本身。

上传脚本：

```bash
python3 scripts/nlm_upload_cli.py <output_directory> <notebook_id_or_url>
```

注意几点：

- 它会上传目录下的 `*.pdf`
- 依赖本地 `nlm` CLI
- 如果还没登录，需要先执行 `nlm login`
- 传入 `CREATE_NEW` 时，脚本会先新建一个 notebook，再上传

## `doctor.py` 里几个容易看错的字段

- `playwright_package` / `playwright`
  表示当前 Python 环境能不能执行网页渲染
- `interactive_terminal`
  只表示当前进程是不是连着 TTY
- `auth_valid` / `nlm_auth_valid`
  只表示 NotebookLM 上传认证状态，不表示目标网站是否已登录
- `is_ready`
  这是面向“完整上传链路”的严格判断；即使它是 `false`，只要 Playwright 正常，网页转 PDF 仍然可能能用

## 安装

如果你的环境支持 `skills` CLI，可以直接安装：

```bash
npx skills add https://github.com/biniendafeliupv187/url-to-pdf
```

如果你只是想手动准备 Python 环境，`doctor.py` 给出的推荐步骤是：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install playwright
python -m playwright install chromium
```

不过大多数情况下，直接走 `python3 scripts/run.py ...` 就够了。

## 在 agent 里怎么用

告诉 agent：

> `@/url-to-pdf [URL]`

比如：

> `@/url-to-pdf https://juejin.cn/post/6844903448337448974`
