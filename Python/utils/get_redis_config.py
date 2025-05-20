import os
import json
import sys
import redis
from redis.exceptions import RedisError
from pathlib import Path

# 将项目根目录添加到模块搜索路径
_project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(_project_root))
from utils.log_utils import LogUtils

logger = LogUtils().get_logger()
logger.info("🔄 Get_Redis_Config 初始化完成")


def main():
    # 获取环境变量
    redis_config = os.environ.get('REDIS_CONFIG')
    if not redis_config:
        logger.warning("ℹ 未配置 REDIS_CONFIG，直接使用本地配置文件")
        sys.exit(0)
    logger.info("✓ 已读取环境变量 REDIS_CONFIG")

    # 解析Redis配置
    try:
        config = json.loads(redis_config)
        logger.info("✓ Redis配置解析成功")
    except json.JSONDecodeError as e:
        logger.warning(f"⚠ 警告：Redis配置JSON格式错误（{e}），使用本地配置")
        sys.exit(0)

    # 建立并验证Redis连接
    try:
        r = redis.Redis(
            host=config.get('host', 'localhost'),
            port=config.get('port', 6379),
            password=config.get('password'),
            db=config.get('db', 0),
            decode_responses=True,
            socket_connect_timeout=5
        )

        # 主动发送PING命令验证连接和认证
        r.ping()
        logger.info("✓ Redis连接验证通过")
    except RedisError as e:
        logger.warning(f"⚠ 警告：Redis连接失败（{e}），使用本地配置")
        sys.exit(0)

    # 读取配置数据
    config_data = r.get('config')
    if not config_data:
        logger.warning("⚠ 警告：Redis中未找到'config'键值，使用本地配置")
        sys.exit(0)
    logger.info("✓ 成功读取配置数据")

    # 解析配置数据
    try:
        json_obj = json.loads(config_data)
        logger.info("✓ 配置数据格式验证成功")
    except json.JSONDecodeError as e:
        logger.warning(f"⚠ 警告：配置数据JSON格式错误（{e}），使用本地配置")
        sys.exit(0)

    # 写入配置文件
    file_path = '../../config/config.json'
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(json_obj, f, indent=2, ensure_ascii=False)
        logger.info(f"✓ 配置文件已生成：{os.path.abspath(file_path)}")
    except IOError as e:
        logger.warning(f"⚠ 警告：文件写入失败（{e}），使用现有配置")
        sys.exit(0)


if __name__ == "__main__":
    main()
