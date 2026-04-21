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

            // Sync buttons
            if (data.bet !== undefined) this.syncBetButtons(data.bet);
            if (data.trade_duration !== undefined) {
                this._activeDuration = parseInt(data.trade_duration);
                this.syncDurButtons(data.trade_duration);
                this._highlightActivePayoutRow();
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
            return;
        }

        if (noPositions) noPositions.classList.add('d-none');
        const currentPriceNum = parseFloat(currentPrice) || 0;
        const positionsKey = positions.map(p => p.entry_time).join('|');
        const needsRebuild = positionsKey !== this._positionsKey;

        if (needsRebuild) {
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
                    <div class="row align-items-center mb-2">
                        <div class="col-md-2">
                            <span class="badge ${sideClass} fs-6">${sideLabel}</span>
                            <div><small class="text-muted">#${idx + 1}</small></div>
                        </div>
                        <div class="col-md-2">
                            <small class="text-muted d-block">Вход</small>
                            <span class="${colorClass} fw-bold">$${entryPrice.toFixed(2)}</span>
                        </div>
                        <div class="col-md-2">
                            <small class="text-muted d-block">Цена</small>
                            <span class="pos-current-price fw-bold ${colorClass}" data-idx="${idx}">$${currentPriceNum.toFixed(2)}</span>
                        </div>
                        <div class="col-md-2">
                            <small class="text-muted d-block">Статус</small>
                            <span class="pos-pnl-status fw-bold ${pnlColorClass}" data-idx="${idx}">${pnlStatus}</span>
                        </div>
                        <div class="col-md-2">
                            <small class="text-muted d-block">Ставка</small>
                            <span class="text-light fw-bold">$${bet.toFixed(2)}</span>
                        </div>
                        <div class="col-md-2 text-end">
                            <button class="btn btn-warning btn-sm" onclick="window.dashboard.closePosition(${idx})">
                                <i class="fas fa-times"></i> Close
                            </button>
                        </div>
                    </div>
                    <div class="d-flex justify-content-between align-items-center">
                        <small class="text-muted">Осталось:</small>
                        <span class="pos-timer badge text-info fs-5"
                              data-entry="${entryIso}"
                              data-duration="${duration}">--:--</span>
                    </div>
                </div>`;
            }).join('');

            positionsList.innerHTML = allHtml;
            this._positionsKey = positionsKey;

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
