const commodityState = {
    filters: window.__INITIAL_COMMODITY_DATA__.filters,
};

const commodityFiltersForm = document.getElementById("commodity-filters-form");
const commodityResetButton = document.getElementById("commodity-reset");
const commodityBuyBody = document.getElementById("commodity-buy-body");
const commoditySellBody = document.getElementById("commodity-sell-body");

function formatNumber(value) {
    return new Intl.NumberFormat().format(value ?? 0);
}

function formatDistance(value, suffix) {
    if (value === null || value === undefined) {
        return "Unknown";
    }
    return `${formatNumber(value)} ${suffix}`;
}

function formatTimestamp(value) {
    return value ? new Date(value).toLocaleString() : "Unknown";
}

function renderSummary(summary) {
    document.getElementById("commodity-buy-count").textContent = formatNumber(summary.buy_listing_count);
    document.getElementById("commodity-sell-count").textContent = formatNumber(summary.sell_listing_count);
    document.getElementById("commodity-best-prices").textContent = `${formatNumber(summary.best_buy_price)} / ${formatNumber(summary.best_sell_price)} Cr`;

    const refreshTarget = document.getElementById("commodity-last-refresh");
    if (summary.last_poll_epoch) {
        refreshTarget.textContent = `Last poll completed ${new Date(summary.last_poll_epoch * 1000).toLocaleString()}.`;
    } else {
        refreshTarget.textContent = "Waiting for the first EDDN polling cycle to complete.";
    }
}

function renderListings(target, listings, emptyMessage, mode) {
    target.innerHTML = "";

    listings.forEach((entry) => {
        const row = document.createElement("tr");
        const quantity = mode === "buy" ? entry.stock : entry.demand;
        const price = mode === "buy" ? entry.buy_price : entry.sell_price;
        row.innerHTML = `
            <td><a class="station-link" href="/stations?system=${encodeURIComponent(entry.system)}&station=${encodeURIComponent(entry.raw_station_name)}">${entry.station_name}</a></td>
            <td><a class="station-link" href="/systems?system=${encodeURIComponent(entry.system)}">${entry.system}</a></td>
            <td>${formatNumber(price)}</td>
            <td>${formatNumber(quantity)}</td>
            <td>${entry.station_type}</td>
            <td>${entry.pad_size}</td>
            <td>${formatDistance(entry.distance_from_origin_ly, "LY")}</td>
            <td>${formatDistance(entry.arrival_distance_ls, "Ls")}</td>
            <td>${formatTimestamp(entry.updated_at)}</td>
        `;
        target.appendChild(row);
    });

    if (!listings.length) {
        const row = document.createElement("tr");
        row.innerHTML = `<td colspan="9" class="empty-table-cell">${emptyMessage}</td>`;
        target.appendChild(row);
    }
}

function renderCommodity(payload) {
    commodityState.filters = payload.filters;
    renderSummary(payload.summary);
    renderListings(
        commodityBuyBody,
        payload.buy_listings,
        payload.summary.commodity_selected ? "No buy stations match these filters." : "Choose a commodity to see buy stations.",
        "buy",
    );
    renderListings(
        commoditySellBody,
        payload.sell_listings,
        payload.summary.commodity_selected ? "No sell stations match these filters." : "Choose a commodity to see sell stations.",
        "sell",
    );
}

async function loadCommodity() {
    const query = new URLSearchParams(commodityState.filters).toString();
    const response = await fetch(`/api/commodities?${query}`);
    if (!response.ok) {
        throw new Error("Failed to load commodity finder");
    }

    const payload = await response.json();
    renderCommodity(payload);
}

commodityFiltersForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(commodityFiltersForm);
    commodityState.filters = Object.fromEntries(formData.entries());
    await loadCommodity();
});

commodityResetButton.addEventListener("click", async () => {
    commodityFiltersForm.reset();
    const defaults = window.__INITIAL_COMMODITY_DATA__.filters;
    Object.entries(defaults).forEach(([key, value]) => {
        const field = commodityFiltersForm.elements.namedItem(key);
        if (field) {
            field.value = value;
        }
    });
    commodityState.filters = defaults;
    await loadCommodity();
});

renderCommodity(window.__INITIAL_COMMODITY_DATA__);
setInterval(() => {
    if (!commodityState.filters.commodity) {
        return;
    }
    loadCommodity().catch((error) => console.error(error));
}, 15000);
