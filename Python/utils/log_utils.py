import sys
import json
import logging
from datetime import datetime
from pathlib import Path


class LogUtils:
    def __init__(self, name=__name__, log_dir="logs",
                 console_level=None,
                 file_level=logging.DEBUG,
                 fmt='[%(asctime)s] [%(levelname)-5s] %(message)s',
                 datefmt="%Y-%m-%d %H:%M:%S"):
        """
        :param name: 日志器名称
        :param log_dir: 日志目录
        :param console_level: 可选参数，手动指定时优先
        :param file_level: 文件日志级别
        """
        self.logger = logging.getLogger(name)

        # 获取python根目录（向上找两级）
        python_root = Path(__file__).resolve().parent.parent
        # 获取项目根目录（向上找三级）
        project_root = python_root.parent
        config_path = project_root / "config" / "config.json"

        # 读取控制台日志级别
        resolved_console_level = self._get_console_level(config_path, console_level)

        # 设置Logger总级别
        self.logger.setLevel(logging.DEBUG)

        # 创建日志目录
        log_dir = python_root / log_dir
        log_dir.mkdir(parents=True, exist_ok=True)

        # 日志文件路径
        log_filename = f"python-{datetime.now().strftime('%Y-%m-%d')}.log"
        log_path = log_dir / log_filename

        # 配置Formatter
        formatter = logging.Formatter(fmt, datefmt=datefmt)

        # 控制台Handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(resolved_console_level)
        console_handler.setFormatter(formatter)

        # 文件Handler
        file_handler = logging.FileHandler(log_path, encoding='utf-8')
        file_handler.setLevel(file_level)
        file_handler.setFormatter(formatter)

        # 添加处理器
        self.logger.addHandler(console_handler)
        self.logger.addHandler(file_handler)

    def _get_console_level(self, config_path, manual_level):
        """优先级：手动指定 > 配置文件 > 默认INFO"""
        if manual_level is not None:
            return manual_level

        try:
            # 读取配置文件
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

            # 获取日志级别配置
            level_str = config.get('consoleLogLevel', 'INFO').upper()
            level_str = {"WARN": "WARNING"}.get(level_str, level_str)
            return getattr(logging, level_str, logging.INFO)

        except (FileNotFoundError, json.JSONDecodeError) as e:
            self._handle_config_error(e)
            return logging.INFO

    def _handle_config_error(self, error):
        """配置文件错误处理"""
        error_msg = {
            FileNotFoundError: f"⚠️ 配置文件未找到，使用默认配置",
            json.JSONDecodeError: f"⚠️ 配置文件格式错误，使用默认配置"
        }.get(type(error), "⚠️ 未知配置错误")

        # 使用基础Logger（此时正式Logger还未初始化）
        temp_logger = logging.getLogger(__name__)
        temp_logger.warning(f"{error_msg} | 错误详情: {str(error)}")

    def get_logger(self):
        """获取配置好的日志器"""
        return self.logger
