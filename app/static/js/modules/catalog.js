// Catalog Management

import { escapeHtml } from './ui.js';

let catalogs = [];
let catalogList = null;

export function initializeCatalogList(domElements, catalogState) {
    catalogList = domElements.catalogList;
    // Use the catalogs array from catalogState (shared reference)
    if (catalogState && catalogState.catalogs) {
        // Replace the array contents to maintain reference
        catalogs.length = 0;
        catalogs.push(...catalogState.catalogs);
    }
    renderCatalogList();
}

export function setCatalogs(newCatalogs) {
    catalogs.length = 0;
    catalogs.push(...newCatalogs);
}

export function getCatalogs() {
    return catalogs;
}

export function renderCatalogList() {
    if (!catalogList) return;
    catalogList.innerHTML = '';
    catalogs.forEach((cat, index) => {
        const item = createCatalogItem(cat, index);
        catalogList.appendChild(item);
    });
}

function moveCatalogUp(index) {
    if (index === 0) return;
    [catalogs[index], catalogs[index - 1]] = [catalogs[index - 1], catalogs[index]];
    renderCatalogList();
}

function moveCatalogDown(index) {
    if (index === catalogs.length - 1) return;
    [catalogs[index], catalogs[index + 1]] = [catalogs[index + 1], catalogs[index]];
    renderCatalogList();
}

function createCatalogItem(cat, index) {
    const item = document.createElement('div');
    const disabledClass = !cat.enabled ? 'opacity-50' : '';
    // Modern neutral glass card to match new theme
    item.className = `catalog-item group bg-neutral-900/60 border border-white/10 rounded-xl p-4 backdrop-blur-sm transition-all hover:border-white/20 hover:bg-neutral-900/70 hover:shadow-lg hover:shadow-black/20 ${disabledClass}`;
    item.setAttribute('data-id', cat.id);
    item.setAttribute('data-index', index);

    const isRenamable = cat.id !== 'watchly.theme';

    // Determine active mode for toggle buttons
    const enabledMovie = cat.enabledMovie !== false;
    const enabledSeries = cat.enabledSeries !== false;
    let activeMode = 'both';
    if (enabledMovie && !enabledSeries) activeMode = 'movie';
    else if (!enabledMovie && enabledSeries) activeMode = 'series';
    item.innerHTML = `
        <div class="flex items-start gap-3 sm:items-center sm:gap-4">
            <div class="sort-buttons flex flex-col gap-1 flex-shrink-0 mt-0.5 sm:mt-0">
                <button type="button" class="action-btn move-up p-1 text-slate-500 hover:text-white hover:bg-white/10 rounded transition disabled:opacity-30 disabled:hover:bg-transparent" title="Move up" ${index === 0 ? 'disabled' : ''}>
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 15l-6-6-6 6"/></svg>
                </button>
                <button type="button" class="action-btn move-down p-1 text-slate-500 hover:text-white hover:bg-white/10 rounded transition disabled:opacity-30 disabled:hover:bg-transparent" title="Move down" ${index === catalogs.length - 1 ? 'disabled' : ''}>
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>
                </button>
            </div>
            <div class="flex-grow min-w-0 space-y-1 sm:space-y-0 sm:flex sm:items-center sm:gap-4">
                <div class="name-container relative flex items-center min-w-0 h-auto sm:h-9 flex-grow">
                    <span class="catalog-name-text font-medium text-white break-words leading-snug sm:truncate cursor-default w-full">${escapeHtml(cat.name)}</span>
                    <input type="text" class="catalog-name-input hidden absolute inset-0 w-full bg-neutral-950 border border-white/20 rounded-lg px-3 text-white outline-none text-sm font-medium shadow-sm font-mono focus:ring-2 focus:ring-white/20 focus:border-white/30" value="${escapeHtml(cat.name)}">
                    ${isRenamable ? `<button type="button" class="action-btn rename-btn ml-2 p-1.5 flex-shrink-0 text-slate-400 hover:text-white hover:bg-white/10 rounded-lg transition opacity-100 sm:opacity-0 sm:group-hover:opacity-100 focus:opacity-100" title="Rename"><svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg></button>` : ''}
                </div>
                <div class="catalog-desc sm:hidden text-xs text-slate-500 leading-relaxed">${escapeHtml(cat.description || '')}</div>
            </div>
            <label class="switch relative inline-flex items-center cursor-pointer flex-shrink-0 ml-auto sm:ml-0">
                <input type="checkbox" class="sr-only peer" ${cat.enabled ? 'checked' : ''} data-catalog-id="${cat.id}">
                <div class="w-11 h-6 bg-neutral-700 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-white/20 rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-white peer-checked:after:bg-black peer-checked:after:border-black"></div>
            </label>
        </div>
        <div class="catalog-desc hidden sm:block text-xs text-slate-500 mt-2 ml-8 pl-1">${escapeHtml(cat.description || '')}</div>
        <div class="mt-3 ml-8">
            <div class="inline-flex items-center bg-neutral-950 border border-white/10 rounded-lg p-1" role="group" aria-label="Content type selection">
                <button type="button" class="catalog-type-btn px-3 py-1.5 text-sm font-medium rounded-md transition-all ${activeMode === 'both' ? 'bg-white text-black shadow-sm hover:text-black' : 'text-slate-400 hover:text-white'}" data-catalog-id="${cat.id}" data-mode="both">
                    Both
                </button>
                <button type="button" class="catalog-type-btn px-3 py-1.5 text-sm font-medium rounded-md transition-all ${activeMode === 'movie' ? 'bg-white text-black shadow-sm hover:text-black' : 'text-slate-400 hover:text-white'}" data-catalog-id="${cat.id}" data-mode="movie">
                    Movie
                </button>
                <button type="button" class="catalog-type-btn px-3 py-1.5 text-sm font-medium rounded-md transition-all ${activeMode === 'series' ? 'bg-white text-black shadow-sm hover:text-black' : 'text-slate-400 hover:text-white'}" data-catalog-id="${cat.id}" data-mode="series">
                    Series
                </button>
            </div>
        </div>
    `;

    if (isRenamable) setupRenameLogic(item, cat);

    const switchInput = item.querySelector('.switch input');
    switchInput.addEventListener('change', (e) => {
        cat.enabled = e.target.checked;
        if (cat.enabled) item.classList.remove('opacity-50');
        else item.classList.add('opacity-50');
    });

    // Handle movie/series toggle button changes
    const allTypeButtons = item.querySelectorAll(`.catalog-type-btn[data-catalog-id="${cat.id}"]`);

    allTypeButtons.forEach(btn => {
        btn.addEventListener('click', (e) => {
            const mode = e.target.dataset.mode;

            // Update state
            if (mode === 'both') {
                cat.enabledMovie = true;
                cat.enabledSeries = true;
            } else if (mode === 'movie') {
                cat.enabledMovie = true;
                cat.enabledSeries = false;
            } else if (mode === 'series') {
                cat.enabledMovie = false;
                cat.enabledSeries = true;
            }

            // Update UI
            allTypeButtons.forEach(b => {
                b.classList.remove('bg-white', 'text-black', 'shadow-sm', 'hover:text-black');
                b.classList.add('text-slate-400', 'hover:text-white');
            });
            e.target.classList.remove('text-slate-400', 'hover:text-white');
            e.target.classList.add('bg-white', 'text-black', 'shadow-sm', 'hover:text-black');
        });
    });

    item.querySelector('.move-up').addEventListener('click', (e) => { e.preventDefault(); moveCatalogUp(index); });
    item.querySelector('.move-down').addEventListener('click', (e) => { e.preventDefault(); moveCatalogDown(index); });

    return item;
}

function setupRenameLogic(item, cat) {
    const nameContainer = item.querySelector('.name-container');
    const nameText = item.querySelector('.catalog-name-text');
    const nameInput = item.querySelector('.catalog-name-input');
    const renameBtn = item.querySelector('.rename-btn');

    const editActions = document.createElement('div');
    editActions.className = 'edit-actions hidden absolute right-1 top-1/2 -translate-y-1/2 flex gap-1 bg-neutral-900 pl-2 z-10';
    editActions.innerHTML = `
        <button type="button" class="edit-btn save p-1 text-green-500 hover:bg-green-500/10 rounded transition" title="Save"><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg></button>
        <button type="button" class="edit-btn cancel p-1 text-red-500 hover:bg-red-500/10 rounded transition" title="Cancel"><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
    `;
    nameContainer.appendChild(editActions);

    const saveBtn = editActions.querySelector('.save');
    const cancelBtn = editActions.querySelector('.cancel');

    function enableEdit() {
        nameContainer.classList.add('editing');
        nameText.classList.add('hidden');
        nameInput.classList.remove('hidden');
        editActions.classList.remove('hidden'); editActions.classList.add('flex');
        if (renameBtn) renameBtn.classList.add('invisible');
        nameInput.focus();
    }
    function saveEdit() {
        const newName = nameInput.value.trim();
        if (newName) { cat.name = newName; nameText.textContent = newName; nameInput.value = newName; }
        else { nameInput.value = cat.name; }
        closeEdit();
    }
    function cancelEdit() { nameInput.value = cat.name; closeEdit(); }
    function closeEdit() {
        nameContainer.classList.remove('editing');
        nameInput.classList.add('hidden');
        editActions.classList.add('hidden'); editActions.classList.remove('flex');
        nameText.classList.remove('hidden');
        if (renameBtn) renameBtn.classList.remove('invisible');
    }
    if (renameBtn) renameBtn.addEventListener('click', (e) => { e.preventDefault(); enableEdit(); });
    saveBtn.addEventListener('click', (e) => { e.preventDefault(); saveEdit(); });
    cancelBtn.addEventListener('click', (e) => { e.preventDefault(); cancelEdit(); });
    nameInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); saveEdit(); }
        else if (e.key === 'Escape') { cancelEdit(); }
    });
}

// catalogs is exported via getCatalogs() to maintain proper state management
