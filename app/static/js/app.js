const state = {
    filters: window.__INITIAL_TRADE_DATA__.filters,
};

const resultsTable = document.getElementById("results-table");
const emptyState = document.getElementById("empty-state");
const filtersForm = document.getElementById("filters-form");
const resetFiltersButton = document.getElementById("reset-filters");

function formatNumber(value) {
    return new Intl.NumberFormat().format(value ?? 0);
}

function formatDistance(value, suffix) {
    if (value === null || value === undefined) {
        return "Unknown";
    }
    return `${formatNumber(value)} ${suffix}`;
}

function renderSummary(summary) {
    document.getElementById("best-profit").textContent = `${formatNumber(summary.best_profit_per_ton)} Cr/t`;
    document.getElementById("opportunity-count").textContent = formatNumber(summary.opportunity_count);
    document.getElementById("shortest-route").textContent = `${summary.shortest_route_ly.toFixed(2)} LY`;

    const refreshTarget = document.getElementById("last-refresh");
    if (summary.last_poll_epoch) {
        refreshTarget.textContent = `Last poll completed ${new Date(summary.last_poll_epoch * 1000).toLocaleString()}.`;
    } else {
        refreshTarget.textContent = "Waiting for the first EDDN polling cycle to complete.";
    }
}

function renderOpportunities(opportunities) {
    resultsTable.innerHTML = "";

    if (!opportunities.length) {
        emptyState.hidden = false;
        return;
    }

    emptyState.hidden = true;
    opportunities.forEach((trade) => {
        const article = document.createElement("article");
        article.className = "trade-card";
        article.innerHTML = `
            <div>
                <h3><a class="station-link" href="/commodities?commodity=${encodeURIComponent(trade.commodity)}">${trade.commodity_display}</a></h3>
                <div class="trade-meta">
                    <span>Buy: <a class="station-link" href="/stations?system=${encodeURIComponent(trade.buy_system)}&station=${encodeURIComponent(trade.buy_raw_station_name)}">${trade.buy_station_name}</a>, ${trade.buy_system}</span>
                    <span>Price: ${formatNumber(trade.buy_price)} Cr | Supply: ${formatNumber(trade.supply)}</span>
                    <span>Pad: ${trade.buy_pad_size} | Arrival: ${formatDistance(trade.buy_station_distance_ls, "Ls")}</span>
                </div>
            </div>
            <div>
                <h3>Destination</h3>
                <div class="route-meta">
                    <span>Sell: <a class="station-link" href="/stations?system=${encodeURIComponent(trade.sell_system)}&station=${encodeURIComponent(trade.sell_raw_station_name)}">${trade.sell_station_name}</a>, ${trade.sell_system}</span>
                    <span>Price: ${formatNumber(trade.sell_price)} Cr | Demand: ${formatNumber(trade.demand)}</span>
                    <span>Route: ${trade.distance_ly.toFixed(2)} LY | From ${trade.distance_origin_system}: ${trade.distance_from_origin_ly.toFixed(2)} LY</span>
                    <span>Pad: ${trade.sell_pad_size}</span>
                </div>
            </div>
            <div class="profit-pill">
                <span>Profit</span>
                <strong>+${formatNumber(trade.profit_per_ton)}</strong>
                <span>Cr per ton</span>
            </div>
        `;
        resultsTable.appendChild(article);
    });
}

function formatTimestamp(value) {
    if (!value) {
        return "Unknown";
    }
    return new Date(value).toLocaleString();
}

async function loadTrades() {
    const query = new URLSearchParams(state.filters).toString();
    const response = await fetch(`/api/trades?${query}`);
    if (!response.ok) {
        throw new Error("Failed to load trades");
    }

    const payload = await response.json();
    state.filters = payload.filters;
    renderSummary(payload.summary);
    renderOpportunities(payload.opportunities);
}

filtersForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(filtersForm);
    state.filters = Object.fromEntries(formData.entries());
    await loadTrades();
});

resetFiltersButton.addEventListener("click", async () => {
    filtersForm.reset();
    const defaults = window.__INITIAL_TRADE_DATA__.filters;
    Object.entries(defaults).forEach(([key, value]) => {
        const field = filtersForm.elements.namedItem(key);
        if (field) {
            field.value = value;
        }
    });
    state.filters = defaults;
    await loadTrades();
});

renderSummary(window.__INITIAL_TRADE_DATA__.summary);
renderOpportunities(window.__INITIAL_TRADE_DATA__.opportunities);
setInterval(() => {
    loadTrades().catch((error) => console.error(error));
}, 15000);
