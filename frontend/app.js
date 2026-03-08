const API_BASE = '/api';
const TOKEN = localStorage.getItem('dashboard_token');

if (!TOKEN) {
    window.location.href = '/login.html';
}

const fetchOptions = {
    headers: {
        'Authorization': `Bearer ${TOKEN}`
    }
};

function handleApiError(response) {
    if (response.status === 401) {
        localStorage.removeItem('dashboard_token');
        localStorage.removeItem('user_role');
        window.location.href = '/login.html';
    }
}

let usersData = [];
let chartInstance = null;
let trafficChartInstance = null;
let trafficTimer = null;
let autoRefreshTimer = null;
let timeLeft = 900;
let isRefreshing = false;
let currentRouterId = 'all';
let currentTrafficInterface = 'all';

// Dark Mode Toggle
const themeToggle = document.getElementById('theme-toggle');
const themeIcon = document.getElementById('theme-icon');

function initTheme() {
    if (localStorage.getItem('theme') === 'dark' || (!('theme' in localStorage) && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
        document.documentElement.classList.add('dark');
        themeIcon.classList.remove('fa-moon');
        themeIcon.classList.add('fa-sun');
    }
}

themeToggle.addEventListener('click', () => {
    document.documentElement.classList.toggle('dark');
    if (document.documentElement.classList.contains('dark')) {
        localStorage.setItem('theme', 'dark');
        themeIcon.classList.remove('fa-moon');
        themeIcon.classList.add('fa-sun');
    } else {
        localStorage.setItem('theme', 'light');
        themeIcon.classList.remove('fa-sun');
        themeIcon.classList.add('fa-moon');
    }
    updateChartTheme();
});

initTheme();

// Initialize Traffic Chart
function initTrafficChart() {
    const ctx = document.getElementById('trafficChart').getContext('2d');
    const isDark = document.documentElement.classList.contains('dark');
    const textColor = isDark ? '#e5e7eb' : '#374151';
    
    trafficChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: 'Rx (Download)',
                    data: [],
                    borderColor: '#10b981', // green
                    backgroundColor: 'rgba(16, 185, 129, 0.1)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.4
                },
                {
                    label: 'Tx (Upload)',
                    data: [],
                    borderColor: '#8b5cf6', // purple
                    backgroundColor: 'rgba(139, 92, 246, 0.1)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.4
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: textColor } }
            },
            scales: {
                x: { ticks: { color: textColor }, grid: { color: isDark ? '#374151' : '#e5e7eb' } },
                y: { 
                    ticks: { 
                        color: textColor,
                        callback: function(value) {
                            if (value === 0 || isNaN(value)) return '0 B';
                            const k = 1024;
                            const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
                            let i = Math.floor(Math.log(value) / Math.log(k));
                            if (i < 0) i = 0;
                            if (i >= sizes.length) i = sizes.length - 1;
                            return parseFloat((value / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
                        }
                    }, 
                    grid: { color: isDark ? '#374151' : '#e5e7eb' }, 
                    beginAtZero: true 
                }
            }
        }
    });
}

// 1. Array to hold the last valid total bytes to calculate Delta (since snmp counters are cumulative)
let lastTrafficData = { rx: null, tx: null, time: null };

async function fetchTrafficData() {
    try {
        let queryParams = currentRouterId !== 'all' ? `?router_id=${currentRouterId}` : '';
        if (currentTrafficInterface !== 'all') {
            queryParams += (queryParams ? '&' : '?') + `interface=${encodeURIComponent(currentTrafficInterface)}`;
        }
        const res = await fetch(`${API_BASE}/traffic${queryParams}`, fetchOptions);
        if (!res.ok) return;
        
        let trafficResponse = await res.json();
        
        // Accumulate if 'all routers'
        let totalRx = 0;
        let totalTx = 0;
        let hasData = false;
        
        if (Array.isArray(trafficResponse)) {
             trafficResponse.forEach(r => {
                 if (r.rx_bytes !== undefined) {
                     totalRx += r.rx_bytes;
                     totalTx += r.tx_bytes;
                     hasData = true;
                 }
             });
        } else {
             if (trafficResponse.rx_bytes !== undefined) {
                 totalRx = trafficResponse.rx_bytes;
                 totalTx = trafficResponse.tx_bytes;
                 hasData = true;
             }
        }
        
        if (hasData && trafficChartInstance) {
            const now = new Date();
            const timeLabel = now.toLocaleTimeString();
            
            // Calculate speed (bytes per second) instead of total sum
            let rxSpeed = 0;
            let txSpeed = 0;
            
            if (lastTrafficData.time !== null) {
                const timeDiff = (now - lastTrafficData.time) / 1000; // seconds
                if (timeDiff > 0) {
                    // Handle counter wraps loosely (if current < last, just use 0 for this tick)
                    if (totalRx >= lastTrafficData.rx) {
                        rxSpeed = (totalRx - lastTrafficData.rx) / timeDiff;
                    }
                    if (totalTx >= lastTrafficData.tx) {
                        txSpeed = (totalTx - lastTrafficData.tx) / timeDiff;
                    }
                }
            }
            
            lastTrafficData = { rx: totalRx, tx: totalTx, time: now };
            
            // Add to chart
            trafficChartInstance.data.labels.push(timeLabel);
            trafficChartInstance.data.datasets[0].data.push(rxSpeed);
            trafficChartInstance.data.datasets[1].data.push(txSpeed);
            
            // Keep only last 15 points
            if (trafficChartInstance.data.labels.length > 15) {
                trafficChartInstance.data.labels.shift();
                trafficChartInstance.data.datasets[0].data.shift();
                trafficChartInstance.data.datasets[1].data.shift();
            }
            
            trafficChartInstance.update();
        }
    } catch (e) {
        console.error("Failed to fetch traffic data", e);
    }
}

function startTrafficPolling() {
    if (trafficTimer) clearInterval(trafficTimer);
    fetchTrafficData(); // Initial fetch
    trafficTimer = setInterval(fetchTrafficData, 5000); // Poll every 5s for smooth graph
}

// Initialize Chart
function initChart() {
    const ctx = document.getElementById('activeUsersChart').getContext('2d');
    const isDark = document.documentElement.classList.contains('dark');
    const textColor = isDark ? '#e5e7eb' : '#374151';
    
    chartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'Active Users',
                data: [],
                borderColor: '#3b82f6',
                backgroundColor: 'rgba(59, 130, 246, 0.1)',
                borderWidth: 2,
                fill: true,
                tension: 0.4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                x: { ticks: { color: textColor }, grid: { color: isDark ? '#374151' : '#e5e7eb' } },
                y: { ticks: { color: textColor, precision: 0 }, grid: { color: isDark ? '#374151' : '#e5e7eb' }, beginAtZero: true }
            }
        }
    });
}

function updateChartTheme() {
    if (!chartInstance) return;
    const isDark = document.documentElement.classList.contains('dark');
    const textColor = isDark ? '#e5e7eb' : '#374151';
    const gridColor = isDark ? '#374151' : '#e5e7eb';
    
    chartInstance.options.scales.x.ticks.color = textColor;
    chartInstance.options.scales.x.grid.color = gridColor;
    chartInstance.options.scales.y.ticks.color = textColor;
    chartInstance.options.scales.y.grid.color = gridColor;
    chartInstance.update();
    
    if (trafficChartInstance) {
        trafficChartInstance.options.scales.x.ticks.color = textColor;
        trafficChartInstance.options.scales.x.grid.color = gridColor;
        trafficChartInstance.options.scales.y.ticks.color = textColor;
        trafficChartInstance.options.scales.y.grid.color = gridColor;
        trafficChartInstance.options.plugins.legend.labels.color = textColor;
        trafficChartInstance.update();
    }
}

async function fetchChartData() {
    try {
        const queryParams = currentRouterId !== 'all' ? `?router_id=${currentRouterId}` : '';
        const res = await fetch(`${API_BASE}/chart_data${queryParams}`, fetchOptions);
        handleApiError(res);
        if (!res.ok) return;
        const data = await res.json();
        if (chartInstance) {
            chartInstance.data.labels = data.labels;
            chartInstance.data.datasets[0].data = data.data;
            chartInstance.update();
        }
    } catch (e) {
        console.error("Failed to fetch chart data", e);
    }
}

// Fetch and update dashboard data
async function fetchRouterStatus() {
    try {
        const queryParams = currentRouterId !== 'all' ? `?router_id=${currentRouterId}` : '';
        const res = await fetch(`${API_BASE}/router/status${queryParams}`, fetchOptions);
        handleApiError(res);
        if (!res.ok) throw new Error("Failed to fetch router status");
        
        const statusResponse = await res.json();
        
        const ring = document.getElementById('router-ping-ring');
        const dot = document.getElementById('router-ping-dot');
        const text = document.getElementById('router-text');
        const container = document.getElementById('router-status-indicator');
        
        // Handle array of statuses or single status object based on the endpoint
        let isOnline = false;
        let tooltipText = "";
        let cpuLoadText = "";
        
        if (Array.isArray(statusResponse)) {
             // 'All Routers' selected
             const total = statusResponse.length;
             const onlineCount = statusResponse.filter(s => s.online).length;
             
             isOnline = onlineCount > 0;
             text.textContent = `${onlineCount} / ${total} Online`;
             tooltipText = statusResponse.map(s => `${s.name}: ${s.online ? 'Online' : 'Offline'}`).join('\n');
             
             if (onlineCount === 0) {
                 cpuLoadText = "Offline";
             }
        } else {
             // Specific router selected
             const status = statusResponse;
             isOnline = status.online;
             
             if (status.online) {
                 cpuLoadText = `${status.cpu_load} CPU`;
                 text.textContent = `Online - ${cpuLoadText}`;
                 tooltipText = `Board: ${status.board_name} | Free Mem: ${status.free_memory} | Uptime: ${status.uptime}`;
             } else {
                 text.textContent = `Offline`;
                 tooltipText = status.error || "Router is unreachable";
             }
        }
        
        if (isOnline) {
            ring.className = 'animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75';
            dot.className = 'relative inline-flex rounded-full h-3 w-3 bg-green-500';
            container.className = 'flex items-center space-x-2 bg-green-900/40 px-3 py-1.5 rounded-full border border-green-500/50 transition-all duration-300';
            container.title = tooltipText;
        } else {
            ring.className = '';
            dot.className = 'relative inline-flex rounded-full h-3 w-3 bg-red-500';
            container.className = 'flex items-center space-x-2 bg-red-900/40 px-3 py-1.5 rounded-full border border-red-500/50 transition-all duration-300';
            container.title = tooltipText || "Offline";
        }
    } catch(e) {
        console.error(e);
        document.getElementById('router-ping-ring').className = '';
        document.getElementById('router-ping-dot').className = 'relative inline-flex rounded-full h-3 w-3 bg-red-500';
        document.getElementById('router-text').textContent = 'Error';
    }
}

async function fetchDashboardData() {
    try {
        fetchRouterStatus(); // Doesn't need to block the rest of the dashboard
        
        const queryParams = currentRouterId !== 'all' ? `?router_id=${currentRouterId}` : '';
        
        const [usersRes, logsRes] = await Promise.all([
            fetch(`${API_BASE}/users${queryParams}`, fetchOptions),
            fetch(`${API_BASE}/logs?limit=10${currentRouterId !== 'all' ? `&router_id=${currentRouterId}` : ''}`, fetchOptions)
        ]);

        handleApiError(usersRes);
        if (!usersRes.ok) return;

        usersData = await usersRes.json();
        const logs = await logsRes.json();

        const total = usersData.length;
        const active = usersData.filter(u => u.status === 'online').length;
        const down = total - active;

        updateStats({total, active, down});
        renderTable();
        // updateMap(usersData); // Removed map
        renderLogs(logs);
        fetchChartData();

    } catch (error) {
        console.error("Error fetching data:", error);
    }
}

function updateStats(stats) {
    document.getElementById('total-users').textContent = stats.total;
    document.getElementById('active-users').textContent = stats.active;
    document.getElementById('down-users').textContent = stats.down;
}

function renderTable() {
    const tbody = document.getElementById('user-table-body');
    const searchTerm = document.getElementById('search-input').value.toLowerCase();
    
    tbody.innerHTML = '';
    
    const filteredUsers = usersData.filter(u => u.name.toLowerCase().includes(searchTerm));

    if (filteredUsers.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" class="px-6 py-4 text-center text-gray-500">No users found.</td></tr>`;
        return;
    }

    filteredUsers.forEach(user => {
        const isOnline = user.status === 'online';
        const tr = document.createElement('tr');
        tr.className = "hover:bg-gray-50 transition-colors dark:hover:bg-gray-700";
        tr.innerHTML = `
            <td class="px-6 py-4 whitespace-nowrap">
                <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${isOnline ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}">
                    ${isOnline ? '<i class="fas fa-check-circle mr-1 mt-0.5"></i> Online' : '<i class="fas fa-times-circle mr-1 mt-0.5"></i> Offline'}
                </span>
            </td>
            <td class="px-6 py-4 whitespace-nowrap font-medium text-gray-900 dark:text-gray-100">${user.name}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-300 font-mono">${user.address || '-'}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-300">${user.service}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-300">${user.uptime || '-'}</td>
        `;
        tbody.appendChild(tr);
    });
}

function updateLogsTable(logs) {
    const tbody = document.getElementById('logs-table-body');
    tbody.innerHTML = '';
    
    logs.forEach(log => {
        const tr = document.createElement('tr');
        tr.className = 'hover:bg-gray-50 dark:hover:bg-gray-750 transition';
        const date = new Date(log.timestamp);
        
        let eventHtml = '';
        if (log.event === 'connected') {
            eventHtml = `<span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-200">Connected</span>`;
        } else {
            eventHtml = `<span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-200">Disconnected</span>`;
        }

        tr.innerHTML = `
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400 font-mono">${date.toLocaleTimeString()}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-white">${log.username}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">${log.router_name || 'Sys'}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm">${eventHtml}</td>
        `;
        tbody.appendChild(tr);
    });
}

function renderLogs(logs) {
    const logList = document.getElementById('log-list');
    logList.innerHTML = '';
    if (logs.length === 0) {
        logList.innerHTML = `<li class="px-6 py-3 text-gray-500 text-center">No recent logs.</li>`;
        return;
    }
    
    logs.forEach(log => {
        const li = document.createElement('li');
        li.className = "px-6 py-3 flex justify-between items-center";
        const date = new Date(log.timestamp).toLocaleString();
        const icon = log.event === 'connected' ? '<i class="fas fa-arrow-right text-green-500 mr-2"></i>' : '<i class="fas fa-arrow-left text-red-500 mr-2"></i>';
        li.innerHTML = `
            <div class="flex items-center"><span class="w-24 text-gray-400 text-xs">${date.split(',')[1]}</span> ${icon} <span class="font-medium ml-2 dark:text-gray-200">${log.username}</span> <span class="ml-2 text-gray-500 dark:text-gray-400">${log.event}</span></div>
            <div class="text-xs text-gray-400">${date.split(',')[0]}</div>
        `;
        logList.appendChild(li);
    });
}

document.getElementById('search-input').addEventListener('input', renderTable);

document.getElementById('export-btn').addEventListener('click', () => {
    if (usersData.length === 0) return;
    
    const headers = ['Username', 'Status', 'IP Address', 'Service', 'Uptime', 'Comment'];
    const csvRows = [headers.join(',')];
    
    usersData.forEach(u => {
        const row = [u.name, u.status, u.address, u.service, u.uptime, `"${u.comment}"`];
        csvRows.push(row.join(','));
    });
    
    const blob = new Blob([csvRows.join('\n')], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.setAttribute('hidden', '');
    a.setAttribute('href', url);
    a.setAttribute('download', 'pppoe_users.csv');
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
});

// Auto Refresh Logic
let refreshInterval;

function startAutoRefresh() {
    clearInterval(refreshInterval);
    
    refreshInterval = setInterval(() => {
        fetchDashboardData();
    }, 5000);
}

document.getElementById('refresh-btn').addEventListener('click', () => {
    fetchDashboardData();
    startAutoRefresh(); // reset timer
});

document.getElementById('logout-btn').addEventListener('click', () => {
    localStorage.removeItem('dashboard_token');
    localStorage.removeItem('user_role');
    window.location.href = '/login.html';
});

// Router Management 
async function loadRouters() {
    try {
        const res = await fetch(`${API_BASE}/routers`, fetchOptions);
        if (res.ok) {
            const routers = await res.json();
            const select = document.getElementById('router-select');
            // Keep the 'all' option, remove others
            select.innerHTML = '<option value="all">All Routers</option>';
            
            routers.forEach(r => {
                const opt = document.createElement('option');
                opt.value = r.id;
                opt.textContent = r.name;
                select.appendChild(opt);
            });
            select.value = currentRouterId;
        }
    } catch(e) {
        console.error("Failed to load routers", e);
    }
}

document.getElementById('router-select').addEventListener('change', (e) => {
    currentRouterId = e.target.value;
    
    const deleteBtn = document.getElementById('delete-router-btn');
    if (localStorage.getItem('user_role') === 'admin' && currentRouterId !== 'all') {
        deleteBtn.classList.remove('hidden');
    } else {
        deleteBtn.classList.add('hidden');
    }
    
    // Clear graph when switching routers
    if (trafficChartInstance) {
        trafficChartInstance.data.labels = [];
        trafficChartInstance.data.datasets[0].data = [];
        trafficChartInstance.data.datasets[1].data = [];
        trafficChartInstance.update();
    }
    lastTrafficData = { rx: null, tx: null, time: null };
    currentTrafficInterface = 'all';
    
    loadTrafficInterfaces();
    fetchDashboardData();
    startAutoRefresh();
});

// Delete Router Logic
const deleteRouterBtn = document.getElementById('delete-router-btn');
deleteRouterBtn.addEventListener('click', async () => {
    if (currentRouterId === 'all') return;
    
    if (!confirm("Are you sure you want to delete this router? This action cannot be undone.")) {
        return;
    }
    
    try {
        const res = await fetch(`${API_BASE}/routers/${currentRouterId}`, {
            method: 'DELETE',
            ...fetchOptions
        });
        
        if (res.ok) {
            currentRouterId = 'all';
            document.getElementById('router-select').value = 'all';
            deleteRouterBtn.classList.add('hidden');
            loadRouters();
            fetchDashboardData();
            startAutoRefresh();
            loadTrafficInterfaces();
        } else {
            const body = await res.json();
            alert(body.detail || "Failed to delete router.");
        }
    } catch (e) {
        console.error(e);
        alert("Network error occurred while deleting router.");
    }
});

// Dynamic Traffic Interface Selection
async function loadTrafficInterfaces() {
    const select = document.getElementById('traffic-interface');
    
    if (currentRouterId === 'all') {
        select.classList.add('hidden');
        currentTrafficInterface = 'all';
        select.innerHTML = '<option value="all">All Interfaces</option>';
        return;
    }
    
    select.classList.remove('hidden');
    select.innerHTML = '<option value="all">Loading...</option>';
    
    try {
        const res = await fetch(`${API_BASE}/routers/${currentRouterId}/interfaces`, fetchOptions);
        if (res.ok) {
            const interfaces = await res.json();
            select.innerHTML = '<option value="all">All Interfaces</option>';
            
            interfaces.forEach(iface => {
                const opt = document.createElement('option');
                opt.value = iface.name;
                opt.textContent = `${iface.name} (${iface.type})`;
                select.appendChild(opt);
            });
            select.value = currentTrafficInterface; // Restore selected if possible
            if (select.selectedIndex === -1) {
                select.value = 'all';
                currentTrafficInterface = 'all';
            }
        } else {
            select.innerHTML = '<option value="all">All Interfaces</option>';
        }
    } catch (e) {
        console.error("Failed to load interfaces", e);
        select.innerHTML = '<option value="all">All Interfaces</option>';
    }
}

document.getElementById('traffic-interface').addEventListener('change', (e) => {
    currentTrafficInterface = e.target.value;
    
    // Clear graph to avoid massive spikes from changing target counters
    if (trafficChartInstance) {
        trafficChartInstance.data.labels = [];
        trafficChartInstance.data.datasets[0].data = [];
        trafficChartInstance.data.datasets[1].data = [];
        trafficChartInstance.update();
    }
    lastTrafficData = { rx: null, tx: null, time: null };
    
    // Immediately fetch new data
    fetchTrafficData();
});

// Add Router Modal Logic
const addRouterBtn = document.getElementById('add-router-btn');
const addRouterModal = document.getElementById('add-router-modal');
const closeRouterModal = document.getElementById('close-router-modal');
const cancelRouterBtn = document.getElementById('cancel-router-btn');
const addRouterForm = document.getElementById('add-router-form');

// API UI Toggles
const useApiCb = document.getElementById('use-api');
const apiSettingsDiv = document.getElementById('api-settings');

useApiCb.addEventListener('change', (e) => {
    if (e.target.checked) {
        apiSettingsDiv.classList.remove('hidden');
    } else {
        apiSettingsDiv.classList.add('hidden');
    }
});

// SSH UI Toggles
const useSshCb = document.getElementById('use-ssh');
const sshSettingsDiv = document.getElementById('ssh-settings');

useSshCb.addEventListener('change', (e) => {
    if (e.target.checked) {
        sshSettingsDiv.classList.remove('hidden');
    } else {
        sshSettingsDiv.classList.add('hidden');
    }
});

// SNMP UI Toggles
const useSnmpCb = document.getElementById('use-snmp');
const snmpSettingsDiv = document.getElementById('snmp-settings');
const snmpVersionSelect = document.getElementById('snmp-version');
const snmpV3SettingsDiv = document.getElementById('snmp-v3-settings');

useSnmpCb.addEventListener('change', (e) => {
    if (e.target.checked) {
        snmpSettingsDiv.classList.remove('hidden');
    } else {
        snmpSettingsDiv.classList.add('hidden');
    }
});

snmpVersionSelect.addEventListener('change', (e) => {
    if (e.target.value === 'v3') {
        snmpV3SettingsDiv.classList.remove('hidden');
        document.getElementById('snmp-community').classList.add('hidden');
    } else {
        snmpV3SettingsDiv.classList.add('hidden');
        document.getElementById('snmp-community').classList.remove('hidden');
    }
});

if (localStorage.getItem('user_role') !== 'admin') {
    addRouterBtn.classList.add('hidden'); // Hide for non-admins
}

addRouterBtn.addEventListener('click', () => {
    addRouterModal.classList.remove('hidden');
});

const hideRouterModal = () => {
    addRouterModal.classList.add('hidden');
    addRouterForm.reset();
    apiSettingsDiv.classList.remove('hidden'); // Default on
    sshSettingsDiv.classList.add('hidden');
    snmpSettingsDiv.classList.add('hidden');
    snmpV3SettingsDiv.classList.add('hidden');
    document.getElementById('snmp-community').classList.remove('hidden');
    document.getElementById('router-error').classList.add('hidden');
};

closeRouterModal.addEventListener('click', hideRouterModal);
cancelRouterBtn.addEventListener('click', hideRouterModal);

addRouterForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = document.getElementById('save-router-btn');
    const err = document.getElementById('router-error');
    
    // Validate at least one protocol is selected
    const useApi = document.getElementById('use-api').checked;
    const useSsh = document.getElementById('use-ssh').checked;
    const useSnmp = document.getElementById('use-snmp').checked;
    
    if (!useApi && !useSsh && !useSnmp) {
        err.textContent = "You must select at least one connection protocol.";
        err.classList.remove('hidden');
        return;
    }
    
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';
    err.classList.add('hidden');
    
    const data = {
        name: document.getElementById('router-name').value,
        host: document.getElementById('router-host').value,
        username: document.getElementById('router-user').value || "",
        password: document.getElementById('router-pass').value || "",
        use_api: useApi,
        api_port: parseInt(document.getElementById('api-port').value) || 8728,
        use_ssh: useSsh,
        ssh_port: parseInt(document.getElementById('ssh-port').value) || 22,
        ssh_username: document.getElementById('ssh-user').value || "",
        ssh_password: document.getElementById('ssh-pass').value || "",
        use_snmp: useSnmp,
        snmp_host: document.getElementById('snmp-host').value || "",
        snmp_port: parseInt(document.getElementById('snmp-port').value) || 161,
        snmp_version: document.getElementById('snmp-version').value || "v2c",
        snmp_community: document.getElementById('snmp-community').value || "",
        snmp_interface: document.getElementById('snmp-interface').value || "all",
        snmp_username: document.getElementById('snmp-username').value || "",
        snmp_auth_password: document.getElementById('snmp-auth-password').value || "",
        snmp_priv_password: document.getElementById('snmp-priv-password').value || ""
    };
    
    try {
        const res = await fetch(`${API_BASE}/routers`, {
            method: 'POST',
            ...fetchOptions,
            headers: {
                ...fetchOptions.headers,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        });
        
        if (res.ok) {
            hideRouterModal();
            loadRouters(); // Refresh list
            fetchDashboardData();
            startAutoRefresh();
        } else {
            const body = await res.json();
            let errMsg = "Failed to add router";
            if (Array.isArray(body.detail)) {
                errMsg = body.detail.map(d => {
                    let field = d.loc ? d.loc.join('.') : '';
                    return `<b>${field}</b>: ${d.msg || JSON.stringify(d)}`;
                }).join('<br>');
            } else if (body.detail) {
                errMsg = body.detail;
            }
            err.innerHTML = errMsg;
            err.classList.remove('hidden');
        }
    } catch (error) {
         err.textContent = "Network error occurred";
         err.classList.remove('hidden');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<span>Save Router</span>';
    }
});


// Initialization
document.addEventListener('DOMContentLoaded', () => {
    if(document.getElementById('app-body')) {
        document.getElementById('app-body').classList.remove('hidden');
    }
    initTrafficChart();
    initChart();
    loadRouters();
    fetchDashboardData();
    startTrafficPolling();
    startAutoRefresh();
});
