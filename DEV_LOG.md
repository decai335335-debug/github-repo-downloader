# GitHub Batch Downloader 开发日志

> 记录从需求到最终版本的完整迭代过程，包括技术决策、踩坑记录、实际测试数据。

---

## 项目起源

**需求**：用户有 25 个 GitHub 仓库需要批量下载到本地，用于后续技术分析。

**约束条件**：
- 国内网络访问 GitHub 不稳定
- 部分仓库体积较大（含音频资源、文档等）
- 需要明确的进度反馈和失败报告
- 需要能重复运行（跳过已下载的）

**新增需求（v2.0）**：支持子目录链接的直接下载。用户经常遇到别人分享的 GitHub 链接指向仓库中的某个子文件夹（如 `.../tree/main/docs`），旧版本会误把子目录路径当成仓库名处理，导致 404 失败。

---

## 迭代时间线

### v0.1 -- Bash 脚本方案（废弃）

**初始思路**：用 Shell 脚本 + `xargs -P` 并发执行 `git clone`。

**问题**：
- Git Bash 环境下并发控制复杂
- 终端输出混在一起，无法区分哪个仓库在报错
- 大仓库卡住时无法自动处理
- 没有进度显示

**结论**：Shell 脚本不适合这个场景，转用 Python。

---

### v0.2 -- Python 顺序版

**改进**：
- 用 Python `subprocess.run()` 顺序执行 `git clone`
- 每个仓库独立处理，输出清晰
- 失败时记录日志

**暴露的问题**：
- 2 个大仓库（`sound_portfolio`、`GA4_Wwise`）`git clone` 失败
  - `sound_portfolio`：网络连接被远程主机强制关闭
  - `GA4_Wwise`：传输速度持续低于 1KB/s，120 秒超时后仍不完整
- 失败后没有任何补救措施，只能手动处理

---

### v0.3 -- ZIP Fallback 版（关键突破）

**核心洞察**：git 协议在国内不稳定，但 GitHub 的 HTTPS ZIP 下载通常更可靠（CDN 分发）。

**新增功能**：
1. **双策略下载**：git clone 失败 -> 自动尝试下载 ZIP
2. **ZIP 下载实时进度**：按 chunk 读取，计算百分比
3. **自动解压**：ZIP 下载后自动解压并展平文件夹层级
4. **多分支尝试**：main 不存在则尝试 master
5. **JSON 报告**：生成结构化报告，记录每个仓库的成功/失败状态和方法

**关键实现细节**：

#### ZIP 下载与进度显示

```python
chunk_size = 64 * 1024
with open(zip_path, 'wb') as f:
    while True:
        chunk = req.read(chunk_size)
        if not chunk:
            break
        f.write(chunk)
        downloaded += len(chunk)
        if total > 0:
            pct = downloaded * 100 // total
            print(f"\r      [ZIP] Downloading: {pct}% ...", end="", flush=True)
```

#### 文件夹展平（GitHub ZIP 的特殊结构）

GitHub 的 ZIP 解压后文件夹名是 `repo-branch/`（如 `GA4_Wwise-main/`），需要重命名为 `repo/`：

```python
top_dir = z.namelist()[0].split('/')[0]   # "repo-main"
extracted = output_dir / top_dir           # .../repo-main
target = output_dir / repo_name            # .../repo
extracted.rename(target)                   # 重命名
```

#### Git 低速检测

通过环境变量让 git 在传输过慢时主动放弃，避免无限等待：

```python
env["GIT_HTTP_LOW_SPEED_TIME"] = "30"      # 30 秒
env["GIT_HTTP_LOW_SPEED_LIMIT"] = "1024"   # 低于 1KB/s
```

---

### v1.0 -- 稳定版

**最终功能清单**：
- [x] git clone 实时进度显示（`--progress`）
- [x] git 低速自动断开（30 秒 < 1KB/s）
- [x] git 失败自动 fallback 到 ZIP
- [x] ZIP 下载实时百分比
- [x] ZIP 自动解压 + 文件夹展平
- [x] main/master 分支自动尝试
- [x] 已存在仓库自动跳过
- [x] JSON 报告自动生成
- [x] 支持文件输入和命令行参数两种模式
- [x] 纯 Python 标准库，零依赖

---

### v2.0 -- 子目录下载支持

**需求触发**：用户粘贴子目录链接 `https://github.com/microsoft/mcp-for-beginners/tree/main/translations/zh-CN`，旧版本解析错误，把 `translations/zh-CN` 当成仓库名，git clone 和 ZIP 均 404。

**实现方案**：

#### URL 解析增强

```python
def parse_owner_repo(url: str) -> tuple[str, str, str, str, str]:
    # 检测 /tree/branch/path 或 /blob/branch/path 模式
    for marker in ("/tree/", "/blob/"):
        if marker in url:
            branch = parts[marker_idx + 1]
            subdir = "/".join(parts[marker_idx + 2:])
    return owner, repo, branch, subdir, clean_url
```

#### 四级 fallback 策略（子目录 URL）

| 优先级 | 方法 | 原理 | 条件 |
|--------|------|------|------|
| 1 | SVN export | GitHub SVN 桥接：`github.com/owner/repo/trunk/subdir` | 需安装 svn |
| 2 | ZIP 子目录提取 | 下载整仓 ZIP，只解压指定前缀的文件 | 无需额外工具 |
| 3 | git clone 整仓 | 下载完整仓库 | 网络允许 |
| 4 | ZIP 整仓下载 | 下载整仓 ZIP 并解压 | 最终 fallback |

#### ZIP 子目录提取实现

```python
def download_subdir_zip(owner, repo, branch, subdir, dest, output_dir):
    # 1. 下载整仓 ZIP
    download_zip(owner, repo, temp_dest)
    
    # 2. 只提取子目录下的文件
    prefix = f"{top_dir}/{subdir}/"
    for name in zf.namelist():
        if name.startswith(prefix) and not name.endswith('/'):
            rel_path = name[len(prefix):]
            out_path = dest / rel_path
            # 写入目标位置
```

#### 修复的 bug

**问题**：`download_zip` 函数在写入 ZIP 文件前未确保父目录存在，当作为子模块被 `download_subdir_zip` 调用时，临时目录可能不存在，导致 `No such file or directory`。

**修复**：在 `download_zip` 开头添加 `zip_path.parent.mkdir(parents=True, exist_ok=True)`。

---

## 踩坑记录

| # | 问题 | 根因 | 解决方案 | 涉及版本 |
|---|------|------|---------|---------|
| 1 | Shell 并发脚本输出混乱 | `xargs -P` 并发时 stdout 交错 | 改用 Python 顺序执行，每个仓库独立输出 | v0.1 -> v0.2 |
| 2 | Git clone 大仓库超时 | 国内网络 git 协议不稳定，大文件传输慢 | 设置 `GIT_HTTP_LOW_SPEED_TIME/LIMIT`，超时后 cleanup | v0.2 |
| 3 | Git 失败后无补救 | 网络问题非用户可控，不能要求手动重试 | 自动 fallback 到 ZIP 下载 | v0.3 |
| 4 | ZIP 解压后文件夹名不对 | GitHub ZIP 解压为 `repo-branch/`，不是 `repo/` | 读取 ZIP 内顶层文件夹名，重命名 | v0.3 |
| 5 | ZIP 下载无进度反馈 | `urlopen().read()` 一次性读取，大文件等待时间长 | 分 chunk 读取，实时计算百分比 | v0.3 |
| 6 | 不知道最终哪些成功哪些失败 | 终端滚动后难以回溯 | 生成 JSON 报告，持久化记录 | v0.3 |
| 7 | 子目录链接解析错误 | URL 含 `/tree/branch/path`，旧解析逻辑把 path 当仓库名 | 增强 `parse_owner_repo`，识别 tree/blob 模式并提取 branch + subdir | v2.0 |
| 8 | ZIP 子目录提取时目录不存在 | `download_zip` 未确保父目录存在，子模块调用时失败 | 在 `download_zip` 开头添加 `mkdir(parents=True, exist_ok=True)` | v2.0 |

---

## 设计决策

### 为什么是 git + ZIP 双策略，而不是只用 ZIP？

| 方案 | 优点 | 缺点 | 决策 |
|------|------|------|------|
| 只用 git | 完整历史、分支信息、后续可 `git pull` 更新 | 国内不稳定、大文件传输慢 | 优先尝试 |
| 只用 ZIP | 下载稳定、速度快 | 无历史记录、无法更新 | fallback |
| git + ZIP | 兼顾两者 | 代码稍复杂 | **采用** |

### 为什么是顺序执行，不是并发？

**测试过并发（ThreadPoolExecutor）**：
- 并发下载多个 ZIP 时，总带宽被分摊，每个都变慢
- git 并发对 GitHub 服务器不友好，可能触发限流
- 顺序执行输出清晰，每个仓库的日志连续可读

**结论**：25 个仓库的顺序执行在可接受时间内完成，并发收益不明显，保持简单。

### 为什么默认输出目录是脚本所在目录？

- 脚本通常放在目标下载目录中运行
- 用户可通过修改 `DEFAULT_OUTPUT` 一行代码调整
- 避免硬编码绝对路径，提高可移植性

### 为什么子目录下载用四级 fallback，不是直接下载整仓？

| 方案 | 优点 | 缺点 | 决策 |
|------|------|------|------|
| 直接下载整仓 | 实现简单 | 浪费带宽和磁盘，大仓库子目录可能只有几 MB | 不作为首选 |
| SVN export | 只下载子目录内容，最快最省 | 需安装 svn，部分环境没有 | 优先尝试 |
| ZIP 子目录提取 | 无需额外工具 | 需下载整仓 ZIP（临时），然后过滤 | 第二优先 |
| 四级 fallback | 最大化成功率 | 代码复杂 | **采用** |

---

## 实际测试数据

### 测试环境

- OS: Windows 11
- Python: 3.12
- 网络: 国内宽带（GitHub 访问需代理/直连不稳定）
- 测试时间: 2026-05-24 / 2026-05-25

### v1.0 测试结果（25 个仓库）

**总计：25 个仓库，全部成功**

| 方法 | 数量 | 占比 | 平均耗时 |
|------|------|------|---------|
| git clone 成功 | 23 | 92% | ~10-30 秒/个 |
| ZIP fallback 成功 | 2 | 8% | ~15-45 秒/个 |
| 失败 | 0 | 0% | -- |

#### Fallback 案例分析

**Case 1: `sound_portfolio`**

```
[1/3] Git clone: sound_portfolio
      fatal: unable to access '...': LibreSSL SSL_read: 
      SSL_ERROR_SYSCALL, errno 10054
      Git failed: git error
[2/3] ZIP fallback: sound_portfolio
      [ZIP] Trying main branch: ...
      [ZIP] Downloading: 100% (139KB / 139KB)
[3/3] Unzipping: sound_port_portfolio
      [OK] Success (zip)
```

**根因**：TCP 连接被远程主机重置（RST），git 协议层断开。
**ZIP 成功**：HTTPS 连接建立新会话，CDN 节点可能不同，传输完成。

**Case 2: `GA4_Wwise`**

```
[1/3] Git clone: GA4_Wwise
      remote: Enumerating objects: 1123, done.
      remote: Counting objects: 100% (1123/1123), done.
      receiving objects:  15% (168/1123), 196.00 KiB | 1.00 KiB/s
      ...（持续低于 1KB/s）...
      Git failed: git timeout (120s)
[2/3] ZIP fallback: GA4_Wwise
      [ZIP] Trying main branch: ...
      [ZIP] Downloading: 100% (2456KB / 2456KB)
[3/3] Unzipping: GA4_Wwise
      [OK] Success (zip)
```

**根因**：仓库包含较大二进制文件（音频资源），git 对象传输极慢。
**ZIP 成功**：GitHub ZIP 是打包好的归档文件，单文件顺序下载，速度稳定。

### v2.0 子目录下载测试

| 测试链接 | 结果 | 方法 | 说明 |
|---------|------|------|------|
| `.../tree/main/translations/zh-CN` | 成功 | zip_subdir | SVN 未安装，fallback 到 ZIP 子目录提取，正确提取 19 个文件 |
| `.../tree/dev/src/utils` | 解析正确 | -- | URL 解析测试通过，branch=dev，subdir=src/utils |
| `.../blob/main/README.md` | 解析正确 | -- | URL 解析测试通过，blob 路径识别正常 |

---

## 性能数据

| 指标 | 数值 |
|------|------|
| 支持下载方式 | 4 种（git clone、ZIP 整仓、ZIP 子目录、SVN export） |
| ZIP 分支尝试 | main -> master |
| git 低速检测 | 30 秒 < 1KB/s |
| git 超时 | 120 秒 |
| ZIP 超时 | 60 秒 |
| 输出格式 | 文件夹 + JSON 报告 |
| Python 版本 | 3.8+ |
| 第三方依赖 | 无 |

---

## 文件位置

```
github-repo-downloader/
├── github_batch_downloader.py      # 主脚本
├── README.md                       # 使用说明
├── DEV_LOG.md                      # 本文件
├── clone_all.sh                    # 早期 Bash 方案（已废弃）
├── repos.txt                       # 仓库链接列表示例
├── downloads/                      # 默认下载输出目录
│   ├── <repo_name>/                # 下载成功的仓库
│   └── download_report_*.json      # 运行报告
└── repos_remaining.txt             # 未完成的链接记录
```

---

## 后续可改进

| 想法 | 优先级 | 说明 |
|------|--------|------|
| 断点续传 | 低 | ZIP 下载支持 `Range` 头，网络中断可续传 |
| 并发下载 | 低 | 小仓库可并发，大仓库顺序执行 |
| 代理支持 | 低 | 自动检测系统代理或支持 `--proxy` 参数 |
| 增量更新 | 低 | 已存在的仓库执行 `git pull` 而非跳过 |
| 分支选择 | 低 | 支持指定非 main/master 分支（当前子目录 URL 已支持） |
