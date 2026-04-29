/**
 * paginator.js — Reusable client-side pagination
 * ─────────────────────────────────────────────────────────────────────────────
 * Usage (drop this script on any page, then call):
 *
 *   const pg = createPaginator({
 *       tableBodySelector : 'tbody',          // where your <tr> rows live
 *       paginationSelector: '.pagination',    // your Bootstrap <ul class="pagination">
 *       rowsPerPage       : 10,               // entries per page (default 10)
 *       getVisibleRows    : () => myRows,     // optional — supply filtered row list
 *   });
 *
 *   pg.render();          // draw the first page
 *   pg.reset();           // jump back to page 1 (call after filtering)
 *   pg.currentPage        // read-only current page number
 *
 * The paginator works on whatever rows are currently "visible" (display !== none),
 * so it composes cleanly with a separate client-side filter — just call pg.reset()
 * inside your applyFilters() function and it will re-paginate the filtered set.
 * ─────────────────────────────────────────────────────────────────────────────
 */

function createPaginator({
    tableBodySelector  = 'tbody',
    paginationSelector = '.pagination',
    rowsPerPage        = 10,
    getVisibleRows     = null,   // optional custom supplier
} = {}) {

    const tbody      = document.querySelector(tableBodySelector);
    const pagination = document.querySelector(paginationSelector);

    if (!tbody || !pagination) {
        console.warn('Paginator: tbody or pagination element not found.');
        return null;
    }

    let currentPage = 1;

    // ── Helpers ──────────────────────────────────────────────────────────────

    /** Returns all rows that should be considered (not hidden by filters). */
    function getRows() {
        if (typeof getVisibleRows === 'function') return getVisibleRows();
        return Array.from(tbody.querySelectorAll('tr'));
    }

    function totalPages(rows) {
        return Math.max(1, Math.ceil(rows.length / rowsPerPage));
    }

    // ── Core render ──────────────────────────────────────────────────────────

    function render() {
        const rows  = getRows();
        const pages = totalPages(rows);

        // Clamp current page in case filters reduced the total
        if (currentPage > pages) currentPage = pages;

        const start = (currentPage - 1) * rowsPerPage;
        const end   = start + rowsPerPage;

        // Show/hide rows for this page
        const allRows = Array.from(tbody.querySelectorAll('tr'));
        allRows.forEach(row => {
            // A row filtered out stays hidden regardless of page
            const inFilteredSet = rows.includes(row);
            const inPageSlice   = rows.indexOf(row) >= start && rows.indexOf(row) < end;
            row.style.display   = (inFilteredSet && inPageSlice) ? '' : 'none';
        });

        buildPaginationUI(pages);
    }

    // ── Pagination UI ────────────────────────────────────────────────────────

    function buildPaginationUI(pages) {
        pagination.innerHTML = '';

        // Previous
        pagination.appendChild(makeItem('&laquo; Prev', currentPage === 1, () => {
            if (currentPage > 1) { currentPage--; render(); }
        }));

        // Page number buttons — show a window of max 5 around current page
        const window_ = 2;
        const start   = Math.max(1, currentPage - window_);
        const end     = Math.min(pages, currentPage + window_);

        if (start > 1) {
            pagination.appendChild(makeItem('1', false, () => { currentPage = 1; render(); }));
            if (start > 2) pagination.appendChild(makeEllipsis());
        }

        for (let i = start; i <= end; i++) {
            const active = i === currentPage;
            pagination.appendChild(makeItem(String(i), false, () => { currentPage = i; render(); }, active));
        }

        if (end < pages) {
            if (end < pages - 1) pagination.appendChild(makeEllipsis());
            pagination.appendChild(makeItem(String(pages), false, () => { currentPage = pages; render(); }));
        }

        // Next
        pagination.appendChild(makeItem('Next &raquo;', currentPage === pages, () => {
            if (currentPage < pages) { currentPage++; render(); }
        }));
    }

    function makeItem(html, disabled, onClick, active = false) {
        const li  = document.createElement('li');
        li.className = `page-item${disabled ? ' disabled' : ''}${active ? ' active' : ''}`;
        const a   = document.createElement('a');
        a.className   = 'page-link';
        a.href        = '#';
        a.innerHTML   = html;
        a.addEventListener('click', e => { e.preventDefault(); if (!disabled) onClick(); });
        li.appendChild(a);
        return li;
    }

    function makeEllipsis() {
        const li  = document.createElement('li');
        li.className  = 'page-item disabled';
        const span    = document.createElement('span');
        span.className = 'page-link';
        span.textContent = '…';
        li.appendChild(span);
        return li;
    }

    // ── Public API ───────────────────────────────────────────────────────────

    function reset() {
        currentPage = 1;
        render();
    }

    return { render, reset, get currentPage() { return currentPage; } };
}