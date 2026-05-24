# GitHub Batch Downloader

粘贴 GitHub 链接即可批量下载仓库，国内网络下自动 fallback 到 ZIP 归档。支持子目录链接，只下需要的部分，不下整个仓库。

---

## 解决什么痛点

**以前是这样的：**

- 要下 20 个仓库，只能逐个 `git clone`，窗口切来切去，复制粘贴地址到眼酸
- 国内 GitHub 时灵时不灵，大仓库 git clone 卡死在 15%，等半天报 `early EOF`
- 看到别人分享的子目录链接（`.../tree/main/docs`），只能手动点进仓库、找到文件夹、再单独下载
- 下载完了不知道哪些成功哪些失败，终端滚动后无从追溯

**现在是这样的：**

- 把链接往脚本里一贴，自动逐个下载，实时显示进度和结果
- git 卡住 30 秒自动放弃，无缝 fallback 到 ZIP 下载，25 个仓库实测全部成功
- 直接粘贴子目录链接，自动识别并只提取该文件夹内容
- 每次运行生成 JSON 报告，成功/失败/跳过一清二楚

**适合谁用：**

- **技术调研者** —— 批量拉取竞品开源项目做代码分析，不用逐个 clone
- **资料收集者** —— 收集 GitHub 上的文档、配置模板、示例代码，子目录链接直接下
- **国内开发者** —— 网络环境不稳定，需要一个能自动兜底的下载工具

---

## 核心功能

| 功能 | 解决什么问题 |
|------|-------------|
| **双策略下载** | git 不稳定时自动 fallback 到 ZIP，不用手动重试 |
| **子目录识别** | 粘贴 `.../tree/main/docs` 这类链接，自动只下载 docs 文件夹，省流量省时间 |
| **实时进度** | git clone 显示传输进度；ZIP 下载显示百分比和已下载大小，心里有数 |
| **自动解压** | ZIP 下载完成后自动解压，并展平 `repo-branch/` 为 `repo/`，不用手动改文件夹名 |
| **跳过已存在** | 目标文件夹已存在时自动跳过，可安全重复执行同一列表 |
| **JSON 报告** | 每次运行生成带时间戳的 JSON 报告，记录每个仓库的状态、方法、错误信息 |
| **三种输入方式** | 交互式粘贴、命令行传参、文件读取，适应不同使用习惯 |
| **纯 Python** | 零第三方依赖，Python 3.8+ 直接运行 |

---

## 安装方法

### 前提条件

- **Python 3.8+**（验证：`python --version`）
- **Git**（验证：`git --version`，用于 git clone 策略）
- **SVN**（可选，验证：`svn --version`，用于子目录下载的最快路径）

### 下载脚本

```bash
# 克隆本项目
git clone https://github.com/decai335335-debug/github-repo-downloader.git
cd github-repo-downloader
```

脚本为单文件，也可直接下载 `github_batch_downloader.py` 到任意目录使用。

---

## 使用方法

### 场景一：交互式粘贴链接（最常见）

**什么时候用**：临时要下几个仓库，懒得建文件，直接粘贴最方便

```bash
python github_batch_downloader.py
```

1. 运行后按提示粘贴 GitHub 链接（支持空格或换行分隔多个链接）
2. 空行确认输入完毕
3. 按 **Enter** 使用默认输出目录，或输入自定义路径

```
==================================================
  GitHub Batch Downloader
==================================================

--------------------------------------------------
  [STEP 1] Paste GitHub links
  - Paste one or more links (space or newline separated)
  - Press Enter on an empty line to finish
--------------------------------------------------
  > https://github.com/microsoft/mcp-for-beginners/tree/main/translations/zh-CN
  > https://github.com/owner/repo2
  >
  [OK] 2 unique link(s) collected
```

### 场景二：从文件批量下载

**什么时候用**：要下载的仓库列表固定，下次还要用，或者列表很长

1. 创建文本文件 `repos.txt`，每行一个链接：

```text
# 这是注释，会被忽略
https://github.com/owner/repo1
https://github.com/owner/repo2
https://github.com/microsoft/mcp-for-beginners/tree/main/translations/zh-CN
```

2. 运行：

```bash
python github_batch_downloader.py repos.txt
```

### 场景三：命令行直接传参

**什么时候用**：在脚本、CI 或其他自动化流程中调用

```bash
python github_batch_downloader.py --links "url1 url2 url3"
```

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 语言 | Python 3.8+ |
| 网络 | `urllib.request`（ZIP 下载，标准库） |
| 文件处理 | `zipfile`、`pathlib`、`shutil`（标准库） |
| 进程调用 | `subprocess.run()`（git / svn 命令） |

| 工具链 | 用途 |
|--------|------|
| `git` | 仓库克隆（首选策略） |
| `svn` | 子目录导出（可选，最快路径） |

| 依赖库 | 说明 |
|--------|------|
| 无 | 纯标准库实现，零第三方依赖 |

---

## 文件结构

```
github-repo-downloader/
├── github_batch_downloader.py      # 主脚本（全部逻辑在此）
├── README.md                       # 使用说明
├── DEV_LOG.md                      # 开发日志与踩坑记录
├── clone_all.sh                    # Bash 辅助脚本（早期方案，已废弃）
├── repos.txt                       # 仓库链接列表示例
├── downloads/                      # 默认下载输出目录
│   ├── <repo_name>/                # 下载成功的仓库
│   └── download_report_*.json      # 运行报告
└── repos_remaining.txt             # 未完成的链接记录
```

---

## 配置说明

编辑脚本顶部的常量即可调整行为：

```python
# ===== Config =====
DEFAULT_OUTPUT = Path(__file__).parent / "downloads"   # 默认输出目录
GIT_TIMEOUT  = 120          # git clone 超时（秒）
ZIP_TIMEOUT  = 60           # ZIP 下载超时（秒）
GIT_RETRIES  = 1            # git 重试次数
ZIP_RETRIES  = 1            # ZIP 重试次数
SLOW_TIME    = 30           # git 低速检测时间（秒）
SLOW_LIMIT   = 1024         # git 低速阈值（字节/秒）
BRANCHES     = ["main", "master"]   # ZIP fallback 尝试的分支顺序
# ==================
```

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `GIT_TIMEOUT` | 120 | git clone 最长等待时间。网络慢可适当增大 |
| `ZIP_TIMEOUT` | 60 | 单个 ZIP 下载的超时时间 |
| `SLOW_TIME` / `SLOW_LIMIT` | 30 / 1024 | git 传输速度持续 30 秒低于 1KB/s 时自动断开，避免无限卡住 |
| `BRANCHES` | `["main", "master"]` | ZIP 下载依次尝试 main、master 分支 |

---

## 常见问题

### Q: 子目录链接下载下来的是整个仓库？

**A:** 请确认使用的是最新版脚本（v2.0+）。旧版会把子目录链接当成普通仓库处理，导致下载整仓。

如果已是最新版，脚本会按以下顺序尝试：
1. `svn export`（只下载子目录，最快，需安装 svn）
2. ZIP 子目录提取（下载整仓 ZIP，只解压子目录部分）
3. git clone 整仓（fallback）

检查输出中的 `[INFO] Subdirectory URL detected` 提示，确认子目录被正确识别。

### Q: git clone 总是超时怎么办？

**A:** 调大 `GIT_TIMEOUT`（如改为 300），或检查网络代理是否配置正确。脚本会在 git 失败后自动 fallback 到 ZIP，通常 ZIP 下载更稳定。

### Q: ZIP 下载也失败了？

**A:** 常见原因和排查：
- 仓库是私有的 &rarr; 需要配置 GitHub Token 或 SSH key
- 分支名不是 main/master &rarr; 修改 `BRANCHES` 配置添加目标分支
- 网络完全不通 &rarr; 检查代理/VPN 配置

### Q: 下载的 ZIP 没有 git 历史，怎么更新？

**A:** ZIP 归档只包含最新代码快照，无提交历史。如需后续更新，建议删除文件夹后重新运行脚本，或手动 `git clone` 替换。

### Q: 可以并发下载多个仓库吗？

**A:** 当前版本为顺序执行。实测并发下载 ZIP 时总带宽被分摊反而更慢，且对 GitHub 服务器不友好。25 个仓库的顺序执行在可接受时间内完成。

---

## 更新日志

### v2.0 &mdash; 子目录下载支持

- **新增**：识别 GitHub 子目录链接（`/tree/branch/path`），自动只下载该部分
- **新增**：SVN export 策略（最快路径，需安装 svn）
- **新增**：ZIP 子目录提取策略（下载整仓 ZIP，只解压指定子目录）
- **新增**：URL 解析支持 `/blob/` 路径（单文件链接，按子目录处理）
- **修复**：ZIP 下载时临时目录未创建导致的写入失败

### v1.0 &mdash; 稳定版

- git clone + ZIP fallback 双策略
- 实时进度显示（git + ZIP）
- 自动解压 + 文件夹展平
- main/master 分支自动尝试
- 已存在仓库自动跳过
- JSON 报告自动生成
- 支持文件输入和命令行参数

### v0.3 &mdash; ZIP Fallback（关键突破）

- 新增 ZIP 下载作为 git 失败后的自动 fallback
- ZIP 下载实时百分比进度
- 自动解压并重命名文件夹
- 新增 JSON 报告

### v0.2 &mdash; Python 顺序版

- 从 Bash 并发脚本迁移到 Python
- 顺序执行，输出清晰
- 基础 git clone 功能

### v0.1 &mdash; Bash 脚本（废弃）

- 初始 Shell 脚本 + `xargs -P` 并发
- 输出混乱，无进度显示，大仓库卡住无处理

---

**许可证**：MIT License
