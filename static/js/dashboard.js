class TradingDashboard {
    constructor() {
        this.lastUpdateTime = null;
        this.isUpdating = false;
        this._strategyLevel = 3;
        this._strategyTfs = ['1m', '3m', '5m'];
        this._lastDirections = null;
        this._lastSignal = null;
        this._payouts = { '600': { up: null, down: null }, '1800': { up: null, down: null }, '3600': { up: null, down: null } };
        this._activeDuration = 600;
        this._payoutsLoaded = false;
        this._priceHistory = [];
        this._positionCharts = {};
        this._chartZoomLevel = {};
        this._chartWindow = {};    // minutes: 1/3/5/15, null = локальные тики
        this._lastTFFetch  = {};   // timestamp последнего fetch для каждого idx
        this._settingsLoaded = false;  // кнопки ставки/времени загружаются только раз

        this.bindEvents();
        this.startDataUpdates();
        this.updateDashboard();
    }

    bindEvents() {
        document.getElementById('start-bot').addEventListener('click', () => this.startBot());
        document.getElementById('stop-bot').addEventListener('click', () => this.stopBot());
        document.getElementById('delete-trade').addEventListener('click', () => this.deleteLastTrade());
        document.getElementById('reset-balance').addEventListener('click', () => this.resetBalance());
        document.getElementById('counter-trade').addEventListener('click', () => this.toggleCounterTrade());
        const clearHistoryBtn = document.getElementById('clear-history');
        if (clearHistoryBtn) clearHistoryBtn.addEventListener('click', () => this.clearHistory());
    }

    /* ─── BOT CONTROLS ─── */
    async startBot() {
        const r = await this._post('/api/start_bot');
        if (r.ok) this.showNotification('success', r.data.message || 'Бот запущен');
        else this.showNotification('error', r.data.error || 'Ошибка запуска');
    }

    async stopBot() {
        const r = await this._post('/api/stop_bot');
        if (r.ok) this.showNotification('success', r.data.message || 'Бот остановлен');
        else this.showNotification('error', r.data.error || 'Ошибка остановки');
    }

    async deleteLastTrade() {
        const r = await this._post('/api/delete_last_trade');
        if (r.ok) { this.showNotification('success', 'Сделка удалена'); this.updateDashboard(); }
        else this.showNotification('error', r.data.error || 'Ошибка');
    }

    async resetBalance() {
        const r = await this._post('/api/reset_balance');
        if (r.ok) { this.showNotification('success', 'Баланс сброшен'); this.updateDashboard(); }
        else this.showNotification('error', r.data.error || 'Ошибка');
    }

    async clearHistory() {
        await this._post('/api/clear_history');
        this.updateTrades([]);
        this.showNotification('success', 'История очищена');
    }

    async toggleCounterTrade() {
        const r = await this._post('/api/toggle_counter_trade');
        if (r.ok) {
            const active = r.data.counter_trade;
            this.syncCounterTradeButton(active);
            this.showNotification(active ? 'warning' : 'success',
                active ? 'Контр трейд включён' : 'Контр трейд выключен');
        } else {
            this.showNotification('error', 'Ошибка переключения контр трейда');
        }
    }

    syncCounterTradeButton(active) {
        const btn = document.getElementById('counter-trade');
        if (!btn) return;
        if (active) {
            btn.classList.remove('ctrl-btn--ghost');
            btn.classList.add('ctrl-btn--amber');
        } else {
            btn.classList.remove('ctrl-btn--amber');
            btn.classList.add('ctrl-btn--ghost');
        }
    }

    async closePosition(idx = 0) {
        const r = await this._post('/api/close_position', { position_idx: idx });
        if (r.ok) {
            if (r.data.trade) this.showResultModal(r.data.trade);
            setTimeout(() => this.updateDashboard(), 1000);
        } else {
            this.showNotification('error', r.data.error || 'Ошибка закрытия');
        }
    }

    /* ─── PAYOUT INPUT ─── */
    async savePayout(duration, direction, value) {
        const numVal = value === '' ? null : parseFloat(value);
        const key = String(duration);

        if (!this._payouts[key]) this._payouts[key] = { up: null, down: null };
        this._payouts[key][direction] = numVal;

        try {
            await fetch('/api/set_payout', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ duration: key, direction, value: numVal })
            });
            this._updatePayoutTimestamp();
            this._applyPayoutStyles();
            this._updateHeroPayoutBlock();
        } catch (e) {
            console.error('savePayout error:', e);
        }
    }

    _updatePayoutTimestamp() {
        const el = document.getElementById('payout-updated');
        if (!el) return;
        const now = new Date();
        el.textContent = `· обновлено ${now.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}`;
    }

    _applyPayoutStyles() {
        const MIN = 80;
        ['600', '1800', '3600'].forEach(dur => {
            ['up', 'down'].forEach(dir => {
                const inp = document.getElementById(`pout-${dur}-${dir}`);
                if (!inp) return;
                const val = this._payouts[dur]?.[dir];
                inp.classList.remove('payout-input--ok', 'payout-input--warn', 'payout-input--low');
                if (val === null || val === undefined || isNaN(val)) {
                    inp.classList.add('payout-input--warn');
                } else if (val >= MIN) {
                    inp.classList.add('payout-input--ok');
                } else {
                    inp.classList.add('payout-input--low');
                }
            });
            this._highlightActivePayoutRow();
        });
    }

    _highlightActivePayoutRow() {
        ['600', '1800', '3600'].forEach(dur => {
            const row = document.getElementById(`prow-${dur}`);
            if (!row) return;
            row.classList.toggle('payout-grid__row--active', parseInt(dur) === this._activeDuration);
        });
    }

    _updateHeroPayoutBlock() {
        const heroPayoutEl = document.getElementById('hero-payout');
        const heroPayoutVal = document.getElementById('hero-payout-val');
        if (!heroPayoutEl || !heroPayoutVal) return;

        const durKey = String(this._activeDuration);
        const p = this._payouts[durKey];
        const sig = this._lastSignal;

        if (!sig || sig === 'none') {
            heroPayoutEl.classList.add('d-none');
            return;
        }

        const dir = sig === 'long' ? 'up' : 'down';
        const val = p?.[dir];

        if (val !== null && val !== undefined && !isNaN(val)) {
            heroPayoutEl.classList.remove('d-none');
            heroPayoutVal.textContent = `${val}%`;
            heroPayoutVal.className = 'hero-payout__val ' + (val >= 80 ? 'text-success' : 'text-danger');
        } else {
            heroPayoutEl.classList.remove('d-none');
            heroPayoutVal.textContent = '—%';
            heroPayoutVal.className = 'hero-payout__val text-muted';
        }
    }

    _loadPayoutsIntoInputs(payouts) {
        if (!payouts) return;
        this._payouts = payouts;
        ['600', '1800', '3600'].forEach(dur => {
            ['up', 'down'].forEach(dir => {
                const inp = document.getElementById(`pout-${dur}-${dir}`);
                if (!inp) return;
                const val = payouts[dur]?.[dir];
                if (val !== null && val !== undefined) {
                    inp.value = val;
                } else {
                    inp.value = '';
                }
            });
        });
        this._applyPayoutStyles();
        this._updateHeroPayoutBlock();
    }

    /* ─── MAIN UPDATE ─── */
    async updateDashboard() {
        if (this.isUpdating) return;
        this.isUpdating = true;

        try {
            const response = await fetch('/api/status');
            if (!response.ok) return;
            const data = await response.json();

            // Bot status
            const statusBadge = document.getElementById('bot-status');
            if (statusBadge) {
                statusBadge.textContent = data.bot_running ? '● RUNNING' : '● STOPPED';
                statusBadge.className = data.bot_running ? 'status-pill status-pill--running' : 'status-pill status-pill--stopped';
            }

            // Stats
            document.getElementById('balance').textContent = `$${parseFloat(data.balance).toFixed(2)}`;
            document.getElementById('available').textContent = `$${parseFloat(data.available).toFixed(2)}`;

            if (data.current_price) {
                const price = parseFloat(data.current_price).toFixed(2);
                document.getElementById('current-price').textContent = `$${price}`;
                const heroPriceEl = document.getElementById('hero-price');
                if (heroPriceEl) heroPriceEl.textContent = `$${price}`;
                this._recordPrice(parseFloat(data.current_price));
            }

            // Payouts — load once on first update, then only reflect server changes
            if (data.payouts) {
                if (!this._payoutsLoaded) {
                    this._loadPayoutsIntoInputs(data.payouts);
                    this._payoutsLoaded = true;
                } else {
                    // Sync only non-focused inputs (don't override while user is typing)
                    this._syncPayoutsIfNotFocused(data.payouts);
                }
            }

            // Sync buttons — только при первой загрузке, не перебивать выбор пользователя
            if (!this._settingsLoaded) {
                if (data.bet !== undefined) this.syncBetButtons(data.bet);
                if (data.trade_duration !== undefined) {
                    this._activeDuration = parseInt(data.trade_duration);
                    this.syncDurButtons(data.trade_duration);
                    this._highlightActivePayoutRow();
                }
                if (data.bet !== undefined || data.trade_duration !== undefined) {
                    this._settingsLoaded = true;
                }
            }
            if (data.strategy_tfs) this.syncTfButtons(data.strategy_tfs);
            else if (data.strategy_level !== undefined) this.syncLevelButtons(data.strategy_level);
            if (data.counter_trade !== undefined) this.syncCounterTradeButton(data.counter_trade);

            // SAR directions
            if (data.sar_directions) this.updateSARDirections(data.sar_directions);

            // Positions
            this.updatePositionsList(data.positions || [], data.current_price);

            // Trades
            if (data.trades) this.updateTrades(data.trades);

            this.lastUpdateTime = new Date();
        } catch (error) {
            console.error('Dashboard update error:', error);
        } finally {
            this.isUpdating = false;
        }
    }

    _syncPayoutsIfNotFocused(payouts) {
        ['600', '1800', '3600'].forEach(dur => {
            ['up', 'down'].forEach(dir => {
                const inp = document.getElementById(`pout-${dur}-${dir}`);
                if (!inp || document.activeElement === inp) return;
                const val = payouts[dur]?.[dir];
                this._payouts[dur] = this._payouts[dur] || {};
                this._payouts[dur][dir] = val;
                inp.value = (val !== null && val !== undefined) ? val : '';
            });
        });
        this._applyPayoutStyles();
        this._updateHeroPayoutBlock();
    }

    /* ─── SETTINGS ─── */
    async setBet(amount) {
        await fetch('/api/set_settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ bet: amount })
        });
        this.syncBetButtons(amount);
    }

    async setDuration(seconds) {
        await fetch('/api/set_settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ trade_duration: seconds })
        });
        this._activeDuration = parseInt(seconds);
        this.syncDurButtons(seconds);
        this._highlightActivePayoutRow();
        this._updateHeroPayoutBlock();
    }

    syncBetButtons(activeBet) {
        document.querySelectorAll('.bet-btn').forEach(btn => {
            btn.classList.toggle('active-setting', parseFloat(btn.dataset.bet) === parseFloat(activeBet));
        });
    }

    syncDurButtons(activeDur) {
        document.querySelectorAll('.dur-btn').forEach(btn => {
            btn.classList.toggle('active-setting', parseInt(btn.dataset.dur) === parseInt(activeDur));
        });
    }

    syncTfButtons(activeTfs) {
        this._strategyTfs = Array.isArray(activeTfs) ? activeTfs : ['1m', '3m', '5m'];
        const TF_MAP = { '1m': 'L1', '3m': 'L2', '5m': 'L3', '15m': 'L4', '30m': 'L5' };
        document.querySelectorAll('.lvl-btn--inline').forEach(btn => {
            btn.classList.toggle('active-setting', this._strategyTfs.includes(btn.dataset.tf));
        });
        const lbl = document.getElementById('strategy-level-label');
        if (lbl) {
            if (this._strategyTfs.length === 0) {
                lbl.textContent = 'нет ТФ';
            } else {
                lbl.textContent = this._strategyTfs.map(t => TF_MAP[t] || t).join('+') + ' · ' + this._strategyTfs.join('+');
            }
        }
    }

    syncLevelButtons(activeLevel) {
        const TF_BY_LEVEL = {
            1: ['1m'], 2: ['1m', '3m'], 3: ['1m', '3m', '5m'],
            4: ['1m', '3m', '5m', '15m'], 5: ['1m', '3m', '5m', '15m', '30m']
        };
        this.syncTfButtons(TF_BY_LEVEL[parseInt(activeLevel)] || TF_BY_LEVEL[3]);
    }

    async toggleStrategyTf(tf) {
        const idx = this._strategyTfs.indexOf(tf);
        let newTfs;
        if (idx === -1) {
            newTfs = [...this._strategyTfs, tf];
        } else {
            newTfs = this._strategyTfs.filter(t => t !== tf);
        }
        if (newTfs.length === 0) return; // минимум 1 ТФ
        const ORDER = ['1m', '3m', '5m', '15m', '30m'];
        newTfs = newTfs.sort((a, b) => ORDER.indexOf(a) - ORDER.indexOf(b));
        const res = await fetch('/api/set_strategy_tfs', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tfs: newTfs })
        });
        const data = await res.json();
        this.syncTfButtons(data.strategy_tfs || newTfs);
        if (this._lastDirections) this.updateSARDirections(this._lastDirections);
    }

    async setStrategyLevel(level) {
        const res = await fetch('/api/set_strategy_level', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ level })
        });
        const data = await res.json();
        this.syncTfButtons(data.strategy_tfs || null);
        if (this._lastDirections) this.updateSARDirections(this._lastDirections);
    }

    /* ─── SAR + HERO SIGNAL ─── */
    updateSARDirections(directions) {
        if (!directions) return;
        this._lastDirections = directions;

        const requiredTfs = this._strategyTfs && this._strategyTfs.length > 0
            ? this._strategyTfs
            : ['1m', '3m', '5m'];
        const allTimeframes = ['1m', '3m', '5m', '15m', '30m'];

        let allMatch = true;
        let matchDirection = null;

        allTimeframes.forEach(tf => {
            const element = document.getElementById(`sar-${tf}`);
            const container = document.getElementById(`sar-${tf}-container`);
            const direction = directions[tf];
            const isRequired = requiredTfs.includes(tf);

            if (element && container) {
                element.className = 'badge sar-badge';
                container.style.opacity = isRequired ? '1' : '0.3';

                if (direction === 'long') {
                    element.textContent = 'LONG';
                    element.classList.add('bg-success');
                    container.classList.remove('text-danger', 'text-muted');
                    container.classList.add('text-success');
                    if (isRequired) {
                        if (matchDirection === null) matchDirection = 'long';
                        else if (matchDirection !== 'long') allMatch = false;
                    }
                } else if (direction === 'short') {
                    element.textContent = 'SHORT';
                    element.classList.add('bg-danger');
                    container.classList.remove('text-success', 'text-muted');
                    container.classList.add('text-danger');
                    if (isRequired) {
                        if (matchDirection === null) matchDirection = 'short';
                        else if (matchDirection !== 'short') allMatch = false;
                    }
                } else {
                    element.textContent = 'N/A';
                    element.classList.add('bg-secondary');
                    container.classList.remove('text-success', 'text-danger');
                    container.classList.add('text-muted');
                    if (isRequired) allMatch = false;
                }
            }
        });

        // Determine signal
        const signalDir = (allMatch && matchDirection && requiredTfs.length > 0) ? matchDirection : null;

        // Detect new signal
        const prevSignal = this._lastSignal;
        this._lastSignal = signalDir;

        if (signalDir && signalDir !== prevSignal) {
            this._onNewSignal(signalDir);
        } else if (!signalDir && prevSignal) {
            this._onSignalLost();
        }

        this._updateHeroSignal(signalDir);
        this._updateHeroPayoutBlock();
    }

    _updateHeroSignal(signalDir, level) {
        const hero = document.getElementById('hero-signal');
        if (!hero) return;

        hero.className = 'hero-signal';
        if (signalDir === 'long') {
            hero.classList.add('hero-signal--long');
            hero.innerHTML = `<span class="hero-signal__icon">▲</span><span class="hero-signal__text">UP / LONG</span><span class="hero-signal__level">L${level}</span>`;
        } else if (signalDir === 'short') {
            hero.classList.add('hero-signal--short');
            hero.innerHTML = `<span class="hero-signal__icon">▼</span><span class="hero-signal__text">DOWN / SHORT</span><span class="hero-signal__level">L${level}</span>`;
        } else {
            hero.classList.add('hero-signal--idle');
            hero.innerHTML = `<span class="hero-signal__icon">—</span><span class="hero-signal__text">НЕТ СИГНАЛА</span>`;
        }
    }

    _onNewSignal(dir) {
        // Flash the hero block
        const hero = document.getElementById('signal-hero');
        if (hero) {
            hero.classList.add('signal-hero--flash');
            setTimeout(() => hero.classList.remove('signal-hero--flash'), 1500);
        }

        // Play beep sound
        this._playBeep(dir === 'long' ? 880 : 440);

    }

    _onSignalLost() {
        // no-op, hero updates to idle automatically
    }

    _playBeep(freq = 660) {
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.frequency.value = freq;
            osc.type = 'sine';
            gain.gain.setValueAtTime(0.4, ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.8);
            osc.start(ctx.currentTime);
            osc.stop(ctx.currentTime + 0.8);
        } catch (e) {
            // Audio not available
        }
    }

    /* ─── PRICE HISTORY ─── */
    _recordPrice(price) {
        const now = Date.now();
        this._priceHistory.push({ time: now, price });
        // Keep last 60 minutes (1200 points at 3s intervals)
        const cutoff = now - 60 * 60 * 1000;
        this._priceHistory = this._priceHistory.filter(p => p.time >= cutoff);
    }

    _getPriceHistorySince(isoTime) {
        const entryMs = new Date(isoTime + (isoTime.endsWith('Z') ? '' : 'Z')).getTime();
        return this._priceHistory.filter(p => p.time >= entryMs);
    }

    _getChartHistory(idx, entryIso) {
        const all = this._getPriceHistorySince(entryIso);
        const winMin = this._chartWindow[idx];
        if (!winMin) return all;
        const cutoff = Date.now() - winMin * 60 * 1000;
        const entryMs = new Date(entryIso + (entryIso.endsWith('Z') ? '' : 'Z')).getTime();
        const from = Math.max(cutoff, entryMs);
        return this._priceHistory.filter(p => p.time >= from);
    }

    _highlightWinBtn(idx, activeMin) {
        const wrap = document.querySelector(`.pos-chart-side[data-idx="${idx}"]`);
        if (!wrap) return;
        wrap.querySelectorAll('.pos-win-btn').forEach(b => {
            b.classList.toggle('active', parseInt(b.dataset.min) === activeMin);
        });
    }

    resetChartWindow(idx) {
        this._chartWindow[idx] = null;
        this._chartZoomLevel[idx] = 1;
        this._highlightWinBtn(idx, 0);   // 0 = Line
        // Вернуть локальные тики
        const chart = this._positionCharts[idx];
        if (!chart) return;
        const entryIso  = chart._entryIso;
        const entry     = chart._entryPrice;
        if (!entry || !entryIso) return;
        const history = this._getPriceHistorySince(entryIso);
        const labels  = history.map(p => {
            const d = new Date(p.time);
            return `${d.getHours().toString().padStart(2,'0')}:${d.getMinutes().toString().padStart(2,'0')}:${d.getSeconds().toString().padStart(2,'0')}`;
        });
        const prices = history.length > 0 ? history.map(p => p.price) : [entry];
        const { min: yMin, max: yMax } = this._tightYRange(prices, entry, 1);
        chart.data.labels = labels.length > 0 ? labels : ['entry'];
        chart.data.datasets[0].data = prices;
        chart.data.datasets[1].data = new Array(chart.data.labels.length).fill(entry);
        chart.options.scales.y.min = yMin;
        chart.options.scales.y.max = yMax;
        chart.update('none');
    }

    async setChartWindow(idx, minutes) {
        this._chartWindow[idx] = minutes;
        this._chartZoomLevel[idx] = 1;
        this._lastTFFetch[idx]  = 0;
        this._highlightWinBtn(idx, minutes);
        await this._fetchAndUpdateTFChart(idx, minutes);
    }

    async _fetchAndUpdateTFChart(idx, minutes) {
        const chart = this._positionCharts[idx];
        if (!chart) return;
        const entry = chart._entryPrice;
        try {
            const resp = await fetch(`/api/pos_chart_data?tf=${minutes}m&limit=80`);
            if (!resp.ok) return;
            const data = await resp.json();
            const prices = data.prices || [];
            const labels = data.labels || [];
            if (prices.length === 0) return;
            const zoom = this._chartZoomLevel[idx] || 1;
            const { min: yMin, max: yMax } = this._tightYRange(prices, entry, zoom);
            chart.data.labels = labels;
            chart.data.datasets[0].data = prices;
            chart.data.datasets[1].data = new Array(labels.length).fill(entry);
            chart.options.scales.y.min = yMin;
            chart.options.scales.y.max = yMax;
            chart.update('none');
            this._lastTFFetch[idx] = Date.now();
        } catch (e) {
            console.error('TF chart fetch error:', e);
        }
    }

    _destroyAllPositionCharts() {
        Object.values(this._positionCharts).forEach(chart => {
            try { chart.destroy(); } catch (e) {}
        });
        this._positionCharts = {};
        this._chartZoomLevel = {};
        this._chartWindow = {};
    }

    _tightYRange(prices, entryPrice, zoom = 1) {
        const all = [...prices, entryPrice];
        const lo = Math.min(...all);
        const hi = Math.max(...all);
        const spread = hi - lo;
        const minSpread = entryPrice * 0.0003 * zoom;
        const pad = Math.max(spread * 0.04 * zoom, minSpread);
        return { min: lo - pad, max: hi + pad };
    }

    zoomChart(idx, direction) {
        const step = 1.6;
        const current = this._chartZoomLevel[idx] || 1;
        this._chartZoomLevel[idx] = direction === 'in'
            ? current / step
            : current * step;
        // Обновить масштаб немедленно
        const chart = this._positionCharts[idx];
        if (!chart) return;
        // Получим данные из датасета
        const prices = chart.data.datasets[0].data;
        const entryPrice = chart.data.datasets[1].data[0];
        const { min: yMin, max: yMax } = this._tightYRange(prices, entryPrice, this._chartZoomLevel[idx]);
        chart.options.scales.y.min = yMin;
        chart.options.scales.y.max = yMax;
        chart.update('none');
    }

    _buildPositionChart(idx, entryPrice, entryIso, side) {
        const canvas = document.getElementById(`pos-chart-${idx}`);
        if (!canvas) return;

        const isLong = side === 'long';
        const lineColor = isLong ? '#10b981' : '#ef4444';
        const fillColor = isLong ? 'rgba(16,185,129,0.10)' : 'rgba(239,68,68,0.10)';

        const history = this._getChartHistory(idx, entryIso);
        const labels = history.map(p => {
            const d = new Date(p.time);
            return `${d.getHours().toString().padStart(2,'0')}:${d.getMinutes().toString().padStart(2,'0')}:${d.getSeconds().toString().padStart(2,'0')}`;
        });
        const prices = history.map(p => p.price);

        if (prices.length === 0) {
            prices.push(entryPrice);
            labels.push('entry');
        }

        const zoom = this._chartZoomLevel[idx] || 1;
        const { min: yMin, max: yMax } = this._tightYRange(prices, entryPrice, zoom);

        const chart = new Chart(canvas, {
            type: 'line',
            data: {
                labels,
                datasets: [
                    {
                        label: 'Цена',
                        data: prices,
                        borderColor: lineColor,
                        backgroundColor: fillColor,
                        borderWidth: 2,
                        pointRadius: 0,
                        pointHoverRadius: 3,
                        tension: 0.3,
                        fill: true,
                    },
                    {
                        label: 'Вход',
                        data: new Array(Math.max(prices.length, 1)).fill(entryPrice),
                        borderColor: 'rgba(255,255,255,0.35)',
                        borderWidth: 1,
                        borderDash: [4, 4],
                        pointRadius: 0,
                        fill: false,
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        enabled: true,
                        mode: 'index',
                        intersect: false,
                        callbacks: {
                            label: ctx => ctx.datasetIndex === 0 ? `$${ctx.parsed.y.toFixed(2)}` : null
                        }
                    }
                },
                scales: {
                    x: {
                        display: true,
                        ticks: {
                            maxTicksLimit: 6,
                            color: '#475569',
                            font: { size: 9 },
                            maxRotation: 0,
                        },
                        grid: { color: 'rgba(255,255,255,0.03)' }
                    },
                    y: {
                        display: true,
                        position: 'right',
                        min: yMin,
                        max: yMax,
                        ticks: {
                            maxTicksLimit: 6,
                            color: '#94a3b8',
                            font: { size: 9 },
                            callback: v => `$${v.toFixed(2)}`
                        },
                        grid: { color: 'rgba(255,255,255,0.06)' }
                    }
                }
            }
        });

        chart._entryPrice = entryPrice;
        chart._entryIso   = entryIso;
        this._positionCharts[idx] = chart;
    }

    _updatePositionChart(idx, entryPrice, entryIso, side) {
        const chart = this._positionCharts[idx];
        if (!chart) return;

        const winMin = this._chartWindow[idx];
        if (winMin) {
            // Режим таймфрейма: перезагружаем свечи каждые 15 сек
            const last = this._lastTFFetch[idx] || 0;
            if (Date.now() - last >= 15000) {
                this._fetchAndUpdateTFChart(idx, winMin);
            }
            return;
        }

        // Режим локальных тиков: данные с момента открытия позиции
        const history = this._getChartHistory(idx, entryIso);
        const labels = history.map(p => {
            const d = new Date(p.time);
            return `${d.getHours().toString().padStart(2,'0')}:${d.getMinutes().toString().padStart(2,'0')}:${d.getSeconds().toString().padStart(2,'0')}`;
        });
        const prices = history.length > 0 ? history.map(p => p.price) : [entryPrice];
        const entryLine = new Array(prices.length).fill(entryPrice);

        const zoom = this._chartZoomLevel[idx] || 1;
        const { min: yMin, max: yMax } = this._tightYRange(prices, entryPrice, zoom);
        chart.options.scales.y.min = yMin;
        chart.options.scales.y.max = yMax;

        chart.data.labels = labels.length > 0 ? labels : ['entry'];
        chart.data.datasets[0].data = prices;
        chart.data.datasets[1].data = entryLine;
        chart.update('none');
    }

    /* ─── POSITIONS ─── */
    updatePositionsList(positions, currentPrice) {
        const noPositions = document.getElementById('no-positions');
        const positionsList = document.getElementById('positions-list');
        if (!positionsList) return;

        if (!positions || positions.length === 0) {
            if (noPositions) noPositions.classList.remove('d-none');
            positionsList.innerHTML = '';
            clearInterval(this.timerInterval);
            this.timerInterval = null;
            this._positionsKey = null;
            this._destroyAllPositionCharts();
            return;
        }

        if (noPositions) noPositions.classList.add('d-none');
        const currentPriceNum = parseFloat(currentPrice) || 0;
        const positionsKey = positions.map(p => p.entry_time).join('|');
        const needsRebuild = positionsKey !== this._positionsKey;

        if (needsRebuild) {
            this._destroyAllPositionCharts();

            const allHtml = positions.map((pos, idx) => {
                const sideClass = pos.side === 'long' ? 'bg-success' : 'bg-danger';
                const colorClass = pos.side === 'long' ? 'text-success' : 'text-danger';
                const entryPrice = parseFloat(pos.entry_price);
                const bet = parseFloat(pos.bet || 5.0);
                const duration = pos.close_time_seconds || 600;
                const willWin = pos.side === 'long' ? currentPriceNum > entryPrice : currentPriceNum < entryPrice;
                const pnlColorClass = willWin ? 'text-success' : 'text-danger';
                const pnlStatus = willWin ? '✓ В ПРИБЫЛИ' : '✗ В УБЫТКЕ';
                const entryIso = pos.entry_time;
                const sideLabel = pos.side === 'long' ? '▲ UP' : '▼ DOWN';

                return `
                <div class="list-group-item bg-dark border-secondary p-3 mb-1">
                    <div class="d-flex align-items-start gap-3">

                        <!-- Левая часть: инфо + зум + таймер -->
                        <div class="flex-grow-1 min-w-0">
                            <div class="pos-info-row">
                                <span class="badge ${sideClass} pos-side-badge">${sideLabel}</span>
                                <span class="text-muted pos-num">#${idx + 1}</span>
                                <span class="pos-field"><span class="pos-label">Вход</span><span class="${colorClass} fw-bold">$${entryPrice.toFixed(2)}</span></span>
                                <span class="pos-field"><span class="pos-label">Цена</span><span class="pos-current-price fw-bold ${colorClass}" data-idx="${idx}">$${currentPriceNum.toFixed(2)}</span></span>
                                <span class="pos-field"><span class="pos-label">Статус</span><span class="pos-pnl-status fw-bold ${pnlColorClass}" data-idx="${idx}">${pnlStatus}</span></span>
                                <span class="pos-field"><span class="pos-label">Ставка</span><span class="text-light fw-bold">$${bet.toFixed(2)}</span></span>
                            </div>
                            <div class="pos-bottom-row">
                                <div class="pos-timer-block">
                                    <small class="text-muted">Осталось:</small>
                                    <span class="pos-timer badge text-info"
                                          data-entry="${entryIso}"
                                          data-duration="${duration}">--:--</span>
                                </div>
                                <button class="btn btn-warning btn-sm pos-close-btn" onclick="window.dashboard.closePosition(${idx})">
                                    <i class="fas fa-times"></i> Close
                                </button>
                            </div>
                        </div>

                        <!-- Правая часть: только график -->
                        <div class="pos-chart-side" data-idx="${idx}">
                            <div class="pos-win-btns">
                                <button class="pos-win-btn pos-win-btn--line active" data-min="0" onclick="window.dashboard.resetChartWindow(${idx})">Line</button>
                                <button class="pos-win-btn" data-min="1" onclick="window.dashboard.setChartWindow(${idx},1)">1m</button>
                                <button class="pos-win-btn" data-min="3" onclick="window.dashboard.setChartWindow(${idx},3)">3m</button>
                                <button class="pos-win-btn" data-min="5" onclick="window.dashboard.setChartWindow(${idx},5)">5m</button>
                                <button class="pos-win-btn" data-min="15" onclick="window.dashboard.setChartWindow(${idx},15)">15m</button>
                                <span class="pos-win-sep"></span>
                                <button class="pos-zoom-btn" onclick="window.dashboard.zoomChart(${idx},'in')" title="Увеличить масштаб">+</button>
                                <button class="pos-zoom-btn" onclick="window.dashboard.zoomChart(${idx},'out')" title="Уменьшить масштаб">−</button>
                            </div>
                            <div class="pos-chart-wrap">
                                <canvas id="pos-chart-${idx}" class="pos-mini-chart"></canvas>
                            </div>
                        </div>

                    </div>
                </div>`;
            }).join('');

            positionsList.innerHTML = allHtml;
            this._positionsKey = positionsKey;

            // Build charts after DOM is ready
            requestAnimationFrame(() => {
                positions.forEach((pos, idx) => {
                    this._buildPositionChart(idx, parseFloat(pos.entry_price), pos.entry_time, pos.side);
                });
            });

            clearInterval(this.timerInterval);
            this.timerInterval = setInterval(() => this._tickTimer(), 1000);
            this._tickTimer();
        } else {
            positions.forEach((pos, idx) => {
                const entryPrice = parseFloat(pos.entry_price);
                const willWin = pos.side === 'long' ? currentPriceNum > entryPrice : currentPriceNum < entryPrice;
                const pnlColorClass = willWin ? 'text-success' : 'text-danger';
                const pnlStatus = willWin ? '✓ В ПРИБЫЛИ' : '✗ В УБЫТКЕ';
                const colorClass = pos.side === 'long' ? 'text-success' : 'text-danger';

                const priceEl = positionsList.querySelector(`.pos-current-price[data-idx="${idx}"]`);
                if (priceEl) { priceEl.textContent = `$${currentPriceNum.toFixed(2)}`; priceEl.className = `pos-current-price fw-bold ${colorClass}`; }
                const statusEl = positionsList.querySelector(`.pos-pnl-status[data-idx="${idx}"]`);
                if (statusEl) { statusEl.textContent = pnlStatus; statusEl.className = `pos-pnl-status fw-bold ${pnlColorClass}`; }

                // Update chart with latest price data
                this._updatePositionChart(idx, entryPrice, pos.entry_time, pos.side);
            });
        }
    }

    _tickTimer() {
        const timers = document.querySelectorAll('.pos-timer');
        if (!timers || timers.length === 0) { clearInterval(this.timerInterval); this.timerInterval = null; return; }
        timers.forEach(timerEl => {
            const entryIso = timerEl.getAttribute('data-entry');
            const duration = parseInt(timerEl.getAttribute('data-duration') || '600');
            const entryTime = new Date(entryIso + (entryIso.endsWith('Z') ? '' : 'Z'));
            const remaining = Math.max(0, duration - (new Date() - entryTime) / 1000);
            const minutes = Math.floor(remaining / 60);
            const seconds = Math.floor(remaining % 60);
            timerEl.textContent = `${minutes}:${seconds.toString().padStart(2, '0')}`;
            timerEl.className = remaining > 180 ? 'pos-timer badge text-info fs-5' : remaining > 60 ? 'pos-timer badge text-warning fs-5' : 'pos-timer badge text-danger fs-5';
        });
    }

    /* ─── TRADES ─── */
    updateTrades(trades) {
        const container = document.getElementById('trades-container');
        if (!container) return;

        if (!trades || trades.length === 0) {
            container.innerHTML = `<div class="empty-state"><i class="fas fa-clock fa-2x mb-2 opacity-50"></i><p class="mb-0 opacity-50">Нет завершённых сделок</p></div>`;
            return;
        }

        const recentTrades = trades.slice(-50).reverse();
        container.innerHTML = recentTrades.map(trade => {
            const pnl = parseFloat(trade.pnl);
            const pnlClass = pnl >= 0 ? 'text-success' : 'text-danger';
            const sideColor = trade.side === 'long' ? 'bg-success' : 'bg-danger';
            const sideLabel = trade.side === 'long' ? '▲ UP' : '▼ DOWN';
            const exitTime = trade.exit_time || trade.time;
            const exitDate = exitTime ? new Date(exitTime).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) : 'N/A';
            const outcome = pnl >= 0 ? 'WIN' : 'LOSE';
            const outcomeClass = pnl >= 0 ? 'text-success' : 'text-danger';

            return `
                <div class="list-group-item">
                    <div class="d-flex justify-content-between align-items-center">
                        <div class="d-flex align-items-center gap-2">
                            <span class="badge ${sideColor}">${sideLabel}</span>
                            <span class="${outcomeClass} fw-bold">${outcome}</span>
                            <span class="${pnlClass} fw-bold">${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}</span>
                        </div>
                        <div class="text-end">
                            <div style="font-size:12px;color:var(--text-muted)">${exitDate}</div>
                        </div>
                    </div>
                    <div class="mt-1" style="font-size:11px;color:var(--text-dim)">
                        Вход $${trade.entry_price.toFixed(2)} → Выход $${trade.exit_price.toFixed(2)}
                    </div>
                </div>`;
        }).join('');
    }

    /* ─── RESULT MODAL ─── */
    showResultModal(tradeData) {
        if (tradeData.pnl === undefined) return;
        const isWin = tradeData.pnl > 0;
        document.getElementById('result-title').textContent = isWin ? 'WIN! 🎉' : 'LOSE 💔';
        document.getElementById('result-title').className = isWin ? 'text-success mb-4' : 'text-danger mb-4';
        document.getElementById('result-message').textContent = isWin ? 'Поздравляем!' : 'Неудача, попробуйте снова.';
        document.getElementById('result-pnl').textContent = `${isWin ? '+' : '-'}$${Math.abs(tradeData.pnl).toFixed(2)}`;
        document.getElementById('result-pnl').className = isWin ? 'text-success mb-4' : 'text-danger mb-4';
        new bootstrap.Modal(document.getElementById('resultModal')).show();
    }

    /* ─── NOTIFICATION ─── */
    showNotification(type, message, duration = 5000) {
        const n = document.createElement('div');
        const cls = type === 'error' ? 'danger' : type === 'signal' ? 'warning' : 'success';
        n.className = `alert alert-${cls} alert-dismissible fade show position-fixed`;
        n.style.cssText = 'top:20px;right:20px;z-index:9999;min-width:280px;max-width:360px;border-radius:10px;';
        n.innerHTML = `${message}<button type="button" class="btn-close" data-bs-dismiss="alert"></button>`;
        document.body.appendChild(n);
        setTimeout(() => n.remove(), duration);
    }

    /* ─── AI POLL ─── */
    async pollAI() {
        const btn = document.getElementById('ai-poll-btn');
        const badge = document.getElementById('ai-consensus-badge');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Опрашиваю AI...';
        }
        if (badge) {
            badge.className = 'badge ai-consensus-badge--loading';
            badge.textContent = '⏳ Ожидание...';
        }

        const nameMap = { ChatGPT: 'chatgpt', Gemini: 'gemini', Grok: 'grok', DeepSeek: 'deepseek', Groq: 'groq', OpenRouter: 'openrouter', Mistral: 'mistral' };
        Object.values(nameMap).forEach(id => {
            const el = document.getElementById(`ai-vote-${id}`);
            const card = document.getElementById(`ai-card-${id}`);
            if (el) { el.textContent = '⏳'; el.className = 'ai-server-badge ai-badge--loading'; }
            if (card) card.className = 'ai-server-card ai-card--loading';
        });

        try {
            const r = await fetch('/api/ai_poll', { method: 'POST', headers: { 'Content-Type': 'application/json' } });
            const data = await r.json();

            if (data.error) {
                this.showNotification('error', 'Ошибка AI опроса: ' + data.error);
                return;
            }

            (data.results || []).forEach(res => {
                const id = nameMap[res.name];
                if (!id) return;
                const el = document.getElementById(`ai-vote-${id}`);
                const card = document.getElementById(`ai-card-${id}`);
                if (el) {
                    if (res.direction === 'long') {
                        el.textContent = '▲ LONG';
                        el.className = 'ai-server-badge ai-badge--long';
                        el.title = '';
                    } else if (res.direction === 'short') {
                        el.textContent = '▼ SHORT';
                        el.className = 'ai-server-badge ai-badge--short';
                        el.title = '';
                    } else {
                        el.textContent = res.error || '?';
                        el.className = 'ai-server-badge ai-badge--error';
                        el.title = res.error || '';
                    }
                }
                if (card) {
                    card.className = 'ai-server-card ' + (
                        res.direction === 'long' ? 'ai-card--long' :
                        res.direction === 'short' ? 'ai-card--short' : 'ai-card--unknown'
                    );
                }
            });

            const longs = data.long_votes || 0;
            const shorts = data.short_votes || 0;
            const consensus = data.consensus || 'none';

            const longEl = document.getElementById('ai-long-count');
            const shortEl = document.getElementById('ai-short-count');
            const tally = document.getElementById('ai-tally');
            if (longEl) longEl.textContent = longs;
            if (shortEl) shortEl.textContent = shorts;
            if (tally) tally.style.display = 'flex';

            if (badge) {
                if (consensus === 'long') {
                    badge.className = 'badge ai-consensus-badge--long';
                    badge.textContent = `▲ LONG (${longs}/${longs + shorts})`;
                } else if (consensus === 'short') {
                    badge.className = 'badge ai-consensus-badge--short';
                    badge.textContent = `▼ SHORT (${shorts}/${longs + shorts})`;
                } else {
                    badge.className = 'badge ai-consensus-badge--tie';
                    badge.textContent = `≈ Ничья`;
                }
            }

            const actionBtns = document.getElementById('ai-action-btns');
            if (actionBtns) actionBtns.style.display = 'flex';

            const timeEl = document.getElementById('ai-poll-time');
            if (timeEl) {
                const t = new Date();
                timeEl.textContent = `Последний опрос: ${t.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}`;
                timeEl.style.display = 'block';
            }

            if (consensus !== 'none') {
                this._playBeep(consensus === 'long' ? 880 : 440);
            }
        } catch (e) {
            this.showNotification('error', 'Ошибка соединения при AI опросе');
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-satellite-dish"></i> Опросить AI';
            }
        }
    }

    async openAIPosition(side) {
        const r = await this._post('/api/ai_open_position', { side });
        if (r.ok) {
            this.showNotification('success', `Позиция ${side.toUpperCase()} открыта на 1 час`);
            setTimeout(() => this.updateDashboard(), 500);
        } else {
            this.showNotification('error', r.data.error || 'Ошибка открытия позиции');
        }
    }

    /* ─── AI COUNCIL ─── */
    openCouncil() {
        const m = document.getElementById('council-modal');
        if (m) m.style.display = 'block';
        const input = document.getElementById('council-question-input');
        if (input && !input.value) {
            input.value = 'Куда пойдёт цена ETH/USDT в следующие 10 минут — LONG или SHORT?';
        }
    }
    closeCouncil() {
        const m = document.getElementById('council-modal');
        if (m) m.style.display = 'none';
    }
    fillCouncilQuestion(q) {
        const input = document.getElementById('council-question-input');
        if (input && q) input.value = q;
    }
    async startCouncil() {
        const btn = document.getElementById('council-start-btn');
        const status = document.getElementById('council-status');
        const result = document.getElementById('council-result');
        const q = (document.getElementById('council-question-input') || {}).value || '';

        if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Идёт обсуждение...'; }
        if (status) status.textContent = 'Раунд 1 → раунд 2 (это занимает 5–15 секунд)';
        if (result) result.style.display = 'none';

        try {
            const r = await fetch('/api/ai_council', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ question: q })
            });
            const data = await r.json();
            if (data.error) {
                this.showNotification('error', 'Ошибка совета: ' + data.error);
                return;
            }
            this._renderCouncil(data);
        } catch (e) {
            this.showNotification('error', 'Ошибка соединения');
        } finally {
            if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-gavel"></i> Начать заседание'; }
            if (status) status.textContent = '';
        }
    }
    _renderCouncil(data) {
        const result = document.getElementById('council-result');
        const r1 = document.getElementById('council-round1');
        const r2 = document.getElementById('council-round2');
        const verdict = document.getElementById('council-verdict');

        const esc = (s) => String(s == null ? '' : s)
            .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
            .replace(/"/g,'&quot;').replace(/'/g,'&#39;');

        const renderOpinion = (op, showChange = false) => {
            const dir = (op.direction === 'long' || op.direction === 'short') ? op.direction : 'unknown';
            const arrow = dir === 'long' ? '▲' : dir === 'short' ? '▼' : '✗';
            const cls   = dir;
            const prev  = (op.previous === 'long' || op.previous === 'short') ? op.previous : '?';
            const changedTag = (showChange && op.changed)
                ? `<span class="op-changed">⚡ изменил мнение (${prev.toUpperCase()} → ${dir.toUpperCase()})</span>`
                : '';
            const reasonOrErr = op.error
                ? `<span class="op-error">${esc(op.error)}</span>`
                : `<span class="op-reason">${esc(op.reason || op.raw || '(без аргумента)')}</span>`;
            return `
                <div class="op-card op-${cls}">
                    <div class="op-head">
                        <span class="op-name">${esc(op.name)}</span>
                        <span class="op-vote">${arrow} ${dir.toUpperCase()}</span>
                    </div>
                    ${reasonOrErr}
                    ${changedTag}
                </div>
            `;
        };

        if (r1) r1.innerHTML = (data.round1 || []).map(o => renderOpinion(o, false)).join('');
        if (r2) r2.innerHTML = (data.round2 || []).map(o => renderOpinion(o, true)).join('');

        const c = data.consensus || 'none';
        const longs = data.long_votes || 0;
        const shorts = data.short_votes || 0;
        let vText, vCls;
        if (c === 'long')      { vText = `▲ КОНСЕНСУС: LONG (${longs} : ${shorts})`;  vCls = 'long'; }
        else if (c === 'short'){ vText = `▼ КОНСЕНСУС: SHORT (${shorts} : ${longs})`; vCls = 'short'; }
        else                   { vText = `≈ Без консенсуса (нужно ≥2 одинаковых голоса). LONG=${longs}, SHORT=${shorts}`; vCls = 'tie'; }
        if (verdict) {
            verdict.className = 'council-verdict council-verdict--' + vCls;
            verdict.innerHTML = `<div class="verdict-text">${vText}</div>` +
                ((c === 'long' || c === 'short')
                    ? `<button class="ai-action-btn ai-action-btn--${c}" onclick="window.dashboard.openAIPosition('${c}'); window.dashboard.closeCouncil();">
                         Открыть ${c === 'long' ? 'BUY' : 'SELL'} на $5
                       </button>`
                    : '');
        }
        if (result) result.style.display = 'block';
        if (c !== 'none') this._playBeep(c === 'long' ? 880 : 440);
    }

    /* ─── POLLING ─── */
    startDataUpdates() {
        setInterval(() => this.updateDashboard(), 3000);
    }

    /* ─── HELPERS ─── */
    async _post(url, body = {}) {
        try {
            const r = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
            return { ok: r.ok, data: await r.json() };
        } catch (e) {
            return { ok: false, data: { error: 'Ошибка соединения' } };
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    window.dashboard = new TradingDashboard();
});
