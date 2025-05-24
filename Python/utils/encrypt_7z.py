import sys
import py7zr
from pathlib import Path

# 将项目根目录添加到模块搜索路径
_project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(_project_root))
from utils.log_utils import LogUtils

logger = LogUtils().get_logger()
logger.info("🔄 Encrypt_7z 初始化完成")


def compress_folders(dirs, output_file, password):
    """执行压缩加密操作"""
    try:
        with py7zr.SevenZipFile(
                output_file,
                mode='w',
                password=password,
                header_encryption=True,
                filters=[{
                    'id': py7zr.FILTER_LZMA2,
                    'preset': 7,
                    'dict_size': 64 * 1024 * 1024
                }]
        ) as archive:
            for folder in dirs:
                folder_path = Path(folder)
                archive.writeall(folder_path, folder_path.name)
        logger.info(f"✓ 压缩完成：{output_file}")
    except Exception as e:
        logger.error(f"⚠ 压缩失败：{str(e)}")
        sys.exit(0)


if __name__ == '__main__':
    """验证参数格式及路径有效性"""
    if len(sys.argv) != 4:
        logger.warning('⚠ 参数错误！正确格式：python encrypt_7z.py "[目录1,目录2,...]" [输出文件.7z] [密码]')
        sys.exit(0)

    dirs = sys.argv[1].split(',')
    output_file = sys.argv[2]
    password = sys.argv[3]

    # 检查密码是否为空或仅包含空格
    if not password.strip():
        logger.warning('⚠ 密码为空，不执行压缩加密操作。')
        sys.exit(0)

    compress_folders(dirs, output_file, password)
