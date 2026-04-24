async function fetchCommoditySuggestions(query) {
    const response = await fetch(`/api/commodity-suggestions?query=${encodeURIComponent(query)}`);
    if (!response.ok) {
        return [];
    }
    const payload = await response.json();
    return Array.isArray(payload.commodities) ? payload.commodities : [];
}

function setupCommodityPicker(input) {
    const wrapper = input.closest(".suggest-field");
    const list = wrapper?.querySelector("[data-commodity-suggest-list]");
    if (!wrapper || !list) {
        return;
    }

    let requestCounter = 0;

    const hideList = () => {
        list.hidden = true;
        list.innerHTML = "";
    };

    const showSuggestions = async () => {
        const query = input.value.trim();
        requestCounter += 1;
        const requestId = requestCounter;

        if (query.length < 2) {
            hideList();
            return;
        }

        const commodities = await fetchCommoditySuggestions(query);
        if (requestId !== requestCounter) {
            return;
        }

        const filteredCommodities = commodities.filter((commodity) => commodity.toLowerCase() !== query.toLowerCase());
        if (!filteredCommodities.length) {
            hideList();
            return;
        }

        list.innerHTML = "";
        filteredCommodities.forEach((commodityName) => {
            const option = document.createElement("button");
            option.type = "button";
            option.className = "suggest-option";
            option.textContent = commodityName.replace(/-/g, " ");
            option.addEventListener("click", () => {
                input.value = commodityName;
                hideList();
            });
            list.appendChild(option);
        });
        list.hidden = false;
    };

    input.addEventListener("input", () => {
        showSuggestions().catch(() => hideList());
    });

    input.addEventListener("focus", () => {
        if (input.value.trim().length >= 2) {
            showSuggestions().catch(() => hideList());
        }
    });

    input.addEventListener("blur", () => {
        window.setTimeout(hideList, 150);
    });
}

document.querySelectorAll("[data-commodity-suggest]").forEach(setupCommodityPicker);
