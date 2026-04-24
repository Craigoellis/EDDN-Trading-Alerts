const stationState = window.__INITIAL_STATION_DATA__;
const stationCommodityBody = document.getElementById("station-commodity-body");
const stationHistoryBody = document.getElementById("station-history-body");
const stationLastRefresh = document.getElementById("station-last-refresh");
const stationSortForm = document.getElementById("station-sort-form");

function formatNumber(value) {
    return new Intl.NumberFormat().format(value ?? 0);
}

function formatTimestamp(value) {
    if (!value) {
        return "Unknown";
    }
    return new Date(value).toLocaleString();
}

function renderStationPayload(payload) {
    stationLastRefresh.textContent = payload.station.last_poll_epoch
        ? new Date(payload.station.last_poll_epoch * 1000).toLocaleString()
        : "Waiting...";

    stationCommodityBody.innerHTML = "";
    stationHistoryBody.innerHTML = "";

    if (!payload.commodities.length) {
        const row = document.createElement("tr");
        row.innerHTML = `<td colspan="6" class="empty-table-cell">No commodity rows have been received for this station yet.</td>`;
        stationCommodityBody.appendChild(row);
    } else {
        payload.commodities.forEach((commodity) => {
            const row = document.createElement("tr");
            row.innerHTML = `
                <td><a class="station-link" href="/commodities?commodity=${encodeURIComponent(commodity.commodity)}">${commodity.commodity_display}</a></td>
                <td>${formatNumber(commodity.buy_price)}</td>
                <td>${formatNumber(commodity.sell_price)}</td>
                <td>${formatNumber(commodity.stock)}</td>
                <td>${formatNumber(commodity.demand)}</td>
                <td>${formatTimestamp(commodity.updated_at)}</td>
            `;
            stationCommodityBody.appendChild(row);
        });
    }

    if (!payload.history.length) {
        const row = document.createElement("tr");
        row.innerHTML = `<td colspan="6" class="empty-table-cell">No history has been captured for this station yet.</td>`;
        stationHistoryBody.appendChild(row);
    } else {
        payload.history.forEach((entry) => {
            const row = document.createElement("tr");
            row.innerHTML = `
                <td><a class="station-link" href="/commodities?commodity=${encodeURIComponent(entry.commodity)}">${entry.commodity_display}</a></td>
                <td>${formatNumber(entry.buy_price)}</td>
                <td>${formatNumber(entry.sell_price)}</td>
                <td>${formatNumber(entry.stock)}</td>
                <td>${formatNumber(entry.demand)}</td>
                <td>${formatTimestamp(entry.updated_at)}</td>
            `;
            stationHistoryBody.appendChild(row);
        });
    }
}

async function refreshStation() {
    const query = new URLSearchParams({
        system: stationState.station.system,
        station: stationState.station.raw_name,
        sort_by: stationSortForm.elements.namedItem("sort_by").value,
        sort_order: stationSortForm.elements.namedItem("sort_order").value,
    }).toString();
    const response = await fetch(`/api/stations?${query}`);
    if (!response.ok) {
        throw new Error("Failed to load station detail");
    }
    const payload = await response.json();
    renderStationPayload(payload);
}

renderStationPayload(stationState);
stationSortForm.addEventListener("change", () => {
    refreshStation().catch((error) => console.error(error));
});
setInterval(() => {
    refreshStation().catch((error) => console.error(error));
}, 15000);
