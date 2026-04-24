const stationBrowserState = {
    filters: window.__INITIAL_STATION_BROWSER_DATA__.filters,
};

const stationBrowserBody = document.getElementById("station-browser-body");
const stationBrowserForm = document.getElementById("station-browser-form");
const stationBrowserReset = document.getElementById("station-browser-reset");
const stationBrowserCount = document.getElementById("station-browser-count");
const stationBrowserCarrier = document.getElementById("station-browser-carrier");
const stationBrowserRefresh = document.getElementById("station-browser-refresh");

function formatNumber(value) {
    return new Intl.NumberFormat().format(value ?? 0);
}

function formatDistance(value) {
    return value === null || value === undefined ? "Unknown" : `${formatNumber(value)} Ls`;
}

function formatTimestamp(value) {
    return value ? new Date(value).toLocaleString() : "Unknown";
}

function renderStationBrowser(payload) {
    stationBrowserCount.textContent = formatNumber(payload.summary.station_count);
    stationBrowserCarrier.textContent = payload.filters.fleet_carrier_mode.charAt(0).toUpperCase() + payload.filters.fleet_carrier_mode.slice(1);
    stationBrowserRefresh.textContent = payload.summary.last_poll_epoch
        ? new Date(payload.summary.last_poll_epoch * 1000).toLocaleString()
        : "Waiting...";

    stationBrowserBody.innerHTML = "";
    if (!payload.stations.length) {
        const row = document.createElement("tr");
        row.innerHTML = `<td colspan="7" class="empty-table-cell">No stations match the current filters.</td>`;
        stationBrowserBody.appendChild(row);
        return;
    }

    payload.stations.forEach((station) => {
        const row = document.createElement("tr");
        row.innerHTML = `
            <td><a class="station-link" href="/stations?system=${encodeURIComponent(station.system)}&station=${encodeURIComponent(station.raw_station_name)}">${station.station_name}</a></td>
            <td><a class="station-link" href="/systems?system=${encodeURIComponent(station.system)}">${station.system}</a></td>
            <td>${station.station_type}</td>
            <td>${station.pad_size}</td>
            <td>${formatDistance(station.arrival_distance_ls)}</td>
            <td>${formatNumber(station.commodity_count)}</td>
            <td>${formatTimestamp(station.updated_at)}</td>
        `;
        stationBrowserBody.appendChild(row);
    });
}

async function loadStationBrowser() {
    const query = new URLSearchParams(stationBrowserState.filters).toString();
    const response = await fetch(`/api/stations-browser?${query}`);
    if (!response.ok) {
        throw new Error("Failed to load stations");
    }
    const payload = await response.json();
    stationBrowserState.filters = payload.filters;
    renderStationBrowser(payload);
}

stationBrowserForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(stationBrowserForm);
    stationBrowserState.filters = Object.fromEntries(formData.entries());
    await loadStationBrowser();
});

stationBrowserReset.addEventListener("click", async () => {
    stationBrowserForm.reset();
    const defaults = window.__INITIAL_STATION_BROWSER_DATA__.filters;
    Object.entries(defaults).forEach(([key, value]) => {
        const field = stationBrowserForm.elements.namedItem(key);
        if (field) {
            field.value = value;
        }
    });
    stationBrowserState.filters = defaults;
    await loadStationBrowser();
});

renderStationBrowser(window.__INITIAL_STATION_BROWSER_DATA__);
setInterval(() => {
    loadStationBrowser().catch((error) => console.error(error));
}, 15000);
