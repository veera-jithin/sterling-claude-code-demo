// WebSocket connection
const socket = io();

// State management
const state = {
    pendingJobs: new Map(), // jobId -> {job, email}
    selectedJobId: null,
    approvedJobs: [],
    processedCount: 0,
    approvedCount: 0,
    editingJobId: null,
    originalJob: null,
    currentEmail: null
};

// DOM elements
const statusDot = document.getElementById('status-dot');
const statusText = document.getElementById('status-text');
const processedCount = document.getElementById('processed-count');
const pendingCount = document.getElementById('pending-count');
const approvedCount = document.getElementById('approved-count');
const jobListContent = document.getElementById('job-list-content');
const jobDetailSection = document.getElementById('job-detail-section');
const emailContent = document.getElementById('email-content');
const jobContent = document.getElementById('job-content');
const btnCollapse = document.getElementById('btn-collapse');
const editModal = document.getElementById('edit-modal');
const databaseTbody = document.getElementById('database-tbody');

// WebSocket event handlers
socket.on('connect', () => {
    console.log('Connected to server');
    statusDot.className = 'dot connected';
    statusText.textContent = 'Connected';
    loadPendingJobs();
    loadApprovedJobs();
});

socket.on('disconnect', () => {
    console.log('Disconnected from server');
    statusDot.className = 'dot disconnected';
    statusText.textContent = 'Disconnected';
});

socket.on('email_processing', (data) => {
    console.log('Email processing:', data);
    state.currentEmail = data.email;
    state.processedCount++;
    processedCount.textContent = state.processedCount;
});

socket.on('job_extracted', (data) => {
    console.log('Job extracted:', data);
    const pendingId = data.pending_id || generateJobId();
    state.pendingJobs.set(pendingId, {
        job: data.job,
        email: data.email || state.currentEmail,
        pending_id: data.pending_id
    });
    displayJobList();
    updatePendingCount();
});

socket.on('job_approved', (data) => {
    console.log('Job approved:', data);
    if (data.pending_job_id) {
        state.pendingJobs.delete(data.pending_job_id);
        if (state.selectedJobId === data.pending_job_id) {
            collapseDetailSection();
        }
        displayJobList();
        updatePendingCount();
    }
    loadApprovedJobs();
});

// Generate unique job ID
function generateJobId() {
    return `job_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
}

// Update pending count
function updatePendingCount() {
    pendingCount.textContent = state.pendingJobs.size;
}

// Display job list as horizontal cards
function displayJobList() {
    if (state.pendingJobs.size === 0) {
        jobListContent.innerHTML = `
            <div class="placeholder">
                <p>No pending jobs</p>
                <p class="hint">Jobs will appear here as they are extracted</p>
            </div>
        `;
        return;
    }

    const html = Array.from(state.pendingJobs.entries()).map(([jobId, data]) => {
        const job = data.job;
        const isSelected = jobId === state.selectedJobId;
        return `
            <div class="job-list-item ${isSelected ? 'selected' : ''}" onclick="selectJob('${jobId}')">
                <div class="job-list-item-header">
                    <div class="job-list-builder">${escapeHtml(job.builder_name || 'Unknown Builder')}</div>
                    <span class="confidence-badge ${job.confidence}">${job.confidence}</span>
                </div>
                <div class="job-list-address">${escapeHtml(job.address || 'No address')}</div>
                <div class="job-list-footer">
                    <span>Lot: ${job.lot || 'N/A'} | Block: ${job.block || 'N/A'}</span>
                </div>
            </div>
        `;
    }).join('');

    jobListContent.innerHTML = html;
}

// Select a job and show details
window.selectJob = function(jobId) {
    const numericJobId = typeof jobId === 'string' ? parseInt(jobId) : jobId;
    const jobData = state.pendingJobs.get(numericJobId);

    if (!jobData) {
        console.error('Job not found for jobId:', numericJobId);
        return;
    }

    state.selectedJobId = numericJobId;
    displayJobList(); // Refresh list to show selection
    showJobDetail(numericJobId, jobData);
};

// Show job detail in expanded section
function showJobDetail(jobId, jobData) {
    const job = jobData.job;
    const email = jobData.email;

    // Show the detail section
    jobDetailSection.classList.remove('hidden');

    // Render email content (left panel)
    renderEmailContent(email, jobId);

    // Render job extraction (right panel)
    renderJobContent(job, jobId, jobData.pending_id);

    // Scroll to detail section
    jobDetailSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// Render email content in left panel
function renderEmailContent(email, jobId) {
    if (!email) {
        emailContent.innerHTML = '<div class="placeholder">No email data available</div>';
        return;
    }

    // First, clear the email content completely
    emailContent.innerHTML = '';

    // Generate the email body HTML
    let emailBodyHtml = '';
    let bodyContent = email.originalBodyHtml || email.body;
    const isHtml = email.bodyContentType === 'html' || email.originalBodyHtml;

    if (isHtml && bodyContent) {
        emailBodyHtml = DOMPurify.sanitize(bodyContent, {
            ALLOWED_TAGS: ['p', 'br', 'strong', 'b', 'em', 'i', 'u', 'span', 'div', 'table', 'tr', 'td', 'th', 'tbody', 'thead', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'a', 'font'],
            ALLOWED_ATTR: ['href', 'class', 'style', 'colspan', 'rowspan', 'target'],
            KEEP_CONTENT: true
        });
    } else if (bodyContent) {
        emailBodyHtml = bodyContent
            .split('\n')
            .map(line => line.trim())
            .filter(line => line.length > 0)
            .map(line => {
                if (line.match(/^(From|To|Subject|Date|Cc|Bcc):/i)) {
                    return `<p><strong>${escapeHtml(line)}</strong></p>`;
                } else if (line.includes(':') && line.split(':')[0].length < 20) {
                    const parts = line.split(':');
                    const key = parts[0].trim();
                    const value = parts.slice(1).join(':').trim();
                    if (value) {
                        return `<p><strong>${escapeHtml(key)}:</strong> ${escapeHtml(value)}</p>`;
                    } else {
                        return `<p><strong>${escapeHtml(key)}:</strong></p>`;
                    }
                } else {
                    return `<p>${escapeHtml(line)}</p>`;
                }
            })
            .join('\n');
    } else {
        emailBodyHtml = '<p>No email content</p>';
    }

    const html = `
        <div class="email-preview">
            <div class="email-subject">${escapeHtml(email.subject || 'No Subject')}</div>
            <div class="email-meta">
                <span><strong>From:</strong> ${escapeHtml(email.from || 'Unknown')}</span>
                <span><strong>Date:</strong> ${formatDate(email.receivedDateTime)}</span>
            </div>
            <div class="email-body-preview">${emailBodyHtml}</div>
            ${email.hasAttachments && email.attachmentNames ? renderAttachments(email) : ''}
        </div>
    `;

    emailContent.innerHTML = html;
}

// Render job extraction in right panel
function renderJobContent(job, jobId, pendingId) {
    const html = `
        <div class="job-detail-actions">
            <button class="btn btn-warning" onclick="editJob('${jobId}')">Edit</button>
            <button class="btn btn-success" onclick="approveJob('${jobId}')">Approve</button>
        </div>

        <div class="job-detail-section">
            <div class="job-field">
                <div class="job-field-label">Builder Name:</div>
                <div class="job-field-value ${!job.builder_name ? 'null' : ''}">${escapeHtml(job.builder_name || 'Not specified')}</div>
            </div>
            <div class="job-field">
                <div class="job-field-label">Community:</div>
                <div class="job-field-value ${!job.community ? 'null' : ''}">${escapeHtml(job.community || 'Not specified')}</div>
            </div>
            <div class="job-field">
                <div class="job-field-label">Address:</div>
                <div class="job-field-value ${!job.address ? 'null' : ''}">${escapeHtml(job.address || 'Not specified')}</div>
            </div>
            <div class="job-field">
                <div class="job-field-label">Lot:</div>
                <div class="job-field-value ${!job.lot ? 'null' : ''}">${escapeHtml(job.lot || 'Not specified')}</div>
            </div>
            <div class="job-field">
                <div class="job-field-label">Block:</div>
                <div class="job-field-value ${!job.block ? 'null' : ''}">${escapeHtml(job.block || 'Not specified')}</div>
            </div>
            <div class="job-field">
                <div class="job-field-label">Job Type:</div>
                <div class="job-field-value ${!job.type_of_job ? 'null' : ''}">${escapeHtml(job.type_of_job || 'Not specified')}</div>
            </div>
            <div class="job-field">
                <div class="job-field-label">Confidence:</div>
                <span class="confidence-badge ${job.confidence}">${job.confidence}</span>
                <span class="job-field-value" style="margin-left: 0.5rem; font-size: 0.85rem; color: #6c757d;">${escapeHtml(job.confidence_reason)}</span>
            </div>
        </div>
    `;

    jobContent.innerHTML = html;
}

// Render attachments
function renderAttachments(email) {
    if (!email.id || !email.attachmentNames) return '';

    const attachmentLinks = email.attachmentNames.map((name, index) => {
        const url = `/api/attachments/${email.id}/${encodeURIComponent(name)}`;
        const icon = getAttachmentIcon(name);
        const safeUrl = url.replace(/'/g, "\\'");
        const safeName = name.replace(/'/g, "\\'");
        return `<a href="#" onclick="openAttachment('${safeUrl}', '${safeName}'); return false;" class="attachment-item">${icon} ${escapeHtml(name)}</a>`;
    }).join('');

    return `
        <div class="attachments">
            <div class="attachments-title">Attachments:</div>
            ${attachmentLinks}
        </div>
    `;
}

// Get attachment icon based on file extension
function getAttachmentIcon(filename) {
    const ext = filename.split('.').pop().toLowerCase();
    if (ext === 'pdf') return '📎';
    if (['jpg', 'jpeg', 'png', 'gif', 'bmp'].includes(ext)) return '📷';
    if (['doc', 'docx', 'txt'].includes(ext)) return '📄';
    if (['xls', 'xlsx', 'csv'].includes(ext)) return '📊';
    return '📎';
}

// Collapse detail section
function collapseDetailSection() {
    jobDetailSection.classList.add('hidden');
    state.selectedJobId = null;
    displayJobList();
}

btnCollapse.addEventListener('click', collapseDetailSection);

// Edit job
window.editJob = function(jobId) {
    const numericJobId = typeof jobId === 'string' ? parseInt(jobId) : jobId;
    const jobData = state.pendingJobs.get(numericJobId);
    if (!jobData) return;

    const job = jobData.job;
    state.editingJobId = numericJobId;
    state.originalJob = JSON.parse(JSON.stringify(job));

    document.getElementById('edit-builder').value = job.builder_name || '';
    document.getElementById('edit-community').value = job.community || '';
    document.getElementById('edit-address').value = job.address || '';
    document.getElementById('edit-lot').value = job.lot || '';
    document.getElementById('edit-block').value = job.block || '';
    document.getElementById('edit-job-type').value = job.type_of_job || '';
    document.getElementById('edit-notes').value = '';

    editModal.classList.remove('hidden');
};

// Save edited job
document.getElementById('btn-save-edit').addEventListener('click', () => {
    const notes = document.getElementById('edit-notes').value.trim();
    if (!notes) {
        alert('Please provide editor\'s notes explaining the changes.');
        return;
    }

    const jobId = state.editingJobId;
    const jobData = state.pendingJobs.get(jobId);

    jobData.job.builder_name = document.getElementById('edit-builder').value.trim() || null;
    jobData.job.community = document.getElementById('edit-community').value.trim() || null;
    jobData.job.address = document.getElementById('edit-address').value.trim() || null;
    jobData.job.lot = document.getElementById('edit-lot').value.trim() || null;
    jobData.job.block = document.getElementById('edit-block').value.trim() || null;
    jobData.job.type_of_job = document.getElementById('edit-job-type').value.trim() || null;

    jobData.job._editor_notes = notes;
    jobData.job._original_extraction = state.originalJob;

    state.editingJobId = null;
    state.originalJob = null;

    editModal.classList.add('hidden');
    displayJobList();
    if (state.selectedJobId === jobId) {
        showJobDetail(jobId, jobData);
    }
});

// Cancel edit
document.getElementById('btn-cancel-edit').addEventListener('click', () => {
    state.editingJobId = null;
    state.originalJob = null;
    editModal.classList.add('hidden');
});

document.getElementById('close-modal').addEventListener('click', () => {
    document.getElementById('btn-cancel-edit').click();
});

// Approve job
window.approveJob = async function(jobId) {
    const numericJobId = typeof jobId === 'string' ? parseInt(jobId) : jobId;
    const jobData = state.pendingJobs.get(numericJobId);
    if (!jobData) return;

    try {
        const response = await fetch('/api/jobs/approve', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                job_data: jobData.job,
                editor_notes: jobData.job._editor_notes || null,
                original_extraction: jobData.job._original_extraction || null,
                approved_by: 'user',
                pending_job_id: jobData.pending_id || null
            })
        });

        const result = await response.json();
        if (result.status === 'ok') {
            console.log('Job approved:', result.job_id);
            state.pendingJobs.delete(numericJobId);
            state.approvedCount++;
            approvedCount.textContent = state.approvedCount;

            if (state.selectedJobId === numericJobId) {
                collapseDetailSection();
            } else {
                displayJobList();
            }

            updatePendingCount();
            loadApprovedJobs();
        } else {
            alert('Failed to approve job: ' + result.message);
        }
    } catch (error) {
        console.error('Error approving job:', error);
        alert('Failed to approve job: ' + error.message);
    }
};

// Load pending jobs from database
async function loadPendingJobs() {
    try {
        const response = await fetch('/api/jobs/pending');
        const result = await response.json();

        if (result.status === 'ok') {
            state.pendingJobs.clear();
            for (const pending of result.pending_jobs) {
                state.pendingJobs.set(pending.id, {
                    job: pending.job_data,
                    email: pending.email_data,
                    pending_id: pending.id
                });
            }
            displayJobList();
            updatePendingCount();
            console.log(`Loaded ${result.pending_jobs.length} pending jobs from database`);
        }
    } catch (error) {
        console.error('Error loading pending jobs:', error);
    }
}

// Load approved jobs from database
async function loadApprovedJobs() {
    try {
        const response = await fetch('/api/jobs');
        const result = await response.json();

        if (result.status === 'ok') {
            state.approvedJobs = result.jobs;
            state.approvedCount = result.jobs.length;
            approvedCount.textContent = state.approvedCount;
            displayApprovedJobs(result.jobs);
        }
    } catch (error) {
        console.error('Error loading approved jobs:', error);
    }
}

// Display approved jobs in database table
function displayApprovedJobs(jobs) {
    if (jobs.length === 0) {
        databaseTbody.innerHTML = '<tr class="placeholder-row"><td colspan="10">No approved jobs yet</td></tr>';
        return;
    }

    const html = jobs.map(job => `
        <tr>
            <td>${job.id}</td>
            <td title="${escapeHtml(job.builder_name || '-')}">${escapeHtml(job.builder_name || '-')}</td>
            <td title="${escapeHtml(job.community || '-')}">${escapeHtml(job.community || '-')}</td>
            <td title="${escapeHtml(job.address || '-')}">${escapeHtml(job.address || '-')}</td>
            <td>${escapeHtml(job.lot || '-')}</td>
            <td>${escapeHtml(job.block || '-')}</td>
            <td title="${escapeHtml(job.type_of_job || '-')}">${escapeHtml(job.type_of_job || '-')}</td>
            <td><span class="confidence-badge ${job.confidence}">${job.confidence}</span></td>
            <td title="${formatDate(job.approved_at)}">${formatDate(job.approved_at)}</td>
            <td title="${escapeHtml(job.editor_notes || '-')}">${escapeHtml(job.editor_notes || '-')}</td>
        </tr>
    `).join('');

    databaseTbody.innerHTML = html;
}

// Search approved jobs
document.getElementById('btn-search').addEventListener('click', async () => {
    const builder = document.getElementById('search-builder').value.trim();
    const community = document.getElementById('search-community').value.trim();
    const address = document.getElementById('search-address').value.trim();

    const params = new URLSearchParams();
    if (builder) params.append('builder', builder);
    if (community) params.append('community', community);
    if (address) params.append('address', address);

    try {
        const response = await fetch(`/api/jobs/search?${params.toString()}`);
        const result = await response.json();

        if (result.status === 'ok') {
            displayApprovedJobs(result.jobs);
        }
    } catch (error) {
        console.error('Error searching jobs:', error);
    }
});

// Refresh database
document.getElementById('btn-refresh').addEventListener('click', () => {
    document.getElementById('search-builder').value = '';
    document.getElementById('search-community').value = '';
    document.getElementById('search-address').value = '';
    loadApprovedJobs();
});

// Utility functions
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatDate(dateString) {
    if (!dateString) return 'Unknown';
    try {
        const date = new Date(dateString);
        return date.toLocaleString();
    } catch {
        return dateString;
    }
}

// Attachment viewer
const attachmentModal = document.getElementById('attachment-modal');
const attachmentFrame = document.getElementById('attachment-frame');
const attachmentTitle = document.getElementById('attachment-title');
const attachmentDownload = document.getElementById('attachment-download');

window.openAttachment = function(url, filename) {
    attachmentTitle.textContent = filename;
    attachmentFrame.src = url;
    attachmentDownload.href = url;
    attachmentDownload.download = filename;
    attachmentModal.classList.remove('hidden');
};

function closeAttachmentModal() {
    attachmentModal.classList.add('hidden');
    attachmentFrame.src = '';
}

document.getElementById('close-attachment-modal').addEventListener('click', closeAttachmentModal);
document.getElementById('btn-close-viewer').addEventListener('click', closeAttachmentModal);

// Close modal when clicking outside
attachmentModal.addEventListener('click', (e) => {
    if (e.target === attachmentModal) {
        closeAttachmentModal();
    }
});

// Initialize
console.log('Email Job Extraction UI loaded - Side-by-Side Layout');
