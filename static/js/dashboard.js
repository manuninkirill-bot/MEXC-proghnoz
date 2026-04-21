class TradingDashboard {
    constructor() {
        this.lastUpdateTime = null;
        this.isUpdating = false;
        
        this.bindEvents();
        this.startDataUpdates();
        
        // Initial load
        this.updateDashboard();
    }

    bindEvents() {
        // Bot control buttons - no password protection
        document.getElementById('start-bot').addEventListener('click', () => this.startBot());
        document.getElementById('stop-bot').addEventListener('click', () => this.stopBot());
        document.getElementById('delete-trade').addEventListener('click', () => this.deleteLastTrade());
        document.getElementById('reset-balance').addEventListener('click', () => this.resetBalance());
        const clearHistoryBtn = document.getElementById('clear-history');
        if (clearHistoryBtn) clearHistoryBtn.addEventListener('click', () => this.clearHistory());
    }

    async startBot() {
        try {
            const response = await fetch('/api/start_bot', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            const data = await response.json();
            
            if (response.ok) {
                this.showNotification('success', data.message || 'Bot started successfully');
            } else {
                this.showNotification('error', data.error || 'Failed to start bot');
            }
        } catch (error) {
            this.showNotification('error', 'Server connection error');
            console.error('Start bot error:', error);
        }
    }

    async stopBot() {
        try {
            const response = await fetch('/api/stop_bot', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            const data = await response.json();
            
            if (response.ok) {
                this.showNotification('success', data.message || 'Bot stopped successfully');
            } else {
                this.showNotification('error', data.error || 'Failed to stop bot');
            }
        } catch (error) {
            this.showNotification('error', 'Server connection error');
            console.error('Stop bot error:', error);
        }
    }

    async closePosition(idx = 0) {
        try {
            const response = await fetch('/api/close_position', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ position_idx: idx })
            });

            const data = await response.json();
            
            if (response.ok) {
                // Show result modal for binary options
                if (data.trade) {
                    this.showResultModal(data.trade);
                }
                setTimeout(() => this.updateDashboard(), 1000);
            } else {
                this.showNotification('error', data.error || 'Failed to close position');
            }
        } catch (error) {
            this.showNotification('error', 'Server connection error');
            console.error('Close position error:', error);
        }
    }
    
    showResultModal(tradeData) {
        if (tradeData.pnl === undefined) return;
        
        const resultTitle = document.getElementById('result-title');
        const resultMessage = document.getElementById('result-message');
        const resultPnL = document.getElementById('result-pnl');
        
        const isWin = tradeData.pnl > 0;
        
        if (isWin) {
            resultTitle.textContent = 'WIN!';
            resultTitle.className = 'text-success mb-4';
            resultMessage.textContent = 'Congratulations! You won the trade.';
            resultPnL.textContent = `+$${Math.abs(tradeData.pnl).toFixed(2)}`;
            resultPnL.className = 'text-success mb-4';
        } else {
            resultTitle.textContent = 'LOSE!';
            resultTitle.className = 'text-danger mb-4';
            resultMessage.textContent = 'Sorry, you lost this trade.';
            resultPnL.textContent = `-$${Math.abs(tradeData.pnl).toFixed(2)}`;
            resultPnL.className = 'text-danger mb-4';
        }
        
        const resultModal = new bootstrap.Modal(document.getElementById('resultModal'));
        resultModal.show();
    }

    async deleteLastTrade() {
        try {
            const response = await fetch('/api/delete_last_trade', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            const data = await response.json();
            
            if (response.ok) {
                this.showNotification('success', data.message || 'Last trade deleted successfully');
                this.updateDashboard();
            } else {
                this.showNotification('error', data.error || 'Failed to delete last trade');
            }
        } catch (error) {
            this.showNotification('error', 'Server connection error');
            console.error('Delete trade error:', error);
        }
    }

    async resetBalance() {
        try {
            const response = await fetch('/api/reset_balance', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            const data = await response.json();
            
            if (response.ok) {
                this.showNotification('success', data.message || 'Balance reset successfully');
                this.updateDashboard();
            } else {
                this.showNotification('error', data.error || 'Failed to reset balance');
            }
        } catch (error) {
            this.showNotification('error', 'Server connection error');
            console.error('Reset balance error:', error);
        }
    }

    async updateDashboard() {
        if (this.isUpdating) {
            return;
        }

        this.isUpdating = true;

        try {
            const response = await fetch('/api/status');
            if (!response.ok) {
                console.error('Status fetch failed');
                return;
            }

            const data = await response.json();

            // Update bot status pill
            const statusBadge = document.getElementById('bot-status');
            if (data.bot_running) {
                statusBadge.textContent = '● RUNNING';
                statusBadge.className = 'status-pill status-pill--running';
            } else {
                statusBadge.textContent = '● STOPPED';
                statusBadge.className = 'status-pill status-pill--stopped';
            }

            // Update balance
            document.getElementById('balance').textContent = `$${parseFloat(data.balance).toFixed(2)}`;
            document.getElementById('available').textContent = `$${parseFloat(data.available).toFixed(2)}`;

            // Update current price
            if (data.current_price) {
                document.getElementById('current-price').textContent = `$${parseFloat(data.current_price).toFixed(2)}`;
            }

            // Update SAR directions
            if (data.sar_directions) {
                this.updateSARDirections(data.sar_directions);
            }

            // Update positions
            const positions = data.positions || [];
            this.updatePositionsList(positions, data.current_price);

            // Update trades
            if (data.trades) {
                this.updateTrades(data.trades);
            }

            // Sync bet/duration buttons with server state
            if (data.bet !== undefined) this.syncBetButtons(data.bet);
            if (data.trade_duration !== undefined) this.syncDurButtons(data.trade_duration);

            this.lastUpdateTime = new Date();
        } catch (error) {
            console.error('Dashboard update error:', error);
        } finally {
            this.isUpdating = false;
        }
    }

    async setBet(amount) {
        try {
            await fetch('/api/set_settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ bet: amount })
            });
            this.syncBetButtons(amount);
        } catch (e) {
            console.error('setBet error:', e);
        }
    }

    async setDuration(seconds) {
        try {
            await fetch('/api/set_settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ trade_duration: seconds })
            });
            this.syncDurButtons(seconds);
        } catch (e) {
            console.error('setDuration error:', e);
        }
    }

    syncBetButtons(activeBet) {
        document.querySelectorAll('.bet-btn').forEach(btn => {
            const val = parseFloat(btn.getAttribute('data-bet'));
            btn.classList.toggle('active-setting', val === parseFloat(activeBet));
        });
    }

    syncDurButtons(activeDur) {
        document.querySelectorAll('.dur-btn').forEach(btn => {
            const val = parseInt(btn.getAttribute('data-dur'));
            btn.classList.toggle('active-setting', val === parseInt(activeDur));
        });
    }

    updateSARDirections(directions) {
        if (!directions) return;
        
        const timeframes = ['1m', '5m', '15m'];
        let allMatch = true;
        let matchDirection = null;
        
        timeframes.forEach(tf => {
            const element = document.getElementById(`sar-${tf}`);
            const container = document.getElementById(`sar-${tf}-container`);
            const direction = directions[tf];
            
            if (element && container) {
                element.className = 'badge sar-badge';
                
                if (direction === 'long') {
                    element.textContent = 'LONG';
                    element.classList.add('bg-success');
                    container.classList.remove('text-danger', 'text-muted');
                    container.classList.add('text-success');
                    if (matchDirection === null) {
                        matchDirection = 'long';
                    } else if (matchDirection !== 'long') {
                        allMatch = false;
                    }
                } else if (direction === 'short') {
                    element.textContent = 'SHORT';
                    element.classList.add('bg-danger');
                    container.classList.remove('text-success', 'text-muted');
                    container.classList.add('text-danger');
                    if (matchDirection === null) {
                        matchDirection = 'short';
                    } else if (matchDirection !== 'short') {
                        allMatch = false;
                    }
                } else {
                    element.textContent = 'N/A';
                    element.classList.add('bg-secondary');
                    container.classList.remove('text-success', 'text-danger');
                    container.classList.add('text-muted');
                    allMatch = false;
                }
            } else {
                allMatch = false;
            }
        });
        
        // Update signal status
        const signalElement = document.getElementById('signal-status');
        if (signalElement) {
            if (allMatch && matchDirection) {
                if (matchDirection === 'long') {
                    signalElement.textContent = 'LONG SIGNAL';
                    signalElement.className = 'badge bg-success signal-badge';
                } else {
                    signalElement.textContent = 'SHORT SIGNAL';
                    signalElement.className = 'badge bg-danger signal-badge';
                }
            } else {
                signalElement.textContent = 'NO SIGNAL';
                signalElement.className = 'badge bg-secondary signal-badge';
            }
        }
    }

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

        // Use a key to detect when positions list structure changes (add/remove)
        const positionsKey = positions.map(p => p.entry_time).join('|');
        const needsRebuild = positionsKey !== this._positionsKey;

        if (needsRebuild) {
            // Build all position cards
            const allHtml = positions.map((pos, idx) => {
                const sideClass = pos.side === 'long' ? 'bg-success' : 'bg-danger';
                const colorClass = pos.side === 'long' ? 'text-success' : 'text-danger';
                const entryPrice = parseFloat(pos.entry_price);
                const bet = parseFloat(pos.bet || 5.0);
                const duration = pos.close_time_seconds || 600;
                const willWin = pos.side === 'long' ? currentPriceNum > entryPrice : currentPriceNum < entryPrice;
                const pnlColorClass = willWin ? 'text-success' : 'text-danger';
                const pnlStatus = willWin ? '✓ IN PROFIT' : '✗ IN LOSS';
                const entryIso = pos.entry_time;

                return `
                <div class="list-group-item bg-dark border-secondary p-3 mb-1">
                    <div class="row align-items-center mb-2">
                        <div class="col-md-2">
                            <span class="badge ${sideClass} fs-6">${pos.side.toUpperCase()}</span>
                            <div><small class="text-muted">#${idx + 1}</small></div>
                        </div>
                        <div class="col-md-2">
                            <small class="text-muted d-block">Entry Price</small>
                            <span class="${colorClass} fw-bold">$${entryPrice.toFixed(2)}</span>
                        </div>
                        <div class="col-md-2">
                            <small class="text-muted d-block">Current Price</small>
                            <span class="pos-current-price fw-bold ${colorClass}" data-idx="${idx}">$${currentPriceNum.toFixed(2)}</span>
                        </div>
                        <div class="col-md-2">
                            <small class="text-muted d-block">Status</small>
                            <span class="pos-pnl-status fw-bold ${pnlColorClass}" data-idx="${idx}">${pnlStatus}</span>
                        </div>
                        <div class="col-md-2">
                            <small class="text-muted d-block">Bet</small>
                            <span class="text-light fw-bold">$${bet.toFixed(2)}</span>
                        </div>
                        <div class="col-md-2 text-end">
                            <button class="btn btn-warning btn-sm" onclick="window.dashboard.closePosition(${idx})">
                                <i class="fas fa-times"></i> Close
                            </button>
                        </div>
                    </div>
                    <div class="d-flex justify-content-between align-items-center">
                        <small class="text-muted">Time Remaining:</small>
                        <span class="pos-timer badge text-info fs-5"
                              data-entry="${entryIso}"
                              data-duration="${duration}">--:--</span>
                    </div>
                </div>`;
            }).join('');

            positionsList.innerHTML = allHtml;
            this._positionsKey = positionsKey;

            // Start a single shared timer for all positions
            clearInterval(this.timerInterval);
            this.timerInterval = setInterval(() => this._tickTimer(), 1000);
            this._tickTimer();
        } else {
            // Positions structure unchanged — just update live price/status
            positions.forEach((pos, idx) => {
                const entryPrice = parseFloat(pos.entry_price);
                const willWin = pos.side === 'long' ? currentPriceNum > entryPrice : currentPriceNum < entryPrice;
                const pnlColorClass = willWin ? 'text-success' : 'text-danger';
                const pnlStatus = willWin ? '✓ IN PROFIT' : '✗ IN LOSS';
                const colorClass = pos.side === 'long' ? 'text-success' : 'text-danger';

                const priceEl = positionsList.querySelector(`.pos-current-price[data-idx="${idx}"]`);
                if (priceEl) {
                    priceEl.textContent = `$${currentPriceNum.toFixed(2)}`;
                    priceEl.className = `pos-current-price fw-bold ${colorClass}`;
                }
                const statusEl = positionsList.querySelector(`.pos-pnl-status[data-idx="${idx}"]`);
                if (statusEl) {
                    statusEl.textContent = pnlStatus;
                    statusEl.className = `pos-pnl-status fw-bold ${pnlColorClass}`;
                }
            });
        }
    }

    _tickTimer() {
        const timers = document.querySelectorAll('.pos-timer');
        if (!timers || timers.length === 0) {
            clearInterval(this.timerInterval);
            this.timerInterval = null;
            return;
        }
        timers.forEach(timerEl => {
            const entryIso = timerEl.getAttribute('data-entry');
            const duration = parseInt(timerEl.getAttribute('data-duration') || '600');
            const entryTime = new Date(entryIso + (entryIso.endsWith('Z') ? '' : 'Z'));
            const now = new Date();
            const elapsed = (now - entryTime) / 1000;
            const remaining = Math.max(0, duration - elapsed);
            const minutes = Math.floor(remaining / 60);
            const seconds = Math.floor(remaining % 60);
            timerEl.textContent = `${minutes}:${seconds.toString().padStart(2, '0')}`;
            if (remaining > 180) {
                timerEl.className = 'pos-timer badge text-info fs-5';
            } else if (remaining > 60) {
                timerEl.className = 'pos-timer badge text-warning fs-5';
            } else {
                timerEl.className = 'pos-timer badge text-danger fs-5';
            }
        });
    }

    updateTrades(trades) {
        const container = document.getElementById('trades-container');
        if (!container) return;
        
        if (!trades || trades.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-clock fa-2x mb-2 opacity-50"></i>
                    <p class="mb-0 opacity-50">No completed trades</p>
                </div>`;
            return;
        }
        
        const recentTrades = trades.slice(-50).reverse();
        
        const tradesHtml = recentTrades.map(trade => {
            const pnl = parseFloat(trade.pnl);
            const pnlClass = pnl >= 0 ? 'text-success' : 'text-danger';
            const sideColor = trade.side === 'long' ? 'bg-success' : 'bg-danger';
            const exitTime = trade.exit_time || trade.time;
            const exitDate = exitTime ? new Date(exitTime).toLocaleTimeString() : 'N/A';
            const exitDateFull = exitTime ? new Date(exitTime).toLocaleDateString() : '';
            const outcome = pnl >= 0 ? 'WIN' : 'LOSE';
            const outcomeClass = pnl >= 0 ? 'text-success' : 'text-danger';
            
            return `
                <div class="list-group-item">
                    <div class="d-flex justify-content-between align-items-center">
                        <div class="d-flex align-items-center gap-2">
                            <span class="badge ${sideColor}">${trade.side.toUpperCase()}</span>
                            <span class="${outcomeClass} fw-bold">${outcome}</span>
                            <span class="${pnlClass} fw-bold">${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}</span>
                        </div>
                        <div class="text-end">
                            <div style="font-size:12px;color:var(--text-muted)">${exitDate}</div>
                            <div style="font-size:11px;color:var(--text-dim)">${exitDateFull}</div>
                        </div>
                    </div>
                    <div class="mt-1" style="font-size:12px;color:var(--text-muted)">
                        Entry $${trade.entry_price.toFixed(2)} → Exit $${trade.exit_price.toFixed(2)}
                    </div>
                </div>`;
        }).join('');
        
        container.innerHTML = tradesHtml;
    }

    async clearHistory() {
        try {
            await fetch('/api/clear_history', { method: 'POST' });
            this.updateTrades([]);
            this.showNotification('success', 'Trade history cleared');
        } catch (e) {
            this.showNotification('error', 'Failed to clear history');
        }
    }

    showNotification(type, message) {
        // Create notification element
        const notification = document.createElement('div');
        notification.className = `alert alert-${type === 'error' ? 'danger' : 'success'} alert-dismissible fade show position-fixed`;
        notification.style.top = '20px';
        notification.style.right = '20px';
        notification.style.zIndex = '9999';
        notification.style.minWidth = '300px';
        
        notification.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        
        document.body.appendChild(notification);
        
        // Auto remove after 5 seconds
        setTimeout(() => {
            notification.remove();
        }, 5000);
    }

    startDataUpdates() {
        // Update dashboard every 3 seconds
        setInterval(() => {
            this.updateDashboard();
        }, 3000);
    }
}

// Initialize dashboard when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.dashboard = new TradingDashboard();
});
