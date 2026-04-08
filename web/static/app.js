const STORAGE_KEY = "gpa.deepseek.apiKey";
const STORAGE_REMEMBER = "gpa.deepseek.remember";
const STORAGE_GITHUB_TOKEN = "gpa.github.token";

const apiKeyInput = document.getElementById("apiKeyInput");
const toggleApiKeyBtn = document.getElementById("toggleApiKeyBtn");
const githubTokenInput = document.getElementById("githubTokenInput");
const toggleGithubTokenBtn = document.getElementById("toggleGithubTokenBtn");
const rememberKey = document.getElementById("rememberKey");
const repoUrlInput = document.getElementById("repoUrlInput");
const startBtn = document.getElementById("startBtn");
const statusHint = document.getElementById("statusHint");

const monitorSection = document.getElementById("monitorSection");
const terminalBox = document.getElementById("terminalBox");
const progressFill = document.getElementById("progressFill");
const stepNodes = Array.from(document.querySelectorAll(".step"));

const reportSection = document.getElementById("reportSection");
const reportFrame = document.getElementById("reportFrame");
const downloadDocx = document.getElementById("downloadDocx");
const downloadHtml = document.getElementById("downloadHtml");
const downloadMd = document.getElementById("downloadMd");

const state = {
    currentStep: 0,
    eventSource: null,
    resultUrl: "",
    jobId: "",
    logCursor: 0,
    pollTimer: null,
    finalResolved: false,
    streamWarned: false,
};

const STEP_RULES = [
    { pattern: /开始抓取 GitHub 项目数据/, step: 1 },
    { pattern: /开始生成项目技术名片/, step: 2 },
    { pattern: /开始生成 .* 报告初稿/, step: 3 },
    { pattern: /Critic 审核第|Critic 第/, step: 4 },
    { pattern: /开始渲染 HTML\/MD\/DOCX 报告|渲染完成|任务结束/, step: 5 },
];

function nowClock() {
    const d = new Date();
    return d.toLocaleTimeString("zh-CN", { hour12: false });
}

function appendLog(message) {
    const normalized = String(message || "")
        .replace(/\\/g, "\\\u200b")
        .replace(/\//g, "/\u200b")
        .replace(/\|/g, "|\u200b");
    const line = `[${nowClock()}] ${normalized}`;
    terminalBox.textContent += `${line}\n`;
    terminalBox.scrollTop = terminalBox.scrollHeight;
}

function setStatus(text, type = "idle") {
    statusHint.textContent = text;
    statusHint.style.color = {
        idle: "#637082",
        running: "#123d87",
        success: "#1f8f5f",
        error: "#d14343",
        warn: "#ca8a04",
    }[type] || "#637082";
}

function setStep(step) {
    state.currentStep = Math.max(state.currentStep, step);
    for (let i = 0; i < stepNodes.length; i += 1) {
        const nodeStep = i + 1;
        stepNodes[i].classList.toggle("done", nodeStep < state.currentStep);
        stepNodes[i].classList.toggle("active", nodeStep === state.currentStep);
    }
    const ratio = Math.min(state.currentStep, 5) / 5;
    progressFill.style.width = `${ratio * 100}%`;
}

function updateStepByMessage(message) {
    for (const rule of STEP_RULES) {
        if (rule.pattern.test(message)) {
            setStep(rule.step);
            break;
        }
    }
}

function clearDownloads() {
    for (const link of [downloadDocx, downloadHtml, downloadMd]) {
        link.classList.add("disabled");
        link.removeAttribute("href");
    }
}

function setDownloadLink(element, url) {
    if (!url) {
        element.classList.add("disabled");
        element.removeAttribute("href");
        return;
    }
    element.classList.remove("disabled");
    element.href = url;
}

function applyHistoryLogs(history) {
    if (!Array.isArray(history)) {
        return;
    }
    for (let i = state.logCursor; i < history.length; i += 1) {
        const msg = String(history[i] || "");
        if (!msg) {
            continue;
        }
        appendLog(msg);
        updateStepByMessage(msg);
    }
    state.logCursor = history.length;
}

function stopStatusPolling() {
    if (state.pollTimer) {
        clearInterval(state.pollTimer);
        state.pollTimer = null;
    }
}

function startStatusPolling() {
    stopStatusPolling();
    state.pollTimer = setInterval(() => {
        syncJobState({ silent: true }).catch(() => {
            // Swallow intermittent polling failures; stream or next poll will recover.
        });
    }, 1500);
}

function finalizeError(message) {
    if (state.finalResolved) {
        return;
    }
    state.finalResolved = true;
    closeEventSource();
    stopStatusPolling();
    appendLog(`任务失败: ${message || "未知错误"}`);
    setStatus("任务失败", "error");
    startBtn.disabled = false;
    startBtn.textContent = "开始智能分析";
}

function finalizeSuccess(data) {
    if (state.finalResolved) {
        return;
    }
    state.finalResolved = true;
    closeEventSource();
    stopStatusPolling();

    reportFrame.srcdoc = data.htmlContent || "<p style='padding:16px'>报告内容为空</p>";
    reportSection.classList.remove("hidden");
    setDownloadLink(downloadDocx, data.downloadUrls?.docx || "");
    setDownloadLink(downloadHtml, data.downloadUrls?.html || "");
    setDownloadLink(downloadMd, data.downloadUrls?.md || "");

    const summary = `最终评分 ${Number(data.selectedCriticScore || 0).toFixed(2)}，采用轮次 ${data.selectedCriticRound || 0}`;
    appendLog(summary);
    setStep(5);
    setStatus("分析完成", "success");
    startBtn.disabled = false;
    startBtn.textContent = "开始智能分析";

    reportSection.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function syncJobState(options = {}) {
    if (!state.resultUrl) {
        return "unknown";
    }

    const silent = Boolean(options.silent);
    let response;
    try {
        response = await fetch(`${state.resultUrl}?t=${Date.now()}`, {
            cache: "no-store",
            headers: { "Cache-Control": "no-cache" },
        });
    } catch (error) {
        if (!silent) {
            appendLog(`结果查询失败: ${error}`);
        }
        return "network-error";
    }

    let data;
    try {
        data = await response.json();
    } catch (error) {
        if (!silent) {
            appendLog(`结果解析失败: ${error}`);
        }
        return "parse-error";
    }

    applyHistoryLogs(data.logHistory);

    if (data.status === "error") {
        finalizeError(data.error || "未知错误");
        return "error";
    }

    if (data.status === "done") {
        finalizeSuccess(data);
        return "done";
    }

    if (!silent) {
        appendLog(`任务状态：${data.status}`);
    }
    return data.status || "running";
}

async function loadResult() {
    if (!state.resultUrl) {
        return;
    }
    await syncJobState();
}

function closeEventSource() {
    if (state.eventSource) {
        state.eventSource.close();
        state.eventSource = null;
    }
}

function connectStream(streamUrl) {
    closeEventSource();
    state.streamWarned = false;
    const source = new EventSource(streamUrl);
    state.eventSource = source;

    source.onopen = () => {
        appendLog("实时日志通道已连接");
    };

    source.onmessage = async (event) => {
        let payload;
        try {
            payload = JSON.parse(event.data || "{}");
        } catch (error) {
            appendLog(`实时日志解析失败: ${error}`);
            return;
        }

        if (payload.type === "log") {
            const msg = payload.message || "";
            appendLog(msg);
            updateStepByMessage(msg);
            state.logCursor += 1;
            return;
        }

        if (payload.type === "done") {
            appendLog(payload.message || "分析任务完成");
            closeEventSource();
            await loadResult();
            return;
        }

        if (payload.type === "error") {
            closeEventSource();
            const status = await syncJobState({ silent: true });
            if (status !== "done") {
                finalizeError(payload.message || "任务失败");
            }
        }
    };

    source.onerror = async () => {
        closeEventSource();
        if (!state.finalResolved) {
            if (!state.streamWarned) {
                appendLog("实时流连接不稳定，已切换轮询模式继续同步...");
                state.streamWarned = true;
            }
            await syncJobState({ silent: true });
        }
    };
}

function saveKeyState() {
    if (rememberKey.checked) {
        localStorage.setItem(STORAGE_REMEMBER, "1");
        localStorage.setItem(STORAGE_KEY, apiKeyInput.value || "");
        localStorage.setItem(STORAGE_GITHUB_TOKEN, githubTokenInput.value || "");
    } else {
        localStorage.removeItem(STORAGE_REMEMBER);
        localStorage.removeItem(STORAGE_KEY);
        localStorage.removeItem(STORAGE_GITHUB_TOKEN);
    }
}

function restoreKeyState() {
    const remember = localStorage.getItem(STORAGE_REMEMBER) === "1";
    rememberKey.checked = remember;
    if (remember) {
        apiKeyInput.value = localStorage.getItem(STORAGE_KEY) || "";
        githubTokenInput.value = localStorage.getItem(STORAGE_GITHUB_TOKEN) || "";
    }
}

async function startAnalysis() {
    const apiKey = apiKeyInput.value.trim();
    const githubToken = githubTokenInput.value.trim();
    const repoUrl = repoUrlInput.value.trim();
    const analysisType = document.querySelector("input[name='analysisType']:checked")?.value || "econ";

    if (!apiKey) {
        setStatus("请先输入 DeepSeek API Key", "warn");
        return;
    }
    if (!repoUrl) {
        setStatus("请先输入 GitHub 仓库链接", "warn");
        return;
    }

    monitorSection.classList.remove("hidden");
    reportSection.classList.add("hidden");
    terminalBox.textContent = "";
    clearDownloads();
    state.currentStep = 0;
    state.logCursor = 0;
    state.finalResolved = false;
    state.streamWarned = false;
    setStep(0);

    startBtn.disabled = true;
    startBtn.textContent = "分析进行中...";
    setStatus("任务已提交，等待执行...", "running");
    appendLog("准备启动分析任务...");

    const response = await fetch("/api/start-analysis", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            apiKey,
            githubToken,
            repoUrl,
            analysisType,
        }),
    });

    const payload = await response.json();
    if (!response.ok) {
        appendLog(payload.error || "任务启动失败");
        if (String(payload.error || "").toLowerCase().includes("rate limit")) {
            setStatus("触发 GitHub 限流，请填写 GitHub Token 后重试", "warn");
        } else {
            setStatus("任务启动失败", "error");
        }
        startBtn.disabled = false;
        startBtn.textContent = "开始智能分析";
        return;
    }

    state.jobId = payload.jobId;
    state.resultUrl = payload.resultUrl;
    appendLog(`任务已创建，Job ID: ${state.jobId}`);
    setStatus("任务执行中...", "running");

    startStatusPolling();
    if (typeof EventSource !== "undefined") {
        connectStream(payload.streamUrl);
    } else {
        appendLog("当前浏览器不支持 EventSource，已启用轮询同步日志。");
    }
}

function bindEvents() {
    toggleApiKeyBtn.addEventListener("click", () => {
        const hidden = apiKeyInput.type === "password";
        apiKeyInput.type = hidden ? "text" : "password";
        toggleApiKeyBtn.textContent = hidden ? "🙈" : "👁";
    });

    toggleGithubTokenBtn.addEventListener("click", () => {
        const hidden = githubTokenInput.type === "password";
        githubTokenInput.type = hidden ? "text" : "password";
        toggleGithubTokenBtn.textContent = hidden ? "🙈" : "👁";
    });

    rememberKey.addEventListener("change", saveKeyState);
    apiKeyInput.addEventListener("input", () => {
        if (rememberKey.checked) {
            localStorage.setItem(STORAGE_KEY, apiKeyInput.value || "");
        }
    });
    githubTokenInput.addEventListener("input", () => {
        if (rememberKey.checked) {
            localStorage.setItem(STORAGE_GITHUB_TOKEN, githubTokenInput.value || "");
        }
    });

    startBtn.addEventListener("click", () => {
        startAnalysis().catch((error) => {
            appendLog(`前端异常: ${error}`);
            setStatus("任务执行异常", "error");
            startBtn.disabled = false;
            startBtn.textContent = "开始智能分析";
        });
    });

    for (const link of [downloadDocx, downloadHtml, downloadMd]) {
        link.addEventListener("click", (event) => {
            if (link.classList.contains("disabled")) {
                event.preventDefault();
            }
        });
    }
}

restoreKeyState();
bindEvents();
setStatus("待开始", "idle");
clearDownloads();
