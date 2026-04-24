const systemState = window.__INITIAL_SYSTEM_DATA__;
const systemStationsBody = document.getElementById("system-stations-body");
const systemHistoryBody = document.getElementById("system-history-body");
const systemLastRefresh = document.getElementById("system-last-refresh");

function formatNumber(value) {
    return new Intl.NumberFormat().format(value ?? 0);
}

function formatDistance(value) {
    return value === null || value === undefined ? "Unknown" : `${formatNumber(value)} Ls`;
}

function formatTimestamp(value) {
    return value ? new Date(value).toLocaleString() : "Unknown";
}

function renderSystem(payload) {
    systemLastRefresh.textContent = payload.system.last_poll_epoch
        ? new Date(payload.system.last_poll_epoch * 1000).toLocaleString()
        : "Waiting...";

    systemStationsBody.innerHTML = "";
    payload.stations.forEach((station) => {
        const row = document.createElement("tr");
        row.innerHTML = `
            <td><a class="station-link" href="/stations?system=${encodeURIComponent(station.system)}&station=${encodeURIComponent(station.raw_station_name)}">${station.station_name}</a></td>
            <td>${station.station_type}</td>
            <td>${station.pad_size}</td>
            <td>${formatDistance(station.arrival_distance_ls)}</td>
            <td>${formatNumber(station.commodity_count)}</td>
            <td>${formatTimestamp(station.latest_update_at)}</td>
        `;
        systemStationsBody.appendChild(row);
    });

    if (!payload.stations.length) {
        const row = document.createElement("tr");
        row.innerHTML = `<td colspan="6" class="empty-table-cell">No stations have been tracked for this system yet.</td>`;
        systemStationsBody.appendChild(row);
    }

    systemHistoryBody.innerHTML = "";
    payload.history.forEach((entry) => {
        const row = document.createElement("tr");
        row.innerHTML = `
            <td><a class="station-link" href="/commodities?commodity=${encodeURIComponent(entry.commodity)}">${entry.commodity_display}</a></td>
            <td><a class="station-link" href="/stations?system=${encodeURIComponent(entry.system)}&station=${encodeURIComponent(entry.station)}">${entry.station}</a></td>
            <td>${formatNumber(entry.buy_price)}</td>
            <td>${formatNumber(entry.sell_price)}</td>
            <td>${formatNumber(entry.stock)}</td>
            <td>${formatNumber(entry.demand)}</td>
            <td>${formatTimestamp(entry.updated_at)}</td>
        `;
        systemHistoryBody.appendChild(row);
    });

    if (!payload.history.length) {
        const row = document.createElement("tr");
        row.innerHTML = `<td colspan="7" class="empty-table-cell">No recent history for this system yet.</td>`;
        systemHistoryBody.appendChild(row);
    }
}

async function refreshSystem() {
    const query = new URLSearchParams({ system: systemState.system.name }).toString();
    const response = await fetch(`/api/systems?${query}`);
    const payload = await response.json();
    renderSystem(payload);
}

renderSystem(systemState);
setInterval(() => {
    refreshSystem().catch((error) => console.error(error));
}, 15000);
