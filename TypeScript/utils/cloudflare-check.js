// 通过 Cloudflare Scheduler 触发
addEventListener('scheduled', (event) => {
    event.waitUntil(checkActionStatus());
});

async function checkActionStatus() {
    // 从环境变量获取（需在 Cloudflare Dashboard 设置）
    const githubToken = GITHUB_TOKEN;
    const githubUser = GITHUB_USER;
    const repoName = REPO_NAME;
    const workflowName = WORKFLOW_NAME;
    const larkKey = LARK_KEY;

    // 环境变量验证
    if (!githubToken || !githubUser || !repoName || !workflowName || !larkKey) {
        console.error('环境变量未正确配置');
        return;
    }

    const apiUrl = `https://api.github.com/repos/${githubUser}/${repoName}/actions/workflows/${workflowName}/runs?per_page=1`;
    const larkUrl = `https://open.feishu.cn/open-apis/bot/v2/hook/${larkKey}`;

    try {
        // GitHub API请求
        const response = await fetch(apiUrl, {
            method: 'GET',
            headers: {
                'Authorization': `token ${githubToken}`,
                'User-Agent': 'Cloudflare-Action-Checker',
                'Accept': 'application/vnd.github+json'
            }
        });

        if (!response.ok) {
            const error = await response.text();
            throw new Error(`GitHub API错误: ${response.status} - ${error}`);
        }

        const data = await response.json();
        const latestRun = data.workflow_runs?.[0];

        // 仅调试用日志
        // console.log('最新运行记录:', latestRun ? JSON.stringify(latestRun) : '无记录');

        if (!latestRun) {
            await sendLarkAlert(larkUrl, '⚠️ 警告：无历史执行记录');
            return;
        }

        if (latestRun.conclusion !== 'success') {
            // 时间转换逻辑
            const createdDate = new Date(latestRun.created_at);
            const beijingTimestamp = createdDate.getTime() + 8 * 60 * 60 * 1000;
            const beijingDate = new Date(beijingTimestamp);

            // 格式化日期
            const formatNumber = n => n.toString().padStart(2, '0');
            const timeString = [
                beijingDate.getFullYear(),
                formatNumber(beijingDate.getMonth() + 1),
                formatNumber(beijingDate.getDate())
            ].join('/') + ' ' + [
                formatNumber(beijingDate.getHours()),
                formatNumber(beijingDate.getMinutes()),
                formatNumber(beijingDate.getSeconds())
            ].join(':');

            // 构造消息
            const message = `🚨 工作流执行状态异常\n` +
                `执行ID: ${latestRun.id}\n` +
                `状态: ${latestRun.conclusion || 'unknown'}\n` +
                `时间: ${timeString}`;
            await sendLarkAlert(larkUrl, message);
        } else {
            console.log('工作流执行状态:', latestRun.conclusion);
        }

    } catch (error) {
        const errorMessage = `‼️ 监控服务异常\n` +
            `错误信息: ${error.message}\n` +
            `时间: ${new Date().toLocaleString('zh-CN')}`;
        await sendLarkAlert(larkUrl, errorMessage);
    }
}

async function sendLarkAlert(url, message) {
    try {
        console.log('发送飞书通知:', message.slice(0, 50) + '...'); // 日志截断

        const payload = {
            msg_type: "text",
            content: {
                text: message
            }
        };

        await fetch(url, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });

    } catch (error) {
        console.error('飞书请求失败:', {
            message: error.message,
            stack: error.stack.split('\n')[0]
        });
    }
}