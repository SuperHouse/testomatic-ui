// Enters "display mode": hides the sidebar, header, footer, page heading, and the
// triggering button itself, leaving only the page's own content visible (see .display-mode
// rules in style.css). Exiting requires reloading the page without a ?display=1 marker.
function enterDisplayMode() {
    document.body.classList.add('display-mode');
}

// Reloads the current page, preserving display mode across the reload if it's currently
// active (via a ?display=1 marker), unlike a plain location.reload(). Pages that need to
// resync themselves (e.g. polling that detects added/removed rows) should call this instead
// of location.reload() so a background refresh doesn't silently exit display mode.
function reloadPreservingDisplayMode() {
    const url = new URL(window.location.href);
    if (document.body.classList.contains('display-mode')) {
        url.searchParams.set('display', '1');
    } else {
        url.searchParams.delete('display');
    }
    window.location.href = url.toString();
}

document.addEventListener('DOMContentLoaded', function () {
    if (new URLSearchParams(window.location.search).get('display') === '1') {
        enterDisplayMode();
    }
});

// Copies the text in btn's data-copy-text attribute to the clipboard, then briefly
// swaps the button's icon to a checkmark as feedback before reverting it.
function copyToClipboard(btn) {
    navigator.clipboard.writeText(btn.dataset.copyText).then(function () {
        const icon = btn.querySelector('i');
        const originalClass = icon.className;
        icon.className = 'bi bi-check-lg';
        setTimeout(function () {
            icon.className = originalClass;
        }, 1500);
    });
}

function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

// Enables drag-and-drop reordering of <tr> rows within the <tbody> identified by tbodyId.
// Each row must have a data-stage-id attribute; the new order is posted to the URL in the
// tbody's data-reorder-url attribute as JSON: {"order": [id, id, ...]}.
function initSortableReorder(tbodyId) {
    const tbody = document.getElementById(tbodyId);
    if (!tbody || typeof Sortable === 'undefined') return;

    Sortable.create(tbody, {
        handle: '.bi-grip-vertical',
        animation: 150,
        onEnd: function () {
            const order = Array.from(tbody.querySelectorAll('tr[data-stage-id]'))
                .map(function (row) { return row.dataset.stageId; });

            fetch(tbody.dataset.reorderUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCookie('csrftoken'),
                },
                body: JSON.stringify({ order: order }),
            });
        },
    });
}

// Wires up .status-btn buttons within the <tbody> identified by tbodyId so clicking one
// posts to its data-url and updates the row's status highlighting, table colour class,
// and completion date input (if returned) without reloading the page.
function initStatusButtons(tbodyId) {
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;

    tbody.addEventListener('click', function (event) {
        const button = event.target.closest('.status-btn');
        if (!button) return;

        const row = button.closest('tr');
        const group = button.closest('.status-buttons');

        fetch(button.dataset.url, {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCookie('csrftoken'),
            },
        })
            .then(function (response) { return response.json(); })
            .then(function (data) {
                if (!data.status) return;

                group.querySelectorAll('.status-btn').forEach(function (btn) {
                    const color = btn.dataset.color;
                    btn.classList.remove('btn-' + color, 'btn-outline-' + color);
                    btn.classList.add(btn.dataset.status === data.status ? 'btn-' + color : 'btn-outline-' + color);
                });

                row.classList.remove('table-info', 'table-warning', 'table-success');
                if (data.table_class) {
                    row.classList.add(data.table_class);
                }

                if (data.completion_date) {
                    const completionInput = row.querySelector('input[name="completion_date"]');
                    if (completionInput) {
                        completionInput.value = data.completion_date;
                    }
                }
            });
    });
}

// Wires up .category-header rows within the container identified by containerId so
// clicking one toggles visibility of its .part-row siblings (matched via data-category)
// and persists the expanded/collapsed state server-side via a POST to toggleUrl. Bound to
// the container itself (not its rows) via event delegation, so it keeps working after
// initServerFilter() replaces the container's innerHTML.
function initCategoryCollapse(containerId, toggleUrl) {
    const container = document.getElementById(containerId);
    if (!container) return;

    container.addEventListener('click', function (event) {
        const header = event.target.closest('.category-header');
        if (!header || !container.contains(header)) return;

        const categoryKey = header.dataset.category;
        const expanded = !header.classList.contains('expanded');
        header.classList.toggle('expanded', expanded);

        const caret = header.querySelector('.category-caret');
        if (caret) {
            caret.classList.toggle('bi-caret-down-fill', expanded);
            caret.classList.toggle('bi-caret-right-fill', !expanded);
        }

        container.querySelectorAll('.part-row[data-category="' + categoryKey + '"]').forEach(function (row) {
            row.style.display = expanded ? '' : 'none';
        });

        fetch(toggleUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-CSRFToken': getCookie('csrftoken'),
            },
            body: 'category=' + encodeURIComponent(categoryKey) + '&expanded=' + expanded,
        });
    });
}

function initServerFilter(resultsId) {
    const input = document.getElementById('list-search');
    const clearBtn = document.getElementById('list-search-clear');
    const resultsDiv = document.getElementById(resultsId);
    if (!input || !resultsDiv) return;

    let debounceTimer;

    async function fetchResults(q) {
        const url = q ? '?q=' + encodeURIComponent(q) : '?';
        try {
            const response = await fetch(url);
            const html = await response.text();
            const doc = new DOMParser().parseFromString(html, 'text/html');
            const newResults = doc.getElementById(resultsId);
            if (newResults) {
                resultsDiv.innerHTML = newResults.innerHTML;
            }
            history.pushState(null, '', url);
        } catch (e) {
            console.error('Filter fetch failed:', e);
        }
    }

    input.addEventListener('input', function() {
        const q = input.value.trim();
        clearBtn.style.display = q ? '' : 'none';
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(function() { fetchResults(q); }, 300);
    });

    clearBtn.addEventListener('click', function() {
        input.value = '';
        clearBtn.style.display = 'none';
        fetchResults('');
        input.focus();
    });
}

// Activates the CoreUI nav-tabs + tab-content tab (see e.g. design_detail.html) containing
// the element matching the current URL hash, if any - so a redirect like "#bom" lands on the
// right tab instead of a hidden pane. Simulates a click on the tab's own trigger link rather
// than calling window.coreui.Tab directly, so this doesn't need its own reference to that
// global. Tab triggers here use data-coreui-toggle, not Bootstrap's data-bs-toggle - this
// CoreUI 4 bundle doesn't expose a window.bootstrap at all, only window.coreui (confirmed by
// inspecting the loaded bundle; a data-bs-toggle="tab" trigger elsewhere in this codebase,
// e.g. device_grid.html, doesn't actually respond to clicks because of this). Call this on
// pages using the tab pattern with anchors inside their panes; a no-op if there's no hash or
// no matching pane.
function activateTabFromHash() {
    if (!location.hash) return;
    let target;
    try {
        target = document.querySelector(location.hash);
    } catch (e) {
        return; // an invalid selector (e.g. a hash that isn't a valid CSS id) - nothing to do
    }
    if (!target) return;
    const pane = target.closest('.tab-pane');
    if (!pane || !pane.id) return;
    const trigger = document.querySelector('[data-coreui-toggle="tab"][href="#' + pane.id + '"]');
    if (trigger) {
        trigger.click();
        target.scrollIntoView({ block: 'start' });
    }
}

// Sidebar drawer toggle for mobile: slides in/out with a tap-to-dismiss backdrop.
// CoreUI's data-coreui-toggle is removed to avoid conflicts with our handler.
document.addEventListener('DOMContentLoaded', function() {
    const sidebar = document.getElementById('sidebar');
    const toggler = document.querySelector('.header-toggler');
    if (!sidebar || !toggler) return;

    toggler.removeAttribute('data-coreui-toggle');
    toggler.removeAttribute('data-coreui-breakpoint');

    function openSidebar() {
        sidebar.classList.add('sidebar-show');
        const backdrop = document.createElement('div');
        backdrop.id = 'sidebar-backdrop';
        backdrop.addEventListener('click', closeSidebar);
        document.body.appendChild(backdrop);
    }

    function closeSidebar() {
        sidebar.classList.remove('sidebar-show');
        const el = document.getElementById('sidebar-backdrop');
        if (el) el.remove();
    }

    toggler.addEventListener('click', function() {
        if (sidebar.classList.contains('sidebar-show')) {
            closeSidebar();
        } else {
            openSidebar();
        }
    });

    window.addEventListener('resize', function() {
        if (window.innerWidth >= 992) closeSidebar();
    });
});
