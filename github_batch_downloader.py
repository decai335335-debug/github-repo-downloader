#!/usr/bin/env python3
"""
GitHub Batch Downloader — Git clone + ZIP fallback
=====================================================
1. Try git clone first (shows real-time progress)
2. If timeout/fail → download ZIP archive + auto unzip
3. If ZIP also fails → report to user

Usage (interactive):
    python github_batch_downloader.py

Usage (file):
    python github_batch_downloader.py repos.txt

Usage (inline):
    python github_batch_downloader.py --links "url1 url2"
"""

import os
import sys
import subprocess
import json
import zipfile
import shutil
from pathlib import Path
from datetime import datetime
from urllib.request import urlopen
from urllib.error import URLError, HTTPError

# ===== Config =====
DEFAULT_OUTPUT = Path(__file__).parent / "downloads"
GIT_TIMEOUT = 120          # git clone timeout (seconds)
ZIP_TIMEOUT = 60           # ZIP download timeout (seconds)
GIT_RETRIES = 1            # git retry count
ZIP_RETRIES = 1            # ZIP retry count
SLOW_TIME = 30             # git low-speed timeout
SLOW_LIMIT = 1024          # git low-speed limit (bytes/s)
BRANCHES = ["main", "master"]  # ZIP branch fallback order
# ==================


def run_git_clone(url: str, dest: Path) -> tuple[bool, str]:
    """Git clone with real-time progress visible (no output hidden)."""
    env = os.environ.copy()
    env["GIT_HTTP_LOW_SPEED_TIME"] = str(SLOW_TIME)
    env["GIT_HTTP_LOW_SPEED_LIMIT"] = str(SLOW_LIMIT)

    cmd = ["git", "clone", "--depth=1", "--single-branch", "--progress", url, str(dest)]

    try:
        result = subprocess.run(cmd, capture_output=False, text=True, timeout=GIT_TIMEOUT, env=env)
        return result.returncode == 0, ""
    except subprocess.TimeoutExpired:
        cleanup(dest)
        return False, f"git timeout ({GIT_TIMEOUT}s)"
    except Exception as e:
        cleanup(dest)
        return False, str(e)


def cleanup(path: Path):
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def parse_owner_repo(url: str) -> tuple[str, str, str, str, str]:
    """Extract owner, repo, branch, subdir, and clean clone URL from GitHub URL.
    
    Handles subdirectory paths like:
      https://github.com/owner/repo/tree/main/path/to/subdir
      https://github.com/owner/repo/blob/main/path/to/file
    
    Returns (owner, repo, branch, subdir_path, clean_url).
    For root URLs, branch="", subdir_path="".
    """
    url = url.rstrip("/").replace(".git", "")
    parts = url.split("/")
    
    gh_idx = parts.index("github.com")
    owner = parts[gh_idx + 1]
    repo = parts[gh_idx + 2]
    clean_url = f"https://github.com/{owner}/{repo}"
    
    # Detect subdirectory URLs: /tree/<branch>/... or /blob/<branch>/...
    branch = ""
    subdir = ""
    
    for marker in ("/tree/", "/blob/"):
        if marker in url:
            marker_idx = parts.index(marker.strip("/"))
            branch = parts[marker_idx + 1] if marker_idx + 1 < len(parts) else "main"
            subdir = "/".join(parts[marker_idx + 2:])
            break
    
    return owner, repo, branch, subdir, clean_url


def download_zip(owner: str, repo: str, dest: Path) -> tuple[bool, str]:
    """Download ZIP archive from GitHub, try main then master branch."""
    zip_path = dest.with_suffix(".zip")
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    for branch in BRANCHES:
        zip_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"
        print(f"      [ZIP] Trying {branch} branch: {zip_url}")

        for attempt in range(ZIP_RETRIES + 1):
            try:
                req = urlopen(zip_url, timeout=ZIP_TIMEOUT)
                total = int(req.headers.get('Content-Length', 0))
                downloaded = 0
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
                            print(f"\r      [ZIP] Downloading: {pct}% ({downloaded//1024}KB / {total//1024}KB)", end="", flush=True)

                print()  # newline after progress
                return True, ""

            except HTTPError as e:
                if e.code == 404:
                    print(f"      [ZIP] Branch '{branch}' not found (404)")
                    break  # try next branch
                err = f"HTTP {e.code}"
            except URLError as e:
                err = f"Network error: {e.reason}"
            except Exception as e:
                err = str(e)

            if attempt < ZIP_RETRIES:
                print(f"      [ZIP] Retry {attempt + 1}/{ZIP_RETRIES}...")
            else:
                print(f"      [ZIP] Failed: {err}")

    return False, "ZIP download failed (all branches)"


def download_subdir_svn(owner: str, repo: str, branch: str, subdir: str, dest: Path) -> tuple[bool, str]:
    """Download a GitHub subdirectory using svn export.
    
    GitHub supports SVN bridge: https://github.com/owner/repo/trunk/subdir
    """
    # Map branch to SVN trunk/branches format
    if branch in ("main", "master"):
        svn_url = f"https://github.com/{owner}/{repo}/trunk/{subdir}"
    else:
        svn_url = f"https://github.com/{owner}/{repo}/branches/{branch}/{subdir}"
    
    print(f"      [SVN] Exporting subdirectory via SVN: {svn_url}")
    
    try:
        # svn export --force to overwrite existing
        cmd = ["svn", "export", "--force", svn_url, str(dest)]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT
        )
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
    """Download full repo ZIP, but only extract the specified subdirectory."""
    temp_dest = output_dir / f"__temp_{repo}_{branch}"
    
    # Step 1: Download full repo ZIP
    print(f"      [Subdir-ZIP] Downloading full repo ZIP, will extract only: {subdir}")
    ok, err = download_zip(owner, repo, temp_dest)
    if not ok:
        return False, err
    
    # Step 2: Unzip
    zip_path = temp_dest.with_suffix(".zip")
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            top_dir = zf.namelist()[0].split('/')[0]
            # Find all files under the subdir
            prefix = f"{top_dir}/{subdir}/"
            extracted_any = False
            
            for name in zf.namelist():
                if name.startswith(prefix) and not name.endswith('/'):
                    # Compute relative path within subdir
                    rel_path = name[len(prefix):]
                    out_path = dest / rel_path
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    with zf.open(name) as src, open(out_path, 'wb') as dst:
                        dst.write(src.read())
                    extracted_any = True
            
            if not extracted_any:
                return False, f"Subdirectory '{subdir}' not found in archive"
        
        # Cleanup temp files
        zip_path.unlink(missing_ok=True)
        cleanup(temp_dest)
        return True, ""
        
    except Exception as e:
        return False, str(e)


def unzip_archive(zip_path: Path, output_dir: Path, repo_name: str) -> tuple[bool, str]:
    """Extract ZIP and rename folder to repo name."""
    try:
        with zipfile.ZipFile(zip_path, 'r') as z:
            # GitHub ZIPs extract to "repo-branch/" folder
            top_dir = z.namelist()[0].split('/')[0]
            z.extractall(output_dir)

        extracted = output_dir / top_dir
        target = output_dir / repo_name
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        extracted.rename(target)
        zip_path.unlink()
        return True, ""
    except Exception as e:
        return False, str(e)


def download_one(url: str, output_dir: Path, url_index: int = 1, total: int = 1) -> dict:
    """Download one repo or subdirectory: svn → git → ZIP subdir → ZIP full → report failure."""
    owner, repo, branch, subdir, clean_url = parse_owner_repo(url)
    
    # Determine output folder name
    if subdir:
        # Use last part of subdir as folder name, e.g. translations/zh-CN → zh-CN
        name = subdir.rstrip("/").split("/")[-1]
        is_subdir = True
    else:
        name = repo
        is_subdir = False
    
    dest = output_dir / name

    result = {
        "name": name,
        "url": url,
        "status": "",
        "method": "",
        "error": ""
    }

    # Skip if already exists
    if dest.exists():
        result["status"] = "skipped"
        result["method"] = "already_exists"
        return result

    # ── SUBDIRECTORY DOWNLOAD (if URL points to a subdir) ──
    if is_subdir:
        print(f"  [INFO] Subdirectory URL detected: {subdir}")
        
        # Phase 1: Try SVN export (fastest, only downloads subdir)
        print(f"  [1/4] SVN export: {owner}/{repo}/{subdir}")
        ok, err = download_subdir_svn(owner, repo, branch or "main", subdir, dest)
        if ok:
            result["status"] = "success"
            result["method"] = "svn"
            return result
        print(f"        SVN failed: {err}")
        cleanup(dest)
        
        # Phase 2: Try ZIP subdir extraction (download full ZIP, extract only subdir)
        print(f"  [2/4] ZIP subdir extraction: {owner}/{repo}/{subdir}")
        ok, err = download_subdir_zip(owner, repo, branch or "main", subdir, dest, output_dir)
        if ok:
            result["status"] = "success"
            result["method"] = "zip_subdir"
            return result
        print(f"        ZIP subdir failed: {err}")
        cleanup(dest)
        
        # Phase 3: Fall back to downloading whole repo via git
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
        
        # Phase 4: ZIP whole repo fallback
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
        
        # Total failure
        print(f"        All methods failed: {err}")
        result["status"] = "failed"
        result["method"] = "all_methods_failed"
        result["error"] = err
        return result

    # ── ROOT REPO DOWNLOAD (original logic) ──
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

    # Phase 3: Total failure
    print(f"        ZIP also failed: {err}")
    result["status"] = "failed"
    result["method"] = "all_methods_failed"
    result["error"] = err
    return result


def load_links(source) -> list[str]:
    links = []
    if isinstance(source, list):
        return [u.strip() for u in source if u.strip()]
    path = Path(source)
    if path.is_file():
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    links.append(line)
    else:
        for part in source.split():
            part = part.strip()
            if part and not part.startswith("#"):
                links.append(part)
    return links


def prompt_links() -> list[str]:
    """Interactive prompt: paste multiple links, blank line to finish."""
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
                break
            raw_lines.append(line)
    except (EOFError, KeyboardInterrupt):
        print("\n[ABORTED] Cancelled by user")
        sys.exit(0)

    # Parse links from all pasted text
    all_text = "\n".join(raw_lines)
    links = []
    for part in all_text.replace(",", " ").split():
        part = part.strip()
        if part and not part.startswith("#"):
            links.append(part)

    # Deduplicate while preserving order
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
    """Ask user where to save repos. Press Enter for default."""
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

    if not user_input:
        default.mkdir(parents=True, exist_ok=True)
        print(f"  [OK] Using default: {default}")
        return default

    path = Path(user_input)
    path = path.expanduser()

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
    if len(sys.argv) >= 2 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    links = []

    # Mode 1: Interactive (no args)
    if len(sys.argv) < 2:
        print("=" * 50)
        print("  GitHub Batch Downloader")
        print("=" * 50)
        links = prompt_links()
    # Mode 2: Inline links
    elif sys.argv[1] == "--links":
        if len(sys.argv) < 3:
            print("Error: --links requires URL list")
            sys.exit(1)
        links = load_links(sys.argv[2])
    # Mode 3: File
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

    # Summary
    print("=" * 60)
    print("  Done")
    print(f"  Success: {success} | Skipped: {skipped} | Failed: {failed}")
    print("=" * 60)

    if failed_list:
        print()
        print("Failed repos (download manually):")
        for f in failed_list:
            print(f"  - {f}")

    # Save report
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
