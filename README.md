# @url-to-pdf Skill

将网页 URL 高质量转换为 PDF 文件的专业技能，支持一键上传到 Google NotebookLM。

## 工作流程
![流程图](./workflow.png)


## 核心功能

| 功能 | 描述 |
|------|------|
| 🏥 **自愈式诊断** | 自动检测并修复环境问题 (uv, nlm, playwright) |
| 🔐 **交互式会话管理** | 自动检测登录需求，无缝切换到可见浏览器让用户登录，保存会话供后续自动运行使用 |
| 🥷 **反爬虫规避** | 伪装 WebDriver 指纹，配置真实 User-Agent，防止 cloudflare/安全拦截 |
| 📜 **深度完整捕获** | 智能识别自定义滚动容器 (如 Simplebar)，滚动触发所有懒加载内容，递归解除 DOM 高度限制 (flex, overflow)，确保从顶到底的完整打印 (支持 10MB+ PDF) |
| 🧹 **纯净打印模式** | 自动注入 CSS 隐藏导航栏、侧边栏、悬浮 footer 等干扰元素，还原纯净阅读体验 |
| 🚀 **零配置上传** | 通过 `notebooklm-mcp-cli` 直接 HTTP 对接 NotebookLM |
| 📁 **智能路径管理** | 无硬编码路径，跨用户账户无缝工作 |

## 工作原理

1. **Doctor 检查**: 技能首先运行诊断，确保所有工具就绪
2. **PDF 生成**: Chromium 渲染页面并保存为 PDF 到 `~/Downloads/PDF/`
3. **NotebookLM 集成**:
   - 列出当前笔记本列表
   - 提示选择目标笔记本或创建新笔记本
   - 通过 HTTP API 即时上传文件

## 技术亮点

### 1. 多模式登录检测
- **Broad 模式** (无会话): 检测"登录/注册"等关键词
- **Strict 模式** (有会话): 仅检测"未登录/请登录"等明确状态
- **防误判**: 即使导航栏有"登录"按钮，已登录用户也不会被拦截

### 2. 智能滚动容器识别
- 自动查找最大滚动容器 (Simplebar 等自定义滚动)
- 递归向上遍历 DOM，解除 flex/overflow 高度限制
- 确保完整捕获无限滚动页面

### 3. 安全的 UI 隐藏策略
- 使用 token 级别匹配 (避免误杀如 `use-femenu`)
- 白名单保护: `body`、`main`、`article`、`#js_content` 等核心内容
- 支持微信等国内平台特殊 class 命名

### 4. 会话持久化
- 登录后保存 `storage_state` 到 `~/.url-to-pdf/session.json`
- 后续运行自动加载 Cookie，无需重复登录

## 安装方式

### 通过 skills.sh / OpenSkills 安装

如果你的环境支持 `skills` CLI，可以直接从 GitHub 安装：

```bash
npx skills add https://github.com/biniendafeliupv187/url-to-pdf
```

### 手动安装

也可以将技能文件夹添加到你的 agentic 环境中。首次运行时会通过内置诊断工具引导安装依赖 (`uv`, `playwright`, `nlm`)。

## 使用方法

告诉 agent:
> `@/url-to-pdf [URL]`

示例:
> `@/url-to-pdf https://juejin.cn/post/6844903448337448974`

---

*为专业研究工作流打造*
