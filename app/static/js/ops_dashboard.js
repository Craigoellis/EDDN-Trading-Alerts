function formatBytes(value) {
    if (value === null || value === undefined) {
        return "Unknown";
    }
    const units = ["B", "KB", "MB", "GB", "TB"];
    let size = Number(value);
    let unitIndex = 0;
    while (size >= 1024 && unitIndex < units.length - 1) {
        size /= 1024;
        unitIndex += 1;
    }
    return `${size.toFixed(size >= 100 || unitIndex === 0 ? 0 : 2)} ${units[unitIndex]}`;
}

function formatPercent(value) {
    return `${Number(value ?? 0).toFixed(2)}%`;
}

function formatUptime(seconds) {
    const totalSeconds = Math.max(0, Math.floor(Number(seconds ?? 0)));
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const remainingSeconds = totalSeconds % 60;
    return `${hours}h ${minutes}m ${remainingSeconds}s`;
}

function formatTimestamp(epoch) {
    if (!epoch) {
        return "Unknown";
    }
    return new Date(epoch * 1000).toLocaleString();
}

function setText(id, value) {
    const node = document.getElementById(id);
    if (node) {
        node.textContent = value;
    }
}

function renderMetrics(metrics) {
    setText("ops-pid", metrics.process.pid);
    setText("ops-working-set", formatBytes(metrics.process.working_set_bytes));
    setText("ops-working-set-detail", formatBytes(metrics.process.working_set_bytes));
    setText("ops-private", formatBytes(metrics.process.private_bytes));
    setText("ops-cpu", formatPercent(metrics.process.cpu_percent));
    setText("ops-cpu-detail", formatPercent(metrics.process.cpu_percent));
    setText("ops-uptime", formatUptime(metrics.process.uptime_seconds));

    setText("ops-cpu-count", metrics.system.cpu_count);
    setText("ops-total-memory", formatBytes(metrics.system.total_memory_bytes));
    setText("ops-available-memory", formatBytes(metrics.system.available_memory_bytes));

    setText("ops-project", formatBytes(metrics.storage.project_bytes));
    setText("ops-project-detail", formatBytes(metrics.storage.project_bytes));
    setText("ops-project-dir", metrics.storage.project_dir);
    setText("ops-store-detail", formatBytes(metrics.storage.app_store_bytes));
    setText("ops-storage-dir", metrics.storage.storage_dir);
    setText("ops-disk-total", formatBytes(metrics.storage.disk_total_bytes));
    setText("ops-disk-used", formatBytes(metrics.storage.disk_used_bytes));
    setText("ops-disk-free", formatBytes(metrics.storage.disk_free_bytes));
    setText("ops-updated-at", formatTimestamp(metrics.captured_at_epoch));
}

async function loadOpsMetrics() {
    const response = await fetch("/api/ops-metrics");
    if (!response.ok) {
        throw new Error("Failed to load ops metrics");
    }
    const payload = await response.json();
    renderMetrics(payload);
}

renderMetrics(window.__OPS_INITIAL_DATA__);
setInterval(() => {
    loadOpsMetrics().catch((error) => console.error(error));
}, 5000);
