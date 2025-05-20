import sys
import os
import shutil
import argparse
from pathlib import Path

# 将项目根目录添加到模块搜索路径
_project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(_project_root))
from utils.log_utils import LogUtils

logger = LogUtils().get_logger()
logger.info("🔄 Sync_Data 初始化完成")


def sync_dirs(source, dest):
    """同步目录的核心函数"""
    # 标准化路径并确保末尾没有斜杠
    source = os.path.normpath(source)
    dest = os.path.normpath(dest)

    # 确保源目录存在
    if not os.path.exists(source):
        raise FileNotFoundError(f"Source directory '{source}' does not exist")

    # 收集源目录中的所有文件相对路径
    source_files = set()
    for root, dirs, files in os.walk(source):
        rel_path = os.path.relpath(root, source)
        for file in files:
            file_rel_path = os.path.join(rel_path, file) if rel_path != '.' else file
            source_files.add(file_rel_path)

    # 复制或更新文件到目标目录
    for file_rel in source_files:
        src_path = os.path.join(source, file_rel)
        dest_path = os.path.join(dest, file_rel)
        dest_dir = os.path.dirname(dest_path)

        # 创建目标目录结构
        os.makedirs(dest_dir, exist_ok=True)

        # 检查是否需要复制（修改时间或大小不同）
        if os.path.exists(dest_path):
            src_stat = os.stat(src_path)
            dest_stat = os.stat(dest_path)
            if src_stat.st_mtime <= dest_stat.st_mtime and src_stat.st_size == dest_stat.st_size:
                continue  # 文件相同，跳过复制

        shutil.copy2(src_path, dest_path)
        logger.debug(f"📥 Copied: {src_path} -> {dest_path}")

    # 收集目标目录中的所有文件相对路径
    dest_files = set()
    for root, dirs, files in os.walk(dest):
        rel_path = os.path.relpath(root, dest)
        for file in files:
            file_rel_path = os.path.join(rel_path, file) if rel_path != '.' else file
            dest_files.add(file_rel_path)

    # 删除目标中存在但源中不存在的文件
    for file_rel in (dest_files - source_files):
        file_path = os.path.join(dest, file_rel)
        try:
            os.remove(file_path)
            logger.debug(f"🗑️ Deleted: {file_path}")
        except Exception as e:
            logger.error(f"⚠ 删除文件失败：{file_path} - {str(e)}")

    # 删除空目录（从叶子目录开始向上删除）
    for root, dirs, files in os.walk(dest, topdown=False):
        # 删除空目录
        if not os.listdir(root):
            try:
                os.rmdir(root)
                logger.debug(f"📁 Removed empty directory: {root}")
            except Exception as e:
                logger.error(f"⚠ 删除目录失败：{root} - {str(e)}")


def main():
    # 预定义任务组
    TASK_GROUPS = {
        "pull": [
            {"source": "data-repo/config", "dest": "config"},
            {"source": "data-repo/Python/dataBase", "dest": "Python/dataBase"},
            {"source": "data-repo/Python/output", "dest": "Python/output"},
            {"source": "data-repo/TypeScript/data", "dest": "TypeScript/data"},
            {"source": "data-repo/TypeScript/tweets", "dest": "TypeScript/tweets"},
        ],
        "push": [
            {"dest": "data-repo/config", "source": "config"},
            {"dest": "data-repo/Python/dataBase", "source": "Python/dataBase"},
            {"dest": "data-repo/Python/output", "source": "Python/output"},
            {"dest": "data-repo/TypeScript/data", "source": "TypeScript/data"},
            {"dest": "data-repo/TypeScript/tweets", "source": "TypeScript/tweets"},
        ]
    }

    # 配置命令行参数
    parser = argparse.ArgumentParser()

    parser.add_argument(
        'task_group',
        nargs='?',  # 设置为可选参数
        default='pull',
        choices=TASK_GROUPS.keys(),
        help="选择同步任务组 (默认: %(default)s)"
    )

    args = parser.parse_args()

    # 执行同步任务
    logger.info(f"🔄 正在执行任务组 [{args.task_group}]")
    for task in TASK_GROUPS[args.task_group]:
        src = task["source"]
        dst = task["dest"]
        logger.debug(f"→ 同步任务: {src} => {dst}")
        try:
            sync_dirs(src, dst)
        except Exception as e:
            logger.error(f"⚠ 同步失败：{src} => {dst} - {str(e)}")
            continue


if __name__ == "__main__":
    main()
