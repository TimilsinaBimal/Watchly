// Catalog Management

import { defaultCatalogs } from '../constants.js';
import { escapeHtml } from './ui.js';

let catalogList = null;
let appState = null;

export function initializeCatalogList(domElements, state) {
    catalogList = domElements.catalogList;
    appState = state;
    renderCatalogList();
}

export function renderCatalogList() {
    if (!catalogList || !appState) return;
    catalogList.innerHTML = '';
    appState.catalogs.forEach((cat, index) => {
        const item = createCatalogItem(cat, index);
        catalogList.appendChild(item);
    });
}

function moveCatalogUp(index) {
    if (index === 0) return;
    [appState.catalogs[index], appState.catalogs[index - 1]] = [appState.catalogs[index - 1], appState.catalogs[index]];
    renderCatalogList();
}

function moveCatalogDown(index) {
    if (index === appState.catalogs.length - 1) return;
    [appState.catalogs[index], appState.catalogs[index + 1]] = [appState.catalogs[index + 1], appState.catalogs[index]];
    renderCatalogList();
}

const MOVE_BTN_CLASS = 'action-btn inline-flex h-8 w-8 items-center justify-center rounded-md text-neutral-400 transition hover:bg-white/5 hover:text-white disabled:pointer-events-none disabled:opacity-25';
const CHIP_CLASS = 'catalog-action-btn inline-flex h-9 items-center gap-1.5 rounded-lg border border-white/10 px-3 text-sm font-medium text-neutral-300 transition hover:bg-white/5 hover:text-white aria-pressed:border-accent/40 aria-pressed:bg-accent/15 aria-pressed:text-accent-soft';
const TYPE_BTN_CLASS = 'catalog-type-btn h-8 rounded-md px-3 text-sm font-medium text-neutral-300 transition hover:text-white aria-pressed:bg-white/10 aria-pressed:text-white';
const ROWS_BTN_CLASS = 'rows-btn inline-flex h-8 w-8 items-center justify-center rounded-md text-base text-neutral-300 transition hover:bg-white/5 hover:text-white disabled:pointer-events-none disabled:opacity-30';

function createCatalogItem(cat, index) {
    const item = document.createElement('div');
    item.className = 'catalog-item group/row flex flex-col gap-3 rounded-xl border border-white/[0.07] bg-surface p-3 sm:p-4 lg:flex-row lg:items-center lg:gap-6 data-[enabled=false]:border-dashed data-[enabled=false]:border-white/10 data-[enabled=false]:bg-transparent';
    item.setAttribute('data-id', cat.id);
    item.setAttribute('data-index', index);
    item.dataset.enabled = String(cat.enabled);

    // watchly.theme builds names from genres/keywords at runtime; watchly.item
    // builds them from the seed bucket ("Because you loved/watched"). Both
    // would discard a user-supplied name, so the rename button is hidden.
    const isRenamable = cat.id !== 'watchly.theme' && cat.id !== 'watchly.item';
    // Only the item catalog can emit several rows; each gets its own seed.
    const hasRowCount = cat.id === 'watchly.item';

    // Determine active mode for toggle buttons
    const enabledMovie = cat.enabledMovie !== false;
    const enabledSeries = cat.enabledSeries !== false;
    let activeMode = 'both';
    if (enabledMovie && !enabledSeries) activeMode = 'movie';
    else if (!enabledMovie && enabledSeries) activeMode = 'series';
    // Initialize display_at_home and shuffle if not present (for backward compatibility)
    if (cat.display_at_home === undefined) cat.display_at_home = true;
    if (cat.shuffle === undefined) cat.shuffle = false;

    const description = escapeHtml(cat.description || '');

    item.innerHTML = `
        <div class="flex min-w-0 items-start gap-2 sm:gap-3 lg:max-w-2xl lg:flex-1">
            <div class="sort-buttons -my-0.5 flex flex-shrink-0 flex-col">
                <button type="button" class="${MOVE_BTN_CLASS} move-up" title="Move up" aria-label="Move up" ${index === 0 ? 'disabled' : ''}>
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m18 15-6-6-6 6"/></svg>
                </button>
                <button type="button" class="${MOVE_BTN_CLASS} move-down" title="Move down" aria-label="Move down" ${index === appState.catalogs.length - 1 ? 'disabled' : ''}>
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>
                </button>
            </div>
            <button type="button" role="switch" aria-checked="${cat.enabled}" aria-label="Enable ${escapeHtml(cat.name)}" title="Show this catalog in Stremio" class="catalog-action-btn visibility-btn group/switch mt-1.5 inline-flex h-6 w-11 flex-shrink-0 items-center rounded-full bg-white/15 transition hover:bg-white/20 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/60 aria-checked:bg-accent aria-checked:hover:bg-accent-hover" data-catalog-id="${cat.id}" data-action="visibility">
                <span class="pointer-events-none ml-0.5 h-5 w-5 rounded-full bg-neutral-400 shadow transition group-aria-checked/switch:translate-x-5 group-aria-checked/switch:bg-white"></span>
            </button>
            <div class="min-w-0 flex-1">
                <div class="name-container flex h-9 min-w-0 items-center gap-1">
                    <span class="catalog-name-text min-w-0 truncate font-medium text-white group-data-[enabled=false]/row:text-neutral-300 ${isRenamable ? 'cursor-text' : 'cursor-default'}">${escapeHtml(cat.name)}</span>
                    ${isRenamable ? `<button type="button" class="catalog-action-btn rename-btn icon-btn h-8 w-8 flex-shrink-0" title="Rename" aria-label="Rename" data-catalog-id="${cat.id}" data-action="rename">
                        <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>
                    </button>
                    <button type="button" class="reset-name-btn icon-btn hidden h-8 w-8 flex-shrink-0">
                        <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
                    </button>
                    <div class="catalog-name-input-wrapper hidden min-w-0 flex-1 items-center gap-1">
                        <input type="text" class="catalog-name-input -ml-1.5 h-8 min-w-0 flex-1 rounded-md bg-surface-sunken px-1.5font-medium text-white outline-none ring-1 ring-white/10 transition focus:ring-2 focus:ring-accent/40" aria-label="Catalog name" autocomplete="off" spellcheck="false">
                        <div class="edit-actions flex flex-shrink-0 items-center">
                            <button type="button" class="edit-btn save icon-btn h-8 w-8 text-accent hover:bg-accent/10 hover:text-accent-soft" title="Save (Enter)" aria-label="Save name">
                                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
                            </button>
                            <button type="button" class="edit-btn cancel icon-btn h-8 w-8" title="Cancel (Esc)" aria-label="Cancel rename">
                                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                            </button>
                        </div>
                    </div>` : ''}
                </div>
                <details class="catalog-desc group/desc">
                    <summary class="line-clamp-1 cursor-pointer list-none text-sm leading-relaxed text-neutral-300 hover:text-neutral-200 group-open/desc:line-clamp-none group-data-[enabled=false]/row:text-neutral-400 [&::-webkit-details-marker]:hidden" title="${description}">${description}</summary>
                </details>
            </div>
        </div>
        <div class="flex flex-wrap items-center gap-2 pl-10 sm:pl-[5.75rem] lg:ml-auto lg:flex-shrink-0 lg:justify-end lg:pl-0">
            ${hasRowCount ? `<div class="inline-flex h-9 items-center rounded-lg border border-white/10 bg-surface-sunken pl-3 pr-0.5" role="group" aria-label="Number of rows">
                <span class="mr-1 text-sm text-neutral-300">Rows</span>
                <button type="button" class="${ROWS_BTN_CLASS}" data-step="-1" aria-label="Fewer rows" ${cat.rows <= 1 ? 'disabled' : ''}>&minus;</button>
                <span class="rows-value w-5 text-center text-sm font-medium text-white">${cat.rows}</span>
                <button type="button" class="${ROWS_BTN_CLASS}" data-step="1" aria-label="More rows" ${cat.rows >= window.MAX_ITEM_ROWS ? 'disabled' : ''}>+</button>
            </div>` : ''}
            <div class="inline-flex h-9 items-center rounded-lg border border-white/10 bg-surface-sunken p-0.5" role="group" aria-label="Content type">
                <button type="button" class="${TYPE_BTN_CLASS}" aria-pressed="${activeMode === 'both'}" data-catalog-id="${cat.id}" data-mode="both">Both</button>
                <button type="button" class="${TYPE_BTN_CLASS}" aria-pressed="${activeMode === 'movie'}" data-catalog-id="${cat.id}" data-mode="movie">Movie</button>
                <button type="button" class="${TYPE_BTN_CLASS}" aria-pressed="${activeMode === 'series'}" data-catalog-id="${cat.id}" data-mode="series">Series</button>
            </div>
            <button type="button" class="${CHIP_CLASS} home-btn" aria-pressed="${cat.display_at_home}" title="Also show this row on the Stremio home screen, not only in Discover" data-catalog-id="${cat.id}" data-action="home">
                <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>
                    <polyline points="9 22 9 12 15 12 15 22"></polyline>
                </svg>
                Home
            </button>
            <button type="button" class="${CHIP_CLASS} shuffle-btn" aria-pressed="${cat.shuffle}" title="Shuffle this row instead of showing it in recommended order" data-catalog-id="${cat.id}" data-action="shuffle">
                <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M2 18h1.4c1.3 0 2.5-.6 3.3-1.7l6.1-8.6c.7-1.1 2-1.7 3.3-1.7H22"></path>
                    <path d="m18 2 4 4-4 4"></path>
                    <path d="M2 6h1.9c1.5 0 2.9.9 3.6 2.2"></path>
                    <path d="M22 18h-5.9c-1.3 0-2.6-.7-3.3-1.8l-.5-.8"></path>
                    <path d="m18 14 4 4-4 4"></path>
                </svg>
                Shuffle
            </button>
        </div>
    `;

    if (isRenamable) setupRenameLogic(item, cat);

    const visibilityBtn = item.querySelector('.visibility-btn');
    visibilityBtn.addEventListener('click', (e) => {
        e.preventDefault();
        cat.enabled = !cat.enabled;
        visibilityBtn.setAttribute('aria-checked', String(cat.enabled));
        item.dataset.enabled = String(cat.enabled);
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

            allTypeButtons.forEach(b => b.setAttribute('aria-pressed', String(b === e.target)));
        });
    });

    item.querySelector('.move-up').addEventListener('click', (e) => { e.preventDefault(); moveCatalogUp(index); });
    item.querySelector('.move-down').addEventListener('click', (e) => { e.preventDefault(); moveCatalogDown(index); });

    const homeBtn = item.querySelector('.home-btn');
    homeBtn.addEventListener('click', (e) => {
        e.preventDefault();
        cat.display_at_home = !cat.display_at_home;
        homeBtn.setAttribute('aria-pressed', String(cat.display_at_home));
    });

    const shuffleBtn = item.querySelector('.shuffle-btn');
    shuffleBtn.addEventListener('click', (e) => {
        e.preventDefault();
        cat.shuffle = !cat.shuffle;
        shuffleBtn.setAttribute('aria-pressed', String(cat.shuffle));
    });

    item.querySelectorAll('.rows-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            const next = cat.rows + Number(btn.dataset.step);
            if (next < 1 || next > window.MAX_ITEM_ROWS) return;
            cat.rows = next;
            item.querySelector('.rows-value').textContent = String(next);
            item.querySelector('.rows-btn[data-step="-1"]').disabled = next <= 1;
            item.querySelector('.rows-btn[data-step="1"]').disabled = next >= window.MAX_ITEM_ROWS;
        });
    });

    return item;
}

function setupRenameLogic(item, cat) {
    const nameContainer = item.querySelector('.name-container');
    const nameText = item.querySelector('.catalog-name-text');
    const nameInputWrapper = item.querySelector('.catalog-name-input-wrapper');
    const nameInput = item.querySelector('.catalog-name-input');
    const renameBtn = item.querySelector('.rename-btn');
    const resetBtn = item.querySelector('.reset-name-btn');
    const visibilityBtn = item.querySelector('.visibility-btn');
    const defaultName = defaultCatalogs.find(d => d.id === cat.id).name;
    resetBtn.title = `Renamed. Reset to "${defaultName}"`;
    resetBtn.setAttribute('aria-label', resetBtn.title);

    function setName(name) {
        cat.name = name;
        nameText.textContent = name;
        visibilityBtn.setAttribute('aria-label', `Enable ${name}`);
        resetBtn.classList.toggle('hidden', name === defaultName);
    }
    function openEdit() {
        nameInput.value = cat.name;
        nameContainer.classList.add('editing');
        nameText.classList.add('hidden');
        renameBtn.classList.add('hidden');
        resetBtn.classList.add('hidden');
        nameInputWrapper.classList.replace('hidden', 'flex');
        nameInput.focus();
        nameInput.select();
    }
    function closeEdit(save, returnFocus) {
        // Hiding or moving focus off the input fires focusout, which calls back in here.
        if (!nameContainer.classList.contains('editing')) return;
        nameContainer.classList.remove('editing');
        nameInputWrapper.classList.replace('flex', 'hidden');
        nameText.classList.remove('hidden');
        renameBtn.classList.remove('hidden');
        setName(save ? nameInput.value.trim() || defaultName : cat.name);
        if (returnFocus) renameBtn.focus();
    }

    setName(cat.name);
    renameBtn.addEventListener('click', openEdit);
    nameText.addEventListener('click', openEdit);
    resetBtn.addEventListener('click', () => { setName(defaultName); renameBtn.focus(); });
    item.querySelector('.edit-btn.save').addEventListener('click', () => closeEdit(true, true));
    item.querySelector('.edit-btn.cancel').addEventListener('click', () => closeEdit(false, true));
    // Keep focus in the input on mouse press, so clicking Cancel doesn't blur-save first.
    item.querySelectorAll('.edit-btn').forEach(btn => btn.addEventListener('mousedown', (e) => e.preventDefault()));
    nameInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); closeEdit(true, true); }
        else if (e.key === 'Escape') { e.preventDefault(); closeEdit(false, true); }
    });
    nameInputWrapper.addEventListener('focusout', (e) => {
        if (!nameInputWrapper.contains(e.relatedTarget)) closeEdit(true, false);
    });
}
