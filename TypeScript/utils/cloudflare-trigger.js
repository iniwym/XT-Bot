addEventListener('scheduled', (event) => {
    event.waitUntil(triggerGitHubAction());
});

async function triggerGitHubAction() {
    // 从环境变量获取（需在 Cloudflare Dashboard 设置）
    const githubUser = GITHUB_USER;
    const repoName = REPO_NAME;
    const token = GITHUB_PAT;
    const workflowName = WORKFLOW_NAME;

    // 环境变量验证
    if (!githubUser || !repoName || !token || !workflowName) {
        console.error('环境变量未正确配置');
        return;
    }

    const url = `https://api.github.com/repos/${githubUser}/${repoName}/actions/workflows/${workflowName}/dispatches`;

    try {
        const response = await fetch(url, {
            method: 'POST',
            headers: {
                'Authorization': `token ${token}`,
                'User-Agent': 'Cloudflare-Worker',
                'Accept': 'application/vnd.github+json'
            },
            body: JSON.stringify({
                ref: "main"
            }),
        });

        if (!response.ok) {
            console.error('触发失败:', await response.text());
        } else {
            console.log('GitHub Action 已触发！');
        }
    } catch (error) {
        console.error('请求错误:', error);
    }
}

