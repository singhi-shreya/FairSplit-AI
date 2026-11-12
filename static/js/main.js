/**
 * FairSplit AI - Frontend Application Logic (Fintech Redesign)
 * 
 * Manages:
 * - Real Fintech Dashboard with live stats (Total Bills, Total Expenses, Pending Payments)
 * - Local history persistence with zero fake stats & settlement status tracking
 * - Left Sidebar Navigation & View Router (Dashboard, Create Split, History, Settings)
 * - TWO INDEPENDENT WORKFLOWS:
 *   1. Mode 1: Manual Step-by-Step Entry (100% preserved)
 *   2. Mode 2: AI-Powered Bill Entry (Natural language & Receipt Photo Vision)
 * - Interactive review cards with participant toggle chips
 * - Precision Python calculation engine (/api/calculate) with integer-paise math
 * - Live latency counter for fast Gemini API extraction
 * - Mobile responsive drawer navigation & Lucide icons
 */

// ==========================================
// 1. Storage & Persistence Keys
// ==========================================
const STORAGE_BILLS_KEY = 'fairsplit_bills_history';
const STORAGE_USER_KEY = 'fairsplit_speaker_name';

// Application State for Mode 1 (Manual Entry)
const state = {
    members: [],
    items: [],
    nextItemId: 1,
    editingItemId: null
};

// Application State for Mode 2 (AI-Powered Entry)
const aiState = {
    members: [],
    items: [],
    nextItemId: 1,
    tax: 0.0,
    tip: 0.0,
    restaurantName: ''
};

// Currently Active Calculation Session
let currentBillSession = null;
let currentFilter = 'all';

// Concurrency Guards
let isCalculating = false;
let isAiInterpreting = false;
let isScanningReceipt = false;
let currentReceiptFile = null;

// ==========================================
// PayPal Sandbox Checkout Configuration
// ==========================================
let paypalConfig = {
    is_enabled: false,
    client_id: '',
    currency: 'USD',
    inr_to_usd_rate: 0.012,
    mode: 'sandbox',
    currency_disclosure: 'PayPal Checkout converts your INR share to USD at a fixed rate of 1 INR = $0.0120 USD. Server validates exact amounts.'
};
let paypalSdkLoaded = false;
let paypalSdkLoadingPromise = null;

async function initPayPalConfig() {
    try {
        const resp = await fetch('/api/paypal/config');
        if (resp.ok) {
            const data = await resp.json();
            paypalConfig = data;
            updatePayPalSettingsCard(data);
            updatePayPalDisclosureBanner(data);
            if (data.is_enabled && data.client_id) {
                loadPayPalSDK(data.client_id, data.currency);
            }
        }
    } catch (err) {
        console.warn('Could not fetch PayPal config from server:', err);
    }
}

function updatePayPalDisclosureBanner(config) {
    const banner = document.getElementById('paypalDisclosureBanner');
    const textEl = document.getElementById('paypalDisclosureText');
    const titleEl = document.getElementById('paypalDisclosureTitle');
    const badgeEl = document.getElementById('paypalModeBadge');
    if (!banner) return;

    if (config.is_enabled) {
        if (textEl && config.currency_disclosure) {
            textEl.textContent = config.currency_disclosure;
        }
        if (badgeEl) {
            badgeEl.textContent = `${(config.mode || 'sandbox').toUpperCase()} READY`;
        }
        banner.classList.remove('hidden');
    } else {
        if (badgeEl) badgeEl.textContent = 'OFFLINE / CASH ONLY';
        if (titleEl) titleEl.textContent = 'PayPal Integration Inactive';
        if (textEl) textEl.textContent = 'Add your Sandbox credentials to .env to enable one-click PayPal payments for each member.';
    }
}

function updatePayPalSettingsCard(config) {
    const statusEl = document.getElementById('settingsPaypalStatus');
    const modeEl = document.getElementById('settingsPaypalMode');
    const rateEl = document.getElementById('settingsPaypalRate');

    if (statusEl) {
        if (config.is_enabled) {
            statusEl.className = 'badge-tag-success';
            statusEl.textContent = 'Active & Connected';
        } else {
            statusEl.className = 'badge-tag-neutral';
            statusEl.textContent = 'Credentials Required';
        }
    }
    if (modeEl) {
        modeEl.textContent = (config.mode || 'sandbox').toUpperCase();
    }
    if (rateEl) {
        rateEl.textContent = `1 INR = $${Number(config.inr_to_usd_rate || 0.012).toFixed(4)} USD`;
    }
}

function loadPayPalSDK(clientId, currency = 'USD') {
    if (window.paypal && typeof window.paypal.Buttons === 'function') {
        paypalSdkLoaded = true;
        return Promise.resolve(window.paypal);
    }
    if (paypalSdkLoadingPromise) {
        return paypalSdkLoadingPromise;
    }
    paypalSdkLoadingPromise = new Promise((resolve, reject) => {
        const existingScript = document.querySelector('script[src*="paypal.com/sdk/js"]');
        if (existingScript) {
            existingScript.addEventListener('load', () => {
                paypalSdkLoaded = true;
                resolve(window.paypal);
            });
            existingScript.addEventListener('error', (err) => reject(err));
            return;
        }

        const script = document.createElement('script');
        script.src = `https://www.paypal.com/sdk/js?client-id=${encodeURIComponent(clientId)}&currency=${encodeURIComponent(currency)}&intent=capture&components=buttons`;
        script.async = true;
        script.onload = () => {
            paypalSdkLoaded = true;
            resolve(window.paypal);
        };
        script.onerror = (err) => {
            console.warn('PayPal JS SDK script failed to load:', err);
            reject(err);
        };
        document.head.appendChild(script);
    });
    return paypalSdkLoadingPromise;
}


// ==========================================
// 2. DOM Elements Selection
// ==========================================

// Views
const viewDashboard = document.getElementById('viewDashboard');
const viewCreateSplit = document.getElementById('viewCreateSplit');
const viewHistory = document.getElementById('viewHistory');
const viewSettings = document.getElementById('viewSettings');

// Sidebar Nav Buttons
const sidebarNavDashboard = document.getElementById('sidebarNavDashboard');
const sidebarNavCreate = document.getElementById('sidebarNavCreate');
const sidebarNavHistory = document.getElementById('sidebarNavHistory');
const sidebarNavSettings = document.getElementById('sidebarNavSettings');
const historyCounterBadge = document.getElementById('historyCounterBadge');

// Mobile Nav Elements
const mobileMenuToggle = document.getElementById('mobileMenuToggle');
const appSidebar = document.getElementById('appSidebar');
const sidebarBackdrop = document.getElementById('sidebarBackdrop');

// Dashboard Elements
const heroHeading = document.getElementById('heroHeading');
const heroGreetingTime = document.getElementById('heroGreetingTime');
const dashboardCreateSplitBtn = document.getElementById('dashboardCreateSplitBtn');
const dashTotalBills = document.getElementById('dashTotalBills');
const dashTotalBillsSubtitle = document.getElementById('dashTotalBillsSubtitle');
const dashTotalExpenses = document.getElementById('dashTotalExpenses');
const dashPendingAmount = document.getElementById('dashPendingAmount');
const dashPendingBadge = document.getElementById('dashPendingBadge');
const recentBillsContainer = document.getElementById('recentBillsContainer');
const viewAllBillsLink = document.getElementById('viewAllBillsLink');

// Quick Actions
const quickActionManual = document.getElementById('quickActionManual');
const quickActionAi = document.getElementById('quickActionAi');
const quickActionReceipt = document.getElementById('quickActionReceipt');

// Create Split View Controls
const createSplitBackBtn = document.getElementById('createSplitBackBtn');
const navManualModeBtn = document.getElementById('navManualModeBtn');
const navAiModeBtn = document.getElementById('navAiModeBtn');
const manualModeWorkflow = document.getElementById('manualModeWorkflow');
const aiModeWorkflow = document.getElementById('aiModeWorkflow');

// Mode 1: Manual Entry Elements
const memberNameInput = document.getElementById('memberNameInput');
const addMemberForm = document.getElementById('addMemberForm');
const membersList = document.getElementById('membersList');
const emptyMembersText = document.getElementById('emptyMembersText');

const addItemForm = document.getElementById('addItemForm');
const itemNameInput = document.getElementById('itemNameInput');
const itemPriceInput = document.getElementById('itemPriceInput');
const itemShareCheckboxes = document.getElementById('itemShareCheckboxes');
const itemsContainer = document.getElementById('itemsContainer');
const emptyItemsText = document.getElementById('emptyItemsText');
const itemsCount = document.getElementById('itemsCount');
const selectAllMembersBtn = document.getElementById('selectAllMembersBtn');
const clearSelectedMembersBtn = document.getElementById('clearSelectedMembersBtn');

const taxInput = document.getElementById('taxInput');
const tipInput = document.getElementById('tipInput');
const tipChips = document.querySelectorAll('.tip-chip');
const calculateBtn = document.getElementById('calculateBtn');
const resetBtn = document.getElementById('resetBtn');

// Mode 2: AI Entry Elements
const aiSpeakerInput = document.getElementById('aiSpeakerInput');
const aiDescriptionInput = document.getElementById('aiDescriptionInput');
const aiInterpretBtn = document.getElementById('aiInterpretBtn');
const aiClearPromptBtn = document.getElementById('aiClearPromptBtn');
const aiLoadingIndicator = document.getElementById('aiLoadingIndicator');
const aiLoadingStatusText = document.getElementById('aiLoadingStatusText');
const aiTimerBadge = document.getElementById('aiTimerBadge');
const aiClarificationBox = document.getElementById('aiClarificationBox');
const aiClarificationList = document.getElementById('aiClarificationList');

// AI Sub-tabs
const tabTextModeBtn = document.getElementById('tabTextModeBtn');
const tabReceiptModeBtn = document.getElementById('tabReceiptModeBtn');
const aiTextEntryPanel = document.getElementById('aiTextEntryPanel');
const aiReceiptEntryPanel = document.getElementById('aiReceiptEntryPanel');

// Receipt Upload Elements
const aiReceiptMembersInput = document.getElementById('aiReceiptMembersInput');
const receiptDropzone = document.getElementById('receiptDropzone');
const receiptFileInput = document.getElementById('receiptFileInput');
const browseReceiptBtn = document.getElementById('browseReceiptBtn');
const dropzonePrompt = document.getElementById('dropzonePrompt');
const receiptPreviewBox = document.getElementById('receiptPreviewBox');
const receiptPreviewImg = document.getElementById('receiptPreviewImg');
const receiptFileName = document.getElementById('receiptFileName');
const receiptFileSize = document.getElementById('receiptFileSize');
const replaceReceiptBtn = document.getElementById('replaceReceiptBtn');
const removeReceiptBtn = document.getElementById('removeReceiptBtn');
const scanReceiptBtn = document.getElementById('scanReceiptBtn');

// AI Review Section Elements
const aiReviewSection = document.getElementById('aiReviewSection');
const aiRestaurantBanner = document.getElementById('aiRestaurantBanner');
const aiRestaurantName = document.getElementById('aiRestaurantName');
const aiMembersCount = document.getElementById('aiMembersCount');
const aiMembersList = document.getElementById('aiMembersList');
const aiAddMemberForm = document.getElementById('aiAddMemberForm');
const aiAddMemberInput = document.getElementById('aiAddMemberInput');
const aiItemsContainer = document.getElementById('aiItemsContainer');
const aiAddNewItemBtn = document.getElementById('aiAddNewItemBtn');
const aiItemsSubtotal = document.getElementById('aiItemsSubtotal');
const aiTaxInput = document.getElementById('aiTaxInput');
const aiTipInput = document.getElementById('aiTipInput');
const aiTipChips = document.querySelectorAll('.ai-tip-chip');
const aiConfirmCalculateBtn = document.getElementById('aiConfirmCalculateBtn');
const aiCopyToManualBtn = document.getElementById('aiCopyToManualBtn');
const aiResetBtn = document.getElementById('aiResetBtn');

// Sample Prompt Buttons
const samplePromptBtn1 = document.getElementById('samplePromptBtn1');
const samplePromptBtn2 = document.getElementById('samplePromptBtn2');
const samplePromptBtn3 = document.getElementById('samplePromptBtn3');

// Results & Breakdown Elements
const resultsPlaceholder = document.getElementById('resultsPlaceholder');
const resultsContent = document.getElementById('resultsContent');
const summarySubtotal = document.getElementById('summarySubtotal');
const summaryTax = document.getElementById('summaryTax');
const summaryTaxLabel = document.getElementById('summaryTaxLabel');
const summaryTip = document.getElementById('summaryTip');
const summaryTipLabel = document.getElementById('summaryTipLabel');
const summaryGrandTotal = document.getElementById('summaryGrandTotal');
const breakdownCardsContainer = document.getElementById('breakdownCardsContainer');
const settlementProgressRatio = document.getElementById('settlementProgressRatio');
const settlementProgressBar = document.getElementById('settlementProgressBar');
const copySplitSummaryBtn = document.getElementById('copySplitSummaryBtn');
const saveSplitToHistoryBtn = document.getElementById('saveSplitToHistoryBtn');

// History View Elements
const fullHistoryContainer = document.getElementById('fullHistoryContainer');
const historyFilteredCount = document.getElementById('historyFilteredCount');
const historyFilterPills = document.querySelectorAll('.filter-pill');
const historyNewSplitBtn = document.getElementById('historyNewSplitBtn');

// Settings Elements
const settingsSpeakerInput = document.getElementById('settingsSpeakerInput');
const saveSpeakerSettingBtn = document.getElementById('saveSpeakerSettingBtn');
const clearAllHistoryBtn = document.getElementById('clearAllHistoryBtn');
const sidebarUserName = document.getElementById('sidebarUserName');
const sidebarUserAvatar = document.getElementById('sidebarUserAvatar');
const toastContainer = document.getElementById('toastContainer');
const alertBox = document.getElementById('alertBox');

// ==========================================
// 3. Formatting, Toasts & Alert Helpers
// ==========================================

function formatINR(amount) {
    const num = Number(amount) || 0;
    return '₹' + num.toLocaleString('en-IN', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
}

function showToast(message, type = 'success') {
    if (!toastContainer) return;

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    
    let iconName = 'check-circle';
    if (type === 'error') iconName = 'alert-circle';
    else if (type === 'info') iconName = 'info';

    toast.innerHTML = `
        <i data-lucide="${iconName}" class="toast-icon"></i>
        <span>${escapeHtml(message)}</span>
    `;

    toastContainer.appendChild(toast);
    refreshIcons();

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(10px)';
        toast.style.transition = 'all 0.25s ease';
        setTimeout(() => toast.remove(), 250);
    }, 4000);
}

function showAlert(message, type = 'error') {
    showToast(message, type);
    if (alertBox) {
        alertBox.textContent = message;
        alertBox.className = `alert alert-${type}`;
        alertBox.classList.remove('hidden');
        setTimeout(() => alertBox.classList.add('hidden'), 6000);
    }
}

function hideAlert() {
    if (alertBox) alertBox.classList.add('hidden');
}

function escapeHtml(str) {
    if (!str) return '';
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function refreshIcons() {
    if (window.lucide && typeof window.lucide.createIcons === 'function') {
        window.lucide.createIcons();
    }
}

// ==========================================
// 4. LocalStorage & Real Data Persistence
// ==========================================

function getBillsHistory() {
    try {
        const raw = localStorage.getItem(STORAGE_BILLS_KEY);
        return raw ? JSON.parse(raw) : [];
    } catch (e) {
        console.error('Failed to parse bills history from localStorage', e);
        return [];
    }
}

function saveBillsHistory(bills) {
    try {
        localStorage.setItem(STORAGE_BILLS_KEY, JSON.stringify(bills));
        updateHistoryBadge();
        updateDashboardStats();
    } catch (e) {
        console.error('Failed to save bills history', e);
    }
}

function saveBillRecord(billData) {
    const bills = getBillsHistory();
    const existingIdx = bills.findIndex(b => b.id === billData.id);

    if (existingIdx >= 0) {
        bills[existingIdx] = billData;
    } else {
        bills.unshift(billData); // Newest first
    }

    saveBillsHistory(bills);
    return billData;
}

function deleteBillRecord(billId) {
    let bills = getBillsHistory();
    bills = bills.filter(b => b.id !== billId);
    saveBillsHistory(bills);
    renderRecentBills();
    renderFullHistory(currentFilter);
    showToast('Bill removed from history', 'info');
}

function updateHistoryBadge() {
    const bills = getBillsHistory();
    if (historyCounterBadge) {
        historyCounterBadge.textContent = bills.length;
    }
}

// ==========================================
// 5. Dashboard Real Statistics & Recent Bills
// ==========================================

function updateDashboardStats() {
    const bills = getBillsHistory();
    const count = bills.length;

    // Total Bills
    if (dashTotalBills) dashTotalBills.textContent = count;
    if (dashTotalBillsSubtitle) {
        dashTotalBillsSubtitle.textContent = count === 1 ? '1 bill recorded' : `${count} bills recorded`;
    }

    // Total Expenses, Collected (PayPal vs Offline), and Outstanding
    let totalRupees = 0;
    let pendingRupees = 0;
    let pendingCount = 0;
    let collectedRupees = 0;
    let paypalRupees = 0;
    let offlineRupees = 0;

    bills.forEach(bill => {
        const gt = bill.summary?.grand_total || 0;
        totalRupees += Number(gt);

        if (bill.settlement && bill.breakdown) {
            Object.entries(bill.breakdown).forEach(([member, info]) => {
                const share = Number(info.total || 0);
                const status = bill.settlement[member] || 'pending';
                if (status === 'paid') {
                    collectedRupees += share;
                    const method = (bill.payment_methods && bill.payment_methods[member]) || 
                                   (bill.paypal_orders && bill.paypal_orders[member] ? 'paypal' : 'offline');
                    if (method === 'paypal') {
                        paypalRupees += share;
                    } else {
                        offlineRupees += share;
                    }
                } else {
                    pendingRupees += share;
                    pendingCount++;
                }
            });
        }
    });

    if (dashTotalExpenses) dashTotalExpenses.textContent = formatINR(totalRupees);

    // Total Collected Card
    const dashTotalCollected = document.getElementById('dashTotalCollected');
    const dashCollectedBreakdown = document.getElementById('dashCollectedBreakdown');
    if (dashTotalCollected) dashTotalCollected.textContent = formatINR(collectedRupees);
    if (dashCollectedBreakdown) {
        dashCollectedBreakdown.textContent = `PayPal: ${formatINR(paypalRupees)} • Offline: ${formatINR(offlineRupees)}`;
    }

    // Total Outstanding Card
    if (dashPendingAmount) dashPendingAmount.textContent = formatINR(pendingRupees);

    if (dashPendingBadge) {
        if (count === 0) {
            dashPendingBadge.textContent = 'All Settled';
            dashPendingBadge.className = 'stat-badge stat-badge-neutral';
        } else if (pendingRupees > 0) {
            dashPendingBadge.textContent = `${pendingCount} Shares Pending`;
            dashPendingBadge.className = 'stat-badge stat-badge-warning';
        } else {
            dashPendingBadge.textContent = 'All Settled ✓';
            dashPendingBadge.className = 'stat-badge stat-badge-success';
        }
    }
}

function renderRecentBills() {
    if (!recentBillsContainer) return;
    const bills = getBillsHistory();

    if (bills.length === 0) {
        recentBillsContainer.innerHTML = `
            <div class="empty-state-box">
                <div class="empty-icon-circle">
                    <i data-lucide="receipt"></i>
                </div>
                <h4 class="empty-title">No bills created yet</h4>
                <p class="empty-desc">
                    Get started by choosing one of the quick actions above to split your first restaurant bill with friends.
                </p>
                <button type="button" class="btn btn-emerald-primary btn-sm" id="emptyCreateFirstSplitBtn">
                    <i data-lucide="plus"></i>
                    <span>Create Your First Split</span>
                </button>
            </div>
        `;

        const firstSplitBtn = document.getElementById('emptyCreateFirstSplitBtn');
        if (firstSplitBtn) {
            firstSplitBtn.addEventListener('click', () => navigateTo('create-split'));
        }
        refreshIcons();
        return;
    }

    // Show up to 4 recent bills
    const recent = bills.slice(0, 4);
    recentBillsContainer.innerHTML = recent.map(bill => {
        const title = bill.title || 'Restaurant Dining Bill';
        const dateStr = bill.displayDate || 'Recent';
        const memberCount = bill.members?.length || 0;
        const grandTotalStr = bill.summary?.grand_total_formatted || formatINR(bill.summary?.grand_total || 0);

        // Check settlement
        let allPaid = true;
        if (bill.settlement && bill.members) {
            allPaid = bill.members.every(m => bill.settlement[m] === 'paid');
        }

        const statusClass = allPaid ? 'bill-status-settled' : 'bill-status-pending';
        const statusText = allPaid ? 'All Settled ✓' : 'Pending';

        return `
            <div class="bill-row-card" data-bill-id="${bill.id}">
                <div class="bill-row-left">
                    <div class="bill-row-icon">
                        <i data-lucide="receipt-text"></i>
                    </div>
                    <div class="bill-row-info">
                        <h4>${escapeHtml(title)}</h4>
                        <div class="bill-row-meta">
                            <span>${escapeHtml(dateStr)}</span>
                            <span class="meta-dot">•</span>
                            <span>${memberCount} ${memberCount === 1 ? 'member' : 'members'}</span>
                        </div>
                    </div>
                </div>
                <div class="bill-row-right">
                    <div class="bill-row-amount">
                        <div class="bill-total-price">${grandTotalStr}</div>
                        <span class="bill-status-pill ${statusClass}">${statusText}</span>
                    </div>
                    <i data-lucide="chevron-right" class="arrow-icon"></i>
                </div>
            </div>
        `;
    }).join('');

    // Attach click handlers to open bill in breakdown view
    recentBillsContainer.querySelectorAll('.bill-row-card').forEach(card => {
        card.addEventListener('click', () => {
            const billId = card.getAttribute('data-bill-id');
            loadBillIntoView(billId);
        });
    });

    refreshIcons();
}

function loadBillIntoView(billId) {
    const bills = getBillsHistory();
    const bill = bills.find(b => b.id === billId);
    if (!bill) return;

    currentBillSession = bill;
    navigateTo('create-split');

    // Populate Results Section directly
    renderResults({
        bill_id: bill.bill_id || bill.id,
        summary: bill.summary,
        breakdown: bill.breakdown
    }, bill);

    showToast(`Loaded "${bill.title}" details`, 'info');
}

// ==========================================
// 6. Navigation & View Routing
// ==========================================

function navigateTo(viewId) {
    const views = {
        'dashboard': viewDashboard,
        'create-split': viewCreateSplit,
        'history': viewHistory,
        'settings': viewSettings
    };

    const navButtons = {
        'dashboard': sidebarNavDashboard,
        'create-split': sidebarNavCreate,
        'history': sidebarNavHistory,
        'settings': sidebarNavSettings
    };

    // Toggle view visibility
    Object.entries(views).forEach(([id, el]) => {
        if (!el) return;
        if (id === viewId) {
            el.classList.remove('hidden');
            el.classList.add('active-view');
        } else {
            el.classList.add('hidden');
            el.classList.remove('active-view');
        }
    });

    // Update active nav button
    Object.entries(navButtons).forEach(([id, btn]) => {
        if (!btn) return;
        if (id === viewId) btn.classList.add('active');
        else btn.classList.remove('active');
    });

    // Close mobile drawer if open
    closeMobileSidebar();

    // Trigger View-specific renders
    if (viewId === 'dashboard') {
        updateDashboardStats();
        renderRecentBills();
    } else if (viewId === 'history') {
        renderFullHistory(currentFilter);
    } else if (viewId === 'settings') {
        loadSettingsView();
    }

    window.scrollTo({ top: 0, behavior: 'smooth' });
    refreshIcons();
}

function openMobileSidebar() {
    if (appSidebar) appSidebar.classList.add('open');
    if (sidebarBackdrop) sidebarBackdrop.classList.add('active');
}

function closeMobileSidebar() {
    if (appSidebar) appSidebar.classList.remove('open');
    if (sidebarBackdrop) sidebarBackdrop.classList.remove('active');
}

// Attach Nav Listeners
if (sidebarNavDashboard) sidebarNavDashboard.addEventListener('click', () => navigateTo('dashboard'));
if (sidebarNavCreate) sidebarNavCreate.addEventListener('click', () => navigateTo('create-split'));
if (sidebarNavHistory) sidebarNavHistory.addEventListener('click', () => navigateTo('history'));
if (sidebarNavSettings) sidebarNavSettings.addEventListener('click', () => navigateTo('settings'));

if (dashboardCreateSplitBtn) dashboardCreateSplitBtn.addEventListener('click', () => navigateTo('create-split'));
if (createSplitBackBtn) createSplitBackBtn.addEventListener('click', () => navigateTo('dashboard'));
if (historyNewSplitBtn) historyNewSplitBtn.addEventListener('click', () => navigateTo('create-split'));
if (viewAllBillsLink) viewAllBillsLink.addEventListener('click', () => navigateTo('history'));

// Mobile menu toggle
if (mobileMenuToggle) mobileMenuToggle.addEventListener('click', openMobileSidebar);
if (sidebarBackdrop) sidebarBackdrop.addEventListener('click', closeMobileSidebar);

// Quick Action Card Click Handlers
if (quickActionManual) {
    quickActionManual.addEventListener('click', () => {
        navigateTo('create-split');
        switchMode('manual');
    });
}

if (quickActionAi) {
    quickActionAi.addEventListener('click', () => {
        navigateTo('create-split');
        switchMode('ai');
        switchToAiTextSubtab();
    });
}

if (quickActionReceipt) {
    quickActionReceipt.addEventListener('click', () => {
        navigateTo('create-split');
        switchMode('ai');
        switchToAiReceiptSubtab();
    });
}

// ==========================================
// 7. Mode Switcher (Mode 1 Manual vs Mode 2 AI)
// ==========================================

function switchMode(mode) {
    if (mode === 'manual') {
        navManualModeBtn.classList.add('active');
        navAiModeBtn.classList.remove('active');
        manualModeWorkflow.classList.remove('hidden');
        aiModeWorkflow.classList.add('hidden');
    } else {
        navAiModeBtn.classList.add('active');
        navManualModeBtn.classList.remove('active');
        aiModeWorkflow.classList.remove('hidden');
        manualModeWorkflow.classList.add('hidden');
    }
    hideAlert();
    refreshIcons();
}

navManualModeBtn.addEventListener('click', () => switchMode('manual'));
navAiModeBtn.addEventListener('click', () => switchMode('ai'));

function switchToAiTextSubtab() {
    if (tabTextModeBtn && tabReceiptModeBtn) {
        tabTextModeBtn.classList.add('active');
        tabReceiptModeBtn.classList.remove('active');
        aiTextEntryPanel.classList.remove('hidden');
        aiReceiptEntryPanel.classList.add('hidden');
    }
}

function switchToAiReceiptSubtab() {
    if (tabTextModeBtn && tabReceiptModeBtn) {
        tabReceiptModeBtn.classList.add('active');
        tabTextModeBtn.classList.remove('active');
        aiReceiptEntryPanel.classList.remove('hidden');
        aiTextEntryPanel.classList.add('hidden');

        if (!aiReceiptMembersInput.value.trim() && state.members.length > 0) {
            aiReceiptMembersInput.value = state.members.join(', ');
        }
    }
}

// ==========================================
// 8. MODE 1: MANUAL ENTRY WORKFLOW (100% PRESERVED)
// ==========================================

addMemberForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const name = memberNameInput.value.trim();

    if (!name) {
        showAlert('Please enter a valid member name.');
        return;
    }

    const exists = state.members.some(m => m.trim().toLowerCase() === name.toLowerCase());
    if (exists) {
        showAlert(`"${name}" is already in the group.`);
        return;
    }

    state.members.push(name);
    memberNameInput.value = '';
    memberNameInput.focus();

    renderMembers();
    renderShareCheckboxes();
    hideAlert();
    showToast(`Added member ${name}`, 'info');
});

function removeMember(nameToRemove) {
    state.members = state.members.filter(m => m !== nameToRemove);

    state.items.forEach(item => {
        item.sharedBy = item.sharedBy.filter(m => m !== nameToRemove);
    });

    renderMembers();
    renderShareCheckboxes();
    renderItems();
}

function renderMembers() {
    membersList.innerHTML = '';

    if (state.members.length === 0) {
        emptyMembersText.classList.remove('hidden');
        membersList.appendChild(emptyMembersText);
        return;
    }

    emptyMembersText.classList.add('hidden');

    state.members.forEach(member => {
        const chip = document.createElement('div');
        chip.className = 'member-chip';
        chip.innerHTML = `
            <span>${escapeHtml(member)}</span>
            <button type="button" class="remove-chip-btn" aria-label="Remove ${escapeHtml(member)}">&times;</button>
        `;

        chip.querySelector('.remove-chip-btn').addEventListener('click', () => {
            removeMember(member);
        });

        membersList.appendChild(chip);
    });
}

function renderShareCheckboxes() {
    itemShareCheckboxes.innerHTML = '';

    if (state.members.length === 0) {
        itemShareCheckboxes.innerHTML = '<span class="empty-state-text">Add group members above first.</span>';
        return;
    }

    state.members.forEach(member => {
        const label = document.createElement('label');
        label.className = 'participant-select-chip selected';

        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.value = member;
        checkbox.checked = true;

        checkbox.addEventListener('change', () => {
            if (checkbox.checked) {
                label.classList.add('selected');
            } else {
                label.classList.remove('selected');
            }
        });

        label.appendChild(checkbox);
        label.appendChild(document.createTextNode(member));
        itemShareCheckboxes.appendChild(label);
    });
}

selectAllMembersBtn.addEventListener('click', () => {
    itemShareCheckboxes.querySelectorAll('label').forEach(label => {
        const cb = label.querySelector('input');
        cb.checked = true;
        label.classList.add('selected');
    });
});

clearSelectedMembersBtn.addEventListener('click', () => {
    itemShareCheckboxes.querySelectorAll('label').forEach(label => {
        const cb = label.querySelector('input');
        cb.checked = false;
        label.classList.remove('selected');
    });
});

addItemForm.addEventListener('submit', (e) => {
    e.preventDefault();

    const name = itemNameInput.value.trim();
    const price = parseFloat(itemPriceInput.value);

    if (!name) {
        showAlert('Please enter an item description.');
        return;
    }

    if (isNaN(price) || price <= 0) {
        showAlert('Please enter a valid price greater than ₹0.00.');
        return;
    }

    const selectedMembers = [];
    itemShareCheckboxes.querySelectorAll('input[type="checkbox"]:checked').forEach(cb => {
        selectedMembers.push(cb.value);
    });

    if (selectedMembers.length === 0) {
        showAlert('Please select at least one person who shared this item.');
        return;
    }

    state.items.push({
        id: state.nextItemId++,
        name: name,
        price: price,
        sharedBy: selectedMembers
    });

    itemNameInput.value = '';
    itemPriceInput.value = '';
    itemNameInput.focus();

    selectAllMembersBtn.click();
    renderItems();
    hideAlert();
    showToast(`Added "${name}" (${formatINR(price)})`, 'info');
});

function removeItem(itemId) {
    state.items = state.items.filter(i => i.id !== itemId);
    renderItems();
}

function renderItems() {
    itemsContainer.innerHTML = '';
    itemsCount.textContent = state.items.length;

    if (state.items.length === 0) {
        emptyItemsText.classList.remove('hidden');
        itemsContainer.appendChild(emptyItemsText);
        return;
    }

    emptyItemsText.classList.add('hidden');

    state.items.forEach(item => {
        const card = document.createElement('div');
        card.className = 'item-card';

        const userTagsHtml = item.sharedBy.map(m => `
            <span class="item-user-tag">${escapeHtml(m)}</span>
        `).join('');

        card.innerHTML = `
            <div class="item-card-left">
                <span class="item-card-name">${escapeHtml(item.name)}</span>
                <div class="item-card-chips">
                    ${userTagsHtml}
                </div>
            </div>
            <div class="item-card-right">
                <span class="item-card-price">${formatINR(item.price)}</span>
                <button type="button" class="item-delete-btn" aria-label="Delete item">
                    <i data-lucide="trash-2"></i>
                </button>
            </div>
        `;

        card.querySelector('.item-delete-btn').addEventListener('click', () => {
            removeItem(item.id);
        });

        itemsContainer.appendChild(card);
    });

    refreshIcons();
}

// Quick Tip Chips
tipChips.forEach(chip => {
    chip.addEventListener('click', () => {
        tipChips.forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
        tipInput.value = chip.dataset.tip;
    });
});

calculateBtn.addEventListener('click', async () => {
    if (state.members.length === 0) {
        showAlert('Please add at least one group member before calculating.');
        return;
    }

    if (state.items.length === 0) {
        showAlert('Please add at least one bill item.');
        return;
    }

    for (const item of state.items) {
        if (!item.sharedBy || item.sharedBy.length === 0) {
            showAlert(`Dish "${item.name}" has no participants assigned.`);
            return;
        }
    }

    const taxValue = parseFloat(taxInput.value) || 0.0;
    const tipValue = parseFloat(tipInput.value) || 0.0;

    if (taxValue < 0 || tipValue < 0) {
        showAlert('Tax and tip percentages cannot be negative.');
        return;
    }

    const payload = {
        members: state.members,
        items: state.items.map(i => ({
            name: i.name,
            price: i.price,
            shared_by: i.sharedBy
        })),
        tax_percentage: taxValue,
        tip_percentage: tipValue
    };

    await executeCalculation(payload, calculateBtn, 'Calculate Fair Split ⚡', 'Manual Dining Split');
});

resetBtn.addEventListener('click', () => {
    if (state.members.length === 0 && state.items.length === 0) return;

    if (confirm('Clear all members and items in Manual Mode?')) {
        state.members = [];
        state.items = [];
        state.nextItemId = 1;
        state.editingItemId = null;

        memberNameInput.value = '';
        itemNameInput.value = '';
        itemPriceInput.value = '';
        taxInput.value = '0';
        tipInput.value = '0';

        renderMembers();
        renderShareCheckboxes();
        renderItems();

        resultsContent.classList.add('hidden');
        resultsPlaceholder.classList.remove('hidden');
        hideAlert();
        showToast('Manual form cleared', 'info');
    }
});

// ==========================================
// 9. MODE 2: AI-POWERED BILL ENTRY WORKFLOW
// ==========================================

if (samplePromptBtn1) {
    samplePromptBtn1.addEventListener('click', () => {
        aiDescriptionInput.value = "Rahul ate pizza which was 600 rupees, Priya and I shared 400 rupees pasta, and we all shared Coke worth 180 rupees.";
        if (!aiSpeakerInput.value.trim()) aiSpeakerInput.value = getSavedSpeakerName() || "Sneha";
        aiDescriptionInput.focus();
    });
}

if (samplePromptBtn2) {
    samplePromptBtn2.addEventListener('click', () => {
        aiDescriptionInput.value = "Amit had biryani for 380, Pooja had dosa for 160, and we both shared kulfi for 140";
        if (!aiSpeakerInput.value.trim()) aiSpeakerInput.value = getSavedSpeakerName() || "Sneha";
        aiDescriptionInput.focus();
    });
}

if (samplePromptBtn3) {
    samplePromptBtn3.addEventListener('click', () => {
        aiDescriptionInput.value = "Rahul had burger for 250, Priya had pasta for 350, and I had dessert";
        if (!aiSpeakerInput.value.trim()) aiSpeakerInput.value = getSavedSpeakerName() || "Sneha";
        aiDescriptionInput.focus();
    });
}

if (tabTextModeBtn && tabReceiptModeBtn) {
    tabTextModeBtn.addEventListener('click', switchToAiTextSubtab);
    tabReceiptModeBtn.addEventListener('click', switchToAiReceiptSubtab);
}

function formatFileSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function handleReceiptFile(file) {
    if (!file) return;

    const validTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp'];
    if (!validTypes.includes(file.type.toLowerCase())) {
        showAlert('Unsupported format. Please upload a JPG, JPEG, or PNG receipt photo.');
        return;
    }

    const maxSize = 10 * 1024 * 1024;
    if (file.size > maxSize) {
        showAlert('The receipt image exceeds 10 MB. Please upload a smaller photo.');
        return;
    }

    currentReceiptFile = file;

    const reader = new FileReader();
    reader.onload = (e) => {
        receiptPreviewImg.src = e.target.result;
        receiptFileName.textContent = file.name;
        receiptFileSize.textContent = formatFileSize(file.size);

        dropzonePrompt.classList.add('hidden');
        receiptPreviewBox.classList.remove('hidden');
        scanReceiptBtn.disabled = false;
        hideAlert();
        showToast('Receipt photo ready for scanning', 'info');
    };
    reader.readAsDataURL(file);
}

if (browseReceiptBtn && receiptFileInput) {
    browseReceiptBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        receiptFileInput.click();
    });
}

if (receiptDropzone && receiptFileInput) {
    receiptDropzone.addEventListener('click', () => {
        if (!currentReceiptFile) receiptFileInput.click();
    });

    receiptFileInput.addEventListener('change', (e) => {
        if (e.target.files && e.target.files[0]) {
            handleReceiptFile(e.target.files[0]);
        }
    });

    receiptDropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        receiptDropzone.classList.add('drag-over');
    });

    receiptDropzone.addEventListener('dragleave', () => {
        receiptDropzone.classList.remove('drag-over');
    });

    receiptDropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        receiptDropzone.classList.remove('drag-over');
        if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]) {
            handleReceiptFile(e.dataTransfer.files[0]);
        }
    });
}

if (replaceReceiptBtn && receiptFileInput) {
    replaceReceiptBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        receiptFileInput.value = '';
        receiptFileInput.click();
    });
}

if (removeReceiptBtn && receiptFileInput) {
    removeReceiptBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        currentReceiptFile = null;
        receiptFileInput.value = '';
        receiptPreviewImg.src = '';
        receiptPreviewBox.classList.add('hidden');
        dropzonePrompt.classList.remove('hidden');
        scanReceiptBtn.disabled = true;
    });
}

// AI Timer Utility
let timerInterval = null;
let timerStartMs = 0;

function startAiTimer(statusText) {
    if (aiLoadingStatusText) aiLoadingStatusText.textContent = statusText;
    if (aiTimerBadge) aiTimerBadge.textContent = '0.0s';
    if (aiLoadingIndicator) aiLoadingIndicator.classList.remove('hidden');

    timerStartMs = Date.now();
    timerInterval = setInterval(() => {
        const elapsedSec = ((Date.now() - timerStartMs) / 1000).toFixed(1);
        if (aiTimerBadge) aiTimerBadge.textContent = `${elapsedSec}s`;
    }, 100);
}

function stopAiTimer() {
    if (timerInterval) clearInterval(timerInterval);
    if (aiLoadingIndicator) aiLoadingIndicator.classList.add('hidden');
}

// Text Interpretation Button
if (aiInterpretBtn) {
    aiInterpretBtn.addEventListener('click', async () => {
        const description = aiDescriptionInput.value.trim();
        const speaker = aiSpeakerInput.value.trim() || getSavedSpeakerName();

        if (!description) {
            showAlert('Please enter a description of your meal.');
            aiDescriptionInput.focus();
            return;
        }

        isAiInterpreting = true;
        aiInterpretBtn.disabled = true;
        startAiTimer('Interpreting description with Gemini AI...');

        try {
            const response = await fetch('/api/ai/parse-bill', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    description: description,
                    speaker_name: speaker
                })
            });

            const data = await response.json();
            stopAiTimer();

            if (!response.ok || !data.success) {
                showAlert(data.error || 'Failed to interpret bill description.');
                return;
            }

            renderAiReview(data);
            showToast('Bill interpreted! Review and confirm your split.', 'success');

        } catch (err) {
            stopAiTimer();
            console.error('AI Interpretation error:', err);
            showAlert('Network error: Could not reach the server.');
        } finally {
            isAiInterpreting = false;
            aiInterpretBtn.disabled = false;
        }
    });
}

if (aiClearPromptBtn) {
    aiClearPromptBtn.addEventListener('click', () => {
        aiDescriptionInput.value = '';
        aiDescriptionInput.focus();
    });
}

// Receipt Scanning Button
if (scanReceiptBtn) {
    scanReceiptBtn.addEventListener('click', async () => {
        if (!currentReceiptFile) {
            showAlert('Please upload or select a receipt photo first.');
            return;
        }

        isScanningReceipt = true;
        scanReceiptBtn.disabled = true;
        startAiTimer('Scanning receipt with Gemini Vision...');

        const formData = new FormData();
        formData.append('receipt', currentReceiptFile);

        const rawMembers = aiReceiptMembersInput.value.trim();
        if (rawMembers) {
            formData.append('members', rawMembers);
        }

        try {
            const response = await fetch('/api/ai/scan-receipt', {
                method: 'POST',
                body: formData
            });

            const data = await response.json();
            stopAiTimer();

            if (!response.ok || !data.success) {
                showAlert(data.error || 'Failed to scan receipt image.');
                return;
            }

            renderAiReview(data);
            showToast('Receipt scanned successfully! Assign participants below.', 'success');

        } catch (err) {
            stopAiTimer();
            console.error('Receipt Scan error:', err);
            showAlert('Network error: Could not process receipt photo.');
        } finally {
            isScanningReceipt = false;
            scanReceiptBtn.disabled = false;
        }
    });
}

// Render AI Review Section
function renderAiReview(data) {
    aiState.members = Array.isArray(data.members) ? [...data.members] : [];
    aiState.restaurantName = data.restaurant_name || '';

    aiState.items = (data.items || []).map((it, idx) => {
        const qty = parseInt(it.quantity) || 1;
        const lineTotal = parseFloat(it.price) || 0;
        const unitPrice = it.unit_price ? parseFloat(it.unit_price) : (qty > 0 ? lineTotal / qty : lineTotal);
        return {
            id: idx + 1,
            name: it.name || `Item #${idx + 1}`,
            quantity: qty,
            unitPrice: Math.round(unitPrice * 100) / 100,
            price: Math.round(lineTotal * 100) / 100,
            has_missing_price: Boolean(it.has_missing_price),
            shared_by: Array.isArray(it.shared_by) ? [...it.shared_by] : []
        };
    });

    aiState.nextItemId = aiState.items.length + 1;
    aiState.tax = parseFloat(data.tax_percentage) || 0.0;
    aiState.tip = parseFloat(data.tip_percentage) || 0.0;

    // Restaurant Banner
    if (aiRestaurantBanner) {
        if (aiState.restaurantName) {
            aiRestaurantName.textContent = aiState.restaurantName;
            aiRestaurantBanner.classList.remove('hidden');
        } else {
            aiRestaurantBanner.classList.add('hidden');
        }
    }

    // Clarifications
    if (aiClarificationBox && aiClarificationList) {
        if (data.needs_clarification && Array.isArray(data.clarifications) && data.clarifications.length > 0) {
            aiClarificationList.innerHTML = data.clarifications
                .map(c => `<li>${escapeHtml(c)}</li>`)
                .join('');
            aiClarificationBox.classList.remove('hidden');
        } else {
            aiClarificationBox.classList.add('hidden');
        }
    }

    if (aiTaxInput) aiTaxInput.value = aiState.tax > 0 ? aiState.tax : '0';
    if (aiTipInput) aiTipInput.value = aiState.tip > 0 ? aiState.tip : '0';

    renderAiMembers();
    renderAiItems();
    updateAiSubtotal();

    aiReviewSection.classList.remove('hidden');
    aiReviewSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderAiMembers() {
    aiMembersList.innerHTML = '';
    aiMembersCount.textContent = aiState.members.length;

    aiState.members.forEach(member => {
        const chip = document.createElement('div');
        chip.className = 'member-chip';
        chip.innerHTML = `
            <span>${escapeHtml(member)}</span>
            <button type="button" class="remove-chip-btn">&times;</button>
        `;

        chip.querySelector('.remove-chip-btn').addEventListener('click', () => {
            aiState.members = aiState.members.filter(m => m !== member);
            aiState.items.forEach(it => {
                it.shared_by = it.shared_by.filter(m => m !== member);
            });
            renderAiMembers();
            renderAiItems();
        });

        aiMembersList.appendChild(chip);
    });
}

if (aiAddMemberForm) {
    aiAddMemberForm.addEventListener('submit', (e) => {
        e.preventDefault();
        const name = aiAddMemberInput.value.trim();
        if (!name) return;

        if (aiState.members.some(m => m.toLowerCase() === name.toLowerCase())) {
            showAlert(`"${name}" is already in the list.`);
            return;
        }

        aiState.members.push(name);
        aiAddMemberInput.value = '';
        renderAiMembers();
        renderAiItems();
    });
}

function renderAiItems() {
    aiItemsContainer.innerHTML = '';

    if (aiState.items.length === 0) {
        aiItemsContainer.innerHTML = '<p class="empty-state-text">No items in this bill.</p>';
        return;
    }

    aiState.items.forEach(item => {
        const card = document.createElement('div');
        card.className = 'ai-item-card';

        const memberPillsHtml = aiState.members.map(member => {
            const isAssigned = item.shared_by.includes(member);
            const activeClass = isAssigned ? 'active' : '';
            return `
                <button type="button" class="ai-member-pill ${activeClass}" data-member="${escapeHtml(member)}">
                    ${isAssigned ? '✓ ' : ''}${escapeHtml(member)}
                </button>
            `;
        }).join('');

        card.innerHTML = `
            <div class="ai-item-row">
                <input type="text" class="ai-item-name-input" value="${escapeHtml(item.name)}" placeholder="Dish name">
                
                <div class="ai-item-qty-wrap">
                    <span class="qty-label">Qty</span>
                    <input type="number" class="ai-item-qty-input" value="${item.quantity || 1}" min="1" step="1">
                </div>

                <div class="ai-item-price-wrap">
                    <span class="price-label">₹</span>
                    <input type="number" class="ai-item-price-input" value="${item.price || ''}" placeholder="0.00" step="0.01" min="0">
                </div>

                <button type="button" class="item-delete-btn" aria-label="Delete item">
                    <i data-lucide="trash-2"></i>
                </button>
            </div>

            <div class="ai-item-members-row">
                ${memberPillsHtml || '<span class="empty-state-text">Add group members above to assign this item.</span>'}
            </div>
        `;

        // Input listeners
        const nameInput = card.querySelector('.ai-item-name-input');
        const qtyInput = card.querySelector('.ai-item-qty-input');
        const priceInput = card.querySelector('.ai-item-price-input');

        nameInput.addEventListener('change', () => {
            item.name = nameInput.value.trim();
        });

        qtyInput.addEventListener('input', () => {
            const newQty = parseInt(qtyInput.value) || 1;
            item.quantity = Math.max(1, newQty);
            if (item.unitPrice > 0) {
                item.price = Math.round(item.unitPrice * item.quantity * 100) / 100;
                priceInput.value = item.price.toFixed(2);
            }
            updateAiSubtotal();
        });

        priceInput.addEventListener('input', () => {
            const val = parseFloat(priceInput.value) || 0;
            item.price = val;
            if (item.quantity > 0) {
                item.unitPrice = Math.round((val / item.quantity) * 100) / 100;
            }
            item.has_missing_price = val <= 0;
            updateAiSubtotal();
        });

        // Delete button
        card.querySelector('.item-delete-btn').addEventListener('click', () => {
            aiState.items = aiState.items.filter(i => i.id !== item.id);
            renderAiItems();
            updateAiSubtotal();
        });

        // Member Pills click
        card.querySelectorAll('.ai-member-pill').forEach(pill => {
            pill.addEventListener('click', () => {
                const mem = pill.dataset.member;
                if (item.shared_by.includes(mem)) {
                    item.shared_by = item.shared_by.filter(m => m !== mem);
                } else {
                    item.shared_by.push(mem);
                }
                renderAiItems();
            });
        });

        aiItemsContainer.appendChild(card);
    });

    refreshIcons();
}

function updateAiSubtotal() {
    const sub = aiState.items.reduce((acc, it) => acc + (parseFloat(it.price) || 0), 0);
    aiItemsSubtotal.textContent = formatINR(sub);
}

if (aiAddNewItemBtn) {
    aiAddNewItemBtn.addEventListener('click', () => {
        aiState.items.push({
            id: aiState.nextItemId++,
            name: 'New Item',
            quantity: 1,
            unitPrice: 0.0,
            price: 0.0,
            has_missing_price: true,
            shared_by: [...aiState.members]
        });
        renderAiItems();
        updateAiSubtotal();
    });
}

// AI Tip Chips
aiTipChips.forEach(chip => {
    chip.addEventListener('click', () => {
        aiTipChips.forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
        aiTipInput.value = chip.dataset.tip;
    });
});

if (aiConfirmCalculateBtn) {
    aiConfirmCalculateBtn.addEventListener('click', async () => {
        if (aiState.members.length === 0) {
            showAlert('Please add at least one member to your bill.');
            return;
        }

        if (aiState.items.length === 0) {
            showAlert('Please add at least one food or drink item.');
            return;
        }

        for (const item of aiState.items) {
            if (!item.price || item.price <= 0) {
                showAlert(`Please enter a valid price for "${item.name}".`);
                return;
            }
            if (!item.shared_by || item.shared_by.length === 0) {
                showAlert(`Please assign at least one member to "${item.name}".`);
                return;
            }
        }

        const taxVal = parseFloat(aiTaxInput.value) || 0.0;
        const tipVal = parseFloat(aiTipInput.value) || 0.0;

        const payload = {
            members: aiState.members,
            items: aiState.items.map(it => ({
                name: it.quantity > 1 ? `${it.name} (x${it.quantity})` : it.name,
                price: it.price,
                shared_by: it.shared_by
            })),
            tax_percentage: taxVal,
            tip_percentage: tipVal
        };

        const sessionTitle = aiState.restaurantName || 'AI Extracted Bill Split';
        await executeCalculation(payload, aiConfirmCalculateBtn, 'Confirm & Calculate Split ⚡', sessionTitle);
    });
}

if (aiCopyToManualBtn) {
    aiCopyToManualBtn.addEventListener('click', () => {
        state.members = [...aiState.members];
        state.items = aiState.items.map(it => ({
            id: state.nextItemId++,
            name: it.quantity > 1 ? `${it.name} (x${it.quantity})` : it.name,
            price: it.price,
            sharedBy: [...it.shared_by]
        }));
        taxInput.value = aiTaxInput.value;
        tipInput.value = aiTipInput.value;

        renderMembers();
        renderShareCheckboxes();
        renderItems();

        switchMode('manual');
        showToast('Extracted bill copied to Manual Mode', 'success');
    });
}

if (aiResetBtn) {
    aiResetBtn.addEventListener('click', () => {
        aiState.members = [];
        aiState.items = [];
        aiState.restaurantName = '';
        aiReviewSection.classList.add('hidden');
        if (aiClarificationBox) aiClarificationBox.classList.add('hidden');
        if (aiRestaurantBanner) aiRestaurantBanner.classList.add('hidden');
        showToast('AI bill review cleared', 'info');
    });
}

// ==========================================
// 10. Core Calculation Engine Integration
// ==========================================

async function executeCalculation(payload, buttonElement, originalButtonText, sessionTitle = 'Restaurant Split') {
    isCalculating = true;
    buttonElement.disabled = true;
    buttonElement.textContent = 'Calculating Exact Split...';

    let response;
    let data;

    try {
        response = await fetch('/api/calculate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        data = await response.json();
    } catch (networkErr) {
        console.error('Calculation network error:', networkErr);
        showAlert('Network error: Could not reach the calculation engine. Please make sure the Flask server is running on http://127.0.0.1:5001.');
        isCalculating = false;
        buttonElement.disabled = false;
        buttonElement.textContent = originalButtonText;
        return;
    }

    try {
        if (!response.ok || !data.success) {
            showAlert(data.error || 'Failed to calculate bill split.');
            return;
        }

        // Build Persistent Bill Record
        const newBillRecord = {
            id: data.bill_id || ('bill_' + Date.now()),
            bill_id: data.bill_id,
            title: data.title || sessionTitle,
            date: new Date().toISOString(),
            displayDate: new Date().toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }),
            members: payload.members,
            items: payload.items,
            summary: data.summary,
            breakdown: data.breakdown,
            settlement: {} // memberName -> 'pending' | 'paid'
        };

        // Populate settlement status from server or default to pending
        payload.members.forEach(m => {
            if (data.settlement && data.settlement.members) {
                if (Array.isArray(data.settlement.members)) {
                    const match = data.settlement.members.find(x => (x.member_name || '').toLowerCase() === m.toLowerCase());
                    newBillRecord.settlement[m] = match ? match.status : 'pending';
                } else if (data.settlement.members[m]) {
                    newBillRecord.settlement[m] = data.settlement.members[m].status;
                } else {
                    newBillRecord.settlement[m] = 'pending';
                }
            } else {
                newBillRecord.settlement[m] = 'pending';
            }
        });

        currentBillSession = saveBillRecord(newBillRecord);

        renderResults(data, currentBillSession);
        hideAlert();
        showToast('Split calculated down to the paise! Saved to history.', 'success');

    } catch (renderErr) {
        console.error('Calculation rendering error:', renderErr);
        showAlert('Error displaying results: ' + renderErr.message);
    } finally {
        isCalculating = false;
        buttonElement.disabled = false;
        buttonElement.textContent = originalButtonText;
    }
}

// ==========================================
// 11. Render Settlement Breakdown (Results)
// ==========================================

function renderResults(data, billRecord = null) {
    const { summary, breakdown } = data;
    const session = billRecord || currentBillSession;
    const billId = data.bill_id || session?.bill_id || session?.id || '';

    summarySubtotal.textContent = summary.subtotal_formatted || formatINR(summary.subtotal);
    summaryTax.textContent = summary.tax_formatted || formatINR(summary.tax);
    summaryTaxLabel.textContent = `Tax (${summary.tax_percentage}%)`;
    summaryTip.textContent = summary.tip_formatted || formatINR(summary.tip);
    summaryTipLabel.textContent = `Tip (${summary.tip_percentage}%)`;
    summaryGrandTotal.textContent = summary.grand_total_formatted || formatINR(summary.grand_total);

    updatePayPalDisclosureBanner(paypalConfig);

    breakdownCardsContainer.innerHTML = '';

    const pendingPaypalButtonsToMount = [];

    for (const [memberName, info] of Object.entries(breakdown)) {
        const card = document.createElement('div');
        card.className = 'member-breakdown-card';

        let itemsHtml = '';
        if (!info.items || info.items.length === 0) {
            itemsHtml = '<li class="member-item-entry"><em>No items ordered</em></li>';
        } else {
            itemsHtml = info.items.map(it => {
                const fullPriceStr = it.full_price_formatted || formatINR(it.full_price);
                const shareStr = it.individual_share_formatted || formatINR(it.individual_share);
                const splitNote = it.split_between > 1 ? `(1/${it.split_between} of ${fullPriceStr})` : '';
                return `
                    <li class="member-item-entry">
                        <span>${escapeHtml(it.name)} <span class="sub-desc">${splitNote}</span></span>
                        <span>${shareStr}</span>
                    </li>
                `;
            }).join('');
        }

        const isPaid = session && session.settlement && session.settlement[memberName] === 'paid';
        const paymentMethod = isPaid ? ((session.payment_methods && session.payment_methods[memberName]) || 
                                       (session.paypal_orders && session.paypal_orders[memberName] ? 'paypal' : 'offline')) : null;
        const sanitizedMemberId = memberName.replace(/[^a-zA-Z0-9_-]/g, '_');
        const shareAmountInr = Number(info.total || 0);
        const rate = Number(paypalConfig.inr_to_usd_rate || 0.012);
        const shareAmountUsd = (shareAmountInr * rate).toFixed(2);

        let paymentSectionHtml = '';
        if (isPaid) {
            if (paymentMethod === 'paypal') {
                paymentSectionHtml = `
                    <div class="payment-settled-box paypal-settled">
                        <div class="settled-badge">
                            <i data-lucide="check-circle-2"></i>
                            <span>Paid via PayPal Sandbox ✓</span>
                        </div>
                        <div class="settled-meta">
                            <span>Captured: <strong>${info.total_formatted || formatINR(info.total)}</strong> (≈ $${shareAmountUsd} USD)</span>
                        </div>
                    </div>
                `;
            } else {
                paymentSectionHtml = `
                    <div class="payment-settled-box offline-settled">
                        <div class="settled-badge">
                            <i data-lucide="check-circle-2"></i>
                            <span>Paid via Cash / Offline ✓</span>
                        </div>
                        <div class="settled-meta">
                            <span>Recorded: <strong>${info.total_formatted || formatINR(info.total)}</strong> (Cash / UPI / Transfer)</span>
                        </div>
                        <button type="button" class="btn-revert-offline" data-member="${escapeHtml(memberName)}">
                            <i data-lucide="rotate-ccw"></i>
                            <span>Accidental? Revert to Pending</span>
                        </button>
                    </div>
                `;
            }
        } else {
            // Member is Pending: Offer TWO distinct payment options
            paymentSectionHtml = `
                <div class="member-payment-options">
                    <!-- Option 1: Pay with PayPal -->
                    <div class="payment-method-box paypal-method-box">
                        <div class="payment-method-header">
                            <span class="method-tag"><i data-lucide="credit-card"></i> Option 1: PayPal Checkout</span>
                            <span class="method-amount-usd">≈ $${shareAmountUsd} USD</span>
                        </div>
                        <div id="paypal-btn-${sanitizedMemberId}" class="paypal-btn-slot"></div>
                        <div class="paypal-slot-fallback ${paypalConfig.is_enabled ? 'hidden' : ''}" id="fallback-${sanitizedMemberId}">
                            <span class="paypal-inactive-note">PayPal checkout requires active credentials</span>
                        </div>
                    </div>

                    <div class="payment-options-divider">
                        <span>OR</span>
                    </div>

                    <!-- Option 2: Mark as Paid (Cash / Offline) -->
                    <div class="payment-method-box offline-method-box">
                        <div class="payment-method-header">
                            <span class="method-tag"><i data-lucide="banknote"></i> Option 2: Cash / Offline</span>
                            <span class="method-amount-inr">${info.total_formatted || formatINR(info.total)}</span>
                        </div>
                        <button type="button" class="btn-offline-settle" data-member="${escapeHtml(memberName)}">
                            <i data-lucide="check"></i>
                            <span>Mark as Paid (Cash / UPI)</span>
                        </button>
                    </div>
                </div>
            `;

            if (paypalConfig.is_enabled) {
                pendingPaypalButtonsToMount.push({
                    slotId: `paypal-btn-${sanitizedMemberId}`,
                    fallbackId: `fallback-${sanitizedMemberId}`,
                    memberName,
                    billId,
                    amountInr: shareAmountInr,
                    amountUsd: shareAmountUsd
                });
            }
        }

        card.innerHTML = `
            <div class="member-card-header">
                <div class="member-name-wrap">
                    <div class="member-avatar-chip">${escapeHtml(memberName.charAt(0).toUpperCase())}</div>
                    <span class="member-name">${escapeHtml(memberName)}</span>
                </div>
                <span class="member-total">${info.total_formatted || formatINR(info.total)}</span>
            </div>
            <div class="member-card-details">
                <span>Subtotal: <strong>${info.subtotal_formatted || formatINR(info.subtotal)}</strong></span>
                <span>•</span>
                <span>Tax: <strong>${info.tax_formatted || formatINR(info.tax)}</strong></span>
                <span>•</span>
                <span>Tip: <strong>${info.tip_formatted || formatINR(info.tip)}</strong></span>
            </div>
            <ul class="member-item-list">
                ${itemsHtml}
            </ul>
            ${paymentSectionHtml}
        `;

        // Wire Option 2: Mark as Paid (Cash / Offline) with Confirmation
        const offlineSettleBtn = card.querySelector('.btn-offline-settle');
        if (offlineSettleBtn) {
            offlineSettleBtn.addEventListener('click', async (e) => {
                e.stopPropagation();
                const formattedAmount = info.total_formatted || formatINR(info.total);
                const confirmed = window.confirm(
                    `Mark ${memberName} as Paid?\n\nAmount: ${formattedAmount}\nPayment Method: Cash / Offline / UPI\n\nThis will record an offline settlement without initiating a PayPal transaction.`
                );
                if (!confirmed) return;

                offlineSettleBtn.disabled = true;
                offlineSettleBtn.innerHTML = '<span>Recording offline payment...</span>';

                try {
                    if (billId) {
                        const response = await fetch(`/api/bills/${encodeURIComponent(billId)}/settle-offline`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ member_name: memberName })
                        });
                        const resData = await response.json();
                        if (!response.ok || !resData.success) {
                            console.warn('Server offline settle warning:', resData.error);
                        }
                    }
                } catch (err) {
                    console.warn('Network offline settle fallback to local storage:', err);
                }

                if (session) {
                    session.settlement = session.settlement || {};
                    session.settlement[memberName] = 'paid';
                    session.payment_methods = session.payment_methods || {};
                    session.payment_methods[memberName] = 'offline';
                    saveBillRecord(session);
                }

                renderResults(data, session);
                updateDashboardStats();
                renderRecentBills();
                renderFullHistory(currentFilter);
                showToast(`✓ ${memberName} marked as paid via Cash/Offline (${formattedAmount})`, 'success');
            });
        }

        // Wire Accidental Revert for Offline Payments
        const revertBtn = card.querySelector('.btn-revert-offline');
        if (revertBtn) {
            revertBtn.addEventListener('click', async (e) => {
                e.stopPropagation();
                const confirmed = window.confirm(
                    `Revert ${memberName}'s offline payment record back to Pending?\n\nThis will restore both PayPal and Offline payment options for ${memberName}.`
                );
                if (!confirmed) return;

                revertBtn.disabled = true;
                revertBtn.textContent = 'Reverting...';

                try {
                    if (billId) {
                        const response = await fetch(`/api/bills/${encodeURIComponent(billId)}/revert-offline`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ member_name: memberName })
                        });
                        const resData = await response.json();
                        if (!response.ok || !resData.success) {
                            showAlert(resData.error || 'Failed to revert offline payment on server.');
                            return;
                        }
                    }
                } catch (err) {
                    console.warn('Network offline revert fallback:', err);
                }

                if (session) {
                    session.settlement = session.settlement || {};
                    session.settlement[memberName] = 'pending';
                    if (session.payment_methods) {
                        delete session.payment_methods[memberName];
                    }
                    saveBillRecord(session);
                }

                renderResults(data, session);
                updateDashboardStats();
                renderRecentBills();
                renderFullHistory(currentFilter);
                showToast(`${memberName} reverted to Pending`, 'info');
            });
        }

        breakdownCardsContainer.appendChild(card);
    }

    // Update Settlement Progress Bar and Financial Metrics
    updateSettlementProgressBar(session, breakdown);

    resultsPlaceholder.classList.add('hidden');
    resultsContent.classList.remove('hidden');

    refreshIcons();

    // Mount individual PayPal buttons for each pending member
    pendingPaypalButtonsToMount.forEach(btnInfo => {
        mountMemberPayPalButton(btnInfo, session, data);
    });

    if (window.innerWidth <= 900) {
        resultsContent.scrollIntoView({ behavior: 'smooth' });
    }
}

async function mountMemberPayPalButton(btnInfo, session, billData) {
    const { slotId, fallbackId, memberName, billId, amountUsd } = btnInfo;
    const slot = document.getElementById(slotId);
    const fallback = document.getElementById(fallbackId);
    if (!slot) return;

    if (!paypalConfig.is_enabled || !paypalConfig.client_id) {
        if (fallback) fallback.classList.remove('hidden');
        return;
    }

    try {
        await loadPayPalSDK(paypalConfig.client_id, paypalConfig.currency);
    } catch (err) {
        console.warn('PayPal SDK not ready, revealing manual fallback:', err);
        if (fallback) fallback.classList.remove('hidden');
        return;
    }

    if (!window.paypal || typeof window.paypal.Buttons !== 'function') {
        if (fallback) fallback.classList.remove('hidden');
        return;
    }

    slot.innerHTML = '';

    try {
        window.paypal.Buttons({
            style: {
                layout: 'horizontal',
                color: 'gold',
                shape: 'rect',
                label: 'paypal',
                height: 38,
                tagline: false
            },
            createOrder: async () => {
                try {
                    const response = await fetch('/api/paypal/create-order', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            bill_id: billId,
                            member_name: memberName
                        })
                    });

                    const resData = await response.json();
                    if (!response.ok || !resData.success) {
                        const errMsg = resData.error || 'Failed to initialize PayPal order.';
                        showAlert(errMsg);
                        throw new Error(errMsg);
                    }
                    return resData.orderID;
                } catch (e) {
                    console.error('Order creation error:', e);
                    showAlert(e.message || 'Error creating PayPal checkout.');
                    throw e;
                }
            },
            onApprove: async (orderData) => {
                showToast(`Verifying capture with PayPal for ${memberName}...`, 'info');
                try {
                    const response = await fetch('/api/paypal/capture-order', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            order_id: orderData.orderID,
                            bill_id: billId,
                            member_name: memberName
                        })
                    });

                    const captureData = await response.json();
                    if (!response.ok || !captureData.success) {
                        const errMsg = captureData.error || 'Payment capture could not be verified.';
                        showAlert(errMsg);
                        return;
                    }

                    showToast(`✓ Payment received for ${memberName} via PayPal!`, 'success');

                    // Update session for this individual member ONLY
                    if (session) {
                        session.settlement = session.settlement || {};
                        session.settlement[memberName] = 'paid';
                        session.payment_methods = session.payment_methods || {};
                        session.payment_methods[memberName] = 'paypal';
                        saveBillRecord(session);
                    }

                    renderResults(billData, session);
                    updateDashboardStats();
                    renderRecentBills();
                    renderFullHistory(currentFilter);

                } catch (err) {
                    console.error('Payment capture error:', err);
                    showAlert('Failed to finalize PayPal capture. Please check network.');
                }
            },
            onCancel: () => {
                showToast(`PayPal checkout cancelled for ${memberName}`, 'info');
            },
            onError: (err) => {
                console.error('PayPal button runtime error:', err);
                showToast(`PayPal checkout error for ${memberName}`, 'error');
            }
        }).render('#' + slotId);
    } catch (err) {
        console.warn(`Could not render PayPal button for ${memberName}:`, err);
        if (fallback) fallback.classList.remove('hidden');
    }
}

function updateSettlementProgressBar(session, breakdown) {
    if (!settlementProgressBar || !settlementProgressRatio) return;

    const members = Object.keys(breakdown);
    const totalMembers = members.length;
    if (totalMembers === 0) return;

    let settledCount = 0;
    let collectedAmount = 0;
    let paypalCollected = 0;
    let offlineCollected = 0;
    let totalAmount = 0;

    members.forEach(m => {
        const share = Number(breakdown[m]?.total || 0);
        totalAmount += share;
        if (session && session.settlement && session.settlement[m] === 'paid') {
            settledCount++;
            collectedAmount += share;
            const method = (session.payment_methods && session.payment_methods[m]) || 
                           (session.paypal_orders && session.paypal_orders[m] ? 'paypal' : 'offline');
            if (method === 'paypal') {
                paypalCollected += share;
            } else {
                offlineCollected += share;
            }
        }
    });

    const outstandingAmount = Math.max(0, totalAmount - collectedAmount);
    const pct = Math.round((settledCount / totalMembers) * 100);

    settlementProgressBar.style.width = `${pct}%`;
    settlementProgressRatio.textContent = `${settledCount} of ${totalMembers} Settled (${pct}%)`;

    const collectedEl = document.getElementById('settlementCollectedAmount');
    const outstandingEl = document.getElementById('settlementOutstandingAmount');
    const paypalEl = document.getElementById('settlementPaypalCollected');
    const offlineEl = document.getElementById('settlementOfflineCollected');

    if (collectedEl) collectedEl.textContent = formatINR(collectedAmount);
    if (outstandingEl) outstandingEl.textContent = formatINR(outstandingAmount);
    if (paypalEl) paypalEl.textContent = formatINR(paypalCollected);
    if (offlineEl) offlineEl.textContent = formatINR(offlineCollected);
}

// Copy Summary
if (copySplitSummaryBtn) {
    copySplitSummaryBtn.addEventListener('click', () => {
        if (!currentBillSession) {
            showAlert('No split available to copy.');
            return;
        }

        const b = currentBillSession;
        let text = `🧾 *FairSplit AI Summary: ${b.title}*\n`;
        text += `Grand Total: ${b.summary.grand_total_formatted || formatINR(b.summary.grand_total)}\n\n`;
        text += `*Individual Shares:*\n`;

        Object.entries(b.breakdown).forEach(([name, info]) => {
            const status = b.settlement[name] === 'paid' ? ' [PAID ✓]' : ' [PENDING]';
            text += `• ${name}: ${info.total_formatted || formatINR(info.total)}${status}\n`;
        });

        text += `\n_Calculated with zero-rounding paise precision by FairSplit AI_`;

        navigator.clipboard.writeText(text).then(() => {
            showToast('Summary copied to clipboard!', 'success');
        }).catch(() => {
            showToast('Failed to copy. Please copy manually.', 'error');
        });
    });
}

if (saveSplitToHistoryBtn) {
    saveSplitToHistoryBtn.addEventListener('click', () => {
        showToast('Split is saved in My Bills / History!', 'info');
    });
}

// ==========================================
// 12. Full History View & Filtering
// ==========================================

function renderFullHistory(filter = 'all') {
    if (!fullHistoryContainer) return;
    currentFilter = filter;

    const bills = getBillsHistory();
    let filtered = bills;

    if (filter === 'pending') {
        filtered = bills.filter(b => b.settlement && Object.values(b.settlement).includes('pending'));
    } else if (filter === 'settled') {
        filtered = bills.filter(b => b.settlement && Object.values(b.settlement).length > 0 && Object.values(b.settlement).every(s => s === 'paid'));
    }

    if (historyFilteredCount) {
        historyFilteredCount.textContent = `Showing ${filtered.length} ${filtered.length === 1 ? 'bill' : 'bills'}`;
    }

    if (filtered.length === 0) {
        fullHistoryContainer.innerHTML = `
            <div class="empty-state-box">
                <div class="empty-icon-circle">
                    <i data-lucide="receipt"></i>
                </div>
                <h4 class="empty-title">No bills found</h4>
                <p class="empty-desc">There are no bills matching your current filter.</p>
            </div>
        `;
        refreshIcons();
        return;
    }

    fullHistoryContainer.innerHTML = filtered.map(bill => {
        const title = bill.title || 'Restaurant Dining Bill';
        const dateStr = bill.displayDate || 'Date unavailable';
        const grandTotalStr = bill.summary?.grand_total_formatted || formatINR(bill.summary?.grand_total || 0);

        const memberSharesHtml = Object.entries(bill.breakdown || {}).map(([member, info]) => {
            const isPaid = bill.settlement && bill.settlement[member] === 'paid';
            const method = isPaid ? ((bill.payment_methods && bill.payment_methods[member]) || 
                                     (bill.paypal_orders && bill.paypal_orders[member] ? 'paypal' : 'offline')) : null;
            const statusClass = isPaid ? 'bill-status-settled' : 'bill-status-pending';
            const statusLabel = isPaid ? (method === 'paypal' ? 'Paid (PayPal) ✓' : 'Paid (Offline) ✓') : 'Pending';

            return `
                <div class="history-member-item">
                    <span><strong>${escapeHtml(member)}</strong></span>
                    <div style="display:flex; align-items:center; gap:0.5rem;">
                        <span>${info.total_formatted || formatINR(info.total)}</span>
                        <span class="bill-status-pill ${statusClass}">${statusLabel}</span>
                    </div>
                </div>
            `;
        }).join('');

        return `
            <div class="history-bill-card" data-bill-id="${bill.id}">
                <div class="history-card-header">
                    <div class="bill-row-left">
                        <div class="bill-row-icon">
                            <i data-lucide="receipt-text"></i>
                        </div>
                        <div class="bill-row-info">
                            <h4>${escapeHtml(title)}</h4>
                            <div class="bill-row-meta">
                                <span>${escapeHtml(dateStr)}</span>
                                <span class="meta-dot">•</span>
                                <span>${bill.members?.length || 0} participants</span>
                            </div>
                        </div>
                    </div>
                    <div class="bill-row-right">
                        <div class="bill-row-amount">
                            <div class="bill-total-price">${grandTotalStr}</div>
                        </div>
                        <i data-lucide="chevron-down" class="expand-icon"></i>
                    </div>
                </div>

                <div class="history-card-body hidden">
                    <p style="font-size:0.82rem; color:var(--muted-grey); margin-bottom:0.6rem;">Member Shares Breakdown:</p>
                    <div class="history-details-grid">
                        ${memberSharesHtml}
                    </div>
                    <div class="history-actions-row">
                        <button type="button" class="btn btn-outline btn-sm delete-bill-btn" data-bill-id="${bill.id}">
                            <i data-lucide="trash-2"></i> Delete
                        </button>
                        <button type="button" class="btn btn-emerald-primary btn-sm load-bill-btn" data-bill-id="${bill.id}">
                            <i data-lucide="external-link"></i> View Full Breakdown
                        </button>
                    </div>
                </div>
            </div>
        `;
    }).join('');

    // Accordion toggle & buttons
    fullHistoryContainer.querySelectorAll('.history-bill-card').forEach(card => {
        const header = card.querySelector('.history-card-header');
        const body = card.querySelector('.history-card-body');

        header.addEventListener('click', () => {
            body.classList.toggle('hidden');
        });

        const deleteBtn = card.querySelector('.delete-bill-btn');
        if (deleteBtn) {
            deleteBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                if (confirm('Are you sure you want to delete this bill from history?')) {
                    deleteBillRecord(card.dataset.billId);
                }
            });
        }

        const loadBtn = card.querySelector('.load-bill-btn');
        if (loadBtn) {
            loadBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                loadBillIntoView(card.dataset.billId);
            });
        }
    });

    refreshIcons();
}

// History Filter Pills Click Handlers
historyFilterPills.forEach(pill => {
    pill.addEventListener('click', () => {
        historyFilterPills.forEach(p => p.classList.remove('active'));
        pill.classList.add('active');
        renderFullHistory(pill.dataset.filter);
    });
});

// ==========================================
// 13. Settings & Personalization
// ==========================================

function getSavedSpeakerName() {
    return localStorage.getItem(STORAGE_USER_KEY) || '';
}

function loadSettingsView() {
    const saved = getSavedSpeakerName();
    if (settingsSpeakerInput) settingsSpeakerInput.value = saved;
    updateUserPill(saved);
    updatePayPalSettingsCard(paypalConfig);
}

function updateUserPill(name) {
    const clean = name ? name.trim() : '';
    if (sidebarUserName) {
        sidebarUserName.textContent = clean ? clean : 'Welcome';
    }
    if (sidebarUserAvatar) {
        sidebarUserAvatar.textContent = clean ? clean.charAt(0).toUpperCase() : 'S';
    }
    if (heroHeading) {
        heroHeading.textContent = clean ? `Welcome back, ${clean}!` : 'Welcome back!';
    }
    if (aiSpeakerInput && !aiSpeakerInput.value.trim() && clean) {
        aiSpeakerInput.value = clean;
    }
}

if (saveSpeakerSettingBtn && settingsSpeakerInput) {
    saveSpeakerSettingBtn.addEventListener('click', () => {
        const name = settingsSpeakerInput.value.trim();
        localStorage.setItem(STORAGE_USER_KEY, name);
        updateUserPill(name);
        showToast('Default speaker name saved!', 'success');
    });
}

if (clearAllHistoryBtn) {
    clearAllHistoryBtn.addEventListener('click', () => {
        if (confirm('Clear all local bill history and settlement statistics?')) {
            localStorage.removeItem(STORAGE_BILLS_KEY);
            updateHistoryBadge();
            updateDashboardStats();
            renderRecentBills();
            renderFullHistory();
            showToast('Local bill history cleared', 'info');
        }
    });
}

// Dynamic Time Greeting (Morning / Afternoon / Evening)
function setTimeGreeting() {
    if (!heroGreetingTime) return;
    const hour = new Date().getHours();
    if (hour < 12) heroGreetingTime.textContent = 'Good morning';
    else if (hour < 18) heroGreetingTime.textContent = 'Good afternoon';
    else heroGreetingTime.textContent = 'Good evening';
}

// ==========================================
// 14. Initial App Bootstrap
// ==========================================

document.addEventListener('DOMContentLoaded', () => {
    setTimeGreeting();
    const savedName = getSavedSpeakerName();
    updateUserPill(savedName);
    updateHistoryBadge();
    updateDashboardStats();
    renderRecentBills();

    renderMembers();
    renderShareCheckboxes();
    renderItems();

    // Initialize PayPal Sandbox Gateway configuration & SDK
    initPayPalConfig();

    refreshIcons();
});
