#!/usr/bin/env python3
"""
GitHub Batch Downloader — Git clone + ZIP fallback
=====================================================
批量下载 GitHub 仓库的工具。

工作流程：
  1. 首先尝试 git clone（保留完整 Git 历史，最快）
  2. 如果超时或失败 → 下载 ZIP 压缩包并自动解压
  3. 如果 ZIP 也失败 → 向用户报告

三种使用方式：
  交互式:     python github_batch_downloader.py
  文件模式:   python github_batch_downloader.py repos.txt
  行内模式:   python github_batch_downloader.py --links "url1 url2"
"""

import os           # 操作系统接口：环境变量、路径
import sys          # 系统相关：命令行参数、退出
import subprocess   # 启动外部命令：git clone
import json         # JSON 序列化：生成下载报告
import zipfile      # ZIP 压缩包处理
import shutil       # 高级文件操作：删除目录树
from pathlib import Path       # 面向对象的路径操作
from datetime import datetime  # 获取当前时间
from urllib.request import urlopen   # HTTP 请求：下载 ZIP
from urllib.error import URLError, HTTPError  # HTTP 错误处理

# ==============================================================================
# 配置常量
# ==============================================================================
# Path(__file__) 获取当前脚本文件的路径
# .parent 获取父目录（即脚本所在的文件夹）
DEFAULT_OUTPUT = Path(__file__).parent / "downloads"

GIT_TIMEOUT = 120          # git clone 超时时间（秒）
ZIP_TIMEOUT = 60           # ZIP 下载超时时间（秒）
GIT_RETRIES = 1            # git 重试次数
ZIP_RETRIES = 1            # ZIP 重试次数
SLOW_TIME = 30             # git 低速超时时间（秒）
SLOW_LIMIT = 1024          # git 低速阈值（字节/秒）
BRANCHES = ["main", "master"]  # ZIP 下载时尝试的分支顺序


def run_git_clone(url: str, dest: Path) -> tuple[bool, str]:
    """
    执行 git clone，保留实时进度输出。
    
    参数:
        url (str): GitHub 仓库 URL
        dest (Path): 本地保存路径
    
    返回:
        tuple[bool, str]: (是否成功, 错误信息)
                           成功时错误信息为空字符串
    """
    # 复制当前环境变量，避免修改系统环境
    env = os.environ.copy()
    # 设置 Git 的低速检测参数：如果 30 秒内速度低于 1024 字节/秒，认为连接断开
    env["GIT_HTTP_LOW_SPEED_TIME"] = str(SLOW_TIME)
    env["GIT_HTTP_LOW_SPEED_LIMIT"] = str(SLOW_LIMIT)

    # 构建 git clone 命令
    # --depth=1: 只下载最新一次提交（浅克隆，大幅减小体积）
    # --single-branch: 只下载默认分支
    # --progress: 显示进度信息
    cmd = ["git", "clone", "--depth=1", "--single-branch", "--progress", url, str(dest)]

    try:
        # subprocess.run 执行命令
        # capture_output=False: 不捕获输出，直接在终端显示 git 进度
        # text=True: 以文本模式处理输出
        # timeout: 超时时间
        # env: 使用修改后的环境变量
        result = subprocess.run(cmd, capture_output=False, text=True, timeout=GIT_TIMEOUT, env=env)
        
        # returncode == 0 表示命令成功执行
        return result.returncode == 0, ""
    
    except subprocess.TimeoutExpired:
        # 超时异常：清理已下载的部分文件
        cleanup(dest)
        return False, f"git timeout ({GIT_TIMEOUT}s)"
    
    except Exception as e:
        cleanup(dest)
        return False, str(e)


def cleanup(path: Path):
    """
    删除指定路径（文件或文件夹）。
    
    参数:
        path (Path): 要删除的路径
    """
    if path.exists():
        # shutil.rmtree 递归删除目录树
        # ignore_errors=True: 删除失败时不报错（例如文件被占用）
        shutil.rmtree(path, ignore_errors=True)


def parse_owner_repo(url: str) -> tuple[str, str, str, str, str]:
    """
    从 GitHub URL 中提取信息。
    
    支持的 URL 格式：
      - 根目录: https://github.com/owner/repo
      - 子目录: https://github.com/owner/repo/tree/main/path/to/subdir
      - 文件:   https://github.com/owner/repo/blob/main/path/to/file
    
    参数:
        url (str): GitHub URL
    
    返回:
        tuple: (owner, repo, branch, subdir_path, clean_url)
               owner: 仓库所有者（如 "microsoft"）
               repo:  仓库名（如 "vscode"）
               branch: 分支名（如 "main"），根目录为空字符串
               subdir_path: 子目录路径，根目录为空字符串
               clean_url: 纯净的仓库根 URL
    """
    # rstrip("/") 去掉末尾的斜杠
    # replace(".git", "") 去掉 .git 后缀
    url = url.rstrip("/").replace(".git", "")
    
    # split("/") 把 URL 按斜杠分割成列表
    # 例如: ["https:", "", "github.com", "microsoft", "vscode", "tree", "main", "src"]
    parts = url.split("/")
    
    # 找到 "github.com" 的索引位置
    gh_idx = parts.index("github.com")
    
    # owner 在 github.com 后面第 1 个
    owner = parts[gh_idx + 1]
    # repo 在 github.com 后面第 2 个
    repo = parts[gh_idx + 2]
    # 构建纯净的仓库根 URL
    clean_url = f"https://github.com/{owner}/{repo}"
    
    # 检测子目录 URL
    branch = ""
    subdir = ""
    
    # 检查 URL 中是否包含 /tree/ 或 /blob/
    for marker in ("/tree/", "/blob/"):
        if marker in url:
            # marker.strip("/") 去掉两端的斜杠，得到 "tree" 或 "blob"
            # parts.index 找到它在列表中的位置
            marker_idx = parts.index(marker.strip("/"))
            # 分支名在 marker 后面
            branch = parts[marker_idx + 1] if marker_idx + 1 < len(parts) else "main"
            # 子目录路径：marker 后面第 2 个开始到末尾
            subdir = "/".join(parts[marker_idx + 2:])
            break
    
    return owner, repo, branch, subdir, clean_url


def download_zip(owner: str, repo: str, dest: Path) -> tuple[bool, str]:
    """
    从 GitHub 下载 ZIP 压缩包。
    
    先尝试 main 分支，如果不存在再尝试 master 分支。
    
    参数:
        owner (str): 仓库所有者
        repo (str): 仓库名
        dest (Path): 保存路径（不含 .zip 后缀）
    
    返回:
        tuple[bool, str]: (是否成功, 错误信息)
    """
    # dest.with_suffix(".zip") 把路径的扩展名改为 .zip
    # 例如 dest="downloads/vscode" → zip_path="downloads/vscode.zip"
    zip_path = dest.with_suffix(".zip")
    # 确保父目录存在
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    # 遍历分支列表（main → master）
    for branch in BRANCHES:
        # GitHub ZIP 下载 URL 格式
        zip_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"
        print(f"      [ZIP] Trying {branch} branch: {zip_url}")

        # 重试循环
        for attempt in range(ZIP_RETRIES + 1):
            try:
                # urlopen 打开 URL 连接
                req = urlopen(zip_url, timeout=ZIP_TIMEOUT)
                
                # 获取 Content-Length 头（文件总大小）
                # 如果服务器没提供，默认为 0
                total = int(req.headers.get('Content-Length', 0))
                downloaded = 0
                chunk_size = 64 * 1024  # 每次读取 64KB

                # 以二进制写模式打开文件
                with open(zip_path, 'wb') as f:
                    # 循环读取数据块
                    while True:
                        chunk = req.read(chunk_size)  # 读取 chunk_size 字节
                        if not chunk:
                            break  # 读完了
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        # 显示下载进度
                        if total > 0:
                            pct = downloaded * 100 // total  # 整数百分比
                            print(f"\r      [ZIP] Downloading: {pct}% ({downloaded//1024}KB / {total//1024}KB)", end="", flush=True)
                
                print()  # 换行，结束进度显示
                return True, ""

            except HTTPError as e:
                # HTTP 错误处理
                if e.code == 404:
                    print(f"      [ZIP] Branch '{branch}' not found (404)")
                    break  # 该分支不存在，尝试下一个分支
                err = f"HTTP {e.code}"
            
            except URLError as e:
                err = f"Network error: {e.reason}"
            
            except Exception as e:
                err = str(e)

            # 重试判断
            if attempt < ZIP_RETRIES:
                print(f"      [ZIP] Retry {attempt + 1}/{ZIP_RETRIES}...")
            else:
                print(f"      [ZIP] Failed: {err}")

    # 所有分支都失败了
    return False, "ZIP download failed (all branches)"


def download_subdir_svn(owner: str, repo: str, branch: str, subdir: str, dest: Path) -> tuple[bool, str]:
    """
    使用 SVN 导出 GitHub 子目录。
    
    GitHub 支持 SVN 桥接：
      https://github.com/owner/repo/trunk/subdir（main/master 分支）
      https://github.com/owner/repo/branches/branch_name/subdir（其他分支）
    
    优点：只下载子目录的内容，不下载整个仓库。
    
    参数:
        owner, repo, branch, subdir: 从 URL 解析出的信息
        dest (Path): 本地保存路径
    
    返回:
        tuple[bool, str]: (是否成功, 错误信息)
    """
    # 根据分支名构建 SVN URL
    if branch in ("main", "master"):
        svn_url = f"https://github.com/{owner}/{repo}/trunk/{subdir}"
    else:
        svn_url = f"https://github.com/{owner}/{repo}/branches/{branch}/{subdir}"
    
    print(f"      [SVN] Exporting subdirectory via SVN: {svn_url}")
    
    try:
        # svn export --force: 强制覆盖已存在的文件
        cmd = ["svn", "export", "--force", svn_url, str(dest)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=GIT_TIMEOUT)
        if result.returncode == 0:
            return True, ""
        else:
            return False, f"svn error: {result.stderr.strip()[:200]}"
    except FileNotFoundError:
        return False, "svn command not found (not installed)"
    except subprocess.TimeoutExpired:
        return False, f"svn timeout ({GIT_TIMEOUT}s)"
    except Exception as e:
        return False, str(e)


def download_subdir_zip(owner: str, repo: str, branch: str, subdir: str, dest: Path, output_dir: Path) -> tuple[bool, str]:
    """
    下载完整仓库 ZIP，但只解压指定的子目录。
    
    这是 SVN 失败后的备选方案。
    
    参数:
        owner, repo, branch, subdir: 仓库信息
        dest (Path): 子目录的本地保存路径
        output_dir (Path): 临时文件存放目录
    
    返回:
        tuple[bool, str]: (是否成功, 错误信息)
    """
    # 创建临时目录名，避免冲突
    temp_dest = output_dir / f"__temp_{repo}_{branch}"
    
    print(f"      [Subdir-ZIP] Downloading full repo ZIP, will extract only: {subdir}")
    
    # 第一步：下载完整 ZIP
    ok, err = download_zip(owner, repo, temp_dest)
    if not ok:
        return False, err
    
    # 第二步：解压指定子目录
    zip_path = temp_dest.with_suffix(".zip")
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            # GitHub ZIP 解压后的顶层目录名格式：repo-branch/
            top_dir = zf.namelist()[0].split('/')[0]
            # 构建子目录在 ZIP 中的前缀路径
            prefix = f"{top_dir}/{subdir}/"
            extracted_any = False
            
            # 遍历 ZIP 中的所有文件
            for name in zf.namelist():
                # 检查是否以子目录前缀开头，且不是文件夹（以 / 结尾的是文件夹）
                if name.startswith(prefix) and not name.endswith('/'):
                    # 计算在子目录内的相对路径
                    rel_path = name[len(prefix):]
                    out_path = dest / rel_path
                    # 确保父目录存在
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    # 从 ZIP 中读取文件内容，写入到目标路径
                    with zf.open(name) as src, open(out_path, 'wb') as dst:
                        dst.write(src.read())
                    extracted_any = True
            
            # 如果没有任何文件被解压，说明子目录不存在
            if not extracted_any:
                return False, f"Subdirectory '{subdir}' not found in archive"
        
        # 清理临时文件
        zip_path.unlink(missing_ok=True)  # 删除 ZIP 文件
        cleanup(temp_dest)                 # 删除解压后的临时目录
        return True, ""
        
    except Exception as e:
        return False, str(e)


def unzip_archive(zip_path: Path, output_dir: Path, repo_name: str) -> tuple[bool, str]:
    """
    解压 ZIP 文件，并将顶层文件夹重命名为仓库名。
    
    GitHub ZIP 解压后的文件夹名是 "repo-branch/" 格式，
    这个函数把它重命名为干净的 "repo/"。
    
    参数:
        zip_path (Path): ZIP 文件路径
        output_dir (Path): 解压目标目录
        repo_name (str): 期望的文件夹名
    
    返回:
        tuple[bool, str]: (是否成功, 错误信息)
    """
    try:
        with zipfile.ZipFile(zip_path, 'r') as z:
            # 获取 ZIP 中的第一个路径，提取顶层目录名
            top_dir = z.namelist()[0].split('/')[0]
            z.extractall(output_dir)  # 解压到 output_dir

        # 重命名：从 "repo-branch" 改为 "repo"
        extracted = output_dir / top_dir
        target = output_dir / repo_name
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        extracted.rename(target)
        
        # 删除 ZIP 文件
        zip_path.unlink()
        return True, ""
    except Exception as e:
        return False, str(e)


def download_one(url: str, output_dir: Path, url_index: int = 1, total: int = 1) -> dict:
    """
    下载单个仓库或子目录。
    
    子目录下载的降级策略（按优先级排序）：
      1. SVN export（最快，只下载子目录）
      2. ZIP subdir extraction（下载全量，只解压部分）
      3. Git clone whole repo（最慢但最可靠）
      4. ZIP whole repo fallback
    
    根目录下载的策略：
      1. Git clone
      2. ZIP fallback
    
    参数:
        url (str): GitHub URL
        output_dir (Path): 保存目录
        url_index (int): 当前是第几个 URL（用于显示进度）
        total (int): 总共有几个 URL
    
    返回:
        dict: 下载结果，包含 name, url, status, method, error
    """
    # 解析 URL
    owner, repo, branch, subdir, clean_url = parse_owner_repo(url)
    
    # 确定输出文件夹名
    if subdir:
        # 子目录：用"仓库名_子目录最后一级"作为文件夹名，避免不同仓库的同名子目录冲突
        # 例如 agents-course/units/zh-CN → name="agents-course_zh-CN"
        subdir_leaf = subdir.rstrip("/").split("/")[-1]
        name = f"{repo}_{subdir_leaf}"
        is_subdir = True
    else:
        name = repo
        is_subdir = False
    
    dest = output_dir / name

    # 初始化结果字典
    result = {
        "name": name,
        "url": url,
        "status": "",      # success / skipped / failed
        "method": "",      # git / zip / svn
        "error": ""
    }

    # 如果目标已存在，跳过
    if dest.exists():
        result["status"] = "skipped"
        result["method"] = "already_exists"
        return result

    # ============ 子目录下载逻辑 ============
    if is_subdir:
        print(f"  [INFO] Subdirectory URL detected: {subdir}")
        
        # Phase 1: SVN export（最快，只下载子目录内容）
        print(f"  [1/4] SVN export: {owner}/{repo}/{subdir}")
        ok, err = download_subdir_svn(owner, repo, branch or "main", subdir, dest)
        if ok:
            result["status"] = "success"
            result["method"] = "svn"
            return result
        print(f"        SVN failed: {err}")
        cleanup(dest)
        
        # Phase 2: ZIP 子目录提取
        print(f"  [2/4] ZIP subdir extraction: {owner}/{repo}/{subdir}")
        ok, err = download_subdir_zip(owner, repo, branch or "main", subdir, dest, output_dir)
        if ok:
            result["status"] = "success"
            result["method"] = "zip_subdir"
            return result
        print(f"        ZIP subdir failed: {err}")
        cleanup(dest)
        
        # Phase 3: Git clone 整个仓库
        print(f"  [3/4] Git clone (whole repo fallback): {repo}")
        whole_dest = output_dir / repo
        ok, err = run_git_clone(clean_url + ".git", whole_dest)
        if ok:
            result["status"] = "success"
            result["method"] = "git_whole_repo"
            print(f"        [NOTE] Downloaded whole repo; subdirectory is at: {whole_dest}/{subdir}")
            return result
        print(f"        Git failed: {err}")
        cleanup(whole_dest)
        
        # Phase 4: ZIP 整个仓库（最后手段）
        print(f"  [4/4] ZIP fallback (whole repo): {repo}")
        ok, err = download_zip(owner, repo, whole_dest)
        if ok:
            ok2, err2 = unzip_archive(whole_dest.with_suffix(".zip"), output_dir, repo)
            if ok2:
                result["status"] = "success"
                result["method"] = "zip_whole_repo"
                print(f"        [NOTE] Downloaded whole repo; subdirectory is at: {output_dir}/{repo}/{subdir}")
                return result
            else:
                result["status"] = "failed"
                result["method"] = "zip_unzip_failed"
                result["error"] = err2
                return result
        
        # 全部失败
        print(f"        All methods failed: {err}")
        result["status"] = "failed"
        result["method"] = "all_methods_failed"
        result["error"] = err
        return result

    # ============ 根目录下载逻辑 ============
    # Phase 1: Git clone
    print(f"  [1/3] Git clone: {name}")
    ok, err = run_git_clone(clean_url + ".git", dest)
    if ok:
        result["status"] = "success"
        result["method"] = "git"
        return result

    print(f"        Git failed: {err}")
    cleanup(dest)

    # Phase 2: ZIP fallback
    print(f"  [2/3] ZIP fallback: {name}")
    ok, err = download_zip(owner, repo, dest)
    if ok:
        print(f"  [3/3] Unzipping: {name}")
        ok2, err2 = unzip_archive(dest.with_suffix(".zip"), output_dir, name)
        if ok2:
            result["status"] = "success"
            result["method"] = "zip"
            return result
        else:
            result["status"] = "failed"
            result["method"] = "zip_unzip_failed"
            result["error"] = err2
            return result

    # Phase 3: 全部失败
    print(f"        ZIP also failed: {err}")
    result["status"] = "failed"
    result["method"] = "all_methods_failed"
    result["error"] = err
    return result


def load_links(source) -> list[str]:
    """
    从各种来源加载 URL 列表。
    
    支持的来源：
      - 列表：直接使用
      - 文件：每行一个 URL
      - 字符串：空格分隔的多个 URL
    
    参数:
        source: 列表、文件路径或 URL 字符串
    
    返回:
        list[str]: URL 列表
    """
    links = []
    
    # 如果已经是列表，直接返回
    if isinstance(source, list):
        return [u.strip() for u in source if u.strip()]
    
    path = Path(source)
    
    # 如果是文件，逐行读取
    if path.is_file():
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                # 跳过空行和注释行（以 # 开头）
                if line and not line.startswith("#"):
                    links.append(line)
    else:
        # 不是文件，当作字符串处理：按空格分割
        for part in source.split():
            part = part.strip()
            if part and not part.startswith("#"):
                links.append(part)
    
    return links


def prompt_links() -> list[str]:
    """
    交互式提示：粘贴多个链接，空行结束。
    
    返回:
        list[str]: 去重后的 URL 列表
    """
    print()
    print("-" * 50)
    print("  [STEP 1] Paste GitHub links")
    print("  - Paste one or more links (space or newline separated)")
    print("  - Press Enter on an empty line to finish")
    print("-" * 50)

    raw_lines = []
    try:
        while True:
            line = input("  > ")
            if line.strip() == "":
                break  # 空行结束输入
            raw_lines.append(line)
    except (EOFError, KeyboardInterrupt):
        print("\n[ABORTED] Cancelled by user")
        sys.exit(0)

    # 将所有输入合并为一个字符串，然后分割成 URL
    all_text = "\n".join(raw_lines)
    links = []
    for part in all_text.replace(",", " ").split():
        part = part.strip()
        if part and not part.startswith("#"):
            links.append(part)

    # 去重（保持顺序）
    seen = set()
    unique_links = []
    for url in links:
        if url not in seen:
            seen.add(url)
            unique_links.append(url)

    if not unique_links:
        print("  [ERROR] No valid links found")
        sys.exit(1)

    print(f"  [OK] {len(unique_links)} unique link(s) collected")
    return unique_links


def prompt_output_dir(default: Path) -> Path:
    """
    询问用户保存位置。
    
    参数:
        default (Path): 默认保存目录
    
    返回:
        Path: 用户选择的或默认的保存目录
    """
    # sys.stdin.isatty() 判断是否在交互式终端中运行
    # 如果不是（比如管道输入），直接返回默认值
    if not sys.stdin.isatty():
        default.mkdir(parents=True, exist_ok=True)
        return default

    print()
    print("-" * 50)
    print("  [STEP 2] Choose save location")
    print(f"  Default: {default}")
    print("  (Press Enter = use default, or type a new path)")
    print("-" * 50)

    try:
        user_input = input("  > ").strip().strip('"')
    except (EOFError, KeyboardInterrupt):
        print("\n[ABORTED] Cancelled by user")
        sys.exit(0)

    # 用户直接回车，使用默认路径
    if not user_input:
        default.mkdir(parents=True, exist_ok=True)
        print(f"  [OK] Using default: {default}")
        return default

    # 使用用户输入的路径
    path = Path(user_input)
    path = path.expanduser()  # 展开 ~ 为用户主目录

    try:
        path.mkdir(parents=True, exist_ok=True)
        print(f"  [OK] Save to: {path}")
        return path
    except Exception as e:
        print(f"  [WARN] Cannot create directory: {e}")
        print(f"  [OK] Fallback to default: {default}")
        default.mkdir(parents=True, exist_ok=True)
        return default


def main():
    """程序入口"""
    # 处理 --help
    if len(sys.argv) >= 2 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    links = []

    # 模式 1：无参数，交互式
    if len(sys.argv) < 2:
        print("=" * 50)
        print("  GitHub Batch Downloader")
        print("=" * 50)
        links = prompt_links()
    
    # 模式 2：--links 行内参数
    elif sys.argv[1] == "--links":
        if len(sys.argv) < 3:
            print("Error: --links requires URL list")
            sys.exit(1)
        links = load_links(sys.argv[2])
    
    # 模式 3：文件参数
    else:
        path = Path(sys.argv[1])
        if not path.exists():
            print(f"Error: file not found: {path}")
            sys.exit(1)
        links = load_links(path)

    if not links:
        print("Error: no valid URLs found")
        sys.exit(1)

    output_dir = prompt_output_dir(DEFAULT_OUTPUT)

    # 统计变量
    total = len(links)
    success = 0
    skipped = 0
    failed = 0
    failed_list = []
    details = []

    print("=" * 60)
    print("  GitHub Batch Downloader")
    print(f"  Total: {total} repos")
    print(f"  Output: {output_dir}")
    print(f"  Git timeout: {GIT_TIMEOUT}s | ZIP timeout: {ZIP_TIMEOUT}s")
    print("=" * 60)
    print()

    # 遍历下载每个链接
    for i, url in enumerate(links, 1):
        print(f"[{i}/{total}] {url}")
        result = download_one(url, output_dir, url_index=i, total=total)
        details.append(result)

        if result["status"] == "success":
            success += 1
            print(f"      [OK] Success ({result['method']})")
        elif result["status"] == "skipped":
            skipped += 1
            print(f"      [SKIP] Already exists")
        else:
            failed += 1
            failed_list.append(f"{result['name']}: {result['error']}")
            print(f"      [FAIL] {result['error']}")
        print()

    # 输出统计摘要
    print("=" * 60)
    print("  Done")
    print(f"  Success: {success} | Skipped: {skipped} | Failed: {failed}")
    print("=" * 60)

    if failed_list:
        print()
        print("Failed repos (download manually):")
        for f in failed_list:
            print(f"  - {f}")

    # 保存 JSON 报告
    report = {
        "timestamp": datetime.now().isoformat(),
        "total": total,
        "success": success,
        "skipped": skipped,
        "failed": failed,
        "details": details
    }
    report_path = output_dir / f"download_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\nReport saved: {report_path}")


if __name__ == "__main__":
    main()
