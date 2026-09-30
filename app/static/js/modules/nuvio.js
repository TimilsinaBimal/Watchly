// Nuvio sign-in — used both to install the addon and to connect Nuvio as a
// watch history source.
//
// Nuvio has no install deep link, and its account data (installed addons, watch
// history, profiles) lives in one Supabase project that it advertises at
// `/.well-known/nuvio`. We sign the user in with their Nuvio email and password
// straight from this page — the same approach as the community Trakt-Nuvio
// bridge — and then either insert the addon row or hand the session to the
// configure page. Nuvio credentials and tokens never touch Watchly's servers:
// only the session the user connects is stored, with the account.
//
// This rides on Nuvio's unofficial API: failures are expected eventually, so
// every error path falls back to the manual path.

let nuvioConfig = null;

const FALLBACK_HINT = 'You can always install manually: copy the manifest URL, then in Nuvio go to Settings → Addons and paste it.';

async function nuvioBackend() {
    if (nuvioConfig) return nuvioConfig;
    const response = await fetch('/nuvio/config');
    if (!response.ok) {
        throw new Error('Could not reach Nuvio. Try again in a moment.');
    }
    const data = await response.json();
    nuvioConfig = { base: data.backend_url, key: data.publishable_key };
    return nuvioConfig;
}

async function nuvioRequest(path, { method = 'GET', token, body, headers = {} } = {}) {
    const { base, key } = await nuvioBackend();
    const response = await fetch(`${base}${path}`, {
        method,
        headers: {
            apikey: key,
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
            ...headers,
        },
        body: body === undefined ? undefined : JSON.stringify(body),
    });

    let data = null;
    try {
        data = await response.json();
    } catch (e) { /* empty body (e.g. 201 with return=minimal) */ }

    if (!response.ok) {
        const message = data?.error_description || data?.msg || data?.message || `Nuvio request failed (${response.status})`;
        throw new Error(message);
    }
    return data;
}

async function nuvioLogin(email, password) {
    const data = await nuvioRequest('/auth/v1/token?grant_type=password', {
        method: 'POST',
        body: { email, password },
    });
    if (!data?.access_token || !data?.user?.id) {
        throw new Error('Nuvio did not return a session. Check your credentials.');
    }
    return {
        access_token: data.access_token,
        refresh_token: data.refresh_token || '',
        expires_at: Math.floor(Date.now() / 1000) + (Number(data.expires_in) || 0),
        user_id: data.user.id,
    };
}

async function nuvioProfiles(token) {
    const profiles = await nuvioRequest('/rest/v1/rpc/sync_pull_profiles', { method: 'POST', token, body: {} });
    return Array.isArray(profiles) && profiles.length ? profiles : [{ profile_index: 1, name: 'Default' }];
}

async function installToProfile({ token, userId, profileId, manifestUrl }) {
    const params = `select=url,sort_order&user_id=eq.${encodeURIComponent(userId)}&profile_id=eq.${profileId}`;
    const existing = await nuvioRequest(`/rest/v1/addons?${params}`, { token });
    const rows = Array.isArray(existing) ? existing : [];

    if (rows.some(row => row.url === manifestUrl)) {
        return 'already-installed';
    }

    const sortOrder = rows.reduce((max, row) => Math.max(max, Number(row.sort_order) || 0), 0) + 1;
    await nuvioRequest('/rest/v1/addons', {
        method: 'POST',
        token,
        headers: { Prefer: 'return=minimal' },
        body: {
            user_id: userId,
            profile_id: profileId,
            url: manifestUrl,
            name: 'Watchly',
            enabled: true,
            sort_order: sortOrder,
        },
    });
    return 'installed';
}

// --- Modal UI ---

let modalEl = null;

function ensureModal() {
    if (modalEl) return modalEl;

    modalEl = document.createElement('div');
    modalEl.id = 'nuvioInstallModal';
    modalEl.className = 'fixed inset-0 z-50 hidden items-center justify-center p-4';
    modalEl.innerHTML = `
        <div class="absolute inset-0 bg-black/70 backdrop-blur-sm" data-nuvio-close></div>
        <div class="relative bg-neutral-900 border border-white/10 rounded-2xl p-6 w-full max-w-md shadow-2xl shadow-black/50">
            <div class="flex items-start justify-between mb-1">
                <h3 class="text-lg font-semibold text-white" id="nuvioModalTitle">Install on Nuvio</h3>
                <button type="button" class="text-slate-500 hover:text-white transition" data-nuvio-close aria-label="Close">✕</button>
            </div>
            <p class="text-xs text-slate-500 mb-2">This signs you in to <strong class="text-slate-400">Nuvio</strong>,
                not Watchly. Your Nuvio email and password go straight from this page to Nuvio's own servers &mdash;
                Watchly never receives, stores or logs them.</p>
            <p class="text-xs text-slate-500 mb-5" id="nuvioModalFallbackHint">Prefer not to type them here? Close this and use
                <strong class="text-slate-400">Copy Link</strong> instead, then paste the URL into Nuvio under
                Settings &rarr; Addons.</p>

            <div id="nuvioLoginStep" class="grid gap-3">
                <input id="nuvioEmail" type="email" autocomplete="off" placeholder="Nuvio email"
                    class="w-full bg-neutral-950 border border-slate-700 rounded-xl px-4 py-3 text-white placeholder-slate-500 focus:ring-2 focus:ring-white/20 focus:border-white/30 outline-none transition-all">
                <input id="nuvioPassword" type="password" autocomplete="off" placeholder="Nuvio password"
                    class="w-full bg-neutral-950 border border-slate-700 rounded-xl px-4 py-3 text-white placeholder-slate-500 focus:ring-2 focus:ring-white/20 focus:border-white/30 outline-none transition-all">
                <button type="button" id="nuvioSubmitBtn"
                    class="mt-1 w-full bg-white text-black hover:bg-white/90 font-medium py-3 rounded-xl transition border border-white/10">
                    Sign in &amp; Install</button>
            </div>

            <div id="nuvioProfileStep" class="hidden grid gap-3">
                <label class="text-xs text-slate-400" id="nuvioProfileLabel">Choose the profile to install to</label>
                <select id="nuvioProfileSelect"
                    class="w-full appearance-none bg-neutral-950 border border-slate-700 rounded-xl px-4 py-3 text-white outline-none"></select>
                <button type="button" id="nuvioProfileInstallBtn"
                    class="mt-1 w-full bg-white text-black hover:bg-white/90 font-medium py-3 rounded-xl transition border border-white/10">Install</button>
            </div>

            <div id="nuvioStatus" class="hidden mt-4 text-sm rounded-xl p-3"></div>
        </div>`;
    document.body.appendChild(modalEl);

    modalEl.querySelectorAll('[data-nuvio-close]').forEach(el => el.addEventListener('click', closeModal));
    return modalEl;
}

function closeModal() {
    if (!modalEl) return;
    modalEl.classList.add('hidden');
    modalEl.classList.remove('flex');
    const password = modalEl.querySelector('#nuvioPassword');
    if (password) password.value = '';
}

function setStatus(kind, message) {
    const el = modalEl.querySelector('#nuvioStatus');
    el.classList.remove('hidden', 'bg-red-500/10', 'text-red-200', 'bg-green-500/10', 'text-green-200', 'bg-white/5', 'text-slate-300');
    const styles = {
        error: ['bg-red-500/10', 'text-red-200'],
        success: ['bg-green-500/10', 'text-green-200'],
        info: ['bg-white/5', 'text-slate-300'],
    };
    el.classList.add(...styles[kind]);
    el.textContent = message;
}

function setBusy(button, busy, busyText) {
    button.disabled = busy;
    button.classList.toggle('opacity-60', busy);
    if (busy) {
        button.dataset.originalText = button.textContent;
        button.textContent = busyText;
    } else if (button.dataset.originalText) {
        button.textContent = button.dataset.originalText;
    }
}

/**
 * Sign in to Nuvio and either install the manifest or hand the session back.
 *
 * @param {object} options
 * @param {string} [options.manifestUrl] install the addon into the chosen profile
 * @param {(session: object) => void} [options.onSession] connect instead of install
 */
function openNuvioDialog({ manifestUrl, onSession } = {}) {
    const installing = Boolean(manifestUrl);
    if (!installing && !onSession) return;

    const modal = ensureModal();
    const loginStep = modal.querySelector('#nuvioLoginStep');
    const profileStep = modal.querySelector('#nuvioProfileStep');
    const status = modal.querySelector('#nuvioStatus');
    const profileBtn = modal.querySelector('#nuvioProfileInstallBtn');

    modal.querySelector('#nuvioModalTitle').textContent = installing ? 'Install on Nuvio' : 'Connect Nuvio';
    modal.querySelector('#nuvioProfileLabel').textContent = installing
        ? 'Choose the profile to install to'
        : 'Choose the profile to read your watch history from';
    profileBtn.textContent = installing ? 'Install' : 'Connect';
    modal.querySelector('#nuvioModalFallbackHint').classList.toggle('hidden', !installing);

    loginStep.classList.remove('hidden');
    profileStep.classList.add('hidden');
    status.classList.add('hidden');

    let session = null;

    const finish = async (profileId, profileName, button) => {
        setBusy(button, true, installing ? 'Installing…' : 'Connecting…');
        try {
            if (installing) {
                const result = await installToProfile({ ...session, userId: session.user_id, profileId, manifestUrl });
                loginStep.classList.add('hidden');
                profileStep.classList.add('hidden');
                setStatus('success', result === 'already-installed'
                    ? 'Watchly is already installed on this Nuvio profile.'
                    : 'Installed! Watchly will appear in Nuvio after its next sync (reopen the app if needed).');
            } else {
                closeModal();
                onSession({ ...session, profile_id: profileId, profile_name: profileName });
            }
        } catch (err) {
            setStatus('error', installing
                ? `Install failed: ${err.message}. ${FALLBACK_HINT}`
                : `Could not connect: ${err.message}`);
        } finally {
            setBusy(button, false);
        }
    };

    const submitBtn = modal.querySelector('#nuvioSubmitBtn');
    submitBtn.textContent = installing ? 'Sign in & Install' : 'Sign in';
    submitBtn.onclick = async () => {
        const email = modal.querySelector('#nuvioEmail').value.trim();
        const password = modal.querySelector('#nuvioPassword').value;
        if (!email || !password) {
            setStatus('error', 'Enter your Nuvio email and password.');
            return;
        }

        setBusy(submitBtn, true, 'Signing in…');
        try {
            session = await nuvioLogin(email, password);
            // Session token in hand, so the password has no reason to stay in the DOM.
            modal.querySelector('#nuvioPassword').value = '';
            const profiles = await nuvioProfiles(session.access_token);

            if (profiles.length === 1) {
                const only = profiles[0];
                await finish(Number(only.profile_index) || 1, only.name || 'Default', submitBtn);
            } else {
                const select = modal.querySelector('#nuvioProfileSelect');
                select.innerHTML = '';
                profiles.forEach(p => {
                    const id = Number(p.profile_index) || 1;
                    const option = document.createElement('option');
                    option.value = String(id);
                    option.textContent = p.name || `Profile ${id}`;
                    select.appendChild(option);
                });
                loginStep.classList.add('hidden');
                profileStep.classList.remove('hidden');
                status.classList.add('hidden');
            }
        } catch (err) {
            setStatus('error', installing ? `${err.message} ${FALLBACK_HINT}` : err.message);
        } finally {
            setBusy(submitBtn, false);
        }
    };

    profileBtn.onclick = () => {
        const select = modal.querySelector('#nuvioProfileSelect');
        const selected = select.options[select.selectedIndex];
        finish(Number(select.value) || 1, selected ? selected.textContent : '', profileBtn);
    };

    modal.classList.remove('hidden');
    modal.classList.add('flex');
}

export function openNuvioInstall(manifestUrl) {
    openNuvioDialog({ manifestUrl });
}

export function openNuvioConnect(onSession) {
    openNuvioDialog({ onSession });
}
