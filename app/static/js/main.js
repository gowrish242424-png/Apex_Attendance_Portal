// Client-side JavaScript for Attendance Management System

document.addEventListener('DOMContentLoaded', function () {
    // Auto-dismiss alerts after 5 seconds
    const alerts = document.querySelectorAll('.alert-dismissible');
    alerts.forEach(function (alert) {
        setTimeout(function () {
            const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
            if (bsAlert) {
                bsAlert.close();
            }
        }, 5000);
    });

    // Check health endpoint automatically
    checkSystemHealth();

    // Button event listener for quick health ping
    const pingBtn = document.getElementById('btn-quick-ping');
    if (pingBtn) {
        pingBtn.addEventListener('click', function () {
            pingHealthEndpoint(true);
        });
    }
});

function checkSystemHealth() {
    const badge = document.getElementById('live-status-badge');
    if (!badge) return;

    fetch('/health')
        .then(response => {
            if (!response.ok) throw new Error('Health check returned HTTP ' + response.status);
            return response.json();
        })
        .then(data => {
            if (data.status === 'healthy') {
                badge.className = 'badge bg-success-subtle text-success border border-success-subtle px-3 py-2 rounded-pill';
                badge.innerHTML = '<i class="bi bi-check-circle-fill me-1"></i>System Healthy &amp; Online';
            } else {
                badge.className = 'badge bg-warning-subtle text-warning-emphasis border border-warning-subtle px-3 py-2 rounded-pill';
                badge.innerHTML = '<i class="bi bi-exclamation-triangle-fill me-1"></i>System Degraded';
            }
        })
        .catch(err => {
            badge.className = 'badge bg-danger-subtle text-danger border border-danger-subtle px-3 py-2 rounded-pill';
            badge.innerHTML = '<i class="bi bi-x-circle-fill me-1"></i>Offline / Error';
            console.error('Health check failed:', err);
        });
}

function pingHealthEndpoint(showBox = false) {
    const box = document.getElementById('ping-result-box');
    const content = document.getElementById('ping-json-content');
    const timestamp = document.getElementById('ping-timestamp');

    fetch('/health')
        .then(res => res.json())
        .then(data => {
            if (showBox && box && content) {
                box.classList.remove('d-none');
                content.textContent = JSON.stringify(data, null, 2);
                if (timestamp) {
                    timestamp.textContent = 'Pinged at ' + new Date().toLocaleTimeString();
                }
            }
        })
        .catch(err => {
            if (showBox && box && content) {
                box.classList.remove('d-none');
                content.textContent = 'Error fetching /health: ' + err.message;
            }
        });
}
