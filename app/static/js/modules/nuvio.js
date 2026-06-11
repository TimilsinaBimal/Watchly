// "Install on Nuvio" — writes the addon into the user's Nuvio Sync account.
//
// Nuvio has no install deep link, but its apps sync installed addons from a
// Supabase table. We sign the user in with their Nuvio credentials directly
// from the browser (same approach as the community Trakt-Nuvio bridge) and
// insert the addon row. Credentials and tokens never touch Watchly's servers.
//
// This rides on Nuvio's unofficial API: failures are expected eventually, so
// every error path falls back to "copy the URL and paste it in Nuvio".

const NUVIO_BASE = 'https://dpyhjjcoabcglfmgecug.supabase.co';
// Public (publishable) client key, same one Nuvio's own web app ships.
const NUVIO_KEY = 'sb_publishable_zcNkgqGJjBtj8GoRlMvl9A_zkdmXhf5';

const FALLBACK_HINT = 'You can always install manually: copy the manifest URL, then in Nuvio go to Settings → Addons and paste it.';

async function nuvioRequest(path, { method = 'GET', token, body, headers = {} } = {}) {
    const response = await fetch(`${NUVIO_BASE}${path}`, {
        method,
        headers: {
            apikey: NUVIO_KEY,
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
    return { token: data.access_token, userId: data.user.id };
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
                <h3 class="text-lg font-semibold text-white">Install on Nuvio</h3>
                <button type="button" class="text-slate-500 hover:text-white transition" data-nuvio-close aria-label="Close">✕</button>
            </div>
            <p class="text-xs text-slate-500 mb-5">Sign in with your Nuvio account. Credentials go directly from your
                browser to Nuvio and are never stored or seen by Watchly.</p>

            <div id="nuvioLoginStep" class="grid gap-3">
                <input id="nuvioEmail" type="email" autocomplete="email" placeholder="Nuvio email"
                    class="w-full bg-neutral-950 border border-slate-700 rounded-xl px-4 py-3 text-white placeholder-slate-500 focus:ring-2 focus:ring-white/20 focus:border-white/30 outline-none transition-all">
                <input id="nuvioPassword" type="password" autocomplete="current-password" placeholder="Nuvio password"
                    class="w-full bg-neutral-950 border border-slate-700 rounded-xl px-4 py-3 text-white placeholder-slate-500 focus:ring-2 focus:ring-white/20 focus:border-white/30 outline-none transition-all">
                <button type="button" id="nuvioSubmitBtn"
                    class="mt-1 w-full bg-white text-black hover:bg-white/90 font-medium py-3 rounded-xl transition border border-white/10">
                    Sign in &amp; Install</button>
            </div>

            <div id="nuvioProfileStep" class="hidden grid gap-3">
                <label class="text-xs text-slate-400">Choose the profile to install to</label>
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

export function openNuvioInstall(manifestUrl) {
    if (!manifestUrl) return;
    const modal = ensureModal();

    const loginStep = modal.querySelector('#nuvioLoginStep');
    const profileStep = modal.querySelector('#nuvioProfileStep');
    const status = modal.querySelector('#nuvioStatus');
    loginStep.classList.remove('hidden');
    profileStep.classList.add('hidden');
    status.classList.add('hidden');

    let session = null;

    const finishInstall = async (profileId, button) => {
        setBusy(button, true, 'Installing…');
        try {
            const result = await installToProfile({ ...session, profileId, manifestUrl });
            loginStep.classList.add('hidden');
            profileStep.classList.add('hidden');
            setStatus('success', result === 'already-installed'
                ? 'Watchly is already installed on this Nuvio profile.'
                : 'Installed! Watchly will appear in Nuvio after its next sync (reopen the app if needed).');
        } catch (err) {
            setStatus('error', `Install failed: ${err.message}. ${FALLBACK_HINT}`);
        } finally {
            setBusy(button, false);
        }
    };

    const submitBtn = modal.querySelector('#nuvioSubmitBtn');
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
            const profiles = await nuvioProfiles(session.token);

            if (profiles.length === 1) {
                await finishInstall(Number(profiles[0].profile_index) || 1, submitBtn);
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
            setStatus('error', `${err.message} ${FALLBACK_HINT}`);
        } finally {
            setBusy(submitBtn, false);
        }
    };

    const profileInstallBtn = modal.querySelector('#nuvioProfileInstallBtn');
    profileInstallBtn.onclick = () => {
        const profileId = Number(modal.querySelector('#nuvioProfileSelect').value) || 1;
        finishInstall(profileId, profileInstallBtn);
    };

    modal.classList.remove('hidden');
    modal.classList.add('flex');
}
