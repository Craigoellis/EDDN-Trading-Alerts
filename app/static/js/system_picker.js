async function fetchSystemSuggestions(query) {
    const response = await fetch(`/api/system-suggestions?query=${encodeURIComponent(query)}`);
    if (!response.ok) {
        return [];
    }
    const payload = await response.json();
    return Array.isArray(payload.systems) ? payload.systems : [];
}

function setupSystemPicker(input) {
    const wrapper = input.closest(".suggest-field");
    const list = wrapper?.querySelector("[data-system-suggest-list]");
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

        const systems = await fetchSystemSuggestions(query);
        if (requestId !== requestCounter) {
            return;
        }

        const filteredSystems = systems.filter((system) => system.toLowerCase() !== query.toLowerCase());
        if (!filteredSystems.length) {
            hideList();
            return;
        }

        list.innerHTML = "";
        filteredSystems.forEach((systemName) => {
            const option = document.createElement("button");
            option.type = "button";
            option.className = "suggest-option";
            option.textContent = systemName;
            option.addEventListener("click", () => {
                input.value = systemName;
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

document.querySelectorAll("[data-system-suggest]").forEach(setupSystemPicker);
