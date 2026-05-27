// Top-level wiring: socket.io, top toolbar, sliders, manual motor, save/load.

(function () {
    const socket = io({ transports: ['websocket', 'polling'] });
    window.appSocket = socket;
    let currentTask = 'BUG';
    let currentMotors = ['motor_forward', 'motor_backward', 'motor_left', 'motor_right'];
    let pendingEnvTask = null;

    // ---------------------------------------------------------- socket events
    socket.on('connect', () => console.log('socket connected'));

    socket.on('state', (s) => {
        if (s.env) window.envView.update(s.env);
        if (s.env) updateEnvironmentChrome(s.env);
        if (s.env && pendingEnvTask && envTaskId(s.env) === pendingEnvTask) hideEnvLoading();
        if (s.gym_env_hz !== undefined) updateGymHzDisplay(s.gym_env_hz);
        if (s.activity) window.editorView.setActivity(s.activity);
        if (s.pulses)   window.editorView.setPulses(s.pulses);
        document.getElementById('stat-time').textContent = s.t.toFixed(1);
        if (s.env && s.env.kind === 'bug' && s.env.agent) {
            const a = s.env.agent;
            document.getElementById('stat-food').textContent    = a.food_eaten;
            document.getElementById('stat-hp').textContent      = a.health.toFixed(2);
            document.getElementById('stat-hunger').textContent  = a.hunger.toFixed(2);
            document.getElementById('stat-fatigue').textContent = a.fatigue.toFixed(2);
        }
        const playBtn = document.getElementById('btn-play');
        const pauseBtn = document.getElementById('btn-pause');
        playBtn.disabled = !!s.running;
        pauseBtn.disabled = !s.running;
    });

    socket.on('topology', (msg) => {
        if (msg.task) currentTask = msg.task;
        if (msg.motors) currentMotors = msg.motors;
        renderTaskSelect(msg.tasks || []);
        renderManualMotors();
        updateEnvironmentChrome({ kind: currentTask === 'BUG' ? 'bug' : 'gym' });
        window.editorView.setTopology(msg.topology, msg.default_neurons);
        if (!pendingEnvTask) hideEnvLoading();
    });

    socket.on('saved', (m) => {
        flash(`Сохранено: ${m.name}`);
    });

    // ---------------------------------------------------------- top toolbar
    document.getElementById('btn-play').addEventListener('click', () => socket.emit('control', { action: 'play' }));
    document.getElementById('btn-pause').addEventListener('click', () => socket.emit('control', { action: 'pause' }));
    document.getElementById('btn-reset-agent').addEventListener('click', () => socket.emit('control', { action: 'reset_agent' }));
    document.getElementById('btn-reset-net').addEventListener('click', () => socket.emit('control', { action: 'reset_network' }));

    function renderTaskSelect(tasks) {
        const select = document.getElementById('env-task');
        if (!select || !tasks.length) return;
        const known = Array.from(select.options).map(o => o.value).join('|');
        const incoming = tasks.map(t => t.id).join('|');
        if (known !== incoming) {
            select.innerHTML = '';
            for (const t of tasks) {
                const opt = document.createElement('option');
                opt.value = t.id;
                opt.textContent = t.label || t.id;
                select.appendChild(opt);
            }
        }
        select.value = currentTask;
    }

    const taskSelect = document.getElementById('env-task');
    if (taskSelect) {
        taskSelect.addEventListener('change', () => {
            const task = taskSelect.value;
            if (task !== currentTask) showEnvLoading(task, 'Подготовка окружения');
            socket.emit('set_task', { task });
        });
    }

    function showEnvLoading(task, title = 'Подготовка окружения') {
        pendingEnvTask = task || null;
        const overlay = document.getElementById('env-loading');
        const titleEl = document.getElementById('env-loading-title');
        const subtitleEl = document.getElementById('env-loading-subtitle');
        if (!overlay) return;
        if (titleEl) titleEl.textContent = title;
        if (subtitleEl) {
            const target = pendingEnvTask ? `: ${pendingEnvTask}` : '';
            subtitleEl.textContent = `Gymnasium готовит задачу${target}`;
        }
        overlay.classList.remove('hidden');
        overlay.setAttribute('aria-busy', 'true');
        if (taskSelect) taskSelect.disabled = true;
    }

    function hideEnvLoading() {
        pendingEnvTask = null;
        const overlay = document.getElementById('env-loading');
        if (overlay) {
            overlay.classList.add('hidden');
            overlay.setAttribute('aria-busy', 'false');
        }
        if (taskSelect) taskSelect.disabled = false;
    }

    function envTaskId(env) {
        if (!env) return '';
        if (env.task_id) return env.task_id;
        if (env.kind === 'bug') return 'BUG';
        if (env.task === 'cartpole') return 'CartPole';
        if (env.task === 'mountain_car') return 'MountainCar';
        return env.task || '';
    }

    function updateEnvironmentChrome(env) {
        const isBug = env.kind === 'bug';
        document.body.classList.toggle('gym-task', !isBug);
        document.body.classList.toggle('bug-task', isBug);
        bugOnlyElements().forEach((el) => {
            if (!el) return;
            el.hidden = !isBug;
            el.style.display = isBug ? '' : 'none';
        });
        gymOnlyElements().forEach((el) => {
            if (!el) return;
            el.hidden = isBug;
            el.style.display = isBug ? 'none' : '';
        });
    }

    function bugOnlyElements() {
        const elements = Array.from(document.querySelectorAll('.bug-only'));
        const add = (el) => {
            if (el && !elements.includes(el)) elements.push(el);
        };
        add(document.getElementById('env-tool-group'));
        add(document.getElementById('env-clear-food'));
        add(document.getElementById('env-clear-threat'));
        add(document.getElementById('env-clear-obs'));
        add(document.getElementById('bug-world-controls'));
        for (const id of ['food-target', 'threat-target', 'threat-life', 'hunger-rate', 'fatigue-gain', 'fatigue-decay']) {
            add(document.getElementById(id)?.closest('.slider-row'));
        }
        for (const id of ['stat-food', 'stat-hp', 'stat-hunger', 'stat-fatigue']) {
            add(document.getElementById(id)?.closest('.stat'));
        }
        return elements;
    }

    function gymOnlyElements() {
        const elements = Array.from(document.querySelectorAll('.gym-only'));
        const gymControls = document.getElementById('gym-world-controls');
        if (gymControls && !elements.includes(gymControls)) elements.push(gymControls);
        return elements;
    }

    // ---------------------------------------------------------- env panel
    document.getElementById('env-clear-food').addEventListener('click', () => socket.emit('clear_objects', { kind: 'food' }));
    document.getElementById('env-clear-threat').addEventListener('click', () => socket.emit('clear_objects', { kind: 'threat' }));
    document.getElementById('env-clear-obs').addEventListener('click', () => socket.emit('clear_objects', { kind: 'obstacle' }));

    function bindSlider(id, eventName, key, valId, decimals = 2, asInt = false) {
        const slider = document.getElementById(id);
        const val = document.getElementById(valId);
        let pending = null;
        const parse = (v) => asInt ? parseInt(v, 10) : parseFloat(v);
        const fmt = (v) => asInt ? String(parseInt(v, 10)) : parseFloat(v).toFixed(decimals);
        const sendNow = () => {
            const msg = {}; msg[key] = parse(slider.value);
            socket.emit(eventName, msg);
            pending = null;
        };
        slider.addEventListener('input', () => {
            val.textContent = fmt(slider.value);
            if (pending === null) pending = setTimeout(sendNow, 100);
        });
        slider.addEventListener('change', sendNow);
        val.textContent = fmt(slider.value);
        sendNow();
    }
    bindSlider('food-target',   'world_params', 'food_target',         'food-target-val',   0, true);
    bindSlider('threat-target', 'world_params', 'threat_target',       'threat-target-val', 0, true);
    bindSlider('threat-life',   'world_params', 'threat_lifetime',     'threat-life-val',   0, true);
    bindSlider('hunger-rate',   'world_params', 'hunger_rate',         'hunger-rate-val',   3);
    bindSlider('fatigue-gain',  'world_params', 'fatigue_action_gain', 'fatigue-gain-val',  3);
    bindSlider('fatigue-decay', 'world_params', 'fatigue_decay',       'fatigue-decay-val', 3);
    bindSlider('gym-env-hz',    'set_gym_env_hz', 'hz',                'gym-env-hz-val',    0, true);

    function updateGymHzDisplay(hz) {
        const slider = document.getElementById('gym-env-hz');
        const val = document.getElementById('gym-env-hz-val');
        if (!slider || !val || document.activeElement === slider) return;
        slider.value = String(hz);
        val.textContent = String(hz);
    }

    bindPanelResizer('rings.server.panelSplit');

    // Sim rate: 1..100 Hz, default 100. Independent socket event.
    (function bindSimHzSlider() {
        const slider = document.getElementById('sim-hz');
        const val = document.getElementById('sim-hz-val');
        let pending = null;
        const send = () => {
            socket.emit('set_sim_hz', { hz: parseInt(slider.value, 10) });
            pending = null;
        };
        slider.addEventListener('input', () => {
            val.textContent = slider.value;
            if (pending === null) pending = setTimeout(send, 80);
        });
        slider.addEventListener('change', send);
        val.textContent = slider.value;
        // Don't emit on init — server starts at 100 Hz already.
    })();

    // ---------------------------------------------------------- manual motor
    function motorLabel(motorId) {
        const key = motorId.replace(/^motor_/, '');
        const labels = {
            forward: 'Forward (W)',
            backward: 'Back (S)',
            left: 'Left (A)',
            right: 'Right (D)',
            coast: 'Coast (S)',
        };
        return labels[key] || key.replaceAll('_', ' ');
    }

    function renderManualMotors() {
        const row = document.getElementById('manual-motors');
        if (!row) return;
        const wanted = currentMotors.join('|');
        if (row.dataset.motors === wanted) return;
        row.dataset.motors = wanted;
        row.innerHTML = '';
        for (const motorId of currentMotors) {
            const key = motorId.replace(/^motor_/, '');
            const btn = document.createElement('button');
            btn.className = 'motor';
            btn.dataset.motor = key;
            btn.textContent = motorLabel(motorId);
            bindMotorButton(btn, key);
            row.appendChild(btn);
        }
    }

    function setMotor(name, on) {
        const msg = {}; msg[name] = on;
        socket.emit('manual_motor', msg);
        document.querySelectorAll(`button.motor[data-motor="${name}"]`).forEach(b => {
            b.classList.toggle('held', on);
        });
    }

    function bindMotorButton(btn, name) {
        btn.addEventListener('mousedown', () => setMotor(name, true));
        btn.addEventListener('mouseup',   () => setMotor(name, false));
        btn.addEventListener('mouseleave',() => setMotor(name, false));
        btn.addEventListener('touchstart', (e) => { e.preventDefault(); setMotor(name, true); });
        btn.addEventListener('touchend',   (e) => { e.preventDefault(); setMotor(name, false); });
    }
    document.querySelectorAll('button.motor').forEach((btn) => bindMotorButton(btn, btn.dataset.motor));

    const KEY_MAP = {
        'w': ['forward'],
        's': ['backward', 'coast'],
        'a': ['left'],
        'd': ['right'],
    };
    const pressed = new Set();
    function keyMotor(k) {
        const candidates = KEY_MAP[k] || [];
        const available = new Set(currentMotors.map(m => m.replace(/^motor_/, '')));
        return candidates.find(c => available.has(c));
    }
    window.addEventListener('keydown', (e) => {
        if (e.target.matches('input, textarea, select')) return;
        const k = e.key.toLowerCase();
        const motor = keyMotor(k);
        if (motor && !pressed.has(k)) {
            pressed.add(k);
            setMotor(motor, true);
        }
    });
    window.addEventListener('keyup', (e) => {
        const k = e.key.toLowerCase();
        const motor = keyMotor(k);
        if (motor) {
            pressed.delete(k);
            setMotor(motor, false);
        }
    });

    // ---------------------------------------------------------- save/load
    const saveDlg = document.getElementById('save-dialog');
    const saveName = document.getElementById('save-name');
    document.getElementById('net-save').addEventListener('click', () => {
        saveDlg.showModal();
    });
    document.getElementById('save-confirm').addEventListener('click', (e) => {
        e.preventDefault();
        const name = saveName.value.trim() || 'network';
        socket.emit('save_network', { name });
        saveDlg.close();
    });

    const loadDlg = document.getElementById('load-dialog');
    const loadList = document.getElementById('load-list');
    document.getElementById('net-load').addEventListener('click', async () => {
        loadList.innerHTML = '<li>загрузка…</li>';
        loadDlg.showModal();
        try {
            const res = await fetch('/api/saved');
            const j = await res.json();
            loadList.innerHTML = '';
            if (!j.files.length) {
                loadList.innerHTML = '<li>пусто</li>';
                return;
            }
            const groups = j.groups || { BUG: j.files || [] };
            for (const [task, files] of Object.entries(groups)) {
                if (!files.length) continue;
                const header = document.createElement('li');
                header.className = 'load-section';
                header.textContent = task;
                loadList.appendChild(header);
                for (const f of files) {
                    const li = document.createElement('li');
                    li.textContent = f;
                    li.addEventListener('click', () => {
                        showEnvLoading(task, 'Загрузка сети');
                        socket.emit('load_network', { name: f });
                        loadDlg.close();
                    });
                    loadList.appendChild(li);
                }
            }
        } catch (err) {
            loadList.innerHTML = `<li>ошибка: ${err}</li>`;
        }
    });

    // Export current network to local file
    document.getElementById('net-export').addEventListener('click', () => {
        const top = window.editorView.currentTopology();
        const blob = new Blob([JSON.stringify(top, null, 2)], { type: 'application/json' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'network.json';
        a.click();
    });

    // Import from local file
    const importInput = document.getElementById('net-import-file');
    document.getElementById('net-import').addEventListener('click', () => importInput.click());
    importInput.addEventListener('change', async () => {
        const f = importInput.files[0];
        if (!f) return;
        const text = await f.text();
        try {
            const data = JSON.parse(text);
            showEnvLoading(data.task || currentTask, 'Загрузка сети');
            socket.emit('load_network', { data });
        } catch (e) {
            alert('Невалидный JSON: ' + e.message);
        }
        importInput.value = '';
    });

    function flash(text) {
        const el = document.createElement('div');
        el.textContent = text;
        Object.assign(el.style, {
            position: 'fixed', top: '70px', right: '20px',
            background: '#3a5cff', color: '#fff',
            padding: '8px 14px', borderRadius: '4px', zIndex: 9999,
            boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
        });
        document.body.appendChild(el);
        setTimeout(() => el.remove(), 1800);
    }

    function bindPanelResizer(storageKey) {
        const layout = document.querySelector('.layout');
        const resizer = document.getElementById('main-panel-resizer');
        if (!layout || !resizer) return;

        const saved = parseFloat(localStorage.getItem(storageKey));
        if (Number.isFinite(saved)) setSplit(saved);

        function setSplit(percent) {
            const clamped = Math.min(72, Math.max(28, percent));
            layout.style.setProperty('--env-panel-width', `${clamped}%`);
            window.dispatchEvent(new Event('resize'));
            return clamped;
        }

        function setFromClientX(clientX) {
            const rect = layout.getBoundingClientRect();
            const raw = ((clientX - rect.left) / rect.width) * 100;
            const split = setSplit(raw);
            localStorage.setItem(storageKey, String(split));
        }

        resizer.addEventListener('pointerdown', (e) => {
            e.preventDefault();
            resizer.setPointerCapture(e.pointerId);
            document.body.classList.add('resizing-panels');
        });
        resizer.addEventListener('pointermove', (e) => {
            if (!resizer.hasPointerCapture(e.pointerId)) return;
            setFromClientX(e.clientX);
        });
        resizer.addEventListener('pointerup', (e) => {
            if (resizer.hasPointerCapture(e.pointerId)) resizer.releasePointerCapture(e.pointerId);
            document.body.classList.remove('resizing-panels');
        });
        resizer.addEventListener('pointercancel', (e) => {
            if (resizer.hasPointerCapture(e.pointerId)) resizer.releasePointerCapture(e.pointerId);
            document.body.classList.remove('resizing-panels');
        });
        resizer.addEventListener('keydown', (e) => {
            if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
            e.preventDefault();
            const current = parseFloat(getComputedStyle(layout).getPropertyValue('--env-panel-width')) || 48;
            const split = setSplit(current + (e.key === 'ArrowLeft' ? -2 : 2));
            localStorage.setItem(storageKey, String(split));
        });
    }
})();
