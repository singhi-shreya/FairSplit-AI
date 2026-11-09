/**
 * FairSplit AI - Frontend Application Logic
 * 
 * Manages:
 * - TWO INDEPENDENT WORKFLOWS:
 *   1. Mode 1: Manual Step-by-Step Entry (100% preserved)
 *   2. Mode 2: AI-Powered Bill Entry (One-sentence description -> review -> calculation)
 * - Group members management & sharing checkboxes
 * - Interactive review cards with clickable participant toggle badges
 * - Missing price validation & pronoun ("I") clarification
 * - Authoritative Python calculation engine (/api/calculate) with exact integer-paise math
 * - Live latency counter for fast Gemini API extraction
 */

// ==========================================
// 1. Application State
// ==========================================

// State for Mode 1 (Manual Entry)
const state = {
    members: [],
    items: [],
    nextItemId: 1,
    editingItemId: null
};

// State for Mode 2 (AI-Powered Entry)
const aiState = {
    members: [],
    items: [],
    nextItemId: 1,
    tax: 0.0,
    tip: 0.0
};

// Concurrency Guard to prevent duplicate submissions
let isCalculating = false;
let isAiInterpreting = false;

// ==========================================
// 2. DOM Elements
// ==========================================

// Mode Navigation Elements
const navManualModeBtn = document.getElementById('navManualModeBtn');
const navAiModeBtn = document.getElementById('navAiModeBtn');
const manualModeWorkflow = document.getElementById('manualModeWorkflow');
const aiModeWorkflow = document.getElementById('aiModeWorkflow');

// Notification Alert Box
const alertBox = document.getElementById('alertBox');

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

// AI Review Section Elements
const aiReviewSection = document.getElementById('aiReviewSection');
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

// Mode 2: AI Sub-Tabs and Panels
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

// Restaurant Banner
const aiRestaurantBanner = document.getElementById('aiRestaurantBanner');
const aiRestaurantName = document.getElementById('aiRestaurantName');

// State for receipt upload
let currentReceiptFile = null;
let isScanningReceipt = false;

// Sample Prompt Buttons
const samplePromptBtn1 = document.getElementById('samplePromptBtn1');
const samplePromptBtn2 = document.getElementById('samplePromptBtn2');
const samplePromptBtn3 = document.getElementById('samplePromptBtn3');

// Results & Breakdown Elements (Shared by both modes)
const resultsPlaceholder = document.getElementById('resultsPlaceholder');
const resultsContent = document.getElementById('resultsContent');
const summarySubtotal = document.getElementById('summarySubtotal');
const summaryTax = document.getElementById('summaryTax');
const summaryTaxLabel = document.getElementById('summaryTaxLabel');
const summaryTip = document.getElementById('summaryTip');
const summaryTipLabel = document.getElementById('summaryTipLabel');
const summaryGrandTotal = document.getElementById('summaryGrandTotal');
const breakdownCardsContainer = document.getElementById('breakdownCardsContainer');

// ==========================================
// 3. Formatting & Alert Helpers
// ==========================================

/**
 * Formats a numeric value into standard Indian Rupees (INR, ₹).
 * Example: 1430 -> "₹1,430.00"
 */
function formatINR(amount) {
    const num = Number(amount) || 0;
    return '₹' + num.toLocaleString('en-IN', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
}

let alertTimeout = null;

function showAlert(message, type = 'error') {
    if (alertTimeout) clearTimeout(alertTimeout);

    alertBox.textContent = message;
    alertBox.className = `alert alert-${type}`;
    alertBox.classList.remove('hidden');
    alertBox.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    alertTimeout = setTimeout(() => {
        alertBox.classList.add('hidden');
    }, 7000);
}

function hideAlert() {
    if (alertTimeout) clearTimeout(alertTimeout);
    alertBox.classList.add('hidden');
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

// ==========================================
// 4. Mode Switcher (Mode 1 Manual vs Mode 2 AI)
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
}

navManualModeBtn.addEventListener('click', () => switchMode('manual'));
navAiModeBtn.addEventListener('click', () => switchMode('ai'));

// ==========================================
// 5. MODE 1: MANUAL ENTRY WORKFLOW (100% PRESERVED)
// ==========================================

// Add Member
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
});

function removeMember(nameToRemove) {
    state.members = state.members.filter(m => m !== nameToRemove);

    // Remove member from any items' sharedBy list
    state.items.forEach(item => {
        item.sharedBy = item.sharedBy.filter(m => m !== nameToRemove);
    });

    renderMembers();
    renderShareCheckboxes();
    renderItems();
}

function renderMembers() {
    if (state.members.length === 0) {
        emptyMembersText.classList.remove('hidden');
        membersList.innerHTML = '';
        membersList.appendChild(emptyMembersText);
        return;
    }

    emptyMembersText.classList.add('hidden');
    membersList.innerHTML = '';

    state.members.forEach(name => {
        const chip = document.createElement('div');
        chip.className = 'member-chip chip';
        chip.innerHTML = `
            <span>${escapeHtml(name)}</span>
            <button type="button" class="chip-remove-btn chip-remove" aria-label="Remove ${escapeHtml(name)}">&times;</button>
        `;
        chip.querySelector('.chip-remove-btn').addEventListener('click', () => removeMember(name));
        membersList.appendChild(chip);
    });
}

function renderShareCheckboxes() {
    if (state.members.length === 0) {
        itemShareCheckboxes.innerHTML = '<span class="empty-state-text">Add group members above first.</span>';
        return;
    }

    itemShareCheckboxes.innerHTML = '';
    state.members.forEach(name => {
        const label = document.createElement('label');
        label.className = 'check-label checkbox-label selected';
        label.innerHTML = `
            <input type="checkbox" name="itemParticipant" value="${escapeHtml(name)}" checked>
            <span>${escapeHtml(name)}</span>
        `;
        const cb = label.querySelector('input[type="checkbox"]');
        cb.addEventListener('change', () => {
            if (cb.checked) {
                label.classList.add('selected');
            } else {
                label.classList.remove('selected');
            }
        });
        itemShareCheckboxes.appendChild(label);
    });
}

selectAllMembersBtn.addEventListener('click', () => {
    const checkboxes = itemShareCheckboxes.querySelectorAll('input[type="checkbox"]');
    checkboxes.forEach(cb => {
        cb.checked = true;
        const label = cb.closest('label');
        if (label) label.classList.add('selected');
    });
});

clearSelectedMembersBtn.addEventListener('click', () => {
    const checkboxes = itemShareCheckboxes.querySelectorAll('input[type="checkbox"]');
    checkboxes.forEach(cb => {
        cb.checked = false;
        const label = cb.closest('label');
        if (label) label.classList.remove('selected');
    });
});

// Add Item
addItemForm.addEventListener('submit', (e) => {
    e.preventDefault();

    if (state.members.length === 0) {
        showAlert('Please add at least one group member before adding items.');
        memberNameInput.focus();
        return;
    }

    const name = itemNameInput.value.trim();
    const priceVal = parseFloat(itemPriceInput.value);

    if (!name) {
        showAlert('Please enter an item description.');
        itemNameInput.focus();
        return;
    }

    if (isNaN(priceVal) || priceVal <= 0) {
        showAlert('Please enter a valid price greater than ₹0.');
        itemPriceInput.focus();
        return;
    }

    const selectedParticipants = [];
    const checkboxes = itemShareCheckboxes.querySelectorAll('input[type="checkbox"]:checked');
    checkboxes.forEach(cb => selectedParticipants.push(cb.value));

    if (selectedParticipants.length === 0) {
        showAlert('Please select at least one person who shared this item.');
        return;
    }

    state.items.push({
        id: state.nextItemId++,
        name: name,
        price: Number(priceVal.toFixed(2)),
        sharedBy: selectedParticipants
    });

    itemNameInput.value = '';
    itemPriceInput.value = '';
    selectAllMembersBtn.click();
    itemNameInput.focus();

    renderItems();
    hideAlert();
});

function removeItem(itemId) {
    state.items = state.items.filter(i => i.id !== itemId);
    renderItems();
}

function renderItems() {
    itemsCount.textContent = state.items.length;

    if (state.items.length === 0) {
        emptyItemsText.classList.remove('hidden');
        itemsContainer.innerHTML = '';
        itemsContainer.appendChild(emptyItemsText);
        return;
    }

    emptyItemsText.classList.add('hidden');
    itemsContainer.innerHTML = '';

    state.items.forEach(item => {
        const itemRow = document.createElement('div');
        itemRow.className = 'item-card';

        const participantChips = (item.sharedBy && item.sharedBy.length > 0)
            ? item.sharedBy.map(p => 
                `<span class="participant-chip" title="${escapeHtml(p)}">${escapeHtml(p)}</span>`
            ).join(' ')
            : '<span class="empty-state-text">No one assigned</span>';

        itemRow.innerHTML = `
            <div class="item-card-left">
                <div class="item-card-header">
                    <span class="item-name">${escapeHtml(item.name)}</span>
                    <span class="item-price">${formatINR(item.price)}</span>
                </div>
                <div class="item-card-participants">
                    <span class="participants-label">Shared by:</span>
                    <div class="participant-chips-wrap">
                        ${participantChips}
                    </div>
                </div>
            </div>
            <div class="item-card-right">
                <button type="button" class="item-delete-btn" aria-label="Delete ${escapeHtml(item.name)}" title="Delete item">
                    &times;
                </button>
            </div>
        `;

        itemRow.querySelector('.item-delete-btn').addEventListener('click', () => removeItem(item.id));
        itemsContainer.appendChild(itemRow);
    });
}

// Mode 1: Quick Tip Chips
tipChips.forEach(chip => {
    chip.addEventListener('click', () => {
        tipInput.value = chip.getAttribute('data-tip');
    });
});

// Mode 1: Calculate Button
calculateBtn.addEventListener('click', async () => {
    if (isCalculating) return;

    if (state.members.length === 0) {
        showAlert('Please add at least one member to calculate.');
        return;
    }

    if (state.items.length === 0) {
        showAlert('Please add at least one bill item.');
        return;
    }

    for (const item of state.items) {
        if (!item.sharedBy || item.sharedBy.length === 0) {
            showAlert(`"${item.name}" has no participants assigned. Please assign at least one person.`);
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

    await executeCalculation(payload, calculateBtn, 'Calculate Fair Split ⚡');
});

// Mode 1: Reset All
resetBtn.addEventListener('click', () => {
    if (state.members.length === 0 && state.items.length === 0) return;

    if (confirm('Are you sure you want to clear all members and items in Manual Mode?')) {
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
    }
});

// ==========================================
// 6. MODE 2: AI-POWERED BILL ENTRY WORKFLOW
// ==========================================

// Sample prompt button click handlers
if (samplePromptBtn1) {
    samplePromptBtn1.addEventListener('click', () => {
        aiDescriptionInput.value = "Rahul ate pizza which was 600 rupees, Priya and I shared 400 rupees pasta, and we all shared Coke worth 180 rupees.";
        if (!aiSpeakerInput.value.trim()) aiSpeakerInput.value = "Sneha";
        aiDescriptionInput.focus();
    });
}

if (samplePromptBtn2) {
    samplePromptBtn2.addEventListener('click', () => {
        aiDescriptionInput.value = "Amit had biryani for 380, Pooja had dosa for 160, and we both shared kulfi for 140";
        if (!aiSpeakerInput.value.trim()) aiSpeakerInput.value = "Sneha";
        aiDescriptionInput.focus();
    });
}

if (samplePromptBtn3) {
    samplePromptBtn3.addEventListener('click', () => {
        aiDescriptionInput.value = "Rahul had burger for 250, Priya had pasta for 350, and I had dessert";
        if (!aiSpeakerInput.value.trim()) aiSpeakerInput.value = "Sneha";
        aiDescriptionInput.focus();
    });
}

// AI Sub-Tabs (Text Description vs Receipt Scan)
if (tabTextModeBtn && tabReceiptModeBtn) {
    tabTextModeBtn.addEventListener('click', () => {
        tabTextModeBtn.classList.add('active');
        tabReceiptModeBtn.classList.remove('active');
        aiTextEntryPanel.classList.remove('hidden');
        aiReceiptEntryPanel.classList.add('hidden');
    });

    tabReceiptModeBtn.addEventListener('click', () => {
        tabReceiptModeBtn.classList.add('active');
        tabTextModeBtn.classList.remove('active');
        aiReceiptEntryPanel.classList.remove('hidden');
        aiTextEntryPanel.classList.add('hidden');

        // Pre-fill receipt members input if empty and manual members exist
        if (!aiReceiptMembersInput.value.trim() && state.members.length > 0) {
            aiReceiptMembersInput.value = state.members.join(', ');
        }
    });
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
        showAlert('Unsupported file format. Please upload a JPG, JPEG, or PNG receipt photo.', 'error');
        return;
    }

    const maxSize = 10 * 1024 * 1024; // 10 MB
    if (file.size > maxSize) {
        showAlert('The receipt image exceeds 10 MB. Please upload a smaller photo.', 'error');
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
        if (!currentReceiptFile) {
            receiptFileInput.click();
        }
    });

    receiptFileInput.addEventListener('change', (e) => {
        if (e.target.files && e.target.files[0]) {
            handleReceiptFile(e.target.files[0]);
        }
    });

    receiptDropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        receiptDropzone.classList.add('dragover');
    });

    receiptDropzone.addEventListener('dragleave', () => {
        receiptDropzone.classList.remove('dragover');
    });

    receiptDropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        receiptDropzone.classList.remove('dragover');
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            handleReceiptFile(e.dataTransfer.files[0]);
        }
    });
}

if (replaceReceiptBtn && receiptFileInput) {
    replaceReceiptBtn.addEventListener('click', (e) => {
        e.stopPropagation();
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

// 📸 Scan Receipt with Gemini
if (scanReceiptBtn) {
    scanReceiptBtn.addEventListener('click', async () => {
        if (isScanningReceipt) return;

        if (!currentReceiptFile) {
            showAlert('Please select or upload a receipt photo first.');
            return;
        }

        isScanningReceipt = true;
        scanReceiptBtn.disabled = true;
        aiLoadingStatusText.textContent = 'Scanning receipt with Gemini Vision AI...';
        aiLoadingIndicator.classList.remove('hidden');
        aiClarificationBox.classList.add('hidden');
        hideAlert();

        const startTime = performance.now();
        aiTimerBadge.textContent = '0.0s';
        const timerInterval = setInterval(() => {
            const elapsed = ((performance.now() - startTime) / 1000).toFixed(1);
            aiTimerBadge.textContent = `${elapsed}s`;
        }, 100);

        try {
            const formData = new FormData();
            formData.append('receipt', currentReceiptFile);

            const membersInputVal = aiReceiptMembersInput.value.trim();
            if (membersInputVal) {
                formData.append('members', membersInputVal);
            } else if (state.members.length > 0) {
                formData.append('members', JSON.stringify(state.members));
            }

            const response = await fetch('/api/ai/scan-receipt', {
                method: 'POST',
                body: formData
            });

            const data = await response.json();
            clearInterval(timerInterval);
            const totalDuration = ((performance.now() - startTime) / 1000).toFixed(2);
            aiTimerBadge.textContent = `${totalDuration}s`;

            if (!response.ok || !data.success) {
                if (data.is_missing_api_key) {
                    showAlert('Gemini API key is not configured in .env. Please add GEMINI_API_KEY to your .env file.', 'error');
                } else {
                    showAlert(data.error || 'Failed to scan receipt with AI.', 'error');
                }
                return;
            }

            // Successfully scanned! Populate aiState
            aiState.members = Array.isArray(data.members) ? [...data.members] : [];
            if (aiState.members.length === 0 && state.members.length > 0) {
                aiState.members = [...state.members];
            }

            aiState.items = [];
            aiState.nextItemId = 1;

            if (Array.isArray(data.items)) {
                data.items.forEach(it => {
                    const qty = parseInt(it.quantity) || 1;
                    const totPrice = parseFloat(it.price) || 0.0;
                    const unitPrice = parseFloat(it.unit_price) || (qty > 0 ? totPrice / qty : 0.0);
                    aiState.items.push({
                        id: aiState.nextItemId++,
                        name: String(it.name || 'Item').trim(),
                        quantity: qty,
                        unit_price: Number(unitPrice.toFixed(2)),
                        price: Number(totPrice.toFixed(2)),
                        has_missing_price: Boolean(it.has_missing_price || totPrice <= 0),
                        shared_by: Array.isArray(it.shared_by) ? [...it.shared_by] : []
                    });
                });
            }

            // Restaurant Name
            if (aiRestaurantBanner && aiRestaurantName) {
                if (data.restaurant_name) {
                    aiRestaurantName.textContent = data.restaurant_name;
                    aiRestaurantBanner.classList.remove('hidden');
                } else {
                    aiRestaurantBanner.classList.add('hidden');
                }
            }

            // Pre-fill Tax & Tip
            if (data.tax_percentage !== undefined && data.tax_percentage !== null) {
                aiTaxInput.value = data.tax_percentage;
                aiState.tax = parseFloat(data.tax_percentage) || 0;
            }
            if (data.tip_percentage !== undefined && data.tip_percentage !== null) {
                aiTipInput.value = data.tip_percentage;
                aiState.tip = parseFloat(data.tip_percentage) || 0;
            }

            // Clarifications
            const clarifs = data.clarifications || [];
            if (aiState.members.length === 0) {
                clarifs.push("Add group members under 'Extracted Group Members' to assign who shared each item.");
            }
            renderAiClarifications(clarifs);

            // Render Interactive Review Box
            renderAiReview();
            aiReviewSection.classList.remove('hidden');
            aiReviewSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

            showAlert(`⚡ Receipt scanned in ${totalDuration}s! Review the extracted items, quantities, and prices below, then assign participants.`, 'success');

        } catch (err) {
            clearInterval(timerInterval);
            console.error('Receipt scan error:', err);
            showAlert('Network error: Could not reach the server. Make sure Python is running on port 5001.');
        } finally {
            isScanningReceipt = false;
            scanReceiptBtn.disabled = false;
            aiLoadingIndicator.classList.add('hidden');
        }
    });
}

// Clear Prompt
aiClearPromptBtn.addEventListener('click', () => {
    aiDescriptionInput.value = '';
    aiDescriptionInput.focus();
});

// AI Mode: Quick Tip Chips
aiTipChips.forEach(chip => {
    chip.addEventListener('click', () => {
        aiTipInput.value = chip.getAttribute('data-tip');
        aiState.tip = parseFloat(chip.getAttribute('data-tip')) || 0;
    });
});

aiTaxInput.addEventListener('input', () => {
    aiState.tax = parseFloat(aiTaxInput.value) || 0;
});

aiTipInput.addEventListener('input', () => {
    aiState.tip = parseFloat(aiTipInput.value) || 0;
});

// ⚡ Interpret Bill with AI (Fast Gemini)
aiInterpretBtn.addEventListener('click', async () => {
    if (isAiInterpreting) return;

    const description = aiDescriptionInput.value.trim();
    const speakerName = aiSpeakerInput.value.trim();

    if (!description) {
        showAlert('Please enter a description of your meal in the box.');
        aiDescriptionInput.focus();
        return;
    }

    // Start timer & loading indicator
    isAiInterpreting = true;
    aiInterpretBtn.disabled = true;
    aiLoadingIndicator.classList.remove('hidden');
    aiClarificationBox.classList.add('hidden');
    hideAlert();

    const startTime = performance.now();
    aiTimerBadge.textContent = '0.0s';
    const timerInterval = setInterval(() => {
        const elapsed = ((performance.now() - startTime) / 1000).toFixed(1);
        aiTimerBadge.textContent = `${elapsed}s`;
    }, 100);

    try {
        const response = await fetch('/api/ai/parse-bill', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                description: description,
                speaker_name: speakerName
            })
        });

        const data = await response.json();
        clearInterval(timerInterval);
        const totalDuration = ((performance.now() - startTime) / 1000).toFixed(2);
        aiTimerBadge.textContent = `${totalDuration}s`;

        if (!response.ok || !data.success) {
            if (data.is_missing_api_key) {
                showAlert('Gemini API key is not configured in .env. Please add GEMINI_API_KEY to your .env file.', 'error');
            } else {
                showAlert(data.error || 'Failed to interpret bill with AI.', 'error');
            }
            return;
        }

        // Successfully parsed! Populate aiState
        aiState.members = Array.isArray(data.members) ? [...data.members] : [];
        aiState.items = [];
        aiState.nextItemId = 1;

        if (Array.isArray(data.items)) {
            data.items.forEach(it => {
                aiState.items.push({
                    id: aiState.nextItemId++,
                    name: String(it.name || 'Dish').trim(),
                    price: parseFloat(it.price) || 0.0,
                    has_missing_price: Boolean(it.has_missing_price || (!it.price || it.price <= 0)),
                    shared_by: Array.isArray(it.shared_by) ? [...it.shared_by] : []
                });
            });
        }

        // Display Clarifications / Missing Info if any
        renderAiClarifications(data.clarifications || []);

        // Render Interactive Review Box
        renderAiReview();
        aiReviewSection.classList.remove('hidden');
        aiReviewSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

        showAlert(`⚡ Interpreted in ${totalDuration}s! Review the extracted items below and edit as needed.`, 'success');

    } catch (err) {
        clearInterval(timerInterval);
        console.error('AI parse error:', err);
        showAlert('Network error: Could not reach the server. Make sure Python is running on port 5001.');
    } finally {
        isAiInterpreting = false;
        aiInterpretBtn.disabled = false;
        aiLoadingIndicator.classList.add('hidden');
    }
});

// Render Clarification Alerts
function renderAiClarifications(clarifications) {
    if (!clarifications || clarifications.length === 0) {
        aiClarificationBox.classList.add('hidden');
        aiClarificationList.innerHTML = '';
        return;
    }

    aiClarificationList.innerHTML = '';
    clarifications.forEach(msg => {
        const li = document.createElement('li');
        li.textContent = msg;
        aiClarificationList.appendChild(li);
    });
    aiClarificationBox.classList.remove('hidden');
}

// Render AI Review Card
function renderAiReview() {
    // 1. Members
    aiMembersCount.textContent = aiState.members.length;
    aiMembersList.innerHTML = '';

    if (aiState.members.length === 0) {
        aiMembersList.innerHTML = '<span class="empty-state-text">No members identified. Add one below:</span>';
    } else {
        aiState.members.forEach(name => {
            const chip = document.createElement('div');
            chip.className = 'member-chip chip';
            chip.innerHTML = `
                <span>${escapeHtml(name)}</span>
                <button type="button" class="chip-remove-btn chip-remove" aria-label="Remove ${escapeHtml(name)}">&times;</button>
            `;
            chip.querySelector('.chip-remove-btn').addEventListener('click', () => {
                aiState.members = aiState.members.filter(m => m !== name);
                aiState.items.forEach(it => {
                    it.shared_by = it.shared_by.filter(m => m !== name);
                });
                renderAiReview();
            });
            aiMembersList.appendChild(chip);
        });
    }

    // 2. Items List
    aiItemsContainer.innerHTML = '';

    if (aiState.items.length === 0) {
        aiItemsContainer.innerHTML = '<p class="empty-state-text">No items found. Click "+ Add Item" above to add one.</p>';
    } else {
        aiState.items.forEach(item => {
            const row = document.createElement('div');
            row.className = 'ai-item-row';

            // Participant toggle pills
            let pillsHtml = '';
            if (aiState.members.length === 0) {
                pillsHtml = '<span class="empty-state-text">Add members first</span>';
            } else {
                pillsHtml = aiState.members.map(member => {
                    const isShared = item.shared_by.some(m => m.toLowerCase() === member.toLowerCase());
                    const activeClass = isShared ? 'active' : '';
                    return `
                        <button 
                            type="button" 
                            class="participant-toggle-pill ${activeClass}" 
                            data-member="${escapeHtml(member)}"
                            data-item-id="${item.id}"
                        >
                            ${isShared ? '✓ ' : '+ '}${escapeHtml(member)}
                        </button>
                    `;
                }).join('');
            }

            const missingPriceClass = item.has_missing_price ? 'missing-price-input' : '';
            const missingBadge = item.has_missing_price 
                ? '<span class="missing-price-badge">⚠️ Price Missing</span>' 
                : '';

            row.innerHTML = `
                <div class="ai-item-main-fields">
                    <input 
                        type="text" 
                        class="ai-item-name-input" 
                        value="${escapeHtml(item.name)}" 
                        placeholder="Dish name"
                    >
                    <div class="ai-item-qty-wrap">
                        <label class="qty-label">Qty</label>
                        <input 
                            type="number" 
                            min="1" 
                            step="1" 
                            class="ai-item-qty-input" 
                            value="${item.quantity || 1}"
                        >
                    </div>
                    <div class="ai-item-price-wrap">
                        <label class="price-label">₹ Total</label>
                        <input 
                            type="number" 
                            step="0.01" 
                            min="0.01" 
                            class="ai-item-price-input ${missingPriceClass}" 
                            value="${item.price > 0 ? item.price : ''}" 
                            placeholder="₹ Price"
                        >
                    </div>
                    ${missingBadge}
                    <button type="button" class="ai-item-delete-btn" title="Delete item">&times;</button>
                </div>
                <div class="participant-toggle-pills-wrap">
                    <span class="toggle-pill-label">Shared By:</span>
                    ${pillsHtml}
                </div>
            `;

            // Event Listeners for inline editing
            const nameInput = row.querySelector('.ai-item-name-input');
            nameInput.addEventListener('input', (e) => {
                item.name = e.target.value.trim();
            });

            const qtyInput = row.querySelector('.ai-item-qty-input');
            const priceInput = row.querySelector('.ai-item-price-input');

            qtyInput.addEventListener('input', (e) => {
                const newQty = parseInt(e.target.value) || 1;
                if (newQty > 0) {
                    item.quantity = newQty;
                    if (item.unit_price && item.unit_price > 0) {
                        item.price = Number((item.unit_price * newQty).toFixed(2));
                        priceInput.value = item.price;
                    }
                    updateAiSubtotal();
                }
            });

            priceInput.addEventListener('input', (e) => {
                const val = parseFloat(e.target.value);
                if (!isNaN(val) && val > 0) {
                    item.price = Number(val.toFixed(2));
                    item.unit_price = Number((item.price / (item.quantity || 1)).toFixed(2));
                    item.has_missing_price = false;
                    priceInput.classList.remove('missing-price-input');
                    const badge = row.querySelector('.missing-price-badge');
                    if (badge) badge.remove();
                } else {
                    item.price = 0.0;
                    item.has_missing_price = true;
                    priceInput.classList.add('missing-price-input');
                }
                updateAiSubtotal();
            });

            row.querySelector('.ai-item-delete-btn').addEventListener('click', () => {
                aiState.items = aiState.items.filter(i => i.id !== item.id);
                renderAiReview();
            });

            // Toggle participant pill click handler
            row.querySelectorAll('.participant-toggle-pill').forEach(pill => {
                pill.addEventListener('click', () => {
                    const memberName = pill.getAttribute('data-member');
                    const existsIndex = item.shared_by.findIndex(m => m.toLowerCase() === memberName.toLowerCase());
                    
                    if (existsIndex >= 0) {
                        item.shared_by.splice(existsIndex, 1);
                    } else {
                        item.shared_by.push(memberName);
                    }
                    renderAiReview();
                });
            });

            aiItemsContainer.appendChild(row);
        });
    }

    updateAiSubtotal();
}

function updateAiSubtotal() {
    const subtotalPaise = aiState.items.reduce((sum, it) => {
        const p = parseFloat(it.price) || 0;
        return sum + Math.round(p * 100);
    }, 0);
    aiItemsSubtotal.textContent = formatINR(subtotalPaise / 100);
}

// Add Missing Member Inline in AI Review
aiAddMemberForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const name = aiAddMemberInput.value.trim();

    if (!name) return;

    const exists = aiState.members.some(m => m.toLowerCase() === name.toLowerCase());
    if (exists) {
        showAlert(`"${name}" is already in the extracted members list.`);
        return;
    }

    aiState.members.push(name);
    aiAddMemberInput.value = '';
    renderAiReview();
});

// Add New Blank Item in AI Review
aiAddNewItemBtn.addEventListener('click', () => {
    aiState.items.push({
        id: aiState.nextItemId++,
        name: 'New Item',
        quantity: 1,
        unit_price: 0.0,
        price: 0.0,
        has_missing_price: true,
        shared_by: [...aiState.members]
    });
    renderAiReview();
});

// Confirm & Calculate Split in AI Mode
aiConfirmCalculateBtn.addEventListener('click', async () => {
    if (isCalculating) return;

    if (aiState.members.length === 0) {
        showAlert('Please add at least one member in the review box.');
        return;
    }

    if (aiState.items.length === 0) {
        showAlert('Please add at least one bill item.');
        return;
    }

    // Verify valid prices and participants
    for (const item of aiState.items) {
        if (!item.name || !item.name.trim()) {
            showAlert('Please give every dish a valid name.');
            return;
        }

        if (item.price <= 0 || item.has_missing_price) {
            showAlert(`Price for "${item.name}" is missing or 0. Please enter its price in INR.`);
            return;
        }

        if (!item.shared_by || item.shared_by.length === 0) {
            showAlert(`Please select who shared "${item.name}" by clicking the member pills.`);
            return;
        }
    }

    const taxVal = parseFloat(aiTaxInput.value) || 0.0;
    const tipVal = parseFloat(aiTipInput.value) || 0.0;

    if (taxVal < 0 || tipVal < 0) {
        showAlert('Tax and tip percentages cannot be negative.');
        return;
    }

    const payload = {
        members: aiState.members,
        items: aiState.items.map(i => {
            let displayName = i.name;
            if (i.quantity && i.quantity > 1 && !displayName.includes(`(x${i.quantity})`)) {
                displayName = `${displayName} (x${i.quantity})`;
            }
            return {
                name: displayName,
                price: i.price,
                shared_by: i.shared_by
            };
        }),
        tax_percentage: taxVal,
        tip_percentage: tipVal
    };

    await executeCalculation(payload, aiConfirmCalculateBtn, '✓ Confirm & Calculate Split ⚡');
});

// Copy Extracted AI Data to Manual Mode
aiCopyToManualBtn.addEventListener('click', () => {
    if (aiState.members.length === 0 && aiState.items.length === 0) {
        showAlert('Nothing to copy. Interpret a bill description first.');
        return;
    }

    // Transfer members
    state.members = [...aiState.members];

    // Transfer items
    state.items = aiState.items.map(i => {
        let displayName = i.name;
        if (i.quantity && i.quantity > 1 && !displayName.includes(`(x${i.quantity})`)) {
            displayName = `${displayName} (x${i.quantity})`;
        }
        return {
            id: state.nextItemId++,
            name: displayName,
            price: i.price,
            sharedBy: [...i.shared_by]
        };
    });

    // Transfer tax & tip
    taxInput.value = aiTaxInput.value || '0';
    tipInput.value = aiTipInput.value || '0';

    // Render manual mode views
    renderMembers();
    renderShareCheckboxes();
    renderItems();

    // Switch view to Manual Mode
    switchMode('manual');
    showAlert('Successfully copied AI items to Manual Mode! You can manage them here.', 'success');
});

// Reset AI Form
aiResetBtn.addEventListener('click', () => {
    if (confirm('Clear the extracted bill review?')) {
        aiState.members = [];
        aiState.items = [];
        if (aiRestaurantBanner) aiRestaurantBanner.classList.add('hidden');
        aiReviewSection.classList.add('hidden');
        aiClarificationBox.classList.add('hidden');
        resultsContent.classList.add('hidden');
        resultsPlaceholder.classList.remove('hidden');
        hideAlert();
    }
});

// ==========================================
// 7. Core Calculation Engine Integration
// ==========================================

async function executeCalculation(payload, buttonElement, originalButtonText) {
    isCalculating = true;
    buttonElement.disabled = true;
    buttonElement.textContent = 'Calculating Split...';

    try {
        const response = await fetch('/api/calculate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const data = await response.json();

        if (!response.ok || !data.success) {
            showAlert(data.error || 'Failed to calculate bill split.');
            return;
        }

        renderResults(data);
        hideAlert();

    } catch (err) {
        console.error('Calculation error:', err);
        showAlert('Network error: Could not reach the server. Make sure Python is running.');
    } finally {
        isCalculating = false;
        buttonElement.disabled = false;
        buttonElement.textContent = originalButtonText;
    }
}

// ==========================================
// 8. Render Settlement Breakdown (Right Column)
// ==========================================

function renderResults(data) {
    const { summary, breakdown } = data;

    // Display summary metrics
    summarySubtotal.textContent = summary.subtotal_formatted || formatINR(summary.subtotal);
    summaryTax.textContent = summary.tax_formatted || formatINR(summary.tax);
    summaryTaxLabel.textContent = `Tax (${summary.tax_percentage}%)`;
    summaryTip.textContent = summary.tip_formatted || formatINR(summary.tip);
    summaryTipLabel.textContent = `Tip (${summary.tip_percentage}%)`;
    summaryGrandTotal.textContent = summary.grand_total_formatted || formatINR(summary.grand_total);

    // Build breakdown cards per member
    breakdownCardsContainer.innerHTML = '';

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

        card.innerHTML = `
            <div class="member-card-header">
                <span class="member-name">${escapeHtml(memberName)}</span>
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
        `;

        breakdownCardsContainer.appendChild(card);
    }

    resultsPlaceholder.classList.add('hidden');
    resultsContent.classList.remove('hidden');

    if (window.innerWidth <= 900) {
        resultsContent.scrollIntoView({ behavior: 'smooth' });
    }
}

// Initial UI Initialization
renderMembers();
renderShareCheckboxes();
renderItems();
