#!/usr/bin/env python3
import os
import re
import subprocess
import sys

def get_project_root():
    """获取项目根目录（scripts 目录的上一级）"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    return project_root

def get_version_from_file():
    """从根目录的 version.py 读取 APP_VERSION 版本号"""
    project_root = get_project_root()
    version_file_path = os.path.join(project_root, "version.py")
    
    if not os.path.exists(version_file_path):
        raise FileNotFoundError(f"未找到版本文件：{version_file_path}（请确认 version.py 在项目根目录）")
    
    with open(version_file_path, "r", encoding="utf-8") as f:
        content = f.read()
        match = re.search(r'APP_VERSION\s*=\s*["\']([0-9.]+)["\']', content)
        if not match:
            raise ValueError("version.py 中未找到 APP_VERSION 定义，格式需为 APP_VERSION = \"x.y\"")
    
    version = match.group(1).strip()
    if not re.match(r'^\d+\.\d+(\.\d+)?$', version):
        raise ValueError(f"版本号格式错误：{version}，需符合 x.y 或 x.y.z（如 1.3 / 1.3.0）")
    return version

def create_git_tag(version):
    """创建并推送 Git 标签（指定 git.exe 完整路径）"""
    project_root = get_project_root()
    tag_name = f"v{version}"
    
    # ===== 关键修改：指定 git.exe 完整路径 =====
    git_path = r"C:\Program Files\Git\bin\git.exe"  # 替换为你的 Git 安装路径
    # 验证 git.exe 是否存在
    if not os.path.exists(git_path):
        raise FileNotFoundError(f"未找到 git.exe，路径：{git_path}（请检查 Git 安装路径）")
    
    os.chdir(project_root)  # 切换到项目根目录
    
    # 检查标签是否存在（使用完整 git 路径）
    try:
        result = subprocess.run(
            [git_path, "tag", "-l", tag_name],  # 替换 git 为完整路径
            capture_output=True,
            text=True,
            check=True
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"检查 Git 标签失败：{e.stderr}（请确认当前目录是 Git 仓库）")
    
    if result.stdout.strip() == tag_name:
        print(f"⚠️  标签 {tag_name} 已存在，跳过创建")
        return
    
    # 创建标签（使用完整 git 路径）
    try:
        subprocess.run(
            [git_path, "tag", "-a", tag_name, "-m", f"Release {tag_name}"],
            check=True,
            capture_output=True,
            text=True
        )
        print(f"✅ 成功创建本地标签：{tag_name}")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"创建标签失败：{e.stderr}")
    
    # 推送标签（使用完整 git 路径）
    try:
        subprocess.run(
            [git_path, "push", "origin", tag_name],
            check=True,
            capture_output=True,
            text=True
        )
        print(f"✅ 成功推送标签 {tag_name} 到远程仓库")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"推送标签失败：{e.stderr}\n可能原因：1. 本地未同步远程仓库 2. 权限不足 3. 标签已存在于远程")

if __name__ == "__main__":
    try:
        version = get_version_from_file()
        print(f"🔍 从根目录 version.py 提取到版本号：{version}")
        create_git_tag(version)
    except Exception as e:
        print(f"❌ 错误：{e}")
        sys.exit(1)