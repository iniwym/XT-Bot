import path from 'path';
import fs from 'fs-extra';
import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';
import timezone from 'dayjs/plugin/timezone';

require('dotenv').config({
    path: path.resolve(__dirname, '../../.env')
});

// 配置时区插件
dayjs.extend(utc);
dayjs.extend(timezone);
dayjs.tz.setDefault('Asia/Shanghai'); // 设置默认时区为北京时间

// 类型定义：日志级别类型
type LogLevel = 'DEBUG' | 'INFO' | 'WARN' | 'ERROR';

// 配置日志目录和文件名格式
const LOG_DIR = path.join(__dirname, '../logs');
const LOG_FILENAME_FORMAT = 'YYYY-MM-DD';

// 确保日志目录存在
fs.ensureDirSync(LOG_DIR);

// 定义日志级别优先级映射（数值越小优先级越低）
const LOG_LEVEL_PRIORITY: Record<LogLevel, number> = {
    DEBUG: 0,
    INFO: 1,
    WARN: 2,
    ERROR: 3
};

// 读取配置文件中的控制台日志级别
const configPath = path.join(__dirname, '../../config/config.json');
let consoleLogLevel: LogLevel = 'INFO'; // 默认日志级别

try {
    const rawData = fs.readFileSync(configPath, 'utf8');
    const config = JSON.parse(rawData);

    // 验证并设置控制台日志级别
    if (['DEBUG', 'INFO', 'WARN', 'ERROR'].includes(config.consoleLogLevel)) {
        consoleLogLevel = config.consoleLogLevel;
    } else if (config.consoleLogLevel) {
        console.error(`⚠️ 无效的日志级别: ${config.consoleLogLevel}，使用默认值 INFO`);
    }
} catch (err) {
    console.error('⚠️ 配置文件读取失败，使用默认值:', err.message);
}

// 获取当天日志文件路径
const getLogFilePath = (): string => {
    const dateStr = dayjs().tz().format(LOG_FILENAME_FORMAT);
    return path.join(LOG_DIR, `typescript-${dateStr}.log`);
};

// 创建初始日志流
let logStream = fs.createWriteStream(getLogFilePath(), {flags: 'a'});

// 格式化日志消息
const formatMessage = (args: any[]): string => {
    return args.map(arg =>
        typeof arg === 'object' ? JSON.stringify(arg, null, 2) : String(arg)
    ).join(' ');
};

// 构建日志格式（包含对齐的日志级别标识）
const formatLog = (level: LogLevel, message: string): string => {
    return `[${dayjs().tz().format('YYYY-MM-DD HH:mm:ss')}] [${level.padEnd(5)}] ${message}\n`;
};

// 创建可复用的日志生成器函数
const createLogHandler = (
    level: LogLevel,
    originalMethod: (...args: any[]) => void
) => (...args: any[]): void => {
    const message = formatMessage(args);

    // 根据级别决定是否输出到控制台
    if (LOG_LEVEL_PRIORITY[level] >= LOG_LEVEL_PRIORITY[consoleLogLevel]) {
        originalMethod(...args);
    }

    // 始终写入文件（文件日志级别为 DEBUG）
    logStream.write(formatLog(level, message));
};

// 控制台方法
const originalConsole = {
    debug: console.debug,
    log: console.log,
    warn: console.warn,
    error: console.error
};

// 控制台输出方法
console.debug = createLogHandler('DEBUG', originalConsole.debug);
console.log = createLogHandler('INFO', originalConsole.log);
console.warn = createLogHandler('WARN', originalConsole.warn);
console.error = createLogHandler('ERROR', originalConsole.error);

// 处理日志流错误
const handleStreamError = (err: Error) => {
    originalConsole.error('日志写入失败:', err.message);
};
logStream.on('error', handleStreamError);

// 清理日志流
export function cleanupLogger() {
    return new Promise((resolve) => {
        if (logStream) {
            logStream.end(() => {
                console.log('🗑️ 日志流已正常关闭');
                resolve(true);
            });
        } else {
            resolve(true);
        }
    });
}

// 进程退出处理
const handleProcessExit = async (signal: string) => {
    await cleanupLogger();
    console.log(`进程收到 ${signal} 信号，正在退出...`);
    process.exit(0);
};

// 监听退出信号
process.on('SIGINT', () => handleProcessExit('SIGINT'));
process.on('SIGTERM', () => handleProcessExit('SIGTERM'));

// 全局错误处理
process.on('uncaughtException', (error) => {
    console.error('[未捕获异常]', error.message, error.stack);
    cleanupLogger().then(() => process.exit(1));
});

process.on('unhandledRejection', (reason, promise) => {
    console.error('[未处理拒绝]', reason, '发生在 Promise:', promise);
    cleanupLogger().then(() => process.exit(1));
});