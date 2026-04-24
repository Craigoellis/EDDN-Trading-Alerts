const commodityState = window.__INITIAL_COMMODITY_DATA__;
const commodityMarketsBody = document.getElementById("commodity-markets-body");
const commodityHistoryBody = document.getElementById("commodity-history-body");

function formatNumber(value) {
    return new Intl.NumberFormat().format(value ?? 0);
}

function formatDistance(value) {
    return value === null || value === undefined ? "Unknown" : `${formatNumber(value)} Ls`;
}

function formatTimestamp(value) {
    return value ? new Date(value).toLocaleString() : "Unknown";
}

function renderCommodity(payload) {
    commodityMarketsBody.innerHTML = "";
    payload.markets.forEach((entry) => {
        const row = document.createElement("tr");
        row.innerHTML = `
            <td><a class="station-link" href="/stations?system=${encodeURIComponent(entry.system)}&station=${encodeURIComponent(entry.raw_station_name)}">${entry.station_name}</a></td>
            <td><a class="station-link" href="/systems?system=${encodeURIComponent(entry.system)}">${entry.system}</a></td>
            <td>${formatNumber(entry.buy_price)}</td>
            <td>${formatNumber(entry.sell_price)}</td>
            <td>${formatNumber(entry.stock)}</td>
            <td>${formatNumber(entry.demand)}</td>
            <td>${entry.pad_size}</td>
            <td>${formatDistance(entry.arrival_distance_ls)}</td>
            <td>${formatTimestamp(entry.updated_at)}</td>
        `;
        commodityMarketsBody.appendChild(row);
    });
    if (!payload.markets.length) {
        const row = document.createElement("tr");
        row.innerHTML = `<td colspan="9" class="empty-table-cell">No live listings for this commodity yet.</td>`;
        commodityMarketsBody.appendChild(row);
    }

    commodityHistoryBody.innerHTML = "";
    payload.history.forEach((entry) => {
        const row = document.createElement("tr");
        row.innerHTML = `
            <td><a class="station-link" href="/stations?system=${encodeURIComponent(entry.system)}&station=${encodeURIComponent(entry.station)}">${entry.station}</a></td>
            <td><a class="station-link" href="/systems?system=${encodeURIComponent(entry.system)}">${entry.system}</a></td>
            <td>${formatNumber(entry.buy_price)}</td>
            <td>${formatNumber(entry.sell_price)}</td>
            <td>${formatNumber(entry.stock)}</td>
            <td>${formatNumber(entry.demand)}</td>
            <td>${formatTimestamp(entry.updated_at)}</td>
        `;
        commodityHistoryBody.appendChild(row);
    });
    if (!payload.history.length) {
        const row = document.createElement("tr");
        row.innerHTML = `<td colspan="7" class="empty-table-cell">No recent history for this commodity yet.</td>`;
        commodityHistoryBody.appendChild(row);
    }
}

async function refreshCommodity() {
    const query = new URLSearchParams({ commodity: commodityState.commodity.name }).toString();
    const response = await fetch(`/api/commodities?${query}`);
    const payload = await response.json();
    renderCommodity(payload);
}

renderCommodity(commodityState);
setInterval(() => {
    refreshCommodity().catch((error) => console.error(error));
}, 15000);
