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
    // Initialize display_at_home and shuffle if not present (for backward compatibility)
    if (cat.display_at_home === undefined) cat.display_at_home = true;
    if (cat.shuffle === undefined) cat.shuffle = false;

    item.innerHTML = `
        <div class="flex gap-2 sm:gap-3">
            <div class="sort-buttons flex flex-col gap-1.5 flex-shrink-0">
                <button type="button" class="action-btn move-up p-2 text-blue-400 bg-blue-500/20 hover:bg-blue-500/30 border border-blue-500/40 hover:border-blue-400/60 rounded-lg transition-all disabled:opacity-30 disabled:hover:bg-blue-500/20 disabled:cursor-not-allowed shadow-sm hover:shadow-md hover:shadow-blue-500/20" title="Move up" ${index === 0 ? 'disabled' : ''}>
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m18 15-6-6-6 6"/></svg>
                </button>
                <div class="h-9 flex items-center">
                    <button type="button" class="action-btn move-down p-2 text-blue-400 bg-blue-500/20 hover:bg-blue-500/30 border border-blue-500/40 hover:border-blue-400/60 rounded-lg transition-all disabled:opacity-30 disabled:hover:bg-blue-500/20 disabled:cursor-not-allowed shadow-sm hover:shadow-md hover:shadow-blue-500/20" title="Move down" ${index === catalogs.length - 1 ? 'disabled' : ''}>
                        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>
                    </button>
                </div>
            </div>
            <div class="flex-grow min-w-0">
                <div class="flex items-center gap-2 sm:gap-3">
                    <div class="name-container relative flex items-center min-w-0 h-9 flex-grow">
                        <span class="catalog-name-text font-medium text-white break-words leading-snug sm:truncate cursor-default w-full">${escapeHtml(cat.name)}</span>
                        <div class="catalog-name-input-wrapper hidden absolute inset-0 w-full bg-neutral-950 border border-white/20 rounded-lg overflow-hidden focus-within:ring-2 focus-within:ring-white/20 focus-within:border-white/30">
                            <input type="text" class="catalog-name-input w-full h-full bg-transparent pl-3 pr-20 text-white outline-none text-sm font-medium font-mono" value="${escapeHtml(cat.name)}">
                        </div>
                    </div>
                    <div class="flex items-center gap-2 flex-shrink-0">
                        ${isRenamable ? `<button type="button" class="catalog-action-btn rename-btn p-2 rounded-lg transition-all text-amber-400 bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 hover:border-amber-400/60 shadow-sm hover:shadow-md hover:shadow-amber-500/10" title="Rename" data-catalog-id="${cat.id}" data-action="rename">
                            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                                <path d="m18.5 2.5 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                            </svg>
                        </button>` : ''}
                        <div class="tooltip-wrapper">
                            <button type="button" class="catalog-action-btn home-btn p-2 rounded-lg transition-all ${cat.display_at_home ? 'text-emerald-400 bg-emerald-500/20 hover:bg-emerald-500/30 border border-emerald-500/40 hover:border-emerald-400/60' : 'text-slate-500 bg-slate-700/30 hover:bg-slate-700/40 border border-slate-600/40 hover:border-slate-500/60'} shadow-sm hover:shadow-md hover:shadow-emerald-500/10" data-catalog-id="${cat.id}" data-action="home">
                                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>
                                    <polyline points="9 22 9 12 15 12 15 22"></polyline>
                                </svg>
                            </button>
                            <span class="custom-tooltip" data-tooltip-text="${cat.display_at_home ? 'Hide from Home Page - This catalog will not appear on your Stremio home screen' : 'Show on Home Page - Display this catalog on your Stremio home screen'}">${cat.display_at_home ? 'Hide from Home Page- Only display this catalog in discover section.' : 'Show on Home Page as well as Discover section.'}</span>
                        </div>
                        <div class="tooltip-wrapper">
                            <button type="button" class="catalog-action-btn shuffle-btn p-2 rounded-lg transition-all ${cat.shuffle ? 'text-purple-400 bg-purple-500/20 hover:bg-purple-500/30 border border-purple-500/40 hover:border-purple-400/60' : 'text-slate-500 bg-slate-700/30 hover:bg-slate-700/40 border border-slate-600/40 hover:border-slate-500/60'} shadow-sm hover:shadow-md hover:shadow-purple-500/10" data-catalog-id="${cat.id}" data-action="shuffle">
                                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"></path>
                                </svg>
                            </button>
                            <span class="custom-tooltip" data-tooltip-text="${cat.shuffle ? 'Disable Random Order - Show items in recommended order' : 'Enable Random Order - Shuffle items in this catalog randomly'}">${cat.shuffle ? 'Disable Random Order - Show items in recommended order' : 'Enable Random Order - Shuffle items in this catalog randomly'}</span>
                        </div>
                        <div class="tooltip-wrapper">
                            <button type="button" class="catalog-action-btn visibility-btn p-2 rounded-lg transition-all ${cat.enabled ? 'text-cyan-400 bg-cyan-500/20 hover:bg-cyan-500/30 border border-cyan-500/40 hover:border-cyan-400/60' : 'text-slate-500 bg-slate-700/30 hover:bg-slate-700/40 border border-slate-600/40 hover:border-slate-500/60'} shadow-sm hover:shadow-md hover:shadow-cyan-500/10" data-catalog-id="${cat.id}" data-action="visibility">
                                ${cat.enabled ? `
                                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                        <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"></path>
                                        <circle cx="12" cy="12" r="3"></circle>
                                    </svg>
                                ` : `
                                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                        <path d="M9.88 9.88a3 3 0 1 0 4.24 4.24"></path>
                                        <path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68"></path>
                                        <path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61"></path>
                                        <line x1="2" x2="22" y1="2" y2="22"></line>
                                    </svg>
                                `}
                            </button>
                            <span class="custom-tooltip" data-tooltip-text="${cat.enabled ? 'Disable Catalog - Hide this catalog from Stremio' : 'Enable Catalog - Show this catalog in Stremio'}">${cat.enabled ? 'Disable Catalog - Hide this catalog from Stremio' : 'Enable Catalog - Show this catalog in Stremio'}</span>
                        </div>
                    </div>
                </div>
                <div class="flex items-center gap-2 sm:gap-3 mt-2">
                    <div class="catalog-desc text-xs text-slate-400 flex-grow">${escapeHtml(cat.description || '')}</div>
                </div>
                <div class="mt-3">
            <div class="inline-flex items-center bg-neutral-900/60 border border-white/10 rounded-xl p-1 backdrop-blur-sm" role="group" aria-label="Content type selection">
                <button type="button" class="catalog-type-btn px-4 py-2 text-sm font-medium rounded-lg transition-all outline-none focus:outline-none ${activeMode === 'both' ? 'bg-white/10 text-white border border-white/20 shadow-sm' : 'text-slate-400 hover:text-white hover:bg-white/5 border border-transparent'}" data-catalog-id="${cat.id}" data-mode="both">
                    Both
                </button>
                <button type="button" class="catalog-type-btn px-4 py-2 text-sm font-medium rounded-lg transition-all outline-none focus:outline-none ${activeMode === 'movie' ? 'bg-white/10 text-white border border-white/20 shadow-sm' : 'text-slate-400 hover:text-white hover:bg-white/5 border border-transparent'}" data-catalog-id="${cat.id}" data-mode="movie">
                    Movie
                </button>
                <button type="button" class="catalog-type-btn px-4 py-2 text-sm font-medium rounded-lg transition-all outline-none focus:outline-none ${activeMode === 'series' ? 'bg-white/10 text-white border border-white/20 shadow-sm' : 'text-slate-400 hover:text-white hover:bg-white/5 border border-transparent'}" data-catalog-id="${cat.id}" data-mode="series">
                    Series
                </button>
            </div>
        </div>
    `;

    if (isRenamable) setupRenameLogic(item, cat);

    // Handle rename button (now always visible, triggers edit mode)
    const renameBtn = item.querySelector('.rename-btn');
    if (renameBtn) {
        renameBtn.addEventListener('click', (e) => {
            e.preventDefault();
            const nameContainer = item.querySelector('.name-container');
            const nameText = item.querySelector('.catalog-name-text');
            const nameInputWrapper = item.querySelector('.catalog-name-input-wrapper');
            const nameInput = item.querySelector('.catalog-name-input');
            const editActions = item.querySelector('.edit-actions');
            if (nameContainer && nameText && nameInputWrapper && nameInput && editActions) {
                nameContainer.classList.add('editing');
                nameText.classList.add('hidden');
                nameInputWrapper.classList.remove('hidden');
                editActions.classList.remove('hidden');
                editActions.classList.add('flex');
                nameInput.focus();
            }
        });
    }

    // Handle visibility button toggle (replaces old switch)
    const visibilityBtn = item.querySelector('.visibility-btn');
    if (visibilityBtn) {
        visibilityBtn.addEventListener('click', (e) => {
            e.preventDefault();
            cat.enabled = !cat.enabled;
            updateVisibilityButton(visibilityBtn, cat.enabled);
            if (cat.enabled) item.classList.remove('opacity-50');
            else item.classList.add('opacity-50');
        });
    }

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
                b.classList.remove('bg-white/10', 'text-white', 'border-white/20', 'shadow-sm');
                b.classList.add('text-slate-400', 'hover:text-white', 'hover:bg-white/5', 'border-transparent');
            });
            e.target.classList.remove('text-slate-400', 'hover:text-white', 'hover:bg-white/5', 'border-transparent');
            e.target.classList.add('bg-white/10', 'text-white', 'border-white/20', 'shadow-sm');
        });
    });

    item.querySelector('.move-up').addEventListener('click', (e) => { e.preventDefault(); moveCatalogUp(index); });
    item.querySelector('.move-down').addEventListener('click', (e) => { e.preventDefault(); moveCatalogDown(index); });

    // Handle home button toggle
    const homeBtn = item.querySelector('.home-btn');
    if (homeBtn) {
        homeBtn.addEventListener('click', (e) => {
            e.preventDefault();
            cat.display_at_home = !cat.display_at_home;
            updateHomeButton(homeBtn, cat.display_at_home);
        });
    }

    // Handle shuffle button toggle
    const shuffleBtn = item.querySelector('.shuffle-btn');
    if (shuffleBtn) {
        shuffleBtn.addEventListener('click', (e) => {
            e.preventDefault();
            cat.shuffle = !cat.shuffle;
            updateShuffleButton(shuffleBtn, cat.shuffle);
        });
    }

    return item;
}

// Helper function to update button state with active/inactive classes and tooltips
function updateButtonState(btn, isActive, activeClasses, inactiveTooltip, activeTooltip, activeHTML = null, inactiveHTML = null) {
    const inactiveClasses = ['text-slate-500', 'bg-slate-700/30', 'border-slate-600/40', 'hover:bg-slate-700/40', 'hover:border-slate-500/60'];

    // Find the tooltip element (it's a sibling in the tooltip-wrapper)
    const tooltipWrapper = btn.closest('.tooltip-wrapper');
    const tooltip = tooltipWrapper ? tooltipWrapper.querySelector('.custom-tooltip') : null;

    if (isActive) {
        btn.classList.remove(...inactiveClasses);
        btn.classList.add(...activeClasses);
        if (tooltip) {
            tooltip.textContent = activeTooltip;
            tooltip.setAttribute('data-tooltip-text', activeTooltip);
        }
        if (activeHTML !== null) {
            btn.innerHTML = activeHTML;
        }
    } else {
        btn.classList.remove(...activeClasses);
        btn.classList.add(...inactiveClasses);
        if (tooltip) {
            tooltip.textContent = inactiveTooltip;
            tooltip.setAttribute('data-tooltip-text', inactiveTooltip);
        }
        if (inactiveHTML !== null) {
            btn.innerHTML = inactiveHTML;
        }
    }
}

function updateHomeButton(btn, isActive) {
    const activeClasses = ['text-emerald-400', 'bg-emerald-500/20', 'border-emerald-500/40', 'hover:bg-emerald-500/30', 'hover:border-emerald-400/60'];
    updateButtonState(
        btn,
        isActive,
        activeClasses,
        'Show on Home Page - Display this catalog on your Stremio home screen',
        'Hide from Home Page - This catalog will not appear on your Stremio home screen'
    );
}

function updateShuffleButton(btn, isActive) {
    const activeClasses = ['text-purple-400', 'bg-purple-500/20', 'border-purple-500/40', 'hover:bg-purple-500/30', 'hover:border-purple-400/60'];
    updateButtonState(
        btn,
        isActive,
        activeClasses,
        'Enable Random Order - Shuffle items in this catalog randomly',
        'Disable Random Order - Show items in recommended order'
    );
}

function updateVisibilityButton(btn, isActive) {
    const activeClasses = ['text-cyan-400', 'bg-cyan-500/20', 'border-cyan-500/40', 'hover:bg-cyan-500/30', 'hover:border-cyan-400/60'];
    const activeHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"></path>
            <circle cx="12" cy="12" r="3"></circle>
        </svg>
    `;
    const inactiveHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M9.88 9.88a3 3 0 1 0 4.24 4.24"></path>
            <path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68"></path>
            <path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61"></path>
            <line x1="2" x2="22" y1="2" y2="22"></line>
        </svg>
    `;
    updateButtonState(
        btn,
        isActive,
        activeClasses,
        'Enable Catalog - Show this catalog in Stremio',
        'Disable Catalog - Hide this catalog from Stremio',
        activeHTML,
        inactiveHTML
    );
}

function setupRenameLogic(item, cat) {
    const nameContainer = item.querySelector('.name-container');
    const nameText = item.querySelector('.catalog-name-text');
    const nameInputWrapper = item.querySelector('.catalog-name-input-wrapper');
    const nameInput = item.querySelector('.catalog-name-input');
    const renameBtn = item.querySelector('.rename-btn');

    const editActions = document.createElement('div');
    editActions.className = 'edit-actions hidden absolute right-1 top-0 bottom-0 flex items-center gap-1.5 pr-1 z-10';
    editActions.innerHTML = `
        <button type="button" class="edit-btn save p-1.5 h-full flex items-center justify-center text-emerald-400 hover:text-emerald-300 hover:bg-emerald-500/20 rounded transition" title="Save"><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg></button>
        <button type="button" class="edit-btn cancel p-1.5 h-full flex items-center justify-center text-red-400 hover:text-red-300 hover:bg-red-500/20 rounded transition" title="Cancel"><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg></button>
    `;
    nameInputWrapper.appendChild(editActions);

    const saveBtn = editActions.querySelector('.save');
    const cancelBtn = editActions.querySelector('.cancel');

    function saveEdit() {
        const newName = nameInput.value.trim();
        if (newName) { cat.name = newName; nameText.textContent = newName; nameInput.value = newName; }
        else { nameInput.value = cat.name; }
        closeEdit();
    }
    function cancelEdit() { nameInput.value = cat.name; closeEdit(); }
    function closeEdit() {
        nameContainer.classList.remove('editing');
        nameInputWrapper.classList.add('hidden');
        editActions.classList.add('hidden'); editActions.classList.remove('flex');
        nameText.classList.remove('hidden');
    }

    saveBtn.addEventListener('click', (e) => { e.preventDefault(); saveEdit(); });
    cancelBtn.addEventListener('click', (e) => { e.preventDefault(); cancelEdit(); });
    nameInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); saveEdit(); }
        else if (e.key === 'Escape') { cancelEdit(); }
    });
}
